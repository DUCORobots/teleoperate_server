import math
import os
import sys
import threading
import time
from typing import Optional

import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
teleop_dir = os.path.dirname(current_dir)
if teleop_dir not in sys.path:
    sys.path.append(teleop_dir)

for dependency_dir in ("gen_py", "lib"):
    dependency_path = os.path.join(teleop_dir, dependency_dir)
    if dependency_path not in sys.path:
        sys.path.append(dependency_path)

from DucoCobot import DucoCobot
from teleop.log_manager import get_logger

_logger = get_logger(__name__)

def _ensure_shape(name: str, value, shape):
    """
    统一做数组维度校验,防止控制指令形状错误直接下发到真机
    机械臂控制核心安全函数：校验指令数组的维度是否正确
    防止错误维度的指令下发到真机,避免机械臂失控
    :param name: 参数名称（报错时提示）
    :param value: 待校验的参数值
    :param shape: 期望的维度(如(2,7)代表双臂7关节)
    :return: 标准化后的numpy数组
    """
    array = np.asarray(value, dtype=np.float64)
    if array.shape != shape:
        raise ValueError(f"{name} 维度错误，期望 {shape}，实际 {array.shape}")
    return array

class SimRicoArmBackend:
    """仿真占位后端
    不连接真实机械臂，仅缓存最近一次下发的指令和状态
    上层代码调试、状态机测试、无硬件环境开发 让上层状态机和录制链路在 `--sim` 模式下仍然可运行
    """

    def __init__(self, robot_config):
        # 从配置文件读取机械臂初始回零关节角度（度→弧度）
        arm_type = robot_config["robot"]["arm_type"]
        if arm_type == "p_arm":
            home_arm_joint_deg = robot_config["robot"]["home_arm_joint_deg_p"]
        else:
            home_arm_joint_deg = robot_config["robot"]["home_arm_joint_deg"]
        self._joint_state = np.array(
            [
                np.deg2rad(home_arm_joint_deg["left"]),   # 左臂初始关节
                np.deg2rad(home_arm_joint_deg["right"]),  # 右臂初始关节
            ],
            dtype=np.float64,
        )
        # 末端执行器(TCP)位姿缓存（2臂×6维度：x,y,z,rx,ry,rz）
        self._tcp_state = np.zeros((2, 6), dtype=np.float64)
        self._world_state = np.zeros((2, 6), dtype=np.float64)
        self._home_running = False  # 回零状态标志

    def ctrl_dual_arm(self, target_pose, target_joint_hint=None):
        """仿真：缓存目标位姿/关节指令"""
        self._tcp_state = _ensure_shape("target_pose", target_pose, (2, 6))
        if target_joint_hint is not None:
            self._joint_state = _ensure_shape("target_joint_hint", target_joint_hint, (2, 7))

    def ctrl_dual_arm_go_home(self, target_joint_rad):
        """仿真：缓存回零指令"""
        self._joint_state = _ensure_shape("target_joint_rad", target_joint_rad, (2, 7))
        self._world_state = np.zeros((2, 6), dtype=np.float64)
        self._home_running = False

    def check_dual_arm_home(self):
        """仿真：默认回零完成"""
        return True

    def get_actual_joints_position(self):
        """仿真：返回缓存的关节状态"""
        return self._joint_state.copy()

    def get_actual_tcp_pose(self):
        """仿真：返回缓存的末端位姿"""
        return self._tcp_state.copy()

    def get_actual_world_pose(self):
        """仿真：返回缓存的世界坐标系位姿"""
        return self._world_state.copy()

    def close(self):
        """仿真：空实现，无资源释放"""
        return

class RICO_ArmController:
    """
    RICO 双臂控制器。

    只保留实际需要的 RICO 机械臂控制逻辑：
    - 真机模式下通过 `DucoCobot` 下发位姿伺服和回零命令；
    - 仿真模式下保留同样的调用接口,但内部只做状态缓存，方便后续继续补齐。
    """

    def __init__(self, robot_config, simulation_mode: bool = False, state_poll_hz: float = 60.0, is_resv_mode: bool = False):
        """
        初始化控制器并启动状态轮询线程
        :param robot_config: 机械臂配置文件(IP、端口、回零位、伺服参数等)
        :param simulation_mode: True=仿真模式, False=真机模式
        :param state_poll_hz: 状态轮询频率(默认60Hz,保证实时性)
        :param is_resv_mode: 是否启用后台状态轮询线程
        """
        self.robot_config = robot_config          # 机械臂配置
        self.simulation_mode = simulation_mode    # 模式标志
        self.state_poll_hz = state_poll_hz        # 状态轮询频率
        self.is_resv_mode = is_resv_mode          # 线程轮询标志
        self._speed_flag = 0                      # 速度爬升计数器（防启动突变）
        self._running = True                      # 线程运行标志

        # 线程安全缓存：最新的关节/末端位姿（多线程读写加锁）
        self._last_joint_state = np.zeros((2, 7), dtype=np.float64)  # 2臂×7关节
        self._last_tcp_state = np.zeros((2, 6), dtype=np.float64)    # 2臂×6位姿
        self._last_world_state = np.zeros((2, 6), dtype=np.float64)  # 2臂×6世界坐标系位姿
        self._left_status = -100                  # 左臂任务状态
        self._right_status = -100                 # 右臂任务状态
        self._home_completed = False              # 回零完成标志
        self._state_lock = threading.Lock()       # 线程锁：保护状态数据
        self._last_poll_error_log_time = 0.0      # 轮询异常日志限频时间戳
        self._poll_error_log_interval_s = 5.0     # 轮询异常日志最小间隔（秒）

        # 读取配置：回零关节角度（度→弧度）
        robot_cfg = robot_config["robot"]
        arm_type = robot_cfg["arm_type"]
        if arm_type == "p_arm":
            home_arm_joint_deg = robot_cfg["home_arm_joint_deg_p"]
        else:
            home_arm_joint_deg = robot_cfg["home_arm_joint_deg"]
        self._home_joint_rad = np.array(
            [
                np.deg2rad(home_arm_joint_deg["left"]),
                np.deg2rad(home_arm_joint_deg["right"]),
            ],
            dtype=np.float64,
        )

        if self.simulation_mode:
            self._backend = SimRicoArmBackend(robot_config)  # 初始化仿真后端
            self._poll_thread = None                         # 仿真无轮询线程
            return

        # 真机模式：初始化左右臂控制器（连接机械臂）
        ip = robot_cfg["ip"]
        self.left_arm_controller = DucoCobot(ip, int(robot_cfg["left_arm_port"]))
        self.right_arm_controller = DucoCobot(ip, int(robot_cfg["right_arm_port"]))
        self.left_arm_controller.open()   # 打开左臂连接
        self.right_arm_controller.open()  # 打开右臂连接
        self.left_arm_controller.enable_servo_optimization(True,True,True)
        self.right_arm_controller.enable_servo_optimization(True,True,True)

        # 启用状态轮询：启动后台线程实时读取机械臂状态
        if is_resv_mode:
            self._poll_thread = threading.Thread(target=self._poll_state_loop, daemon=True)
            self._poll_thread.start()
        else:
            self._poll_thread = None

    def _poll_state_loop(self):
        """
        后台状态轮询线程（真机专用）
        周期读取机械臂的关节/末端位姿，缓存到本地，保证上层读取实时性，供主循环和录制器使用
        """
        interval = 1.0 / max(self.state_poll_hz, 1.0)  # 轮询间隔
        while self._running:
            try:
                # 读取双臂关节角度
                joint_state = np.array(
                    [
                        self.left_arm_controller.get_target_joints_position(),
                        self.right_arm_controller.get_target_joints_position(),
                    ],
                    dtype=np.float64,
                )
                # 读取双臂末端基座标系位姿
                tcp_state = np.array(
                    [
                        self.left_arm_controller.get_tcp_pose(),
                        self.right_arm_controller.get_tcp_pose(),
                    ],
                    dtype=np.float64,
                )
                # 读取双臂世界坐标系位姿
                world_state = np.array(
                    [
                        self.left_arm_controller.get_tcp_pose_coord("",""),
                        self.right_arm_controller.get_tcp_pose_coord("",""),
                    ],
                    dtype=np.float64,
                )
                # 加锁更新缓存（线程安全）
                with self._state_lock:
                    self._last_joint_state = joint_state
                    self._last_tcp_state = tcp_state
                    self._last_world_state = world_state
            except Exception as exc:
                # 读取失败：沿用上一帧数据，不崩溃
                now = time.monotonic()
                if now - self._last_poll_error_log_time >= self._poll_error_log_interval_s:
                    _logger.warning(f"读取 RICO 双臂状态失败，本帧沿用上一帧数据: {exc}")
                    self._last_poll_error_log_time = now
            time.sleep(interval)

    def _get_servo_speed(self) -> float:
        """
        速度平滑爬升算法
        机械臂启动时速度从慢到快平滑提升，避免启动突变导致晃动/失控
        按照配置中的爬升策略平滑提高伺服速度，减少启动突变
        """
        servo_cfg = self.robot_config["robot"]["servo"]
        self._speed_flag += 1
        ramp_steps = max(int(servo_cfg["ramp_steps"]), 1)  # 爬升步数
        ratio = min(self._speed_flag / ramp_steps, 1.0)    # 爬升比例（0→1）
        # 计算当前速度：最小速度 + 比例×(最大速度-最小速度)
        return float(servo_cfg["arm_speed_min_cart"] + ratio * (servo_cfg["arm_speed_max_cart"] - servo_cfg["arm_speed_min_cart"]))

    def speed_reset(self):
        """在回零或重新开始控制后重置速度爬升计数。"""
        self._speed_flag = 0

    def ctrl_dual_arm_go_home(self, block: bool = True):
        """
        双臂自动回零
            :param block: True=阻塞等待回零完成,False=非阻塞
        控制双臂回到配置文件中的 home 关节位姿。
        """
        with self._state_lock:
            self._home_completed = False
        if self.simulation_mode:
            self._backend.ctrl_dual_arm_go_home(self._home_joint_rad)
            return
        _logger.info("-- 双臂正在回到 home 关节位，请等待......")
        # 先停止机械臂当前运动
        self.left_arm_controller.stop(block=True)
        self.right_arm_controller.stop(block=True)

        # 下发关节回零指令（movej：关节空间运动）
        with self._state_lock:
            self._left_status = self.left_arm_controller.movej2(
                self._home_joint_rad[0].tolist(),
                float(self.robot_config["robot"]["servo"]["home_velocity"]),
                float(self.robot_config["robot"]["servo"]["home_acceleration"]),
                0,
                False,
            )
            self._right_status = self.right_arm_controller.movej2(
                self._home_joint_rad[1].tolist(),
                float(self.robot_config["robot"]["servo"]["home_velocity"]),
                float(self.robot_config["robot"]["servo"]["home_acceleration"]),
                0,
                False,
            )

        # 阻塞模式：等待回零完成
        if block:
            time.sleep(0.01)
            while not self.check_dual_arm_home():
                time.sleep(0.01)
            _logger.info("-- 双臂已回到 home 关节位")

    def check_dual_arm_home(self) -> bool:
        """检查双臂非阻塞回零任务是否完成。"""
        if self.simulation_mode:
            return self._backend.check_dual_arm_home()

        with self._state_lock:
            if self._home_completed:
                return True
            # 查询真机非阻塞任务状态
            left_status = self.left_arm_controller.get_noneblock_taskstate(self._left_status)
            right_status = self.right_arm_controller.get_noneblock_taskstate(self._right_status)
            left_done = left_status >= 4
            right_done = right_status >= 4
            if left_done and right_done:
                self._left_status = -100
                self._right_status = -100
                self._home_completed = True
                return True
            return False

    def get_actual_joints_position(self) -> np.ndarray:
        """对外接口:获取当前双臂关节角度(2,7)"""
        if self.simulation_mode:
            return self._backend.get_actual_joints_position()
        with self._state_lock:
            return self._last_joint_state.copy()

    def get_actual_tcp_pose(self) -> np.ndarray:
        """对外接口:获取当前双臂末端位姿(2,6)"""
        if self.simulation_mode:
            return self._backend.get_actual_tcp_pose()
        with self._state_lock:
            return self._last_tcp_state.copy()

    def get_actual_world_pose(self) -> np.ndarray:
        """对外接口:获取当前双臂世界坐标系位姿(2,6)"""
        if self.simulation_mode:
            return self._backend.get_actual_world_pose()
        with self._state_lock:
            return self._last_world_state.copy()

    def ctrl_dual_arm(self, target_tcp_or_pose, target_joint_hint: Optional[np.ndarray] = None, block: bool = False):
        """
        核心控制接口：下发双臂末端位姿伺服指令
        :param target_tcp_or_pose: 目标位姿 (2,6) [左臂, 右臂][x,y,z,rx,ry,rz]
        :param target_joint_hint: 用于给底层控制器提供关节参考，关节参考值（可选，提升控制精度）
        :param block: 是否阻塞执行
        """
        # 严格校验目标位姿维度
        target_pose = _ensure_shape("target_tcp_or_pose", target_tcp_or_pose, (2, 6))

        # 无关节参考值时，使用当前关节状态
        if target_joint_hint is None:
            target_joint_hint = self.get_actual_joints_position()
        else:
            target_joint_hint = _ensure_shape("target_joint_hint", target_joint_hint, (2, 7))

        # 仿真模式：仅缓存指令
        if self.simulation_mode:
            self._backend.ctrl_dual_arm(target_pose, target_joint_hint)
            return

        # 真机模式：获取平滑爬升的速度
        servo_cfg = self.robot_config["robot"]["servo"]
        speed = self._get_servo_speed()

        # 下发左臂位姿伺服指令（servoj_pose：末端位姿实时伺服）
        self.left_arm_controller.servoj_pose(
            target_pose[0].tolist(),
            speed,
            float(servo_cfg["arm_acceleration_cart"]),
            target_joint_hint[0].tolist(),
            self.robot_config["robot"]["left_arm_tcp_frame"],
            self.robot_config["robot"]["left_arm_base_frame"],
            block,
            int(servo_cfg["lookahead_time_ms"]),
            int(servo_cfg["gain"]),
            int(servo_cfg["blend"]),
        )
        # 下发右臂位姿伺服指令
        self.right_arm_controller.servoj_pose(
            target_pose[1].tolist(),
            speed,
            float(servo_cfg["arm_acceleration_cart"]),
            target_joint_hint[1].tolist(),
            self.robot_config["robot"]["right_arm_tcp_frame"],
            self.robot_config["robot"]["right_arm_base_frame"],
            block,
            int(servo_cfg["lookahead_time_ms"]),
            int(servo_cfg["gain"]),
            int(servo_cfg["blend"]),
        )

    def close(self):
        """
        资源释放：关闭轮询线程、断开底层机械臂连接
        程序退出时必须调用，防止硬件卡死
        """
        self._running = False
        # 等待轮询线程退出
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2.0)
        # 仿真模式：关闭仿真后端
        if self.simulation_mode:
            self._backend.close()
            return
        # 真机模式：断开左右臂连接
        for controller in (self.left_arm_controller, self.right_arm_controller):
            try:
                controller.close()
            except Exception as exc:
                _logger.warning(f"关闭机械臂连接失败: {exc}")