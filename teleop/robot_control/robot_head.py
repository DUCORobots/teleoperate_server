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

from DucoCobotHead import DucoCobotHead
from teleop.log_manager import get_logger

_logger = get_logger(__name__)


def _ensure_head_shape(value):
    """校验头部目标维度，统一要求为 2 轴数组。"""
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (2,):
        raise ValueError(f"head_pose 维度错误，期望 (2,)，实际 {array.shape}")
    return array


class SimRicoHeadBackend:
    """仿真占位后端"""

    def __init__(self, robot_config):
        self.robot_config = robot_config
        self._head_state = np.array(
            robot_config["robot"]["home_head_rad"],
            dtype=np.float64,
        )
        self._home_running = False  # 回零状态标志

    def ctrl_head(self, target_pose):
        """仿真：缓存目标位姿/关节指令"""
        self._head_state = _ensure_head_shape(target_pose)

    def ctrl_head_go_home(self):
        """仿真：缓存回零指令"""
        self._head_state = _ensure_head_shape(self.robot_config["robot"]["home_head_rad"])
        self._home_running = False

    def check_head_home(self):
        """仿真：默认回零完成"""
        return True

    def get_actual_head_position(self):
        """仿真：返回缓存的头部关节角度"""
        return self._head_state.copy()

    def close(self):
        """仿真：空实现，无资源释放"""
        return


class RICO_HeadController:
    """
    RICO 头部控制器
    """

    def __init__(
        self,
        robot_config,
        simulation_mode: bool = False,
        state_poll_hz: float = 60.0,
        is_resv_mode: bool = False,
    ):
        """
        :param robot_config: 机器人配置
        :param simulation_mode: True=仿真模式, False=真机模式
        :param state_poll_hz: 状态轮询频率
        :param is_resv_mode: 是否启用后台状态轮询线程
        """
        self.robot_config = robot_config
        self.simulation_mode = simulation_mode
        self.state_poll_hz = state_poll_hz
        self.is_resv_mode = is_resv_mode
        self._speed_flag = 0
        self._running = True
        self._home_completed = False
        self._head_status = -100
        self._state_lock = threading.Lock()
        self._last_poll_error_log_time = 0.0
        self._poll_error_log_interval_s = 5.0

        self._latest_head_position = np.array(
            robot_config["robot"]["home_head_rad"],
            dtype=np.float64,
        )

        if self.simulation_mode:
            self._backend = SimRicoHeadBackend(robot_config)
            self._poll_thread = None
            return

        robot_cfg = robot_config["robot"]
        self.head_controller = DucoCobotHead(robot_cfg["ip"], int(robot_cfg["head_port"]))
        self.head_controller.open()

        if is_resv_mode:
            self._poll_thread = threading.Thread(target=self._poll_state_loop, daemon=True)
            self._poll_thread.start()
        else:
            self._poll_thread = None

    def _poll_state_loop(self):
        """后台状态轮询线程（真机专用）"""
        interval = 1.0 / max(self.state_poll_hz, 1.0)
        while self._running:
            try:
                joint_state = np.array(self.head_controller.get_actual_joints_position(), dtype=np.float64)
                with self._state_lock:
                    self._latest_head_position = joint_state
            except Exception as exc:
                # 读取失败：沿用上一帧数据
                now = time.monotonic()
                if now - self._last_poll_error_log_time >= self._poll_error_log_interval_s:
                    _logger.warning(f"读取 RICO 头部状态失败，本帧沿用上一帧数据: {exc}")
                    self._last_poll_error_log_time = now
            time.sleep(interval)

    def _get_servo_speed(self) -> float:
        """
        速度平滑爬升算法
        头部启动时速度从慢到快平滑提升，避免启动突变导致晃动/失控
        按照配置中的爬升策略平滑提高伺服速度，减少启动突变
        """
        servo_cfg = self.robot_config["robot"]["servo"]
        self._speed_flag += 1
        ramp_steps = max(int(servo_cfg["ramp_steps"]), 1)  # 爬升步数
        ratio = min(self._speed_flag / ramp_steps, 1.0)    # 爬升比例（0→1）
        # 计算当前速度：最小速度 + 比例×(最大速度-最小速度)
        s_min = servo_cfg["head_speed_min_joint"]
        s_max = servo_cfg["head_speed_max_joint"]
        return float(s_min + ratio * (s_max - s_min))

    def speed_reset(self):
        """重置内部速度阶段计数。"""
        self._speed_flag = 0

    def ctrl_head_go_home(self, block: bool = True):
        """控制头部回到配置中的 home 位姿。"""
        target_pose = _ensure_head_shape(self.robot_config["robot"]["home_head_rad"])
        with self._state_lock:
            self._home_completed = False
        _logger.info("-- 头部正在回到 home 关节位，请等待......")
        if self.simulation_mode:
            self._backend.ctrl_head_go_home()
            return
        with self._state_lock:
            self._head_status = self.head_controller.movej2(
                target_pose.tolist(),
                float(self.robot_config["robot"]["servo"]["home_velocity"]),
                float(self.robot_config["robot"]["servo"]["home_acceleration"]),
                0,
                False,
            )
        if block:
            while not self.check_head_home():
                time.sleep(0.01)
            _logger.info("-- 头部已回到 home 关节位")

    def check_head_home(self) -> bool:
        """检查头部回零动作是否完成。"""
        if self.simulation_mode:
            return self._backend.check_head_home()

        with self._state_lock:
            if self._home_completed:
                return True
            task_state = self.head_controller.get_noneblock_taskstate(self._head_status)

            if task_state >= 4:
                self._head_status = -100
                self._home_completed = True
                return True
            return False

    def ctrl_head(self, target_head):
        """下发头部伺服目标"""
        head_pose = _ensure_head_shape(target_head)
        if self.simulation_mode:
            self._backend.ctrl_head(head_pose)
            return

        servo_cfg = self.robot_config["robot"]["servo"]
        speed = self._get_servo_speed()
        self.head_controller.servoj(
            head_pose.tolist(),
            speed,
            servo_cfg["head_acceleration_joint"],
            False,
            int(servo_cfg["lookahead_time_ms"]),
            int(servo_cfg["gain"]),
            int(servo_cfg["blend"]),
            1
        )

    def get_actual_head_position(self) -> np.ndarray:
        """
        返回头部实际关节角度(从后台轮询线程缓存读取)
        仿真模式返回缓存值。
        """
        if self.simulation_mode:
            return self._backend.get_actual_head_position()
        with self._state_lock:
            return self._latest_head_position.copy()

    def close(self):
        """停止轮询线程并关闭控制器。"""
        self._running = False
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2.0)
        if self.simulation_mode:
            self._backend.close()
            return
        try:
            self.head_controller.close()
        except Exception as exc:
            _logger.warning(f"关闭头部连接失败: {exc}")