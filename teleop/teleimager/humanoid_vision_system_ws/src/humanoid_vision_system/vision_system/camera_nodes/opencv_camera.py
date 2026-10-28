#!/usr/bin/env python3
"""OpenCV相机节点"""
import cv2
import numpy as np
from typing import Optional, Dict, Any
 
from .base_camera_node import BaseCameraNode
from ..config.config_manager import ConfigManager, CameraConfig
 
class OpenCVCamera(BaseCameraNode):
    """OpenCV相机节点"""
    
    def __init__(self, node, config_manager: ConfigManager, camera_config: CameraConfig):
        super().__init__(node, config_manager, camera_config)
        self.cap: Optional[cv2.VideoCapture] = None
        self.device_index = self.camera_config.device_index

    def _initialize_camera(self) -> bool:
        try:
            if not isinstance(self.device_index, int) or self.device_index < 0:
                self.logger.error(f"设备索引无效: {self.device_index}")
                return False

            self.logger.info(f"打开相机{self.camera_id}，设备索引: {self.device_index}")
            self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_V4L2)

            if not self.cap or not self.cap.isOpened():
                self.logger.error(f"无法打开设备索引{self.device_index}的相机: {self.camera_id}")
                return False

            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

            capture_width = self.camera_config.streams.color_capture_width
            capture_height = self.camera_config.streams.color_capture_height
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, capture_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, capture_height)

            actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            if actual_w != capture_width or actual_h != capture_height:
                self.logger.warning(f"分辨率不支持: 目标{capture_width}x{capture_height}, 实际{actual_w:.0f}x{actual_h:.0f}")

            target_fps = self.camera_config.streams.color_fps if self.camera_config.streams.color_enabled else 30
            self.cap.set(cv2.CAP_PROP_FPS, target_fps)
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.logger.info(f"相机{self.camera_id}初始化成功，帧率: {actual_fps:.1f}fps")
            return True

        except Exception as e:
            self.logger.error(f"相机{self.camera_id}初始化失败: {e}")
            self._cleanup_camera()
            return False

    def _cleanup_camera(self) -> None:
        """清理相机资源"""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            
    def _capture_frames(self) -> Optional[Dict[str, Any]]:
        """采集相机帧"""
        try:
            if self.cap is None or not self.cap.isOpened():
                self.logger.warning(f"相机{self.camera_id}未打开，采集失败")
                return None
                
            ret, frame = self.cap.read()
            if not ret:
                self.logger.warning(f"读取帧失败: {self.camera_id}，设备索引{self.device_index}")
                return None
                
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            publish_w = self.camera_config.streams.color_publish_width
            publish_h = self.camera_config.streams.color_publish_height
            capture_w, capture_h = rgb_frame.shape[1], rgb_frame.shape[0]
            if (publish_w, publish_h) != (capture_w, capture_h):
                rgb_frame = cv2.resize(rgb_frame, (publish_w, publish_h), interpolation=cv2.INTER_LINEAR)
            
            return {
                'color': rgb_frame,  # 仅RGB帧有效
                'depth': None        # 无深度图，无需映射/处理
            }
            
        except Exception as e:
            self.logger.error(f"采集失败 {self.camera_id}: {str(e)}")
            return None
