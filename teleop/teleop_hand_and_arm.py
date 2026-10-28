import argparse
import os
import sys
import threading
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
for extra_path in (
    PROJECT_ROOT,
    os.path.join(CURRENT_DIR, "televuer", "src"),
    os.path.join(CURRENT_DIR, "teleimager", "src"),
):
    if extra_path not in sys.path:
        sys.path.insert(0, extra_path)

# 统一日志
from teleop.log_manager import setup_logging, shutdown_logging, get_logger
_logger = get_logger(__name__)

from api.shared_state import SharedState, TeleopCommand
from api.app import run_server
from api.dataset_manager import DatasetManager

import cv2
import numpy as np
import signal as _signal
from sshkeyboard import listen_keyboard, stop_listening
from config_loader import apply_cli_overrides, load_all_configs
from teleop.teleimager.src.teleimager.humanoid_image_client import ImageClient
from teleop.televuer.src.televuer.tv_wrapper import TeleVuerWrapper
from teleop.robot_control.robot_arm import RICO_ArmController
from teleop.robot_control.robot_arm_ik import RICO_ArmIK
from teleop.robot_control.robot_hand_bchand import BChand_Gripper_Controller
from teleop.robot_control.robot_waist import RICO_WaistController
from teleop.robot_control.robot_head import RICO_HeadController
from teleop.utils.episode_writer import EpisodeWriter
from teleop.utils.camera_manager import CameraManager

STATE_INACTIVE = "INACTIVE"              # XR不可用态
STATE_IDLE = "IDLE"                      # 待机态（可开始控制）
STATE_ACTIVE_CONTROL = "ACTIVE_CONTROL"  # 主动控制态
STATE_RETURNING_HOME = "RETURNING_HOME"  # 自动回零态

class KeyboardFallbackState:
    """键盘备用输入，仅紧急停止"""
    def __init__(self):
        self.emergency_stop_requested = False   # 紧急停止请求标志

    def on_press(self, key):
        """记录键盘触发的停止请求。"""
        if key == "e":   # 紧急停止键
            self.emergency_stop_requested = True

class ButtonEdgeDetector:
    """
    按钮上升沿检测：避免长按按钮重复触发
    只在[按下瞬间]触发一次，防止状态疯狂切换
    """
    def __init__(self):
        self._previous = {} # 缓存上一帧按钮状态

    def rising(self, key: str, current_value: bool) -> bool:
        """返回True:按钮从松开→按下(上升沿)"""
        previous_value = self._previous.get(key, False)
        self._previous[key] = bool(current_value)
        return bool(current_value) and not previous_value

def parse_args():
    """定义命令行参数，并交给配置层做统一覆盖，支持覆盖配置"""
    parser = argparse.ArgumentParser(description="RICO 机器人遥操作与数据采集主程序")
    parser.add_argument("--config-dir", type=str, default=os.path.join(PROJECT_ROOT, "config"), help="配置目录")
    parser.add_argument("--task-dir", type=str, default=None, help="录制目录,可覆盖配置文件")
    parser.add_argument("--headless", action="store_true", help="不显示本地图像窗口")
    parser.add_argument("--sim", action="store_true", help="使用仿真占位控制链路")
    parser.add_argument("--full-body", action="store_true", default=None, help="是否是全身人形整机")
    parser.add_argument("--no-waist", dest="waist_enabled", action="store_false", default=None, help="禁用 waist 控制链路")
    parser.add_argument("--no-head", dest="head_enabled", action="store_false", default=None, help="禁用 head 控制链路")
    parser.add_argument("--no-image-server", dest="enable_image_server", action="store_false", default=None, help="禁用图像服务端，纯遥操作模式")
    parser.add_argument("--image-server-ip", type=str, default=None, help="图像服务端 IP,可覆盖配置文件")
    parser.add_argument("--frequency", type=float, default=None, help="主循环频率,可覆盖配置文件")
    return parser.parse_args()

def split_head_images(head_image, head_config):
    """按头部相机配置拆分单目/双目图像：双目=左右眼，单目=单张"""
    if head_image is None:
        return {}
    if head_config.get("binocular"):
        half_width = head_image.shape[1] // 2
        return {
            "color_0": head_image[:, :half_width],
            "color_1": head_image[:, half_width:],
        }
    return {"color_0": head_image}

def collect_camera_payload(image_client, camera_config):
    """
    所有相机数据：头部彩色/深度、左右腕部相机
    统一采集当前帧颜色图和深度图，供显示与录制共用。
    当 image_client 为 None 时返回空数据。
    """
    colors = {}
    depths = {}

    if image_client is None or not camera_config:
        return colors, depths, None, None, None, None

    head_image, _ = image_client.get_head_frame()
    head_depth, _ = image_client.get_head_depth_frame()
    left_wrist_image, _ = image_client.get_left_wrist_frame()
    left_wrist_depth, _ = image_client.get_left_wrist_depth_frame()
    right_wrist_image, _ = image_client.get_right_wrist_frame()
    right_wrist_depth, _ = image_client.get_right_wrist_depth_frame()
    front_chest_image, _ = image_client.get_front_chest_frame()
    back_chest_image, _ = image_client.get_back_chest_frame()

    colors.update(split_head_images(head_image, camera_config["head_camera"]))
    if left_wrist_image is not None:
        colors["color_2"] = left_wrist_image
    if right_wrist_image is not None:
        colors["color_3"] = right_wrist_image
    if front_chest_image is not None:
        colors["color_4"] = front_chest_image
    if back_chest_image is not None:
        colors["color_5"] = back_chest_image
    if head_depth is not None:
        depths["depth_0"] = head_depth
    if left_wrist_depth is not None:
        depths["depth_2"] = left_wrist_depth
    if right_wrist_depth is not None:
        depths["depth_3"] = right_wrist_depth

    return colors, depths, head_image, head_depth, left_wrist_image, right_wrist_image

def _normalize_preview_tile(image, tile_width, tile_height):
    """将彩色图统一缩放到预览网格尺寸，缺帧时返回黑图占位。"""
    if image is None:
        return np.zeros((tile_height, tile_width, 3), dtype=np.uint8)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return cv2.resize(image, (tile_width, tile_height))

def _normalize_depth_tile(depth_image, tile_width, tile_height):
    """将深度图转成伪彩色 BGR 图，并统一缩放到预览网格尺寸。"""
    if depth_image is None:
        return np.zeros((tile_height, tile_width, 3), dtype=np.uint8)
    depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.09), cv2.COLORMAP_JET)
    return cv2.resize(depth_colormap, (tile_width, tile_height))

def _annotate_preview_tile(image, label):
    """给单个预览格添加左上角文字标签。"""
    annotated = image.copy()
    cv2.rectangle(annotated, (8, 8), (160, 42), (0, 0, 0), thickness=-1)
    cv2.putText(annotated, label, (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return annotated

def show_debug_image(head_image, head_depth, left_wrist_image, right_wrist_image, tile_shape):
    """在本地窗口显示固定 2x2 调试画面：头部图、深度图、左右腕部图"""
    has_preview_source = any(frame is not None for frame in (head_image, head_depth, left_wrist_image, right_wrist_image))
    if not has_preview_source:
        return False

    tile_width, tile_height = (int(tile_shape[0]), int(tile_shape[1]))
    # 预览窗口固定为 2x2 布局，缺失帧也保留黑图占位，避免窗口尺寸抖动。
    top_row = np.hstack(
        (
            _annotate_preview_tile(_normalize_preview_tile(head_image, tile_width, tile_height), "head"),
            _annotate_preview_tile(_normalize_depth_tile(head_depth, tile_width, tile_height), "head_depth"),
        )
    )
    bottom_row = np.hstack(
        (
            _annotate_preview_tile(_normalize_preview_tile(left_wrist_image, tile_width, tile_height), "left"),
            _annotate_preview_tile(_normalize_preview_tile(right_wrist_image, tile_width, tile_height), "right"),
        )
    )
    display_image = np.vstack((top_row, bottom_row))
    height, width = display_image.shape[:2]
    cv2.imshow("rico_teleop_preview", cv2.resize(display_image, (width // 2, height // 2)))
    return True

def build_runtime_config(args):
    """加载配置文件并叠加命令行覆盖项。"""
    config = load_all_configs(args.config_dir)
    return apply_cli_overrides(config, args)

def main():
    """主入口。
    1. 加载配置 → 2. 初始化所有硬件/软件组件 → 3. 状态机循环 → 4. 控制机器人 → 5. 录制数据 → 6. 安全退出
    - 启动后等待唤醒；
    - 进入待机后由按钮切换控制与录制；
    - 回零、退回、录制收尾都放在同一状态机内处理。
    """
    args = parse_args()
    config = build_runtime_config(args)
    system_cfg = config["system"]
    robot_cfg = config["robot"]

    # 初始化统一日志系统
    setup_logging(system_cfg.get("log_manager"))

    # 键盘备用控制（仅紧急停止）
    keyboard_state = KeyboardFallbackState()
    keyboard_thread = threading.Thread(
        target=listen_keyboard,
        kwargs={"on_press": keyboard_state.on_press, "until": None, "sequential": False},
        daemon=True,
    )
    keyboard_thread.start()

    # 读取运行时参数
    upper_body = bool(robot_cfg["robot"].get("upper_body", True))
    headless = bool(system_cfg["runtime"]["headless"])
    frequency = float(system_cfg["runtime"]["frequency"])
    simulation_mode = bool(system_cfg["runtime"]["sim_enabled_default"])
    enable_image_server = system_cfg["runtime"].get("enable_image_server", True)
    # waist, head 开关同时受 system.json 默认值和 CLI 覆盖控制
    waist_enabled = bool(system_cfg["runtime"].get("waist_enabled_default", False))
    head_enabled = bool(system_cfg["runtime"].get("head_enabled_default", False))

    # 初始化图像客户端
    image_client = None
    camera_config = {}
    if enable_image_server:
        try:
            image_client = ImageClient(
                image_server_ip=system_cfg["network"]["image_server_ip"],
                image_request_port=system_cfg["network"]["image_request_port"],
            )
            _logger.info("ImageClient初始化成功")
            camera_config = image_client.get_cam_config()
        except Exception as e:
            _logger.warning(f"图像服务端不可用，降级为无图像模式: {e}")
            enable_image_server = False
            camera_config = {}
    else:
        _logger.info("图像服务端已禁用，进入纯遥操作模式")

    input_mode = system_cfg["xr"]["input_mode"]

    # 初始化XR包装器(接收VR输入)
    if enable_image_server and camera_config:
        head_cfg = camera_config["head_camera"]
        head_streams = head_cfg["streams"]["color"]
        head_comm = head_cfg["communication"]
        tv_binocular = bool(head_cfg["binocular"])
        tv_img_shape = (head_streams["publish_width"], head_streams["publish_height"])
        tv_display_fps = min(frequency, float(head_streams["fps"]))
        tv_zmq = bool(head_comm["zeromq"]["enabled"])
        tv_webrtc = bool(head_comm["webrtc"]["enabled"])
        tv_webrtc_url = f"https://{system_cfg['network']['image_server_ip']}:{head_comm['webrtc']['port']}/webrtc/head_camera/offer"
        tv_display_mode = system_cfg["xr"]["display_mode"]
    else:
        tv_binocular = False
        tv_img_shape = (640, 480)
        tv_display_fps = frequency
        tv_zmq = False
        tv_webrtc = False
        tv_webrtc_url = None
        tv_display_mode = "pass-through"

    tv_wrapper = TeleVuerWrapper(
        upper_body=upper_body,
        use_hand_tracking=(input_mode == "hand"),
        binocular=tv_binocular,
        img_shape=tv_img_shape,
        display_fps=tv_display_fps,
        display_mode=tv_display_mode,
        zmq=tv_zmq,
        webrtc=tv_webrtc,
        webrtc_url=tv_webrtc_url,
        stun_servers=["stun:stun.l.google.com:19302"]
    )

    _logger.info("请在XR设备访问 https://<host-ip>:8012/?ws=wss://<host-ip>:8012")

    # 初始化机器人控制组件
    arm_ik = RICO_ArmIK()  # 机械臂逆运动学
    arm_ctrl_send = RICO_ArmController(robot_cfg, simulation_mode=simulation_mode)    # 左臂右臂控制器(发送指令)
    arm_ctrl_recv = RICO_ArmController(robot_cfg, simulation_mode=simulation_mode, is_resv_mode=True) # 接收双臂状态
    hand_ctrl = BChand_Gripper_Controller(robot_cfg, simulation_mode=simulation_mode) # 灵巧手控制器
    head_ctrl_send = RICO_HeadController(robot_cfg, simulation_mode=simulation_mode) if head_enabled else None # 头部控制器(发送指令)
    head_ctrl_recv = RICO_HeadController(robot_cfg, simulation_mode=simulation_mode, is_resv_mode=True) # 接收头部状态
    waist_ctrl_send = RICO_WaistController(robot_cfg, simulation_mode=simulation_mode, upper_body=upper_body) if waist_enabled else None # 腰部控制器(发送指令)
    waist_ctrl_recv = RICO_WaistController(robot_cfg, simulation_mode=simulation_mode, upper_body=upper_body, is_resv_mode=True) # 接收腰部状态

    # 任务管理：初始化 CameraManager 和 SharedState 并确保默认任务
    task_dir_root = system_cfg["paths"]["task_dir"]
    task_trash_dir = system_cfg["paths"]["trash_dir"]

    camera_manager = CameraManager(
        server_ip=system_cfg["network"]["image_server_ip"],
        server_port=int(system_cfg["network"]["image_request_port"]),
    ) if enable_image_server else None
    if camera_manager is not None:
        _logger.info(f"CameraManager 已初始化: {system_cfg['network']['image_server_ip']}:{system_cfg['network']['image_request_port']}")
    else:
        _logger.info("CameraManager 已禁用（无图像模式）")

    shared_state = SharedState(
        task_dir=task_dir_root,
        trash_dir=task_trash_dir,
        camera_manager=camera_manager
    )

    # 导入 DatasetManager 以使用 ensure_default_task
    dataset_manager = DatasetManager(task_dir_root, task_trash_dir)
    # 确保默认任务 task_0000 存在
    default_task = dataset_manager.ensure_default_task()
    _logger.info(f"默认任务已准备: {default_task.task_id}")

    # 加载活动任务，若没有则设置为默认任务
    active_task = shared_state.get_active_task()
    if active_task is None:
        # 如果没有活动任务，设置为默认任务
        shared_state.set_active_task(default_task.task_id)
        active_task = default_task.task_id
        _logger.info(f"未找到活动任务，已设置为默认任务: {active_task}")
    else:
        # 检查活动任务文件夹是否存在，不存在则回退到默认任务
        task_path = os.path.join(task_dir_root, active_task)
        if not os.path.isdir(task_path):
            _logger.warning(f"活动任务 {active_task} 文件夹不存在，回退到默认任务")
            shared_state.set_active_task(default_task.task_id)
            active_task = default_task.task_id
            _logger.info(f"已回退到默认任务: {active_task}")
        else:
            _logger.info(f"已加载活动任务: {active_task}")

    # 当前活动任务的完整路径
    current_task_path = os.path.join(task_dir_root, active_task)
    # 初始化 EpisodeWriter（传入任务目录）
    recorder = EpisodeWriter(
        task_dir=current_task_path,
        frequency=frequency,
        rerun_log=False,
        save_config=system_cfg.get("recording", {}),
        camera_config=camera_config,
    )

    # 记录当前使用的任务ID，用于检测切换
    current_recorder_task_id = active_task

    # 创建 SharedState 并启动 FastAPI 服务
    fastapi_thread = threading.Thread(
        target=run_server,
        args=(shared_state,),
        kwargs={"host": system_cfg["network"]["fastapi_host"],
                "port": int(system_cfg["network"]["fastapi_port"])},
        daemon=True,
    )
    fastapi_thread.start()
    _logger.info("FastAPI 服务已启动（后台线程）")

    # 初始化系统状态：开机→等待唤醒
    state = STATE_INACTIVE          # 初始为不可用态
    is_recording = False
    edge_detector = ButtonEdgeDetector()
    exit_pending = False            # 回零完成后是否进入 INACTIVE
    last_web_connected = False      # 上一帧XR网页连接状态

    # 提示信息
    parts = ["双臂"]
    if waist_enabled:
        parts.append("腰部")
    if head_enabled:
        parts.append("头部")
    reset_target_desc = "、".join(parts)
    reset_command_desc = f"复位{reset_target_desc}"

    robot_type = '半身人形整机' if upper_body else '全身人形整机'
    mode_desc = "仿真占位" if simulation_mode else "真机"
    head_status = "启用" if head_enabled else "禁用"
    waist_status = "启用" if waist_enabled else "禁用"

    # 操作提示
    _logger.info(f"系统启动完成 | 类型：{robot_type}, 运行模式:{mode_desc}, head控制:{head_status}, waist控制:{waist_status}")
    _logger.info("右手 A: 唤醒并回零（仅在 INACTIVE 态有效）")
    _logger.info("右手 B: 退出遥操作，回零后进入 INACTIVE")
    _logger.info("左手 X: 开始/停止遥操作（仅在 IDLE/ACTIVE_CONTROL 态有效）")
    _logger.info("左手 Y: 开始/停止录制（仅在 ACTIVE_CONTROL 态有效）")
    _logger.info(f"左手 X+Y: 手动回零{reset_command_desc}（若在录制中，回零过程将被录制，回零完成后自动停止录制，不改变控制状态）")
    _logger.info("左手 扳机键: 灵巧手握持或松开(按下=握持，松开=松开)")
    _logger.info("右手 扳机键: 灵巧手握持或松开(按下=握持，松开=松开)")
    _logger.info("键盘 e: 停止")

    try:
        while True:
            loop_start = time.time()

            current_lr_arm_q = None
            hand_state = None
            target_lr_arm_pose = None
            should_record_returning_home = False
            finalize_recording_after_frame = False

            cmd_data = shared_state.pop_command(timeout=0)  # 非阻塞
            if cmd_data:
                cmd = cmd_data["command"]
                data = cmd_data.get("data", {})
                _logger.debug(f"收到 API 命令: {cmd.value}, 数据: {data}")

                # 停止（最高优先级）
                if cmd == TeleopCommand.EMERGENCY_STOP:
                    if state != STATE_INACTIVE:
                        _logger.warning("!!! API停止指令 !!!")
                        shared_state.set_emergency_stop()
                        # 立即停止机械臂运动
                        arm_ctrl_send.left_arm_controller.stop(block=True)
                        arm_ctrl_send.right_arm_controller.stop(block=True)
                        # 回零机械臂,腰部关节,头部关节
                        arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                        if waist_enabled:
                            waist_ctrl_send.ctrl_waist_go_home(block=False)
                        if head_enabled:
                            head_ctrl_send.ctrl_head_go_home(block=False)
                        if state == STATE_ACTIVE_CONTROL:
                            shared_state.release_control()
                        exit_pending = True
                        state = STATE_RETURNING_HOME
                    continue

                # FastAPI 更新相机配置后，客户端与录制器同步刷新
                if cmd == TeleopCommand.REFRESH_CAMERA_CONFIG:
                    _logger.info("收到刷新相机配置命令")
                    if image_client is None:
                        _logger.warning("图像服务端不可用，无法刷新相机配置")
                        continue
                    try:
                        refreshed_config = image_client.refresh_config()
                        if refreshed_config:
                            camera_config = refreshed_config
                        recorder.camera_config = camera_config
                        _logger.info("相机配置刷新完成")
                    except Exception as e:
                        _logger.error(f"刷新相机配置失败: {e}")
                    continue

                # 开机复位（唤醒）
                if cmd == TeleopCommand.INIT_RESET:
                    # 仅在 WAIT_HOME_CONFIRM 状态有效
                    if state == STATE_INACTIVE:
                        _logger.info("API 触发唤醒回零")
                        arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                        if waist_enabled:
                            waist_ctrl_send.ctrl_waist_go_home(block=False)
                        if head_enabled:
                            head_ctrl_send.ctrl_head_go_home(block=False)
                        exit_pending = False
                        state = STATE_RETURNING_HOME
                    else:
                        _logger.warning(f"当前状态 {state} 不允许唤醒，仅在 INACTIVE 有效")
                    continue

                # 回零命令（无论状态，只要不是退出/回零中）
                if cmd == TeleopCommand.GO_HOME:
                    if state not in (STATE_INACTIVE, STATE_RETURNING_HOME):
                        _logger.info("API 触发回零")
                        # 如果是主动控制状态，先释放控制权
                        if state == STATE_ACTIVE_CONTROL:
                            shared_state.release_control()
                        arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                        if waist_enabled:
                            waist_ctrl_send.ctrl_waist_go_home(block=False)
                        if head_enabled:
                            head_ctrl_send.ctrl_head_go_home(block=False)
                        exit_pending = False
                        state = STATE_RETURNING_HOME
                    else:
                        _logger.warning(f"当前状态 {state} 不允许回零")
                    continue

                # 启动遥操作
                if cmd == TeleopCommand.START_TELEOP:
                    # 只有空闲状态且控制锁空闲时才允许启动
                    if state == STATE_IDLE and not shared_state.control_lock:
                        if shared_state.acquire_control("API"):
                            _logger.info("API 获取控制权，进入 ACTIVE_CONTROL")
                            state = STATE_ACTIVE_CONTROL
                    else:
                        _logger.warning(f"无法启动遥操作：state={state}, control_lock={shared_state.control_lock}")
                    continue

                # 停止遥操作
                if cmd == TeleopCommand.STOP_TELEOP:
                    if state == STATE_ACTIVE_CONTROL and shared_state.get_control_source() == "API":
                        shared_state.release_control()
                        if is_recording:
                            recorder.save_episode()
                            is_recording = False
                            _logger.info("API 停止录制")
                        state = STATE_IDLE
                    continue

                # 开始录制
                if cmd == TeleopCommand.START_RECORD:
                    if state == STATE_ACTIVE_CONTROL and not is_recording:
                        # 传入 task_info
                        task_info = data.get("task_info")
                        if recorder.create_episode(task_info):
                            is_recording = True
                            _logger.info("API 开始录制")
                    else:
                        _logger.warning(f"无法开始录制：state={state}, is_recording={is_recording}")
                    continue

                # 停止录制
                if cmd == TeleopCommand.STOP_RECORD:
                    if is_recording:
                        recorder.save_episode()
                        is_recording = False
                        _logger.info("API 停止录制")
                    continue

            if keyboard_state.emergency_stop_requested:
                keyboard_state.emergency_stop_requested = False
                if state != STATE_INACTIVE:
                    _logger.warning("键盘紧急停止触发")
                    shared_state.set_emergency_stop()
                    arm_ctrl_send.left_arm_controller.stop(block=False)
                    arm_ctrl_send.right_arm_controller.stop(block=False)
                    arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                    if waist_enabled:
                        waist_ctrl_send.ctrl_waist_go_home(block=False)
                    if head_enabled:
                        head_ctrl_send.ctrl_head_go_home(block=False)
                    if state == STATE_ACTIVE_CONTROL:
                        shared_state.release_control()
                    exit_pending = True
                    state = STATE_RETURNING_HOME
                continue

            new_active_task = shared_state.get_active_task()
            if new_active_task is not None and new_active_task != current_recorder_task_id:
                # 任务已切换，需要重建录制器
                if is_recording:
                    # 如果正在录制，先停止录制并保存当前片段
                    _logger.warning("任务切换时正在录制，自动停止录制并保存")
                    recorder.save_episode()
                    is_recording = False
                # 关闭旧录制器
                recorder.close()
                # 更新当前任务路径
                current_recorder_task_id = new_active_task
                current_task_path = os.path.join(task_dir_root, new_active_task)
                # 确保任务目录存在
                os.makedirs(current_task_path, exist_ok=True)
                # 创建新录制器
                recorder = EpisodeWriter(
                    task_dir=current_task_path,
                    frequency=frequency,
                    rerun_log=False,
                    save_config=system_cfg.get("recording", {}),
                    camera_config=camera_config,
                )
                _logger.info(f"录制器已切换到任务: {new_active_task}，路径: {current_task_path}")
            tele_data = tv_wrapper.get_motion_state_data()  # 获取VR输入数据
            tele_state = tele_data.tele_state               # VR按钮状态

            # - 右手 A: 唤醒并回零（仅在 INACTIVE 态有效）
            # - 右手 B: 退出遥操作，回零后进入 INACTIVE
            # - 左手 X+Y：手动回零（若在录制中，回零过程将被录制，回零完成后自动停止录制）
            # - 左手 X：启停遥操作，停止遥操作时会停止录制
            # - 左手 Y：开启/关闭录制
            # - 左手 扳机键：灵巧手握持或松开(按下=握持，松开=松开)
            # - 右手 扳机键：灵巧手握持或松开(按下=握持，松开=松开)
            right_a_only = bool(tele_state.right_aButton and not tele_state.right_bButton)
            right_b_only = bool(tele_state.right_bButton and not tele_state.right_aButton)
            left_x_only = bool(tele_state.left_aButton and not tele_state.left_bButton)
            left_y_only = bool(tele_state.left_bButton and not tele_state.left_aButton)
            left_xy = bool(tele_state.left_aButton and tele_state.left_bButton)

            # 边沿检测：只触发一次
            right_a_rising = edge_detector.rising("right_a_only", right_a_only)
            right_b_rising = edge_detector.rising("right_b_only", right_b_only)
            left_x_rising = edge_detector.rising("left_x_only", left_x_only)
            left_y_rising = edge_detector.rising("left_y_only", left_y_only)
            left_xy_rising = edge_detector.rising("left_xy", left_xy)

            # 控制源互斥（API 持有时屏蔽 XR 按钮）
            control_held_by_api = (shared_state.control_lock and shared_state.get_control_source() == "API")
            if control_held_by_api:
                # 屏蔽所有手柄按钮
                right_a_rising = False
                right_b_rising = False
                left_xy_rising = False
                left_x_rising = False
                left_y_rising = False

            current_web_connected = tv_wrapper.is_xr_web_connected()
            if not current_web_connected and last_web_connected:
                # 下降沿：断开连接，执行退出回零
                if state not in (STATE_INACTIVE, STATE_RETURNING_HOME):
                    _logger.info("检测到 XR 网页断开，触发退出回零")
                    arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                    if waist_enabled:
                        waist_ctrl_send.ctrl_waist_go_home(block=False)
                    if head_enabled:
                        head_ctrl_send.ctrl_head_go_home(block=False)
                    if state == STATE_ACTIVE_CONTROL:
                        shared_state.release_control()
                    exit_pending = True
                    state = STATE_RETURNING_HOME
            last_web_connected = current_web_connected

            # 状态机负责统一处理唤醒、待机、主动控制、回零和退出。

            # INACTIVE: 等待唤醒
            if state == STATE_INACTIVE:
                if right_a_rising:
                    _logger.info("INACTIVE: 收到右手 A 唤醒指令，开始回零")
                    arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                    if waist_enabled:
                        waist_ctrl_send.ctrl_waist_go_home(block=False)
                    if head_enabled:
                        head_ctrl_send.ctrl_head_go_home(block=False)
                    exit_pending = False
                    state = STATE_RETURNING_HOME

            # IDLE: 等待进入控制或回零
            elif state == STATE_IDLE:
                if right_b_rising:        # 退出,回到XR未唤醒状态
                    _logger.info("IDLE: 收到右手 B 退出指令，开始回零")
                    arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                    if waist_enabled:
                        waist_ctrl_send.ctrl_waist_go_home(block=False)
                    if head_enabled:
                        head_ctrl_send.ctrl_head_go_home(block=False)
                    # 若之前有控制权（理论上 IDLE 无控制权，但安全释放）
                    if shared_state.control_lock:
                        shared_state.release_control()
                    exit_pending = True
                    state = STATE_RETURNING_HOME
                elif left_xy_rising:
                    _logger.info("IDLE: 收到手动回零指令")
                    arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                    if waist_enabled:
                        waist_ctrl_send.ctrl_waist_go_home(block=False)
                    if head_enabled:
                        head_ctrl_send.ctrl_head_go_home(block=False)
                    exit_pending = False
                    state = STATE_RETURNING_HOME
                elif left_x_rising:      # 开始遥操
                    # 尝试获取控制权（如果是手柄触发，控制源为 XR）
                    if not shared_state.acquire_control("XR"):
                        _logger.warning("IDLE: 无法获取 XR 控制权，可能被 API 占用")
                    else:
                        _logger.info("IDLE: 进入 ACTIVE_CONTROL")
                        state = STATE_ACTIVE_CONTROL
                # 左手Y 在 IDLE 下无效（不处理）

            # ACTIVE_CONTROL: 执行控制与录制
            elif state == STATE_ACTIVE_CONTROL:
                if right_b_rising:      # 退出
                    _logger.info("ACTIVE_CONTROL: 收到右手 B 退出指令，释放控制并回零")
                    shared_state.release_control()
                    arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                    if waist_enabled:
                        waist_ctrl_send.ctrl_waist_go_home(block=False)
                    if head_enabled:
                        head_ctrl_send.ctrl_head_go_home(block=False)
                    exit_pending = True
                    state = STATE_RETURNING_HOME
                elif left_xy_rising:     # 手动回零
                    _logger.info("ACTIVE_CONTROL: 收到手动回零指令，释放控制并回零")
                    shared_state.release_control()
                    arm_ctrl_send.ctrl_dual_arm_go_home(block=False)
                    if waist_enabled:
                        waist_ctrl_send.ctrl_waist_go_home(block=False)
                    if head_enabled:
                        head_ctrl_send.ctrl_head_go_home(block=False)
                    exit_pending = False
                    state = STATE_RETURNING_HOME
                elif left_x_rising:      # 停止遥操
                    _logger.info("ACTIVE_CONTROL: 停止遥操作(手柄)")
                    shared_state.release_control()
                    if is_recording:
                        recorder.save_episode()
                        is_recording = False
                        _logger.info("停止遥操时停止录制。")
                    state = STATE_IDLE
                elif left_y_rising:      # 切换录制状态
                    if not is_recording:
                        if recorder.create_episode():
                            is_recording = True
                            _logger.info("录制开始（手柄）。")
                        else:
                            _logger.warning("录制器不可用，无法开始录制")
                    else:
                        recorder.save_episode()
                        is_recording = False 
                        _logger.info("录制停止（手柄）。")

            # RETURNING_HOME: 回零完成后进入 INACTIVE 或 IDLE
            elif state == STATE_RETURNING_HOME:
                _logger.debug("RETURNING_HOME: 回零中")
                should_record_returning_home = True
                # 检测回零是否完成，关闭 waist 时，回零完成判定只依赖双臂，避免流程卡在外轴。
                arm_home_ok = arm_ctrl_send.check_dual_arm_home()
                head_home_ok = (not head_enabled) or head_ctrl_send.check_head_home()
                waist_home_ok = (not waist_enabled) or waist_ctrl_send.check_waist_home()
                if arm_home_ok and waist_home_ok and head_home_ok:
                    _logger.info("RETURNING_HOME: 回零完成")
                    tv_wrapper.start_head_pose()
                    arm_ctrl_send.speed_reset()
                    if head_enabled:
                        _logger.info("RETURNING_HOME: 回零完成，头部关节回零")
                        head_ctrl_send.speed_reset()
                    if waist_enabled:
                        _logger.info("RETURNING_HOME: 回零完成，腰部关节回零")
                        waist_ctrl_send.speed_reset()
                    shared_state.clear_emergency_stop()
                    if exit_pending:
                        _logger.info("回零完成，进入 INACTIVE 状态")
                        state = STATE_INACTIVE
                        exit_pending = False
                    else:
                        _logger.info("回零完成，进入 IDLE 状态")
                        state = STATE_IDLE
                    if is_recording:
                        _logger.info("回零完成，停止录制")
                        finalize_recording_after_frame = True

            colors, depths, head_image, head_depth, left_wrist_image, right_wrist_image = collect_camera_payload(
                image_client, camera_config
            )
            # 渲染到XR
            if head_image is not None and system_cfg["xr"]["display_mode"] != "pass-through" and not tv_wrapper.tvuer.webrtc:
                # WebRTC 未启用时采用 ZMQ 中转
                tv_wrapper.render_to_xr(head_image)
            # 显示本地图像窗口
            if not headless:
                preview_shown = show_debug_image(
                    head_image,
                    head_depth,
                    left_wrist_image,
                    right_wrist_image,
                    [640, 480]
                )
                if preview_shown:
                    cv2.waitKey(1)

            if state == STATE_ACTIVE_CONTROL:
                # 机械臂以末端位姿为主控制量，IK 目前仅作为接口兼容层保留。
                # 获取当前机器人关节角度
                try:
                    current_lr_arm_q = arm_ctrl_recv.get_actual_joints_position()
                    current_lr_arm_world_pose = arm_ctrl_recv.get_actual_world_pose()
                    if head_enabled:
                        head_joint = tv_wrapper.head_joint_from_robot_world_pose(current_lr_arm_world_pose[0], current_lr_arm_world_pose[1])
                    else:
                        head_joint = None
                except Exception as e:
                    _logger.warning(f"读取关节状态失败: {e}")
                    current_lr_arm_q = None
                    current_lr_arm_world_pose = None
                    head_joint = None
                if current_lr_arm_q is not None:
                    target_lr_arm_pose = np.array([tele_data.left_arm_pose, tele_data.right_arm_pose], dtype=np.float64)
                    sol_q = arm_ik.solve_ik(tele_data.left_arm_pose, tele_data.right_arm_pose, current_lr_arm_q)
                    arm_ctrl_send.ctrl_dual_arm(target_lr_arm_pose, sol_q)
                    if head_enabled and head_joint is not None:
                        head_ctrl_send.ctrl_head(head_joint)
                    if waist_enabled and tele_data.waist_pose is not None:
                        # 半身:1个关节采用关节目标控制,全身:4个关节，采用笛卡尔目标控制
                        waist_ctrl_send.ctrl_waist(tele_data.waist_pose)
                    if input_mode == "controller":
                        hand_ctrl.set_target(tele_data.left_trigger_value or 10.0, tele_data.right_trigger_value or 10.0)
                    else:
                        hand_ctrl.set_target(tele_data.left_pinch_value or 10.0, tele_data.right_pinch_value or 10.0)

                    hand_state = hand_ctrl.get_state()
                    if is_recording:
                        head_state_qpos = head_ctrl_recv.get_actual_head_position().tolist()
                        head_action_qpos = head_joint.tolist() if head_enabled and head_joint is not None else []
                        waist_state_qpos = waist_ctrl_recv.get_actual_waist_position().tolist()
                        # 半身:关节角度,全身:笛卡尔位姿
                        waist_action_qpos = tele_data.waist_pose.tolist() if waist_enabled and tele_data.waist_pose is not None else []
                        states = {
                            "head": {"qpos": head_state_qpos},
                            "left_arm": {"qpos": current_lr_arm_q[0].tolist()},
                            "right_arm": {"qpos": current_lr_arm_q[1].tolist()},
                            "left_ee": {"qpos": hand_state["left"]["states"]},
                            "right_ee": {"qpos": hand_state["right"]["states"]},
                            "waist": {"qpos": waist_state_qpos},
                        }
                        actions = {
                            "head": {"qpos": head_action_qpos},
                            "left_arm": {"qpos": target_lr_arm_pose[0].tolist()},
                            "right_arm": {"qpos": target_lr_arm_pose[1].tolist()},
                            "left_ee": {"qpos": hand_state["left"]["action"]},
                            "right_ee": {"qpos": hand_state["right"]["action"]},
                            "waist": {"qpos": waist_action_qpos},
                        }
                        recorder.add_item(colors=colors, depths=depths, states=states, actions=actions)

            # 回零过程中也录制数据
            elif should_record_returning_home and state != STATE_INACTIVE and is_recording:
                robot_home = robot_cfg["robot"]
                home_waist_rad = robot_home["home_half_waist_rad"] if upper_body else robot_home["home_full_waist_rad"]
                lr_arm_current_q = arm_ctrl_recv.get_actual_joints_position()
                arm_type = robot_home["arm_type"]
                if arm_type == "p_arm":
                    home_arm_joint_deg = robot_home["home_arm_joint_deg_p"]
                else:
                    home_arm_joint_deg = robot_home["home_arm_joint_deg"]
                lr_arm_target_q = np.asarray([
                    np.deg2rad(home_arm_joint_deg["left"]),
                    np.deg2rad(home_arm_joint_deg["right"]),
                ], dtype=np.float64)
                hand_state = hand_ctrl.get_state()
                current_head_joint = head_ctrl_recv.get_actual_head_position()
                target_head_joint = np.asarray(robot_home["home_head_rad"], dtype=np.float64)
                current_waist_qpos = waist_ctrl_recv.get_actual_waist_position()
                target_waist_qpos = np.asarray(home_waist_rad, dtype=np.float64)
                states = {
                    "head": {"qpos": current_head_joint.tolist()},
                    "left_arm": {"qpos": lr_arm_current_q[0].tolist()},
                    "right_arm": {"qpos": lr_arm_current_q[1].tolist()},
                    "left_ee": {"qpos": hand_state["left"]["states"]},
                    "right_ee": {"qpos": hand_state["right"]["states"]},
                    "waist": {"qpos": current_waist_qpos.tolist()},
                }
                actions = {
                    "head": {"qpos": target_head_joint.tolist()},
                    "left_arm": {"qpos": lr_arm_target_q[0].tolist()},
                    "right_arm": {"qpos": lr_arm_target_q[1].tolist()},
                    "left_ee": {"qpos": hand_state["left"]["action"]},
                    "right_ee": {"qpos": hand_state["right"]["action"]},
                    "waist": {"qpos": target_waist_qpos.tolist()},
                }
                recorder.add_item(colors=colors, depths=depths, states=states, actions=actions)

            # 回零完成后自动停止录制
            if finalize_recording_after_frame and is_recording:
                recorder.save_episode()
                is_recording = False
                _logger.info("回零完成后自动停止录制。")

            # 更新遥操作状态
            shared_state.update_teleop_state(state)

            # 更新 XR 状态
            last_pose_time = tv_wrapper.get_xr_last_pose_time()
            xr_active = tv_wrapper.is_xr_active(timeout=10.0)      # VR 设备活跃（基于移动事件）
            xr_web_alive = tv_wrapper.is_xr_web_connected()        # 网页连接存活

            shared_state.update_xr_status(
                xr_active=xr_active,
                xr_web_connected=xr_web_alive,
                last_pose_time=last_pose_time if xr_active else None
            )

            # 更新录制状态
            frame_count = recorder.item_id + 1 if is_recording else 0
            episode_id_str = f"episode_{recorder.episode_id:04d}" if is_recording and hasattr(recorder, 'episode_id') else None
            shared_state.update_record_status(
                is_recording=is_recording,
                episode_id=episode_id_str,
                start_time=recorder.episode_start_time if is_recording else None,
                frame_count=frame_count
            )

            # 更新机器人关节状态
            try:
                robot_joints = arm_ctrl_recv.get_actual_joints_position()
                robot_tcp = arm_ctrl_recv.get_actual_tcp_pose()
                head_qpos = head_ctrl_recv.get_actual_head_position()
                waist_qpos = waist_ctrl_recv.get_actual_waist_position()
                shared_state.update_robot_status(
                    head_qpos=head_qpos.tolist(),
                    left_arm_qpos=robot_joints[0].tolist(),
                    right_arm_qpos=robot_joints[1].tolist(),
                    left_arm_tcp=robot_tcp[0].tolist(),
                    right_arm_tcp=robot_tcp[1].tolist(),
                    waist_qpos=waist_qpos.tolist(),
                )
            except Exception as e:
                _logger.warning(f"更新机器人关节状态失败: {e}")

            # 控制循环频率
            elapsed = time.time() - loop_start
            time.sleep(max(0.0, (1.0 / frequency) - elapsed))

    except KeyboardInterrupt:
        _logger.info("接收到中断信号，准备退出。")
    except Exception as exc:
        _logger.exception(f"主程序异常: {exc}")
    finally:
        _logger.info("开始执行清理流程。")
        _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
        # 关闭独立的外部资源
        tv_wrapper.close()
        if image_client is not None:
            image_client.close()
        stop_listening()
        keyboard_thread.join(timeout=1.0)
        try:
            arm_ctrl_send.ctrl_dual_arm_go_home(block=True)
        except Exception as exc:
            _logger.warning(f"双臂回零失败: {exc}")
        if head_enabled:
            try:
                head_ctrl_send.ctrl_head_go_home(block=True)
            except Exception as exc:
                _logger.warning(f"头部回零失败: {exc}")
        if waist_enabled:
            try:
                waist_ctrl_send.ctrl_waist_go_home(block=True)
            except Exception as exc:
                _logger.warning(f"腰部回零失败: {exc}")
        # 保存未完成的录制
        if is_recording and "recorder" in locals():
            recorder.save_episode()
        # 关闭所有组件
        if "recorder" in locals():
            recorder.close()
        hand_ctrl.close()
        arm_ctrl_send.close()
        arm_ctrl_recv.close()
        if head_enabled:
            head_ctrl_send.close()
        head_ctrl_recv.close()
        if waist_enabled:
            waist_ctrl_send.close()
        waist_ctrl_recv.close()
        cv2.destroyAllWindows()
        _logger.info("遥操数采程序已退出。")
        shutdown_logging()


if __name__ == "__main__":
    main()
