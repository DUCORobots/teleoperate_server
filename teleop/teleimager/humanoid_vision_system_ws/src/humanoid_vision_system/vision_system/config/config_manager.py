#!/usr/bin/env python3
"""配置管理器"""
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger
from ament_index_python.packages import get_package_share_directory
from ..utils.port_manager import PortAllocationError, PortManager
from ..utils.camera_discovery import CameraDiscovery
import rclpy
from rclpy.node import Node

@dataclass
class PublisherCompressionConfig:
    """发布器压缩配置数据类"""
    rgb_quality: int
    rgb_format: str
    depth_quantization_bits: int
    depth_zstd_level: int

@dataclass
class CompressionConfig:
    """压缩配置数据类"""
    rgb_quality: int
    rgb_format: str
    depth_quantization_bits: int
    depth_zstd_level: int
    publisher_compression: Dict[str, PublisherCompressionConfig]  # 发布器压缩配置

@dataclass
class StreamConfig:
    """分辨率流配置数据类"""
    color_enabled: bool
    color_capture_width: int
    color_capture_height: int
    color_publish_width: int
    color_publish_height: int
    color_fps: int
    depth_enabled: bool
    depth_capture_width: int
    depth_capture_height: int
    depth_publish_width: int
    depth_publish_height: int
    depth_fps: int

@dataclass
class CommunicationConfig:
    """通信配置数据类"""
    zeromq_enabled: bool
    zeromq_image_port: int
    zeromq_status_port: int
    zeromq_max_queue_size: int
    zeromq_high_water_mark: int

    websocket_enabled: bool
    websocket_host: str
    websocket_port: int
    websocket_max_connections: int
    websocket_max_queue_size: int
    websocket_ping_interval: float

    ros2_enabled: bool
    ros2_camera_info_topic: str
    ros2_status_topic: str
    ros2_tf_frame_prefix: str
    ros2_qos_depth: int
    ros2_qos_reliability: str

    # WebRTC配置
    webrtc_enabled: bool = False
    webrtc_host: str = "0.0.0.0"
    webrtc_port: int = 8998
    webrtc_stun_servers: List[str] = field(default_factory=list)
    webrtc_turn_servers: List[str] = field(default_factory=list)
    webrtc_video_codec: str = "VP8"
    webrtc_max_bitrate_kbps: int = 2000
    webrtc_min_bitrate_kbps: int = 500
    webrtc_max_fps: int = 30
    webrtc_max_connections: int = 5
    webrtc_audio_enabled: bool = False
    webrtc_max_queue_size: int = 50
    webrtc_ice_timeout_sec: float = 30.0
    webrtc_connection_timeout_sec: float = 60.0

@dataclass
class CameraConfig:
    """相机配置数据类"""
    camera_id: str
    camera_type: str
    model: str
    serial_number: str
    device_index: int
    position: str
    enabled: bool
    binocular: bool
    compression: CompressionConfig
    communication: CommunicationConfig
    streams: StreamConfig

class ConfigManager:
    """配置管理器类"""
    
    def __init__(self, node: Node = None, 
                 global_config_path: str = None, 
                 camera_config_path: str = None):
        self.node = node
        self.logger = logger
        if global_config_path is None:
            package_share_dir = Path(get_package_share_directory('humanoid_vision_system'))
            self.global_config_path = package_share_dir / "config" / "global_config.json"
        else:
            self.global_config_path = Path(global_config_path)
            
        if camera_config_path is None:
            package_share_dir = Path(get_package_share_directory('humanoid_vision_system'))
            self.camera_config_path = package_share_dir / "config" / "camera_config.json"
        else:
            self.camera_config_path = Path(camera_config_path)
            
        # 配置存储
        self.global_config: Dict[str, Any] = {}
        self.camera_default_config: Dict[str, Any] = {}
        self.active_camera_configs: Dict[str, CameraConfig] = {}

        # 端口管理器
        self.port_manager = PortManager()

        # 加载配置
        self._load_configuration()
        self._configure_port_manager()
        self._validate_configuration()
        
    def _load_configuration(self) -> None:
        """加载配置文件"""
        try:
            # 加载全局配置
            if not self.global_config_path.exists():
                raise FileNotFoundError(f"全局配置文件不存在: {self.global_config_path}")
                
            with open(self.global_config_path, 'r', encoding='utf-8') as file:
                self.global_config = json.load(file)
                
            # 加载相机默认配置
            if not self.camera_config_path.exists():
                raise FileNotFoundError(f"相机配置文件不存在: {self.camera_config_path}")
                
            with open(self.camera_config_path, 'r', encoding='utf-8') as file:
                camera_config_data = json.load(file)
                self.camera_default_config = camera_config_data.get('camera_default', {})
                
            self.logger.info(f"成功加载配置文件: {self.global_config_path}, {self.camera_config_path}")
            
        except Exception as e:
            self.logger.error(f"加载配置失败: {e}")
            raise
            
    def _validate_configuration(self) -> None:
        """验证配置"""
        required_global_sections = ['vision_system', 'synchronization', 'log_manager']
        for section in required_global_sections:
            if section not in self.global_config:
                raise ValueError(f"缺少全局配置项: {section}")
                
        required_camera_keys = [
            'camera_type', 'model', 'position', 'enabled', 'binocular', 
            'streams', 'compression', 'communication'
        ]
        for key in required_camera_keys:
            if key not in self.camera_default_config:
                raise ValueError(f"缺少相机配置项: {key}")
                
        self.logger.info("配置验证完成")

    def _configure_port_manager(self) -> None:
        """配置端口管理器"""
        port_config = self.global_config.get('port_allocation', {})
        self.port_manager.configure(port_config)

    def create_camera_config(self, camera_id: str, dynamic_config: Dict[str, Any]) -> CameraConfig:
        """创建相机配置"""
        merged_config = self.camera_default_config.copy()
        merged_config.update(dynamic_config)

        # 解析分辨率帧率配置
        streams_data = merged_config.get('streams', {})
        color_res = streams_data.get('color', {})
        depth_res = streams_data.get('depth', {})
        stream_config = StreamConfig(
            color_enabled=color_res.get('enabled', False),
            color_capture_width=color_res.get('capture_width', 640),
            color_capture_height=color_res.get('capture_height', 480),
            color_publish_width=color_res.get('publish_width', 640),
            color_publish_height=color_res.get('publish_height', 480),
            color_fps=color_res.get('fps', 30),
            depth_enabled=depth_res.get('enabled', False),
            depth_capture_width=depth_res.get('capture_width', 640),
            depth_capture_height=depth_res.get('capture_height', 480),
            depth_publish_width=depth_res.get('publish_width', 640),
            depth_publish_height=depth_res.get('publish_height', 480),
            depth_fps=depth_res.get('fps', 30)
        )

        # 解析压缩配置(公共默认值发布器配置)
        compression_data = merged_config.get('compression', {})
        rgb_data = compression_data.get('rgb', {})
        depth_data = compression_data.get('depth', {})

        # 解析发布器压缩配置(特例发布器覆盖)
        publisher_compression_configs = {}
        publisher_compression_data = merged_config.get('publisher_compression', {})
        
        for publisher_type, pub_comp_data in publisher_compression_data.items():
            pub_rgb_data = pub_comp_data.get('rgb', {})
            pub_depth_data = pub_comp_data.get('depth', {})
            
            publisher_compression_configs[publisher_type] = PublisherCompressionConfig(
                rgb_quality=pub_rgb_data.get('quality', rgb_data.get('quality', 85)),
                rgb_format=pub_rgb_data.get('format', rgb_data.get('format', 'JPEG')),
                depth_quantization_bits=pub_depth_data.get('quantization_bits', depth_data.get('quantization_bits', 12)),
                depth_zstd_level=pub_depth_data.get('zstd_compression_level', depth_data.get('zstd_compression_level', 3)),
            )

        compression_config = CompressionConfig(
            rgb_quality=rgb_data.get('quality', 85),
            rgb_format=rgb_data.get('format', 'JPEG'),
            depth_quantization_bits=depth_data.get('quantization_bits', 12),
            depth_zstd_level=depth_data.get('zstd_compression_level', 3),
            publisher_compression=publisher_compression_configs
        )

        # 解析通信配置
        comm_data = merged_config.get('communication', {})
        zmq_data = comm_data.get('zeromq', {})
        ws_data = comm_data.get('websocket', {})
        ros2_data = comm_data.get('ros2', {})
        webrtc_data = comm_data.get('webrtc', {})
        
        # 为相机分配端口
        external_ports = {
            'zeromq': {
                'image_publish_port': zmq_data.get('image_publish_port'),
                'status_publish_port': zmq_data.get('status_publish_port')
            },
            'websocket': {
                'port': ws_data.get('port')
            }
        }

        try:
            allocated_ports = self.port_manager.allocate_ports_for_camera(
                camera_id, external_ports
            )
        except PortAllocationError as e:
            self.logger.warning(f"相机{camera_id}端口分配失败: {e}")
            # 使用安全的备选方案：基于相机ID生成唯一端口
            try:
                allocated_ports = self.port_manager.generate_fallback_ports(camera_id)
                # 检查备选端口是否已被占用，避免重复
                conflict_ports = [p for p in allocated_ports.values() if p in self.port_manager.allocated_ports]
                if conflict_ports:
                    self.logger.error(f"备选端口仍有冲突: {conflict_ports}，重新生成")
                    raise PortAllocationError(f"Fallback ports conflict: {conflict_ports}")
                for port in allocated_ports.values():
                    self.port_manager.allocated_ports.add(port)
                self.port_manager.camera_ports[camera_id] = allocated_ports
                self.logger.warning(f"使用备选端口: {allocated_ports}")
            except Exception as e2:
                self.logger.error(f"备选端口分配失败: {e2}")
                raise ValueError(f"无法为相机{camera_id}分配端口: {e2}")

        # 解析WebRTC配置
        webrtc_stun_servers = webrtc_data.get('stun_servers', ['stun:stun.l.google.com:19302'])
        webrtc_turn_servers = webrtc_data.get('turn_servers', [])
        webrtc_global_port = self.global_config.get('port_allocation', {}).get('webrtc', {}).get('base_port', 8998)

        communication_config = CommunicationConfig(
            zeromq_enabled=zmq_data.get('enabled', True),
            zeromq_image_port=allocated_ports['zeromq_image'],
            zeromq_status_port=allocated_ports['zeromq_status'],
            zeromq_max_queue_size=zmq_data.get('max_queue_size', 200),
            zeromq_high_water_mark=zmq_data.get('high_water_mark', 50),
            
            websocket_enabled=ws_data.get('enabled', True),
            websocket_host=ws_data.get('host', '0.0.0.0'),
            websocket_port=allocated_ports['websocket'],
            websocket_max_connections=ws_data.get('max_connections', 10),
            websocket_max_queue_size=ws_data.get('max_queue_size', 200),
            websocket_ping_interval=ws_data.get('ping_interval_sec', 30.0),
            
            ros2_enabled=ros2_data.get('enabled', True),
            ros2_camera_info_topic=ros2_data.get('camera_info_topic', '/vision/camera_info'),
            ros2_status_topic=ros2_data.get('status_topic', '/vision/camera_status'),
            ros2_tf_frame_prefix=ros2_data.get('tf_frame_prefix', 'vision'),
            ros2_qos_depth=ros2_data.get('qos_depth', 10),
            ros2_qos_reliability=ros2_data.get('qos_reliability', 'RELIABLE'),
            
            # WebRTC配置
            webrtc_enabled=webrtc_data.get('enabled', True),
            webrtc_host=webrtc_data.get('host', '0.0.0.0'),
            webrtc_port=webrtc_global_port,
            webrtc_stun_servers=webrtc_stun_servers,
            webrtc_turn_servers=webrtc_turn_servers,
            webrtc_max_bitrate_kbps=webrtc_data.get('max_bitrate_kbps', 2000),
            webrtc_min_bitrate_kbps=webrtc_data.get('min_bitrate_kbps', 500),
            webrtc_max_fps=webrtc_data.get('max_fps', 30),
            webrtc_video_codec=webrtc_data.get('video_codec', 'VP8'),
            webrtc_max_connections=webrtc_data.get('max_connections', 5),
            webrtc_audio_enabled=webrtc_data.get('audio_enabled', False),
            webrtc_max_queue_size=webrtc_data.get('max_queue_size', 50),
            webrtc_ice_timeout_sec=webrtc_data.get('ice_timeout_sec', 30.0),
            webrtc_connection_timeout_sec=webrtc_data.get('connection_timeout_sec', 60.0)
        )

        # 创建相机配置对象
        camera_config = CameraConfig(
            camera_id=camera_id,
            camera_type=merged_config.get('camera_type', 'realsensecamera'),
            model=merged_config.get('model', 'UNKNOWN'),
            serial_number=merged_config.get('serial_number', ''),
            device_index=merged_config.get('device_index', -1),
            position=merged_config.get('position', 'UNKNOWN'),
            enabled=merged_config.get('enabled', False),
            binocular=merged_config.get('binocular', False),
            compression=compression_config,
            communication=communication_config,
            streams=stream_config,
        )

        return camera_config

    def add_camera_config(self, camera_id: str, dynamic_config: Dict[str, Any]) -> bool:
        """
        添加相机配置到活动配置列表,返回添加是否成功
        camera_id: 相机ID
        dynamic_config: 动态配置
        """
        try:      
            self.logger.info(f"正在为相机 {camera_id} 创建配置...")
            camera_config = self.create_camera_config(camera_id, dynamic_config)

            self.active_camera_configs[camera_id] = camera_config
            self.logger.info(f"成功添加相机配置: {camera_id}")
            return True
        except Exception as e:
            self.logger.error(f"添加相机配置失败 {camera_id}: {e}")
            return False

    def remove_camera_config(self, camera_id: str) -> bool:
        """
        移除相机配置

        Args:
            camera_id: 相机ID
            
        Returns:
            bool: 移除是否成功
        """
        if camera_id in self.active_camera_configs:
            # 释放端口
            self.port_manager.release_ports(camera_id)
            del self.active_camera_configs[camera_id]
            self.logger.info(f"成功移除相机配置: {camera_id}")
            return True
        else:
            self.logger.warning(f"相机配置不存在: {camera_id}")
            return False

    def update_camera_config(self, camera_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新相机配置
        
        Args:
            camera_id: 相机ID
            updates: 更新配置
            
        Returns:
            bool: 更新是否成功
        """
        if camera_id not in self.active_camera_configs:
            self.logger.error(f"无法更新不存在的相机配置: {camera_id}")
            return False
            
        try:
            # 获取当前配置
            current_config = self.active_camera_configs[camera_id]

            self.port_manager.release_ports(camera_id)

            # 将当前 dataclass 转为嵌套格式字典
            config_dict = self._config_to_nested_dict(current_config)

            # 递归合并更新
            self._deep_update(config_dict, updates)

            updated_config = self.create_camera_config(camera_id, config_dict)
            self.active_camera_configs[camera_id] = updated_config

            self.logger.info(f"成功更新相机配置: {camera_id}")
            return True

        except Exception as e:
            self.logger.error(f"更新相机配置失败 {camera_id}: {e}")
            return False

    def _config_to_nested_dict(self, config: CameraConfig) -> Dict[str, Any]:
        """将 CameraConfig dataclass 转为嵌套格式字典"""
        streams = config.streams
        comp = config.compression
        comm = config.communication

        publisher_compression_dict = {}
        for pub_type, pub_comp in comp.publisher_compression.items():
            publisher_compression_dict[pub_type] = {
                'rgb': {
                    'quality': pub_comp.rgb_quality,
                    'format': pub_comp.rgb_format,
                },
                'depth': {
                    'quantization_bits': pub_comp.depth_quantization_bits,
                    'zstd_compression_level': pub_comp.depth_zstd_level,
                },
            }

        return {
            'camera_type': config.camera_type,
            'model': config.model,
            'serial_number': config.serial_number,
            'device_index': config.device_index,
            'position': config.position,
            'enabled': config.enabled,
            'binocular': config.binocular,
            'streams': {
                'color': {
                    'enabled': streams.color_enabled,
                    'capture_width': streams.color_capture_width,
                    'capture_height': streams.color_capture_height,
                    'publish_width': streams.color_publish_width,
                    'publish_height': streams.color_publish_height,
                    'fps': streams.color_fps,
                },
                'depth': {
                    'enabled': streams.depth_enabled,
                    'capture_width': streams.depth_capture_width,
                    'capture_height': streams.depth_capture_height,
                    'publish_width': streams.depth_publish_width,
                    'publish_height': streams.depth_publish_height,
                    'fps': streams.depth_fps,
                },
            },
            'compression': {
                'rgb': {
                    'quality': comp.rgb_quality,
                    'format': comp.rgb_format,
                },
                'depth': {
                    'quantization_bits': comp.depth_quantization_bits,
                    'zstd_compression_level': comp.depth_zstd_level,
                },
            },
            'publisher_compression': publisher_compression_dict,
            'communication': {
                'zeromq': {
                    'enabled': comm.zeromq_enabled,
                    'image_publish_port': comm.zeromq_image_port,
                    'status_publish_port': comm.zeromq_status_port,
                    'max_queue_size': comm.zeromq_max_queue_size,
                    'high_water_mark': comm.zeromq_high_water_mark,
                },
                'websocket': {
                    'enabled': comm.websocket_enabled,
                    'host': comm.websocket_host,
                    'port': comm.websocket_port,
                    'max_connections': comm.websocket_max_connections,
                    'max_queue_size': comm.websocket_max_queue_size,
                    'ping_interval_sec': comm.websocket_ping_interval,
                },
                'ros2': {
                    'enabled': comm.ros2_enabled,
                    'camera_info_topic': comm.ros2_camera_info_topic,
                    'status_topic': comm.ros2_status_topic,
                    'tf_frame_prefix': comm.ros2_tf_frame_prefix,
                    'qos_depth': comm.ros2_qos_depth,
                    'qos_reliability': comm.ros2_qos_reliability,
                },
                'webrtc': {
                    'enabled': comm.webrtc_enabled,
                    'host': comm.webrtc_host,
                    'stun_servers': comm.webrtc_stun_servers,
                    'turn_servers': comm.webrtc_turn_servers,
                    'max_bitrate_kbps': comm.webrtc_max_bitrate_kbps,
                    'min_bitrate_kbps': comm.webrtc_min_bitrate_kbps,
                    'max_fps': comm.webrtc_max_fps,
                    'video_codec': comm.webrtc_video_codec,
                    'max_connections': comm.webrtc_max_connections,
                    'audio_enabled': comm.webrtc_audio_enabled,
                    'max_queue_size': comm.webrtc_max_queue_size,
                    'ice_timeout_sec': comm.webrtc_ice_timeout_sec,
                    'connection_timeout_sec': comm.webrtc_connection_timeout_sec,
                },
            },
        }

    def _deep_update(self, original: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """深度更新字典"""
        for key, value in updates.items():
            if value is None:
                continue
            if isinstance(value, dict) and key in original and isinstance(original[key], dict):
                self._deep_update(original[key], value)
            else:
                original[key] = value

    def get_camera_config(self, camera_id: str) -> Optional[CameraConfig]:
        """获取指定相机的配置"""
        return self.active_camera_configs.get(camera_id)
        
    def get_all_camera_configs(self) -> Dict[str, CameraConfig]:
        """获取所有相机配置"""
        return self.active_camera_configs.copy()
        
    def get_enabled_cameras(self) -> List[str]:
        """获取所有启用的相机ID"""
        return [camera_id for camera_id, config in self.active_camera_configs.items() 
                if config.enabled]
                
    def get_global_config(self, key: str = None, default: Any = None) -> Any:
        """获取全局配置"""
        if key is None:
            return self.global_config
        return self.global_config.get(key, default)
        
    def get_camera_default_config(self) -> Dict[str, Any]:
        """获取相机默认配置"""
        return self.camera_default_config.copy()

    def get_webrtc_config(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定相机的WebRTC配置
        
        Args:
            camera_id: 相机ID
            
        Returns:
            Optional[Dict[str, Any]]: WebRTC配置字典
        """
        camera_config = self.get_camera_config(camera_id)
        if camera_config and camera_config.communication.webrtc_enabled:
            comm_config = camera_config.communication
            return {
                'enabled': comm_config.webrtc_enabled,
                'host': comm_config.webrtc_host,
                'port': comm_config.webrtc_port,
                'stun_servers': comm_config.webrtc_stun_servers,
                'turn_servers': comm_config.webrtc_turn_servers,
                'max_bitrate_kbps': comm_config.webrtc_max_bitrate_kbps,
                'min_bitrate_kbps': comm_config.webrtc_min_bitrate_kbps,
                'max_fps': comm_config.webrtc_max_fps,
                'video_codec': comm_config.webrtc_video_codec,
                'max_connections': comm_config.webrtc_max_connections,
                'audio_enabled': comm_config.webrtc_audio_enabled,
                'max_queue_size': comm_config.webrtc_max_queue_size,
                'ice_timeout_sec': comm_config.webrtc_ice_timeout_sec,
                'connection_timeout_sec': comm_config.webrtc_connection_timeout_sec
            }
        return None
        
    def get_all_webrtc_cameras(self) -> List[str]:
        """获取所有启用了WebRTC的相机ID"""
        return [camera_id for camera_id, config in self.active_camera_configs.items() 
                if config.enabled and config.communication.webrtc_enabled]


    # 自动发现与配置
    def auto_configure_cameras(self, config_handler=None) -> List[str]:
        """
        自动发现相机并根据默认策略创建配置，启动相机。
        只自动启动头部相机(建议位置为 HEAD 且建议 ID 不为空)
        返回成功启动的相机 ID 列表

        Args:
            config_handler: DynamicConfigHandler实例, 用于触发相机添加回调
        """

        discovery_result = CameraDiscovery.discover()
        devices = discovery_result.get("devices", [])
        if not devices:
            self.logger.warning("自动发现未找到任何相机设备")
            return []
        
        started = []
        for device in devices:
            # 只处理建议启动的相机（头部相机）
            suggested_id = device.get("suggested_id")
            suggested_position = device.get("suggested_position")

            if not suggested_id or suggested_id != "head_camera":
                self.logger.info(f"设备 {device['id']} 不建议自动启动，跳过")
                continue

            # 检查是否已存在
            if suggested_id in self.active_camera_configs:
                self.logger.info(f"相机 {suggested_id} 已存在，跳过自动配置")
                continue
            
            # 确定后端
            default_backend = device.get("default_backend")
            if not default_backend:
                # 寻找可用后端
                for bk in device.get("backends", []):
                    if bk.get("available"):
                        default_backend = bk["id"]
                        break
            if not default_backend:
                self.logger.warning(f"设备 {device['id']} 无可用后端，跳过")
                continue
            
            # 获取首选模式
            backend_config = None
            for bk in device.get("backends", []):
                if bk["id"] == default_backend:
                    backend_config = bk
                    break
            if not backend_config:
                continue
            
            default_mode = backend_config.get("color_default", {"width": 640, "height": 480, "fps": 30})
            
            # 判断是否支持深度（RealSense 设备一般支持）
            supports_depth = device.get("family") == "realsense" and backend_config.get("supports_depth", False)
            
            # 构建完整配置
            dynamic_config = {
                "camera_id": suggested_id,
                "camera_type": self._family_to_camera_type(device["family"], default_backend),
                "model": device.get("model", "Unknown"),
                "serial_number": device.get("serial", ""),
                "device_index": self._extract_video_id(device),
                "position": suggested_position or "UNKNOWN",
                "enabled": True,
                "binocular": False,
                "streams": {
                    "color": {
                        "enabled": True,
                        "capture_width": default_mode["width"],
                        "capture_height": default_mode["height"],
                        "publish_width": default_mode["width"],
                        "publish_height": default_mode["height"],
                        "fps": default_mode["fps"]
                    },
                    "depth": {
                        "enabled": supports_depth,
                        "capture_width": default_mode["width"],
                        "capture_height": default_mode["height"],
                        "publish_width": default_mode["width"],
                        "publish_height": default_mode["height"],
                        "fps": default_mode["fps"]
                    }
                },
                "compression": {
                    "rgb": {"quality": 85, "format": "JPEG"},
                    "depth": {"quantization_bits": 12, "zstd_compression_level": 3}
                },
                "communication": {
                    "zeromq": {"enabled": True},
                    "websocket": {"enabled": False, "host": "0.0.0.0", "port": 8765},
                    "webrtc": {"enabled": True, "video_codec": "VP8"},
                    "ros2": {"enabled": False}
                }
            }
    
            # 添加相机配置
            if config_handler:
                # 通过DynamicConfigHandler添加，触发回调
                config_handler.apply_config_update({
                    "action": "add",
                    "camera_id": suggested_id,
                    "camera_config": dynamic_config
                })
                started.append(suggested_id)
                self.logger.debug(f"自动配置相机 {suggested_id} 成功")
            else:
                # 直接添加配置（不触发回调，仅用于测试）
                if self.add_camera_config(suggested_id, dynamic_config):
                    started.append(suggested_id)
                    self.logger.debug(f"自动配置相机 {suggested_id} 成功（直接添加）")
                else:
                    self.logger.error(f"自动配置相机 {suggested_id} 失败")
        
        return started    

    def _family_to_camera_type(self, family: str, backend: str) -> str:
        """将 family 和 backend 映射到 camera_type 字符串（用于工厂）"""
        if family == "realsense":
            return "realsensecamera"
        if family == "uvc":
            return "opencv"  # UVC 通过 OpenCV 采集
        if family == "opencv":
            return "opencv"
        return "opencv"

    def _extract_video_id(self, device: Dict) -> int:
        """从设备信息中提取首个 video_id"""
        nodes = device.get("nodes", [])
        for node in nodes:
            vid = node.get("video_id")
            if vid is not None:
                return vid
        return -1
    
    def get_discovered_devices(self) -> List[Dict]:
        """获取最近一次发现的设备列表（用于 API 响应）"""
        return CameraDiscovery.discover()
    
    def find_device_modes(self, camera_type: str, serial_number: str = "", device_index: int = -1) -> Dict[str, Any]:
        """
        从发现设备中查找匹配设备的支持模式

        Args:
            camera_type: 相机类型
            serial_number: 序列号(realsense/uvc 用)
            device_index: 设备索引(opencv 用)
        Returns:
            {"color_modes": [...], "depth_modes": [...]} 或空字典
        """
        discovery_result = CameraDiscovery.discover()
        devices = discovery_result.get("devices", [])
        camera_type_lower = camera_type.lower()

        def _node_video_ids(device: Dict[str, Any]) -> List[int]:
            ids: List[int] = []
            for node in device.get("nodes", []):
                vid = node.get("video_id")
                if isinstance(vid, int):
                    ids.append(vid)
            return ids

        for device in devices:
            family = device.get("family", "")

            if "realsense" in camera_type_lower and family == "realsense":
                if device.get("serial") == serial_number:
                    backends = device.get("backends", [])
                    for bk in backends:
                        if bk.get("id") == "realsense":
                            return {
                                "color_modes": bk.get("color_modes", []),
                                "depth_modes": bk.get("depth_modes", []),
                            }

            elif "opencv" in camera_type_lower:
                backends = device.get("backends", [])
                node_ids = _node_video_ids(device)
                matches_index = (device_index < 0) or (device_index in node_ids)

                # 主路径: opencv 设备按 video_id 匹配
                if family == "opencv":
                    for bk in backends:
                        if bk.get("id") == "opencv" and bk.get("video_id") == device_index:
                            modes = bk.get("modes", [])
                            if not modes:
                                modes = [{"width": 640, "height": 480, "fps": 30, "format": "MJPG"}]
                            return {
                                "color_modes": modes
                            }

                if family == "uvc" and matches_index:
                    for bk in backends:
                        if bk.get("id") == "uvc":
                            modes = bk.get("modes", [])
                            if not modes:
                                modes = [{"width": 640, "height": 480, "fps": 30, "format": "MJPG"}]
                            return {
                                "color_modes": modes
                            }

            elif "uvc" in camera_type_lower and family == "uvc":
                if device.get("serial") == serial_number:
                    backends = device.get("backends", [])
                    for bk in backends:
                        if bk.get("id") == "uvc":
                            modes = bk.get("modes", [])
                            return {
                                "color_modes": modes,
                                "depth_modes": [],
                            }

        return {}