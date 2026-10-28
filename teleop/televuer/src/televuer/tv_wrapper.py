import math
from dataclasses import dataclass, field
from typing import Literal, Optional
import numpy as np

from .televuer import TeleVuer

from teleop.log_manager import get_logger

_logger = get_logger(__name__)


def safe_mat_update(prev_mat: np.ndarray, mat: np.ndarray):
    """矩阵异常时回退到上一帧，避免姿态链路被脏数据打断，(防机器人失控)"""
    det = np.linalg.det(mat)
    if not np.isfinite(det) or np.isclose(det, 0.0, atol=1e-6):
        return prev_mat, False
    return mat, True


def safe_rot_update(prev_rot_array: np.ndarray, rot_array: np.ndarray):
    """批量旋转矩阵异常时回退到上一帧。"""
    dets = np.linalg.det(rot_array)
    if not np.all(np.isfinite(dets)) or np.any(np.isclose(dets, 0.0, atol=1e-6)):
        return prev_rot_array, False
    return rot_array, True


def fast_mat_inv(mat: np.ndarray):
    """快速求取 SE(3) 变换矩阵的逆，快速求变换矩阵逆矩阵(机器人运动学专用)"""
    ret = np.eye(4)
    ret[:3, :3] = mat[:3, :3].T
    ret[:3, 3] = -mat[:3, :3].T @ mat[:3, 3]
    return ret


def rot2euler(rotation: np.ndarray):
    """
    旋转矩阵 → 欧拉角(机器人控制标准格式: x,y,z,rx,ry,rz)
    将 4x4 位姿矩阵转换成 `[x, y, z, rx, ry, rz]`。
    """
    sy = math.sqrt(rotation[0, 0] * rotation[0, 0] + rotation[1, 0] * rotation[1, 0])
    singular = sy < 1e-6
    if not singular:
        rx = math.atan2(rotation[2, 1], rotation[2, 2])
        ry = math.atan2(-rotation[2, 0], sy)
        rz = math.atan2(rotation[1, 0], rotation[0, 0])
    else:
        rx = math.atan2(-rotation[1, 2], rotation[1, 1])
        ry = math.atan2(-rotation[2, 0], sy)
        rz = 0.0
    return np.array([rotation[0, 3], rotation[1, 3], rotation[2, 3], rx, ry, rz], dtype=np.float64)


def euler2rot(pose: np.ndarray):
    """将欧拉角位姿转换成 4x4 位姿矩阵。"""
    tx, ty, tz, rx, ry, rz = pose
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rotation = np.array(
        [
            [cy * cz, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [cy * sz, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx],
        ],
        dtype=np.float64,
    )
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = [tx, ty, tz]
    return transform


CONST_HEAD_POSE = np.array([[1, 0, 0, 0], [0, 1, 0, 1.2], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float64)
CONST_LEFT_ARM_POSE = np.array([[1, 0, 0, 0], [0, 1, 0, 1.13], [0, 0, 1, 0.1], [0, 0, 0, 1]], dtype=np.float64)
CONST_RIGHT_ARM_POSE = np.array([[1, 0, 0, 0], [0, 1, 0, 1.13], [0, 0, 1, 0.1], [0, 0, 0, 1]], dtype=np.float64)
CONST_HAND_ROT = np.tile(np.eye(3)[None, :, :], (25, 1, 1))

# 下面四个常量矩阵用于完成 XR 坐标到机器人控制坐标的映射。
T_TO_ROBOT_HAND_LEFT = np.array([[0, 1, 0, 0], [0, 0, -1, 0], [-1, 0, 0, 0], [0, 0, 0, 1]], dtype=np.float64)
T_TO_ROBOT_HAND_RIGHT = np.array([[0, 1, 0, 0], [0, 0, -1, 0], [-1, 0, 0, 0], [0, 0, 0, 1]], dtype=np.float64)
T_ROBOT_OPENXR_LEFT = np.array([[0, -1, 0, 0], [0, 0, 1, 0], [-1, 0, 0, 0], [0, 0, 0, 1]], dtype=np.float64)
T_ROBOT_OPENXR_RIGHT = np.array([[0, -1, 0, 0], [0, 0, -1, 0], [1, 0, 0, 0], [0, 0, 0, 1]], dtype=np.float64)


@dataclass
class TeleStateData:
    """
    按钮/手势状态封装
    统一存放离散按钮状态与模拟量状态。
    """
    left_pinch_state: bool = False
    left_squeeze_state: bool = False
    left_squeeze_value: float = 0.0
    right_pinch_state: bool = False
    right_squeeze_state: bool = False
    right_squeeze_value: float = 0.0

    left_trigger_state: bool = False
    left_squeeze_ctrl_state: bool = False
    left_squeeze_ctrl_value: float = 0.0
    left_thumbstick_state: bool = False
    left_thumbstick_value: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float64))
    left_aButton: bool = False
    left_bButton: bool = False

    right_trigger_state: bool = False
    right_squeeze_ctrl_state: bool = False
    right_squeeze_ctrl_value: float = 0.0
    right_thumbstick_state: bool = False
    right_thumbstick_value: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float64))
    right_aButton: bool = False
    right_bButton: bool = False


@dataclass
class TeleData:
    """
    机器人控制全量数据：头部/手臂/腰部/手势/按钮
    统一存放主程序每一帧需要用到的遥操作数据。
    """
    head_pose: np.ndarray
    left_arm_pose: np.ndarray   # 机器人左臂目标位姿(6维: x,y,z,rx,ry,rz)
    right_arm_pose: np.ndarray  # 机器人右臂目标位姿(6维)
    left_hand_pos: Optional[np.ndarray] = None
    right_hand_pos: Optional[np.ndarray] = None
    left_hand_rot: Optional[np.ndarray] = None
    right_hand_rot: Optional[np.ndarray] = None
    left_pinch_value: Optional[float] = None
    right_pinch_value: Optional[float] = None
    left_trigger_value: Optional[float] = None
    right_trigger_value: Optional[float] = None
    waist_pose: Optional[np.ndarray] = None
    tele_state: TeleStateData = field(default_factory=TeleStateData)


class TeleVuerWrapper:
    """
    VR数据→机器人控制数据 适配层
    TeleVuer 高层封装。

    目标是保留`televuer.py` 的底层通信能力，适配
    RICO 机器人姿态变换、按钮语义和腰/外轴推导逻辑。
    """

    def __init__(
        self,
        upper_body: bool,
        use_hand_tracking: bool,
        binocular: bool = True,
        img_shape=(640, 480),
        display_fps: float = 30.0,
        display_mode: Literal["immersive", "pass-through", "ego"] = "immersive",
        zmq: bool = False,
        webrtc: bool = False,
        webrtc_url: str = None,
        cert_file: str = None,
        key_file: str = None,
        return_state_data: bool = True,
        return_hand_rot_data: bool = False,
        stun_servers: list = None
    ):
        """
        初始化 XR 数据封装层。

        该类的职责不是直接控制机器人，而是把 XR 输出整理成主程序可直接消费的统一格式。
        """
        self.upper_body = upper_body
        self.use_hand_tracking = use_hand_tracking
        self.return_state_data = return_state_data
        self.return_hand_rot_data = return_hand_rot_data
        self.tvuer = TeleVuer(
            use_hand_tracking=use_hand_tracking,
            binocular=binocular,
            img_shape=img_shape,
            display_fps=display_fps,
            display_mode=display_mode,
            zmq=zmq,
            webrtc=webrtc,
            webrtc_url=webrtc_url,
            cert_file=cert_file,
            key_file=key_file,
            stun_servers=stun_servers,
        )

        # 头部姿态对齐基准(控制机器人的核心参考系)
        # `_head_world_alignment` 用于固定操作者开始遥操作时的头部朝向，
        # `_head_start_inverse` 用于计算后续头部相对初始时刻的偏移。
        self._head_world_alignment = np.eye(4, dtype=np.float64)
        self._head_start_inverse = np.eye(4, dtype=np.float64)
        self._head_alignment_ready = False
        # 上一帧有效数据（脏数据回退用）
        self._last_head_pose = CONST_HEAD_POSE.copy()
        self._last_left_arm_pose = CONST_LEFT_ARM_POSE.copy()
        self._last_right_arm_pose = CONST_RIGHT_ARM_POSE.copy()
        self._last_left_hand_rot = CONST_HAND_ROT.copy()
        self._last_right_hand_rot = CONST_HAND_ROT.copy()
        self._half_last_waist_pose = np.array([0.0], dtype=np.float64)
        self._full_last_waist_cart_pose = np.asarray([[0.0] * 6], dtype=np.float64)
        self._waist_start_rot = euler2rot([0.120, 0.0, 0.960, 0.0, 0.0, 0.0])

    def start_head_pose(self):
        """锁定头部初始参考系，作为后续腰部/外轴推导的基准，作为机器人控制的基准坐标系。"""
        head_pose, _ = safe_mat_update(self._last_head_pose, self.tvuer.head_pose)
        self._last_head_pose = head_pose
        if abs(head_pose[0, 1]) < 1e-3 and abs(head_pose[2, 1]) < 1e-3:
            yaw = 0.0
        else:
            # 计算头部朝向对齐矩阵
            head_pose_ = rot2euler(head_pose)
            yaw = -head_pose_[4]

        self._head_world_alignment = np.array(
            [
                [math.cos(yaw), 0, math.sin(yaw), 0],
                [0, 1, 0, 0],
                [-math.sin(yaw), 0, math.cos(yaw), 0],
                [0, 0, 0, 1],
            ],
            dtype=np.float64,
        )
        aligned_head_pose = self._head_world_alignment @ head_pose
        self._head_start_inverse = fast_mat_inv(aligned_head_pose)
        self._head_alignment_ready = True
        _logger.info("头部初始姿态基准已锁定。")

    def _validate_arm_pose(self, arm_pose: np.ndarray, name: str):
        """检查输出位姿维度和数值合法性。"""
        arm_pose = np.asarray(arm_pose, dtype=np.float64)
        if arm_pose.shape != (6,):
            raise ValueError(f"{name} 位姿维度错误，期望 (6,)，实际 {arm_pose.shape}")
        if not np.all(np.isfinite(arm_pose)):
            raise ValueError(f"{name} 位姿存在非有限值")
        return arm_pose

    def head_joint_from_robot_world_pose(self, left_world_pose: np.ndarray, right_world_pose: np.ndarray) -> np.ndarray:
        """
        根据机器人双臂tcp世界坐标系位姿计算头部关节目标
        th1: 旋转(yaw),对应机器人头部关节1
        th2: 俯仰(pitch),对应机器人头部关节2
        机器人头目光聚集在双臂之间。
        """

        x1, y1, z1 = left_world_pose[0], left_world_pose[1], left_world_pose[2]
        x2, y2, z2 = right_world_pose[0], right_world_pose[1], right_world_pose[2]

        x_avg = (x1 + x2) / 2
        y_avg = (y1 + y2) / 2
        z_avg = (z1 + z2) / 2

        th1 = math.atan2(y_avg, x_avg)
        th1 = np.clip(th1, -1.5707963, 1.5707963)

        th2 = math.atan2(-z_avg + 0.2, x_avg)
        th2 = np.clip(th2, -0.349065844, 0.349065844)

        return np.array([th1, th2], dtype=np.float64)

    def _compute_hand_tracking_data(self, head_pose):
        """
        处理手部跟踪模式下的双臂目标位姿
        VR数据→机器人位姿
        """
        left_arm_pose, _ = safe_mat_update(self._last_left_arm_pose, self.tvuer.left_arm_pose)
        right_arm_pose, _ = safe_mat_update(self._last_right_arm_pose, self.tvuer.right_arm_pose)
        self._last_left_arm_pose = left_arm_pose
        self._last_right_arm_pose = right_arm_pose

        # 先把 XR 返回的手臂位姿复制出来，再减去头部偏移量，
        # 让手臂目标相对机器人控制坐标系保持稳定。
        # 核心：VR坐标 -> 机器人坐标变换
        left_hand_pose = left_arm_pose.copy()
        right_hand_pose = right_arm_pose.copy()
        left_hand_pose[0:3, 3] = left_hand_pose[0:3, 3] - (head_pose[0:3, 3] - CONST_HEAD_POSE[0:3, 3] + CONST_LEFT_ARM_POSE[0:3, 3])
        right_hand_pose[0:3, 3] = right_hand_pose[0:3, 3] - (head_pose[0:3, 3] - CONST_HEAD_POSE[0:3, 3] + CONST_RIGHT_ARM_POSE[0:3, 3])

        # 经过左右手各自的基坐标与手部初始姿态修正后，
        # 才得到真正可用于机器人侧控制的末端位姿。
        left_robot_pose = T_ROBOT_OPENXR_LEFT @ left_hand_pose @ T_TO_ROBOT_HAND_LEFT
        right_robot_pose = T_ROBOT_OPENXR_RIGHT @ right_hand_pose @ T_TO_ROBOT_HAND_RIGHT

        # 旋转矩阵转欧拉角(机器人控制格式)
        left_arm_euler = self._validate_arm_pose(rot2euler(left_robot_pose), "left_arm_pose")
        right_arm_euler = self._validate_arm_pose(rot2euler(right_robot_pose), "right_arm_pose")

        # 当前主流程没有直接使用 25 个手部关键点，因此先保留占位数组，
        left_hand_positions = np.zeros((25, 3), dtype=np.float64)
        right_hand_positions = np.zeros((25, 3), dtype=np.float64)

        left_hand_rot = None
        right_hand_rot = None
        if self.return_hand_rot_data:
            left_hand_rot, left_ok = safe_rot_update(self._last_left_hand_rot, self.tvuer.left_hand_orientations)
            right_hand_rot, right_ok = safe_rot_update(self._last_right_hand_rot, self.tvuer.right_hand_orientations)
            if left_ok:
                self._last_left_hand_rot = left_hand_rot
            if right_ok:
                self._last_right_hand_rot = right_hand_rot

        tele_state = TeleStateData(
            left_pinch_state=bool(self.tvuer.left_hand_pinch),
            left_squeeze_state=bool(self.tvuer.left_hand_squeeze),
            left_squeeze_value=float(self.tvuer.left_hand_squeezeValue),
            right_pinch_state=bool(self.tvuer.right_hand_pinch),
            right_squeeze_state=bool(self.tvuer.right_hand_squeeze),
            right_squeeze_value=float(self.tvuer.right_hand_squeezeValue),
        )
        return TeleData(
            head_pose=head_pose,
            left_arm_pose=left_arm_euler,
            right_arm_pose=right_arm_euler,
            left_hand_pos=left_hand_positions,
            right_hand_pos=right_hand_positions,
            left_hand_rot=left_hand_rot,
            right_hand_rot=right_hand_rot,
            left_pinch_value=float(self.tvuer.left_hand_pinchValue) * 100.0,
            right_pinch_value=float(self.tvuer.right_hand_pinchValue) * 100.0,
            tele_state=tele_state,
        )

    def _compute_controller_tracking_data(self, head_pose):
        """
        手柄控制模式:VR数据→机器人位姿+腰部姿态
        处理手柄模式下的双臂目标位姿与腰部目标。
        """
        left_arm_pose, _ = safe_mat_update(self._last_left_arm_pose, self.tvuer.left_arm_pose)
        right_arm_pose, _ = safe_mat_update(self._last_right_arm_pose, self.tvuer.right_arm_pose)
        self._last_left_arm_pose = left_arm_pose
        self._last_right_arm_pose = right_arm_pose

        if abs(head_pose[0, 1]) < 1e-3 and abs(head_pose[2, 1]) < 1e-3:
            current_head_alignment = self._head_world_alignment.copy()
        else:
            head_pose_ = rot2euler(head_pose)
            yaw = -head_pose_[4]
            current_head_alignment = np.array(
                [
                    [math.cos(yaw), 0, math.sin(yaw), 0],
                    [0, 1, 0, 0],
                    [-math.sin(yaw), 0, math.cos(yaw), 0],
                    [0, 0, 0, 1],
                ],
                dtype=np.float64,
            )
        # 头部对齐+腰部姿态解算
        # `aligned_head_pose` 是头部在“锁定初始朝向”后的位姿；
        # `diff_trans` 表示当前头部相对初始头部的变化量。
        aligned_head_pose = self._head_world_alignment @ head_pose
        diff_trans = self._head_start_inverse @ aligned_head_pose
        bias = rot2euler(diff_trans)

        # - 俯仰和横摆来自头部相对偏移；
        thy = max(0, min(-bias[3], 0.5236)) # 俯仰范围，0°~30°
        thz = max(-0.7854, min(bias[4], 0.7854)) # 横摆范围，-45°~45°
        thz_err = bias[4]-thz
        biasx = max(0, min(-bias[2], 0.3)) # 前后范围，0~300
        biasz = max(-0.15, min(bias[1], 0.15)) # 高低范围，-150~150
        bias_waist =  np.array([biasx,0,biasz,0,thy,thz], dtype=np.float64)
        waist_rot = self._waist_start_rot @ euler2rot(bias_waist)
        #全身:4个关节，采用笛卡尔目标控制
        self._full_last_waist_cart_pose = rot2euler(waist_rot)

        # 仅用于半身控制，关节目标控制
        self._half_last_waist_pose = np.array([thz], dtype=np.float64)

        # VR坐标 -> 机器人坐标变换
        # 手柄位姿先叠加当前头部对齐矩阵，
        # 然后再扣除头部平移，让目标点始终相对机器人控制坐标表达。
        th2 = -bias[3]
        left_hand_pose = current_head_alignment @ left_arm_pose
        right_hand_pose = current_head_alignment @ right_arm_pose
        aligned_head_pose = current_head_alignment @ head_pose
        left_hand_pose[0:3, 3] = left_hand_pose[0:3, 3] - (
            aligned_head_pose[0:3, 3] - CONST_HEAD_POSE[0:3, 3] + CONST_LEFT_ARM_POSE[0:3, 3]
        )
        right_hand_pose[0:3, 3] = right_hand_pose[0:3, 3] - (
            aligned_head_pose[0:3, 3] - CONST_HEAD_POSE[0:3, 3] + CONST_RIGHT_ARM_POSE[0:3, 3]
        )

        left_waist_rot = np.array(
            [
                [math.cos(-th2), -math.sin(-th2), 0, 0],
                [math.sin(-th2), math.cos(-th2), 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            dtype=np.float64,
        )
        right_waist_rot = np.array(
            [
                [math.cos(th2), -math.sin(th2), 0, 0],
                [math.sin(th2), math.cos(th2), 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            dtype=np.float64,
        )

        # 腰部转角参与到左右臂末端的控制坐标中，
        # 这样在操作者头部和腰部联动时，双臂目标仍能保持相对一致。
        left_robot_pose = left_waist_rot @ T_ROBOT_OPENXR_LEFT @ left_hand_pose @ T_TO_ROBOT_HAND_LEFT
        right_robot_pose = right_waist_rot @ T_ROBOT_OPENXR_RIGHT @ right_hand_pose @ T_TO_ROBOT_HAND_RIGHT

        left_arm_euler = self._validate_arm_pose(rot2euler(left_robot_pose), "left_arm_pose")
        right_arm_euler = self._validate_arm_pose(rot2euler(right_robot_pose), "right_arm_pose")

        tele_state = TeleStateData(
            left_trigger_state=bool(self.tvuer.left_ctrl_trigger),
            left_squeeze_ctrl_state=bool(self.tvuer.left_ctrl_squeeze),
            left_squeeze_ctrl_value=float(self.tvuer.left_ctrl_squeezeValue),
            left_thumbstick_state=bool(self.tvuer.left_ctrl_thumbstick),
            left_thumbstick_value=np.asarray(self.tvuer.left_ctrl_thumbstickValue, dtype=np.float64),
            left_aButton=bool(self.tvuer.left_ctrl_aButton),
            left_bButton=bool(self.tvuer.left_ctrl_bButton),
            right_trigger_state=bool(self.tvuer.right_ctrl_trigger),
            right_squeeze_ctrl_state=bool(self.tvuer.right_ctrl_squeeze),
            right_squeeze_ctrl_value=float(self.tvuer.right_ctrl_squeezeValue),
            right_thumbstick_state=bool(self.tvuer.right_ctrl_thumbstick),
            right_thumbstick_value=np.asarray(self.tvuer.right_ctrl_thumbstickValue, dtype=np.float64),
            right_aButton=bool(self.tvuer.right_ctrl_aButton),
            right_bButton=bool(self.tvuer.right_ctrl_bButton),
        )
        return TeleData(
            head_pose=aligned_head_pose,
            left_arm_pose=left_arm_euler,
            right_arm_pose=right_arm_euler,
            waist_pose=self._half_last_waist_pose.copy() if self.upper_body else self._full_last_waist_cart_pose.copy(),
            # 扳机值映射：0-1 → 0-10(适配灵巧手控制)
            left_trigger_value=10.0 - float(self.tvuer.left_ctrl_triggerValue) * 10.0,
            right_trigger_value=10.0 - float(self.tvuer.right_ctrl_triggerValue) * 10.0,
            tele_state=tele_state,
        )

    def get_motion_state_data(self):
        """输出主程序需要的统一遥操作数据结构。"""
        head_pose, _ = safe_mat_update(self._last_head_pose, self.tvuer.head_pose)
        self._last_head_pose = head_pose
        if not self._head_alignment_ready:
            self.start_head_pose()
        if self.use_hand_tracking:
            # 自动切换手部/手柄模式
            return self._compute_hand_tracking_data(head_pose)
        return self._compute_controller_tracking_data(head_pose)

    def get_tele_data(self):
        return self.get_motion_state_data()

    def render_to_xr(self, img):
        """对外接口：将机器人当前图像推送回 XR 端显示。"""
        self.tvuer.render_to_xr(img)

    def is_xr_active(self, timeout: float = 10.0) -> bool:
        """
        判断 XR 设备是否活跃(基于事件接收)默认超时时间10秒
        收到事件且在超时范围内则认为活跃
        """
        return self.tvuer.is_active(timeout)
    
    def is_xr_web_connected(self) -> bool:
        """
        判断 XR 设备网页连接(WebSocket 连接)是否存活
        """
        return self.tvuer.is_web_connected
    
    def get_xr_last_pose_time(self) -> float:
        """
        获取最后一次收到移动事件的时间戳(秒),0表示从未收到
        """
        return self.tvuer.last_pose_time


    def close(self):
        """关闭所有资源"""
        self.tvuer.close()
