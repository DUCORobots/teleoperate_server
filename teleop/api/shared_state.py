import threading
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, Dict, Any, List
from queue import Queue, Empty
import os
from utils.camera_manager import CameraManager
from teleop.log_manager import get_logger

_logger = get_logger(__name__)

class TeleopCommand(Enum):
    START_TELEOP = "start_teleop"
    STOP_TELEOP = "stop_teleop"
    START_RECORD = "start_record"
    STOP_RECORD = "stop_record"
    EMERGENCY_STOP = "emergency_stop"
    GO_HOME = "go_home"
    INIT_RESET = "init_reset"
    SET_TASK = "set_task"
    CREATE_TASK = "create_task"
    DELETE_TASK = "delete_task"
    EDIT_TASK = "edit_task"
    REFRESH_CAMERA_CONFIG = "refresh_camera_config"

@dataclass
class RecordTaskInfo:
    goal: str = ""
    desc: str = ""
    steps: str = ""

@dataclass
class XRStatus:
    xr_active: bool = False
    xr_web_connected: bool = False
    last_pose_time: Optional[float] = None
    timeout: float = 10.0

@dataclass
class RecordStatus:
    is_recording: bool = False
    episode_id: Optional[str] = None
    start_time: Optional[float] = None
    frame_count: int = 0
    task_info: Optional[RecordTaskInfo] = None

@dataclass
class RobotStatus:
    head_qpos: Optional[List[float]] = None
    left_arm_qpos: Optional[List[float]] = None
    right_arm_qpos: Optional[List[float]] = None
    left_arm_tcp: Optional[List[float]] = None
    right_arm_tcp: Optional[List[float]] = None
    last_update_time: Optional[float] = None
    waist_qpos: Optional[List[float]] = None

class SharedState:
    def __init__(self, task_dir: str = "data", trash_dir: str = "data/.trash", camera_manager: Optional[CameraManager] = None):
        self.command_queue: Queue = Queue()
        self.camera_manager: Optional[CameraManager] = camera_manager

        self.teleop_state: str = "IDLE"
        self.xr_status = XRStatus()
        self.record_status = RecordStatus()
        self.robot_status = RobotStatus()
        self._lock = threading.RLock()

        self.config: Dict[str, Any] = {}
        self.task_dir: str = os.path.abspath(task_dir) if task_dir else "data"
        self.trash_dir: str = os.path.abspath(trash_dir) if trash_dir else "data/.trash"

        self.control_source: Optional[str] = None
        self.control_lock: bool = False
        self.emergency_stop_flag: bool = False

        self.active_task: Optional[str] = None
        self._active_task_file = os.path.join(self.task_dir, ".active_task")

        os.makedirs(self.task_dir, exist_ok=True)
        os.makedirs(self.trash_dir, exist_ok=True)
        self.load_active_task_from_file()

    def get_command(self) -> Optional[str]:
        """获取命令(兼容性方法)"""
        cmd_data = self.pop_command()
        return cmd_data["command"].value if cmd_data else None

    def push_command(self, command: TeleopCommand, data: Optional[Dict[str, Any]] = None):
        """推送命令到队列"""
        with self._lock:
            self.command_queue.put({
                "command": command,
                "data": data,
                "timestamp": time.time()
            })
            _logger.debug(f"命令入队: {command.value}")
    
    def pop_command(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """主程序获取命令"""
        try:
            return self.command_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def update_teleop_state(self, state: str):
        """更新遥操作状态"""
        with self._lock:
            self.teleop_state = state

    def update_xr_status(self, xr_active: bool, xr_web_connected: bool = None, last_pose_time: Optional[float] = None):
        """更新 XR 状态"""
        with self._lock:
            self.xr_status.xr_active = xr_active
            if xr_web_connected is not None:
                self.xr_status.xr_web_connected = xr_web_connected
            if last_pose_time is not None:
                self.xr_status.last_pose_time = last_pose_time
            else:
                self.xr_status.last_pose_time = time.time() if xr_active else None


    def update_record_status(self, is_recording: bool, episode_id: Optional[str] = None,
                           start_time: Optional[float] = None, frame_count: int = 0,
                           task_info: Optional[RecordTaskInfo] = None):
        """更新录制状态"""
        with self._lock:
            self.record_status.is_recording = is_recording
            if episode_id is not None:
                self.record_status.episode_id = episode_id
            if start_time is not None:
                self.record_status.start_time = start_time
            self.record_status.frame_count = frame_count
            if task_info is not None:
                self.record_status.task_info = task_info

    def acquire_control(self, source: str) -> bool:
        """尝试获取控制权，返回是否成功"""
        with self._lock:
            if self.control_lock:
                return False
            self.control_source = source
            self.control_lock = True
            _logger.info(f"控制权被 {source} 获取")
            return True

    def release_control(self):
        """释放控制权"""
        with self._lock:
            self.control_source = None
            self.control_lock = False
            _logger.info("控制权已释放")

    def is_control_held_by(self, source: str) -> bool:
        """检查当前控制是否由指定源持有"""
        with self._lock:
            return self.control_lock and self.control_source == source

    def get_control_source(self) -> Optional[str]:
        """获取当前控制源"""
        with self._lock:
            return self.control_source

    def set_emergency_stop(self):
        """设置紧急停止标志(主程序轮询并执行)"""
        with self._lock:
            self.emergency_stop_flag = True
            self.control_source = None
            self.control_lock = False
            _logger.warning("紧急停止标志已设置，控制锁已释放")

    def clear_emergency_stop(self):
        """清除紧急停止标志"""
        with self._lock:
            self.emergency_stop_flag = False

    def check_emergency_stop(self) -> bool:
        """检查是否有紧急停止请求"""
        with self._lock:
            return self.emergency_stop_flag

    def load_active_task_from_file(self):
        """从持久化文件加载活动任务ID"""
        if os.path.exists(self._active_task_file):
            try:
                with open(self._active_task_file, 'r') as f:
                    task_id = f.read().strip()
                    if task_id:
                        self.active_task = task_id
                        _logger.info(f"加载活动任务: {self.active_task}")
                        return
            except Exception as e:
                _logger.warning(f"读取活动任务文件失败: {e}")
        self.active_task = None
        _logger.debug("未找到活动任务文件，活动任务为空")

    def save_active_task_to_file(self):
        """将当前活动任务ID持久化到文件"""
        if self.active_task:
            try:
                os.makedirs(os.path.dirname(self._active_task_file), exist_ok=True)
                with open(self._active_task_file, 'w', encoding="utf-8") as f:
                    f.write(self.active_task)
                _logger.info(f"活动任务已保存: {self.active_task}")
            except Exception as e:
                _logger.error(f"保存活动任务失败: {e}")

    def set_active_task(self, task_id: str) -> bool:
        """设置活动任务"""
        with self._lock:
            if self.record_status.is_recording:
                _logger.warning(f"正在录制中，无法切换任务: {task_id}")
                return False
            self.active_task = task_id
            self.save_active_task_to_file()
            _logger.info(f"活动任务已切换为: {task_id}")
            return True

    def get_active_task(self) -> Optional[str]:
        """获取当前活动任务ID"""
        with self._lock:
            return self.active_task

    def update_robot_status(self, head_qpos=None, left_arm_qpos=None, right_arm_qpos=None,
                             left_arm_tcp=None, right_arm_tcp=None, waist_qpos=None):
        with self._lock:
            if head_qpos is not None:
                self.robot_status.head_qpos = head_qpos
            if left_arm_qpos is not None:
                self.robot_status.left_arm_qpos = left_arm_qpos
            if right_arm_qpos is not None:
                self.robot_status.right_arm_qpos = right_arm_qpos
            if left_arm_tcp is not None:
                self.robot_status.left_arm_tcp = left_arm_tcp
            if right_arm_tcp is not None:
                self.robot_status.right_arm_tcp = right_arm_tcp
            if waist_qpos is not None:
                self.robot_status.waist_qpos = waist_qpos
            self.robot_status.last_update_time = time.time()

    def get_robot_status(self) -> Dict[str, Any]:
        with self._lock:
            return asdict(self.robot_status)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典,用于API响应"""
        with self._lock:
            return {
                "teleop_state": self.teleop_state,
                "xr_status": asdict(self.xr_status),
                "record_status": {
                    "is_recording": self.record_status.is_recording,
                    "episode_id": self.record_status.episode_id,
                    "start_time": self.record_status.start_time,
                    "frame_count": self.record_status.frame_count,
                    "duration": time.monotonic() - self.record_status.start_time if self.record_status.start_time else 0,
                    "task_info": asdict(self.record_status.task_info) if self.record_status.task_info else None
                },
                "config": self.config,
                "control_source": self.control_source,
                "control_lock": self.control_lock,
                "emergency_stop": self.emergency_stop_flag,
                "active_task": self.active_task,
                "robot_status": asdict(self.robot_status),
            }