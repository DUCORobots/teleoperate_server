#!/usr/bin/env python3
"""
RealSense相机节点实现
支持D435、D405等RealSense系列相机
支持深度流控制和分辨率配置
"""

import pyrealsense2 as rs
import numpy as np
import time
from typing import Optional, Dict, Any
import cv2

from .base_camera_node import BaseCameraNode
from ..config.config_manager import ConfigManager, CameraConfig

class RealSenseCamera(BaseCameraNode):
    """RealSense相机节点实现"""
    
    def __init__(self, node, config_manager: ConfigManager, camera_config: CameraConfig):
        super().__init__(node, config_manager, camera_config)

        # RealSense管道和配置
        self.pipeline: Optional[rs.pipeline] = None
        self.config: Optional[rs.config] = None
        self.align: Optional[rs.align] = None
        
    def _initialize_camera(self) -> bool:
        """初始化RealSense相机硬件"""
        try:
            # 创建RealSense管道和配置
            self.pipeline = rs.pipeline()
            self.config = rs.config()
            
            # 启用设备
            if self.camera_config.serial_number:
                self.logger.info(f"尝试启用设备: {self.camera_config.serial_number}")
                self.config.enable_device(self.camera_config.serial_number)
            else:
                self.logger.info("未指定序列号，使用默认设备")

            # 配置数据流
            streams = self.camera_config.streams
            
            if not streams or (not streams.color_enabled and not streams.depth_enabled):
                self.logger.error("未配置有效数据流")
                return False

            if streams.color_enabled :
                self.config.enable_stream(
                    rs.stream.color,
                    streams.color_capture_width,
                    streams.color_capture_height,
                    rs.format.rgb8,
                    streams.color_fps
                )

            if streams.depth_enabled :
                self.config.enable_stream(
                    rs.stream.depth,
                    streams.depth_capture_width,
                    streams.depth_capture_height,
                    rs.format.z16,
                    streams.depth_fps
                )

            # 启动管道
            pipeline_profile = self.pipeline.start(self.config)
            
            # 创建对齐对象(将深度图对齐到彩色图)
            self.align = rs.align(rs.stream.color)

            self.logger.info(f"RealSense相机 {self.camera_id} 预热中...")
            warmup_frames = 10
            for i in range(warmup_frames):
                try:
                    frames = self.pipeline.wait_for_frames(timeout_ms=1000)
                except Exception:
                    pass
                time.sleep(0.05)
            self.logger.info(f"RealSense相机 {self.camera_id} 预热完成")

            # 获取深度传感器并设置参数（重试逻辑，兼容设备忙状态）
            depth_sensor = pipeline_profile.get_device().first_depth_sensor()
            if depth_sensor.supports(rs.option.visual_preset):
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        depth_sensor.set_option(rs.option.visual_preset, 3)  # 3 = High Accuracy
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            self.logger.warning(
                                f"设置visual_preset失败(第{attempt+1}次): {e}, 200ms后重试"
                            )
                            time.sleep(0.2)
                        else:
                            self.logger.warning(
                                f"设置visual_preset最终失败: {e}, 继续使用默认预设"
                            )
                
            self.logger.info(f"RealSense相机初始化成功: {self.camera_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"RealSense相机初始化失败 {self.camera_id}: {e}")
            return False
            
    def _cleanup_camera(self) -> None:
        """清理RealSense相机资源"""
        if self.pipeline:
            self.pipeline.stop()
            self.pipeline = None
            self.config = None
            self.align = None

    def _capture_frames(self) -> Optional[Dict[str, Any]]:
        """采集RealSense相机帧"""
        try:
            # 首次采集时等待10秒，后续采集时等待5秒
            timeout_ms = 10000 if self.frames_captured == 0 else 5000
            # 等待帧集
            frames = self.pipeline.wait_for_frames(timeout_ms=timeout_ms)
            
            # 检查启用的流类型
            color_enabled = self.camera_config.streams.color_enabled
            depth_enabled = self.camera_config.streams.depth_enabled

            # 根据启用的流类型进行不同的处理
            if color_enabled and depth_enabled:
                # 同时启用color和depth：使用对齐
                aligned_frames = self.align.process(frames)
                color_frame = aligned_frames.get_color_frame()
                depth_frame = aligned_frames.get_depth_frame()
            elif color_enabled:
                # 只启用color：直接获取color帧
                color_frame = frames.get_color_frame()
                depth_frame = None
            elif depth_enabled:
                # 只启用depth：直接获取depth帧
                color_frame = None
                depth_frame = frames.get_depth_frame()
            else:
                # 没有启用任何流
                self.logger.warning(f"没有启用任何数据流: {self.camera_id}")
                return None
            
            # 检查是否有有效帧
            if (color_enabled and not color_frame) or (depth_enabled and not depth_frame):
                return None
                
            # 转换为numpy数组
            color_image = np.asanyarray(color_frame.get_data()) if color_frame else None
            depth_image = np.asanyarray(depth_frame.get_data()) if depth_frame else None
            
            # 调整发布分辨率
            color_publish_resolution = (self.camera_config.streams.color_publish_width, 
                                self.camera_config.streams.color_publish_height)
            depth_publish_resolution = (self.camera_config.streams.depth_publish_width, 
                                self.camera_config.streams.depth_publish_height)
            
            if color_image is not None:
                capture_resolution = (color_image.shape[1], color_image.shape[0])
                if color_publish_resolution != capture_resolution:
                    color_image = cv2.resize(color_image, color_publish_resolution, interpolation=cv2.INTER_LINEAR)

            if depth_image is not None:
                depth_capture_resolution = (depth_image.shape[1], depth_image.shape[0])
                if depth_publish_resolution != depth_capture_resolution:
                    depth_image = cv2.resize(depth_image, depth_publish_resolution, interpolation=cv2.INTER_NEAREST)
                    
            return {
                'color': color_image,
                'depth': depth_image
            }
            
        except Exception as e:
            self.logger.error(f"采集帧失败 {self.camera_id}: {e}")
            return None