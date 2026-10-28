#!/usr/bin/env python3
"""ROS2发布器"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from sensor_msgs.msg import CameraInfo
from loguru import logger
from typing import Dict, Any

from humanoid_vision_system.msg import CameraStatus as RosCameraStatus
from ..proto.vision_messages_pb2 import CameraStatus as PbCameraStatus
from ..utils.ros2_message_converter import ROS2MessageConverter

class ROS2Publisher:
    """ROS2发布器类"""
    
    def __init__(self, node: Node, topic_prefix: str = "/vision",
                 qos_depth: int = 10, qos_reliability: str = "RELIABLE",
                 logger: logger = None):
        self.node = node
        self.logger = logger
        self.topic_prefix = topic_prefix
        
        # 配置QoS
        if qos_reliability.upper() == "RELIABLE":
            reliability = ReliabilityPolicy.RELIABLE
        else:
            reliability = ReliabilityPolicy.BEST_EFFORT
            
        self.qos_profile = QoSProfile(
            depth=qos_depth,
            reliability=reliability,
            durability=DurabilityPolicy.VOLATILE
        )
        
        self.camera_info_publishers: Dict[str, Any] = {}
        self.status_publishers: Dict[str, Any] = {}

    def stop(self):
        self.destroy_publishers()

    def create_camera_info_publisher(self, camera_id: str) -> None:
        """创建相机信息发布器"""
        topic_name = f"{self.topic_prefix}/{camera_id}/camera_info"
        publisher = self.node.create_publisher(
            CameraInfo, topic_name, self.qos_profile
        )
        self.camera_info_publishers[camera_id] = publisher
        self.logger.info(f"创建相机信息发布器: {topic_name}")
        
    def create_status_publisher(self, camera_id: str) -> None:
        """创建状态发布器"""
        topic_name = f"{self.topic_prefix}/{camera_id}/status"
        publisher = self.node.create_publisher(
            RosCameraStatus, topic_name, self.qos_profile
        )
        self.status_publishers[camera_id] = publisher
        self.logger.info(f"创建状态发布器: {topic_name}")

    def publish_camera_info(self, camera_id: str, camera_info: CameraInfo) -> bool:
        """发布相机信息"""
        if camera_id not in self.camera_info_publishers:
            self.create_camera_info_publisher(camera_id)
            
        try:
            self.camera_info_publishers[camera_id].publish(camera_info)
            self.logger.debug(f"发布相机信息: {camera_id}")
            return True
        except Exception as e:
            self.logger.error(f"发布相机信息失败 {camera_id}: {e}")
            return False
            
    def publish_status(self, camera_id: str, status: PbCameraStatus) -> bool:
        """发布相机状态"""
        if camera_id not in self.status_publishers:
            self.create_status_publisher(camera_id)
            
        try:
            ros_status = ROS2MessageConverter.pb_camera_status_to_ros2(status)
            self.status_publishers[camera_id].publish(ros_status)
            self.logger.debug(f"发布相机状态: {camera_id}")
            return True
        except Exception as e:
            self.logger.error(f"发布相机状态失败 {camera_id}: {e}")
            return False

    def destroy_publishers(self) -> None:
        """销毁所有发布器"""
        for publisher in self.camera_info_publishers.values():
            self.node.destroy_publisher(publisher)
            
        for publisher in self.status_publishers.values():
            self.node.destroy_publisher(publisher)
            
        self.camera_info_publishers.clear()
        self.status_publishers.clear()
