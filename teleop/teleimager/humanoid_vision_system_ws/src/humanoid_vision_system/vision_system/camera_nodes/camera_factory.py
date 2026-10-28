#!/usr/bin/env python3
"""相机工厂类"""
import threading
from typing import Optional
from loguru import logger
 
from .base_camera_node import BaseCameraNode
from .opencv_camera import OpenCVCamera
from .realsense_camera import RealSenseCamera
from ..config.config_manager import CameraConfig

class CameraFactory:
    """相机工厂"""
    def __init__(self):
        # 相机类型映射：配置中的camera_type -> 相机子类
        self.camera_type_map = {
            "opencv": OpenCVCamera,
            "realsense": RealSenseCamera,
            "realsensecamera": RealSenseCamera
        }
        self._lock = threading.RLock()
        logger.info(f"相机工厂初始化完成，支持类型：{list(self.camera_type_map.keys())}")
 
    def create_camera(self, node, config_manager, camera_config: CameraConfig) -> Optional[BaseCameraNode]:
        """创建相机实例"""
        with self._lock:
            try:
                camera_id = camera_config.camera_id
                camera_type = camera_config.camera_type.lower()
 
                if camera_type not in self.camera_type_map:
                    logger.error(f"相机{camera_id}类型{camera_config.camera_type}不支持")
                    return None
 
                if not camera_config.enabled:
                    logger.warning(f"相机{camera_id}已禁用")
                    return None
 
                camera_cls = self.camera_type_map[camera_type]
                camera_instance = camera_cls(
                    node=node,
                    config_manager=config_manager,
                    camera_config=camera_config
                )
                return camera_instance
 
            except Exception as e:
                logger.error(f"相机工厂创建相机失败：{e}")
                return None
