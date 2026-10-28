#!/usr/bin/env python3
"""
ROS2消息转换工具 - 将Protobuf消息转换为ROS2消息
"""

from builtin_interfaces.msg import Time as BuiltinTime
from rclpy.time import Time as RclpyTime
from rclpy.duration import Duration

from humanoid_vision_system.msg import CameraStatus as RosCameraStatus
from humanoid_vision_system.msg import CompressedImage as RosCompressedImage
from humanoid_vision_system.msg import CompressionInfo as RosCompressionInfo

from ..proto.vision_messages_pb2 import CameraStatus as PbCameraStatus
from ..proto.vision_messages_pb2 import CompressedImage as PbCompressedImage
from ..proto.vision_messages_pb2 import CompressionInfo as PbCompressionInfo

class ROS2MessageConverter:
    """ROS2消息转换器"""
    
    @staticmethod
    def pb_camera_status_to_ros2(pb_status: PbCameraStatus) -> RosCameraStatus:
        ros_status = RosCameraStatus()
        
        # 基本字段
        ros_status.camera_id = pb_status.camera_id

        # 枚举转换
        health_mapping = {
            PbCameraStatus.UNKNOWN: RosCameraStatus.UNKNOWN,
            PbCameraStatus.HEALTHY: RosCameraStatus.HEALTHY,
            PbCameraStatus.WARNING: RosCameraStatus.WARNING,
            PbCameraStatus.ERROR: RosCameraStatus.ERROR,
            PbCameraStatus.OFFLINE: RosCameraStatus.OFFLINE
        }
        ros_status.health_status = health_mapping.get(pb_status.health_status, RosCameraStatus.UNKNOWN)
        ros_status.frame_rate = float(pb_status.frame_rate)
        
        return ros_status
    
    @staticmethod
    def pb_compressed_image_to_ros2(pb_image: PbCompressedImage) -> RosCompressedImage:
        ros_image = RosCompressedImage()
        
        # 图像类型枚举转换
        image_type_mapping = {
            PbCompressedImage.UNKNOWN: RosCompressedImage.UNKNOWN,
            PbCompressedImage.RGB: RosCompressedImage.RGB,
            PbCompressedImage.DEPTH: RosCompressedImage.DEPTH,
            PbCompressedImage.INFRARED: RosCompressedImage.INFRARED
        }
        ros_image.image_type = image_type_mapping.get(pb_image.image_type, RosCompressedImage.UNKNOWN)
        
        ros_image.image_data = list(pb_image.image_data)
        ros_image.original_width = int(pb_image.original_width)
        ros_image.original_height = int(pb_image.original_height)
        
        # 压缩信息
        if pb_image.HasField('compression_info'):
            pb_compression = pb_image.compression_info
            ros_compression = RosCompressionInfo()
            
            # 更新压缩类型枚举映射，支持新的压缩类型
            compression_type_mapping = {
                PbCompressionInfo.NONE: RosCompressionInfo.NONE,
                PbCompressionInfo.JPEG: RosCompressionInfo.JPEG,
                PbCompressionInfo.ZSTD_LOSSLESS: RosCompressionInfo.ZSTD_LOSSLESS,
                PbCompressionInfo.ZSTD_LOSSY: RosCompressionInfo.ZSTD_LOSSY
            }
            ros_compression.compression_type = compression_type_mapping.get(
                pb_compression.compression_type, RosCompressionInfo.NONE
            )

            ros_image.compression_info = ros_compression
        
        return ros_image

    @staticmethod
    def ros2_camera_status_to_pb(ros_status: RosCameraStatus) -> PbCameraStatus:
        pb_status = PbCameraStatus()
        
        pb_status.camera_id = ros_status.camera_id
        
        health_mapping = {
            RosCameraStatus.UNKNOWN: PbCameraStatus.UNKNOWN,
            RosCameraStatus.HEALTHY: PbCameraStatus.HEALTHY,
            RosCameraStatus.WARNING: PbCameraStatus.WARNING,
            RosCameraStatus.ERROR: PbCameraStatus.ERROR,
            RosCameraStatus.OFFLINE: PbCameraStatus.OFFLINE
        }
        pb_status.health_status = health_mapping.get(ros_status.health_status, PbCameraStatus.UNKNOWN)
        pb_status.frame_rate = float(ros_status.frame_rate)
        
        return pb_status
