#!/usr/bin/env python3
"""动态配置处理器"""
import json
import threading
from typing import Dict, Any, List, Callable, Optional
from loguru import logger
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .config_manager import ConfigManager, CameraConfig

class DynamicConfigHandler:
    """动态配置处理器类"""
    
    def __init__(self, node: Node, config_manager: ConfigManager):
        self.node = node
        self.logger = logger
        self.config_manager = config_manager
        self.camera_add_callback: Optional[Callable] = None
        self.camera_remove_callback: Optional[Callable] = None
        self.camera_update_callback: Optional[Callable] = None
        self._lock = threading.RLock()
        
        self.config_subscriber = self.node.create_subscription(
            String,
            '/vision_system/config_updates',
            self._config_update_callback,
            10
        )
        
        self.logger.info("动态配置处理器初始化完成")
        
    def set_camera_add_callback(self, callback: Callable[[str, CameraConfig], None]) -> None:
        """设置相机添加回调"""
        self.camera_add_callback = callback
        
    def set_camera_remove_callback(self, callback: Callable[[str], None]) -> None:
        """设置相机移除回调"""
        self.camera_remove_callback = callback
        
    def set_camera_update_callback(self, callback: Callable[[str, CameraConfig], None]) -> None:
        """设置相机更新回调"""
        self.camera_update_callback = callback
        
    def _config_update_callback(self, msg: String) -> None:
        """配置更新回调"""
        try:
            with self._lock:
                config_data = json.loads(msg.data)
                self._process_config_update(config_data)
                
        except json.JSONDecodeError as e:
            self.logger.error(f"配置更新JSON解析失败: {e}")
        except Exception as e:
            self.logger.error(f"处理配置更新失败: {e}")
            
    def _process_config_update(self, config_data: Dict[str, Any]) -> None:
        """处理配置更新"""
        action = config_data.get('action', '')
        camera_id = config_data.get('camera_id', '')
        camera_config = config_data.get('camera_config', {})

        if not action or not camera_id:
            self.logger.error("配置更新缺少必要字段: action 或 camera_id")
            return

        if action == 'add':
            self._handle_camera_add(camera_id, camera_config)
        elif action == 'remove':
            self._handle_camera_remove(camera_id)
        elif action == 'update':
            self._handle_camera_update(camera_id, camera_config)
        else:
            self.logger.warning(f"未知的配置操作: {action}")
            
    def _handle_camera_add(self, camera_id: str, camera_config: Dict[str, Any]) -> None:
        """处理相机添加"""
        try:
            success = self.config_manager.add_camera_config(camera_id, camera_config)
            if not success:
                self.logger.error(f"配置管理器添加相机失败: {camera_id}")
                return
                
            if self.camera_add_callback:
                config_obj = self.config_manager.get_camera_config(camera_id)
                if config_obj:
                    self.camera_add_callback(camera_id, config_obj)
            
        except Exception as e:
            self.logger.error(f"添加相机失败 {camera_id}: {e}")
            
    def _handle_camera_remove(self, camera_id: str) -> None:
        """处理相机移除"""
        try:
            success = self.config_manager.remove_camera_config(camera_id)
            if not success:
                self.logger.error(f"配置管理器移除相机失败: {camera_id}")
                return
                
            if self.camera_remove_callback:
                self.camera_remove_callback(camera_id)
                
        except Exception as e:
            self.logger.error(f"移除相机失败 {camera_id}: {e}")
            
    def _handle_camera_update(self, camera_id: str, camera_config: Dict[str, Any]) -> None:
        """处理相机更新"""
        try:
            success = self.config_manager.update_camera_config(camera_id, camera_config)
            if not success:
                self.logger.error(f"配置管理器更新相机失败: {camera_id}")
                return
                
            if self.camera_update_callback:
                config_obj = self.config_manager.get_camera_config(camera_id)
                if config_obj:
                    self.camera_update_callback(camera_id, config_obj)
            
        except Exception as e:
            self.logger.error(f"更新相机失败 {camera_id}: {e}")

    def apply_config_update(self, config_data: Dict[str, Any]) -> None:
        """应用外部配置更新"""
        self._process_config_update(config_data)