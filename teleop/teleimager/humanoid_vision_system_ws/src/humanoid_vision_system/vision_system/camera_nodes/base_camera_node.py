#!/usr/bin/env python3
"""相机节点基类"""
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable
from loguru import logger

from ..config.config_manager import CameraConfig, ConfigManager
from ..utils.timing import FrameRateController
from ..proto.vision_messages_pb2 import CameraStatus
from google.protobuf.timestamp_pb2 import Timestamp

class BaseCameraNode(ABC):
    """相机基类"""
    def __init__(self, node, config_manager: ConfigManager, camera_config: CameraConfig):
        self.node = node
        self.config_manager = config_manager
        self.camera_config: CameraConfig = camera_config
        self.camera_id = camera_config.camera_id

        self.logger = logger.bind(camera_id=self.camera_id, module="camera_node")

        self.is_initialized = False
        self.is_running = False
        self.capture_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        target_fps = 30
        if self.camera_config.streams.color_enabled and self.camera_config.streams.depth_enabled:
            target_fps = min(self.camera_config.streams.color_fps, self.camera_config.streams.depth_fps)
        elif self.camera_config.streams.color_enabled:
            target_fps = self.camera_config.streams.color_fps
        elif self.camera_config.streams.depth_enabled:
            target_fps = self.camera_config.streams.depth_fps
        self.fps_controller = FrameRateController(target_fps)

        self.reconnect_cfg = {
            "max_failure_count": 5,	# 连续采集失败N次触发重连
            "max_retry_times": 10,	# 最大重连次数，超出则标记离线
            "retry_interval_s": 2.0	# 重连间隔（秒）
        }
        self.capture_failure_cnt = 0	# 连续采集失败计数
        self.retry_cnt = 0		# 已重连次数

        # 采集帧后推送回调：入参为帧数据 {'color': rgb_np, 'depth': depth_np}
        self.frame_push_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.status_push_callback: Optional[Callable[[CameraStatus], None]] = None

        self.frames_captured = 0  # 总采集帧数  

        self.logger.info(f"相机{self.camera_id}初始化完成，目标帧率：{target_fps}fps")

    @abstractmethod
    def _initialize_camera(self) -> bool:
        """初始化相机硬件"""
        pass

    @abstractmethod
    def _cleanup_camera(self) -> None:
        """清理相机硬件"""
        pass

    @abstractmethod
    def _capture_frames(self) -> Optional[Dict[str, Any]]:
        """
        采集单帧数据
        :return: 帧数据 {'color': rgb_np(H,W,3), 'depth': depth_np(H,W)},失败返回None
        """
        pass

    # 设置推送回调
    def set_push_callbacks(self, frame_callback: Callable, status_callback: Callable) -> None:
        """设置数据推送回调"""
        with self._lock:
            self.frame_push_callback = frame_callback
            self.status_push_callback = status_callback
            self.logger.info(f"相机{self.camera_id}已绑定帧/状态推送回调")

    def start(self) -> bool:
        """启动相机"""
        with self._lock:
            if self.is_running:
                self.logger.warning(f"相机{self.camera_id}已运行，无需重复启动")
                return True

            if not self.is_initialized:
                self.logger.info(f"相机{self.camera_id}初始化硬件")
                if not self._initialize_camera():
                    self.logger.error(f"相机{self.camera_id}初始化失败")
                    return False
                self.is_initialized = True
                self.retry_cnt = 0  # 初始化成功，重置重连次数
                self.logger.info(f"相机{self.camera_id}初始化成功")

            self.is_running = True
            self.capture_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True,
                name=f"{self.camera_id}_capture"
            )
            self.capture_thread.start()
            self.logger.info(f"相机[{self.camera_id}] 启动成功，采集线程已运行）")
            return True

    def stop(self) -> None:
        """停止相机"""
        with self._lock:
            if not self.is_running:
                self.logger.warning(f"相机{self.camera_id}已停止，无需重复操作")
                return

            self.is_running = False
            if self.capture_thread and self.capture_thread.is_alive():
                self.capture_thread.join(timeout=2.0)
                if self.capture_thread.is_alive():
                    self.logger.warning(f"[{self.camera_id}] 采集线程超时未退出，强制清理")
            if self.is_initialized:
                self._cleanup_camera()
                self.is_initialized = False
            self.capture_failure_cnt = 0
            self.retry_cnt = 0
            self.frames_captured = 0
            self.logger.info(f"相机[{self.camera_id}] 已停止，资源清理完成，状态已重置")

    def _capture_loop(self) -> None:
        """相机采集循环"""
        while self.is_running:
            try:
                self.fps_controller.wait_for_next_frame()

                frame_data = self._capture_frames()
                
                if frame_data is None:
                    self.capture_failure_cnt += 1
                    self.logger.warning(
                        f"相机{self.camera_id}采集帧失败，连续失败{self.capture_failure_cnt}/{self.reconnect_cfg['max_failure_count']}"
                    )
                    self._check_hardware_reconnect()
                    continue
                
                self.capture_failure_cnt = 0
                self.frames_captured += 1
                
                if self.frame_push_callback:
                    self.frame_push_callback(frame_data)

                if self.frames_captured % 40 == 0 and self.status_push_callback:
                    self.status_push_callback(self._generate_camera_status())
                    
            except Exception as e:
                self.logger.error(f"相机{self.camera_id}采集异常: {e}")
                self.capture_failure_cnt += 1
                self._check_hardware_reconnect()
                time.sleep(0.1)


    def _check_hardware_reconnect(self) -> None:
        """检查并触发硬件重连"""
        if self.capture_failure_cnt < self.reconnect_cfg["max_failure_count"]:
            return

        if self.retry_cnt >= self.reconnect_cfg["max_retry_times"]:
            self.logger.error(
                f"相机{self.camera_id}连续采集失败{self.capture_failure_cnt}次，重连{self.retry_cnt}次均失败，标记为离线"
            )
            self.is_running = False
            # 推送离线状态
            if self.status_push_callback:
                status = self._generate_camera_status()
                status.health_status = CameraStatus.ERROR
                self.status_push_callback(status)
            return

        self.retry_cnt += 1
        self.logger.warning(
            f"相机{self.camera_id}重连(第{self.retry_cnt}/{self.reconnect_cfg['max_retry_times']}次)"
        )
        time.sleep(self.reconnect_cfg["retry_interval_s"])

        with self._lock:
            if not self.is_running:
                return
            self._cleanup_camera()
            self.is_initialized = False
            if self._initialize_camera():
                self.is_initialized = True
                self.capture_failure_cnt = 0
                self.logger.info(f"相机[{self.camera_id}] 第{self.retry_cnt}次重连成功，恢复采集")
                # 推送恢复状态
                if self.status_push_callback:
                    status = self._generate_camera_status()
                    status.health_status = CameraStatus.HEALTHY
                    self.status_push_callback(status)
            else:
                self.logger.error(f"相机{self.camera_id}重连失败")

    def _generate_camera_status(self) -> CameraStatus:
        """生成相机状态"""
        status = CameraStatus()
        status.camera_id = self.camera_id

        if self.retry_cnt == 0 and self.is_running:
            status.health_status = CameraStatus.HEALTHY
        elif self.retry_cnt < self.reconnect_cfg["max_retry_times"] // 2:
            status.health_status = CameraStatus.WARNING
        else:
            status.health_status = CameraStatus.ERROR

        status.frame_rate = round(self.fps_controller.get_actual_fps(), 2)
        return status
