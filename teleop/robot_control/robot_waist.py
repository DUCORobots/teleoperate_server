import math
import os
import sys
import threading
import time
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
teleop_dir = os.path.dirname(current_dir)
if teleop_dir not in sys.path:
    sys.path.append(teleop_dir)
for dependency_dir in ("gen_py", "lib"):
    dependency_path = os.path.join(teleop_dir, dependency_dir)
    if dependency_path not in sys.path:
        sys.path.append(dependency_path)

from DucoCobotWaist import DucoCobotWaist
from teleop.log_manager import get_logger

_logger = get_logger(__name__)


def _ensure_waist_shape(value, go_home: bool, upper_body: bool = True):
    """校验腰部目标维度,半身: 1 轴数组，全身: 回零:4 轴数组,非回零:6 轴数组"""
    array = np.asarray(value, dtype=np.float64)
    expected_len = 1 if upper_body else (4 if go_home else 6)

    if array.shape != (expected_len,):
        raise ValueError(f"类型：{'半身' if upper_body else '全身'},回零：{go_home},waist_pose 维度错误，期望 ({expected_len})，实际 {array.shape}")
    return array

class SimRicoWaistBackend:
    """仿真占位后端,作用同手部仿真"""

    def __init__(self, upper_body: bool, home_waist_rad: np.ndarray = None):
        self.upper_body = upper_body
        self.home_waist_rad = home_waist_rad
        self._waist_state = np.array(
            home_waist_rad,
            dtype=np.float64,
        )
        self._waist_cart = np.asarray([[0.0] * 6], dtype=np.float64)
        self._home_running = False  # 回零状态标志

    def ctrl_waist(self, target_pose):
        """仿真：缓存目标位姿/关节指令"""
        if self.upper_body:
            self._waist_state = _ensure_waist_shape(target_pose, False, self.upper_body)
        else:
            self._waist_cart = _ensure_waist_shape(target_pose, False, self.upper_body)

    def ctrl_waist_go_home(self):
        """仿真：缓存回零指令"""
        if self.upper_body: 
            self._waist_state = _ensure_waist_shape(self.home_waist_rad, True, self.upper_body)
        else:
            self._waist_cart = np.array([0.0825, 0, 1.063426, 0.0, 0.0, 0.0], dtype=np.float64)
        self._home_running = False

    def check_waist_home(self):
        """仿真：默认回零完成"""
        return True

    def get_actual_waist_position(self):
        """仿真：返回缓存的腰部关节角度"""
        if self.upper_body:
            return self._waist_state.copy()
        else:
            return self._waist_cart.copy()

    def close(self):
        return

class RICO_WaistController:
    """
    RICO 腰部控制器。
    """

    def __init__(
        self,
        robot_config,
        simulation_mode: bool = False,
        upper_body: bool = True,
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
        self.upper_body = upper_body

        self._speed_flag = 0
        self._home_completed = False
        self._waist_status = -100
        self._state_lock = threading.Lock()
        self._last_poll_error_log_time = 0.0
        self._poll_error_log_interval_s = 5.0
        self._running = True
        robot_cfg = robot_config["robot"]
        self.home_waist_rad = robot_cfg["home_half_waist_rad"] if self.upper_body else robot_cfg["home_full_waist_rad"]

        self._latest_waist_position = np.array(
            self.home_waist_rad,
            dtype=np.float64,
        )
        if self.simulation_mode:
            self._backend = SimRicoWaistBackend(self.upper_body, self.home_waist_rad)
            self._poll_thread = None
            return

        self.waist_controller = DucoCobotWaist(robot_cfg["ip"], int(robot_cfg["waist_port"]))
        self.waist_controller.open()

        if is_resv_mode:
            self._poll_thread = threading.Thread(target=self._poll_state_loop, daemon=True)
            self._poll_thread.start()
        else:
            self._poll_thread = None

    def _poll_state_loop(self):
        """后台状态轮询线程(真机专用)"""
        interval = 1.0 / max(self.state_poll_hz, 1.0)
        while self._running:
            try:
                joint_state = self.waist_controller.get_actual_joints_position()
                with self._state_lock:
                    self._latest_waist_position = np.asarray(joint_state, dtype=np.float64)
            except Exception as exc:
                now = time.monotonic()
                if now - self._last_poll_error_log_time >= self._poll_error_log_interval_s:
                    _logger.warning(f"读取 RICO 腰部状态失败，本帧沿用上一帧数据: {exc}")
                    self._last_poll_error_log_time = now
            time.sleep(interval)

    def _get_servo_speed(self) -> float:
        """
        速度平滑爬升算法
        腰部启动时速度从慢到快平滑提升，避免启动突变导致晃动/失控
        """
        servo_cfg = self.robot_config["robot"]["servo"]
        self._speed_flag += 1
        ramp_steps = max(int(servo_cfg["ramp_steps"]), 1)
        ratio = min(self._speed_flag / ramp_steps, 1.0)
        if self.upper_body:
            s_min = servo_cfg["waist_speed_min_joint"]
            s_max = servo_cfg["waist_speed_max_joint"]
        else:
            s_min = servo_cfg["waist_speed_min_cart"]
            s_max = servo_cfg["waist_speed_max_cart"]

        return float(s_min + ratio * (s_max - s_min))

    def speed_reset(self):
        """重置内部速度阶段计数"""
        self._speed_flag = 0

    def ctrl_waist_go_home(self, block: bool = True):
        """控制腰部回到配置中的 home 位姿。"""
        target_pose = _ensure_waist_shape(self.home_waist_rad, True, self.upper_body)

        with self._state_lock:
            self._home_completed = False
        if self.simulation_mode:
            self._backend.ctrl_waist_go_home()
            return
        _logger.info("-- 腰部正在回到 home 关节位，请等待......")
        with self._state_lock:
            # 半身:1个关节，全身:4个关节
            self._waist_status = self.waist_controller.movej2(
                target_pose.tolist(),
                float(self.robot_config["robot"]["servo"]["home_velocity"]),
                float(self.robot_config["robot"]["servo"]["home_acceleration"]),
                0,
                False,
            )
        if block:
            while not self.check_waist_home():
                time.sleep(0.01)
            _logger.info("-- 腰部已回到 home 关节位")

    def check_waist_home(self) -> bool:
        """检查腰部回零动作是否完成。"""
        if self.simulation_mode:
            return self._backend.check_waist_home()
        with self._state_lock:
            if self._home_completed:
                return True
            task_state = self.waist_controller.get_noneblock_taskstate(self._waist_status)
            if task_state >= 4:
                self._waist_status = -100
                self._home_completed = True
                return True
            return False

    def ctrl_waist(self, target_waist):
        """下发腰部伺服目标"""
        waist_pose = _ensure_waist_shape(target_waist, False, self.upper_body)
        if self.simulation_mode:
            self._backend.ctrl_waist(waist_pose)
            return
        # 半身:1个关节采用关节目标控制,全身:4个关节，采用笛卡尔目标控制
        servo_cfg = self.robot_config["robot"]["servo"]
        speed = self._get_servo_speed()
        if self.upper_body:
            self.waist_controller.servoj(
                waist_pose.tolist(),
                speed,
                servo_cfg["waist_acceleration_joint"],
                False,
                int(servo_cfg["lookahead_time_ms"]),
                int(servo_cfg["gain"]),
                int(servo_cfg["blend"]),
                1
            )
        else:
            self.waist_controller.servoj_pose(
                waist_pose.tolist(),
                speed,
                servo_cfg["waist_acceleration_cart"],
                [],
                "",
                "",
                False,
                int(servo_cfg["lookahead_time_ms"]),
                int(servo_cfg["gain"]),
                int(servo_cfg["blend"]),
                1
            )

    def get_actual_waist_position(self) -> np.ndarray:
        """
        返回腰部实际关节角度(从后台轮询线程缓存读取)
        仿真模式返回缓存的关节状态
        """
        if self.simulation_mode:
            return self._backend.get_actual_waist_position()
        with self._state_lock:
            return self._latest_waist_position.copy()

    def close(self):
        """停止轮询线程并关闭控制器。"""
        self._running = False
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2.0)
        if self.simulation_mode:
            self._backend.close()
            return
        try:
            self.waist_controller.close()
        except Exception as exc:
            _logger.warning(f"关闭腰部连接失败: {exc}")