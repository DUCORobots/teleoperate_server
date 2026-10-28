#!/usr/bin/env python3
"""视觉系统主入口 - 多相机异步启动与配置管理"""
import argparse
import json
import os
import threading
import time
import signal as _signal
from typing import Dict, Any, Optional

import rclpy
import zmq
from loguru import logger

from vision_system import __version__
from vision_system.config.config_manager import ConfigManager, CameraConfig, CompressionConfig, PublisherCompressionConfig
from vision_system.config.dynamic_config_handler import DynamicConfigHandler
from vision_system.camera_nodes.camera_factory import CameraFactory
from vision_system.communication.communication_manager import CommunicationManager
from vision_system.image_processing.compression import ImageCompressor
from vision_system.image_processing.synchronization import SynchronizationManager
from vision_system.log_manager.loguru_logger import LoguruLogger
from vision_system.proto.vision_messages_pb2 import CompressedImage, CompressionInfo
from google.protobuf.timestamp_pb2 import Timestamp
from rclpy.node import Node
from ament_index_python.packages import get_package_share_directory

def parse_args():
    parser = argparse.ArgumentParser(description="视觉系统服务端")
    parser.add_argument("--auto-detect", action="store_true", default=True,
                        help="启动时自动发现并配置相机")
    parser.add_argument("--no-auto-detect", dest="auto_detect", action="store_false",
                        help="禁用自动发现，使用静态配置")
    return parser.parse_args()

class VisionSystem:
    """视觉系统主类 - 管理所有模块生命周期"""
    def __init__(self, ros2_node: Node, auto_detect: bool = True):
        """初始化视觉系统"""
        self.ros2_node = ros2_node
        self.logger = logger.bind(module="vision_system")

        # 初始化核心模块
        self.config_mgr = ConfigManager(node=ros2_node)
        self.loguru_logger = LoguruLogger(
            log_directory=self.config_mgr.get_global_config("log_manager", {}).get("log_directory", "./logs"),
            log_level=self.config_mgr.get_global_config("log_manager", {}).get("log_level", "INFO"),
            rotation_size_mb=self.config_mgr.get_global_config("log_manager", {}).get("rotation_size_mb", 150),
            retention_days=self.config_mgr.get_global_config("log_manager", {}).get("retention_days", 60),
            compression_enabled=self.config_mgr.get_global_config("log_manager", {}).get("compression_enabled", True),
            encoding=self.config_mgr.get_global_config("log_manager", {}).get("encoding", "utf-8"),
        )
        self.dynamic_config_handler = DynamicConfigHandler(ros2_node, self.config_mgr)

        # 初始化视觉系统模块
        self.sync_mgr = SynchronizationManager(
            sync_tolerance_ms=self.config_mgr.get_global_config("synchronization", {}).get("sync_tolerance_ms", 5.0)
        )
        self.image_compressor = ImageCompressor(logger=self.logger)
        self.camera_factory = CameraFactory()
        self.comm_mgr = CommunicationManager(ros2_node, self.loguru_logger, self.sync_mgr, self.config_mgr)

        # ZMQ配置服务
        self.config_rep_port = self.config_mgr.get_global_config("port_allocation", {}).get("zeromq", {}).get("config_rep_port", 60000)
        self.config_rep_thread: Optional[threading.Thread] = None
        self._config_rep_running = False
        self._start_config_rep_service()

        # 相机实例缓存
        self.camera_instances: Dict[str, Optional[object]] = {}
        self._camera_lock = threading.RLock()

        # 设置动态配置回调
        self.dynamic_config_handler.set_camera_add_callback(self._on_camera_add)
        self.dynamic_config_handler.set_camera_remove_callback(self._on_camera_remove)
        self.dynamic_config_handler.set_camera_update_callback(self._on_camera_update)

        # 自动发现并配置相机
        if auto_detect:
            self.logger.info("启用自动相机发现与配置")
            started = self.config_mgr.auto_configure_cameras(config_handler=self.dynamic_config_handler)
            if started:
                self.logger.info(f"自动启动相机: {started}")
            else:
                self.logger.warning("自动发现完成，未找到可用相机设备，图像服务将以空配置运行")
        else:
            self.logger.info("使用静态配置模式")
            _load_static_config(self)

        self.logger.info("视觉系统初始化完成")


    def _start_config_rep_service(self):
        """启动ZMQ配置服务"""
        self._config_rep_running = True
        self.config_rep_thread = threading.Thread(target=self._config_rep_loop, daemon=True)
        self.config_rep_thread.start()
        self.logger.info(f"ZMQ配置服务已启动，端口 {self.config_rep_port}")

    def _config_rep_loop(self):
        """ZMQ配置服务主循环"""
        context = zmq.Context()
        socket = None
        poller = zmq.Poller()

        while self._config_rep_running:
            try:
                if socket is None:
                    socket = context.socket(zmq.REP)
                    socket.setsockopt(zmq.RCVTIMEO, 2000)
                    socket.bind(f"tcp://*:{self.config_rep_port}")
                    poller.register(socket, zmq.POLLIN)
                    self.logger.info(f"ZMQ服务绑定端口 {self.config_rep_port} 成功")

                socks = dict(poller.poll(100))
                if socket in socks:
                    try:
                        request = socket.recv_json()
                        req_type = request.get("type", "")
                        
                        if req_type == "get_config":
                            response = self._build_config_response()
                        elif req_type == "discover":
                            response = self.config_mgr.get_discovered_devices()
                        elif req_type == "update":
                            response = self._handle_update_request(request)
                        else:
                            response = {"error": f"未知请求类型: {req_type}"}
                        
                        socket.send_json(response)
                    except zmq.ZMQError as e:
                        if e.errno != zmq.EAGAIN:
                            self.logger.error(f"ZMQ通信错误: {e}")
                            poller.unregister(socket)
                            socket.close(linger=0)
                            socket = None
                            continue
                if not self._config_rep_running:
                    break
            except Exception as e:
                self.logger.error(f"ZMQ服务异常: {e}")
                if socket:
                    try:
                        poller.unregister(socket)
                        socket.close(linger=0)
                    except:
                        pass
                    socket = None
                time.sleep(0.5)

        if socket:
            poller.unregister(socket)
            socket.close(linger=0)
        context.term()
        self.logger.info("ZMQ配置服务已停止")

    def _handle_update_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理更新请求"""
        action = request.get("action")
        camera_id = request.get("camera_id")
        camera_config = request.get("camera_config", {})
        
        if action == "add":
            self.dynamic_config_handler.apply_config_update({
                "action": "add",
                "camera_id": camera_id,
                "camera_config": camera_config
            })
            return {"status": "ok", "message": f"相机 {camera_id} 添加中"}
        elif action == "remove":
            self.dynamic_config_handler.apply_config_update({
                "action": "remove",
                "camera_id": camera_id
            })
            return {"status": "ok", "message": f"相机 {camera_id} 移除中"}
        elif action == "update":
            self.dynamic_config_handler.apply_config_update({
                "action": "update",
                "camera_id": camera_id,
                "camera_config": camera_config
            })
            return {"status": "ok", "message": f"相机 {camera_id} 更新中"}
        else:
            return {"error": f"未知操作: {action}"}

    def _build_config_response(self) -> Dict[str, Any]:
        """构建相机配置响应，返回完整配置信息"""
        config = {}
        with self._camera_lock:
            if not self.camera_instances:
                self.logger.warning("无可用相机实例，返回空配置")
                return config
            for camera_id in self.camera_instances.keys():
                cam_cfg = self.config_mgr.get_camera_config(camera_id)
                if cam_cfg and cam_cfg.enabled:
                    cam_dict = {
                        "camera_id": cam_cfg.camera_id,
                        "camera_type": cam_cfg.camera_type,
                        "model": cam_cfg.model,
                        "serial_number": cam_cfg.serial_number,
                        "device_index": cam_cfg.device_index,
                        "position": cam_cfg.position,
                        "enabled": cam_cfg.enabled,
                        "binocular": cam_cfg.binocular,
                        "streams": {
                            "color": {
                                "enabled": cam_cfg.streams.color_enabled,
                                "capture_width": cam_cfg.streams.color_capture_width,
                                "capture_height": cam_cfg.streams.color_capture_height,
                                "publish_width": cam_cfg.streams.color_publish_width,
                                "publish_height": cam_cfg.streams.color_publish_height,
                                "fps": cam_cfg.streams.color_fps,
                            },
                            "depth": {
                                "enabled": cam_cfg.streams.depth_enabled,
                                "capture_width": cam_cfg.streams.depth_capture_width,
                                "capture_height": cam_cfg.streams.depth_capture_height,
                                "publish_width": cam_cfg.streams.depth_publish_width,
                                "publish_height": cam_cfg.streams.depth_publish_height,
                                "fps": cam_cfg.streams.depth_fps,
                            },
                        },
                        "compression": {
                            "rgb": {
                                "quality": cam_cfg.compression.rgb_quality,
                                "format": cam_cfg.compression.rgb_format,
                            },
                            "depth": {
                                "quantization_bits": cam_cfg.compression.depth_quantization_bits,
                                "zstd_compression_level": cam_cfg.compression.depth_zstd_level,
                            },
                        },
                        "communication": {
                            "zeromq": {
                                "enabled": cam_cfg.communication.zeromq_enabled,
                                "image_publish_port": cam_cfg.communication.zeromq_image_port,
                                "status_publish_port": cam_cfg.communication.zeromq_status_port,
                                "max_queue_size": cam_cfg.communication.zeromq_max_queue_size,
                                "high_water_mark": cam_cfg.communication.zeromq_high_water_mark,
                            },
                            "websocket": {
                                "enabled": cam_cfg.communication.websocket_enabled,
                                "host": cam_cfg.communication.websocket_host,
                                "port": cam_cfg.communication.websocket_port,
                                "max_connections": cam_cfg.communication.websocket_max_connections,
                                "max_queue_size": cam_cfg.communication.websocket_max_queue_size,
                                "ping_interval_sec": cam_cfg.communication.websocket_ping_interval,
                            },
                            "ros2": {
                                "enabled": cam_cfg.communication.ros2_enabled,
                                "camera_info_topic": cam_cfg.communication.ros2_camera_info_topic,
                                "status_topic": cam_cfg.communication.ros2_status_topic,
                                "tf_frame_prefix": cam_cfg.communication.ros2_tf_frame_prefix,
                                "qos_depth": cam_cfg.communication.ros2_qos_depth,
                                "qos_reliability": cam_cfg.communication.ros2_qos_reliability,
                            },
                            "webrtc": {
                                "enabled": cam_cfg.communication.webrtc_enabled,
                                "host": cam_cfg.communication.webrtc_host,
                                "port": cam_cfg.communication.webrtc_port,
                                "stun_servers": cam_cfg.communication.webrtc_stun_servers,
                                "turn_servers": cam_cfg.communication.webrtc_turn_servers,
                                "max_bitrate_kbps": cam_cfg.communication.webrtc_max_bitrate_kbps,
                                "min_bitrate_kbps": cam_cfg.communication.webrtc_min_bitrate_kbps,
                                "max_fps": cam_cfg.communication.webrtc_max_fps,
                                "video_codec": cam_cfg.communication.webrtc_video_codec,
                                "max_connections": cam_cfg.communication.webrtc_max_connections,
                                "audio_enabled": cam_cfg.communication.webrtc_audio_enabled,
                                "max_queue_size": cam_cfg.communication.webrtc_max_queue_size,
                                "ice_timeout_sec": cam_cfg.communication.webrtc_ice_timeout_sec,
                                "connection_timeout_sec": cam_cfg.communication.webrtc_connection_timeout_sec,
                            },
                        },
                    }

                    if cam_cfg.compression.publisher_compression:
                        cam_dict["publisher_compression"] = {
                            pub_type: {
                                "rgb": {
                                    "quality": pub_comp.rgb_quality,
                                    "format": pub_comp.rgb_format,
                                },
                                "depth": {
                                    "quantization_bits": pub_comp.depth_quantization_bits,
                                    "zstd_compression_level": pub_comp.depth_zstd_level,
                                },
                            }
                            for pub_type, pub_comp in cam_cfg.compression.publisher_compression.items()
                        }

                    modes_info = self.config_mgr.find_device_modes(
                        camera_type=cam_cfg.camera_type,
                        serial_number=cam_cfg.serial_number,
                        device_index=cam_cfg.device_index,
                    )
                    if modes_info:
                        cam_dict["color_modes"] = modes_info.get("color_modes", [])
                        if "depth_modes" in modes_info:
                            cam_dict["depth_modes"] = modes_info.get("depth_modes", [])

                    config[camera_id] = cam_dict

        return config

    def _on_camera_add(self, camera_id: str, camera_config: CameraConfig) -> None:
        """添加相机回调"""
        with self._camera_lock:
            if camera_id in self.camera_instances:
                self.logger.warning(f"相机{camera_id}已存在")
                return

            try:
                camera = self.camera_factory.create_camera(self.ros2_node, self.config_mgr, camera_config)
                if camera is None:
                    self.logger.error(f"相机{camera_id}创建失败")
                    return

                if not self.comm_mgr.init_camera_communication(camera_config):
                    self.logger.error(f"相机{camera_id}通信初始化失败")
                    return

                camera.set_push_callbacks(
                    frame_callback=lambda frame_data: self._frame_process_pipeline(camera_id, frame_data),
                    status_callback=lambda status_msg: self.comm_mgr.publish_data(camera_id, "status", status_msg)
                )

                if camera.start():
                    self.camera_instances[camera_id] = camera
                    self.logger.info(f"相机{camera_id}启动成功")
                else:
                    self.logger.error(f"相机{camera_id}启动失败")
                    self.comm_mgr.destroy_camera_communication(camera_id)

            except Exception as e:
                self.logger.error(f"相机{camera_id}添加失败: {e}")
                self.comm_mgr.destroy_camera_communication(camera_id)

    def _cleanup_camera_communication(self, camera_id: str) -> None:
        """仅清理相机通信资源(相机采集线程已停止)"""
        with self._camera_lock:
            if camera_id not in self.camera_instances:
                self.logger.warning(f"相机{camera_id}不存在")
                return
            try:
                self.comm_mgr.destroy_camera_communication(camera_id)
                del self.camera_instances[camera_id]
                self.logger.info(f"相机{camera_id}通信资源清理完成")
            except Exception as e:
                self.logger.error(f"相机{camera_id}通信资源清理失败: {e}")

    def _on_camera_remove(self, camera_id: str) -> None:
        """移除相机回调"""
        with self._camera_lock:
            if camera_id not in self.camera_instances:
                self.logger.warning(f"相机{camera_id}不存在")
                return

            try:
                camera = self.camera_instances[camera_id]
                if camera:
                    try:
                        camera.set_push_callbacks(frame_callback=None, status_callback=None)
                    except Exception as e:
                        self.logger.warning(f"清除相机{camera_id}回调失败: {e}")
                    camera.stop()

                self.comm_mgr.destroy_camera_communication(camera_id)
                del self.camera_instances[camera_id]
                self.logger.info(f"相机{camera_id}移除成功")

            except Exception as e:
                self.logger.error(f"相机{camera_id}移除失败: {e}")

    def _on_camera_update(self, camera_id: str, camera_config: CameraConfig) -> None:
        """更新相机回调"""
        self.logger.info(f"更新相机{camera_id}配置")
        self._on_camera_remove(camera_id)
        self._on_camera_add(camera_id, camera_config)
        self.logger.info(f"相机{camera_id}更新完成")

    def _frame_process_pipeline(self, camera_id: str, frame_data: Dict[str, Any]) -> None:
        """帧数据处理流水线"""
        camera_config = self.config_mgr.get_camera_config(camera_id)
        if not camera_config or not camera_config.enabled:
            return
        
        compress_cache = {}
        
        try:
            publishers = self.comm_mgr.camera_comm_state.get(camera_id, {}).get("publishers", {})
            if not publishers:
                return

            rgb_np = frame_data.get("color")
            if rgb_np is not None:
                for publisher_type in publishers.keys():
                    pub_comp_config = camera_config.compression.publisher_compression.get(
                        publisher_type, 
                        self._get_default_publisher_compression_config(camera_config.compression)
                    )

                    cache_key = ("RGB", pub_comp_config.rgb_format, pub_comp_config.rgb_quality, None)

                    if cache_key in compress_cache:
                        compressed_data, compression_info = compress_cache[cache_key]
                    else:
                        compressed_data, compression_info = self.image_compressor.compress_rgb(
                            rgb_np, pub_comp_config.rgb_quality, pub_comp_config.rgb_format
                        )
                        compress_cache[cache_key] = (compressed_data, compression_info)
                    
                    if compressed_data is not None:
                        rgb_msg = self._create_compressed_image_msg(
                            camera_id, compressed_data, CompressedImage.RGB, rgb_np, compression_info
                        )
                        self.comm_mgr.publish_data(camera_id, "image", rgb_msg, publisher_type)

            depth_np = frame_data.get("depth")
            if depth_np is not None:
                for publisher_type in publishers.keys():
                    pub_comp_config = camera_config.compression.publisher_compression.get(
                        publisher_type,
                        self._get_default_publisher_compression_config(camera_config.compression)
                    )

                    cache_key = ("DEPTH", None, pub_comp_config.depth_quantization_bits, 
                            pub_comp_config.depth_zstd_level)
                    
                    if cache_key in compress_cache:
                        compressed_data, compression_info = compress_cache[cache_key]
                    else:
                        compressed_data, compression_info = self.image_compressor.compress_depth(
                            depth_np,
                            pub_comp_config.depth_quantization_bits,
                            pub_comp_config.depth_zstd_level,
                        )
                        compress_cache[cache_key] = (compressed_data, compression_info)
                    
                    if compressed_data is not None:
                        depth_msg = self._create_compressed_image_msg(
                            camera_id, compressed_data, CompressedImage.DEPTH, depth_np, compression_info,
                        )
                        
                        if publisher_type != "webrtc":
                            if not self.comm_mgr.publish_data(camera_id, "image", depth_msg, publisher_type):
                                self.logger.warning(f"[{camera_id}-{publisher_type}] 深度图像发布失败")
                    else:
                        self.logger.warning(f"[{camera_id}-{publisher_type}] 深度图压缩失败，跳过发布")
            
        except Exception as e:
            self.logger.error(f"[{camera_id}] 帧处理流水线异常: {e}", exc_info=True)

    def _get_default_publisher_compression_config(self, compression_config: CompressionConfig) -> PublisherCompressionConfig:
        """获取默认发布器压缩配置"""
        return PublisherCompressionConfig(
            rgb_quality=compression_config.rgb_quality,
            rgb_format=compression_config.rgb_format,
            depth_quantization_bits=compression_config.depth_quantization_bits,
            depth_zstd_level=compression_config.depth_zstd_level,
        )

    def _create_compressed_image_msg(self, camera_id: str, image_data: bytes,
                                    image_type: int, original_frame: Any,
                                    compression_info: CompressionInfo) -> CompressedImage:
        """封装 CompressedImage Protobuf 消息"""
        msg = CompressedImage()

        msg.camera_id = camera_id
        msg.image_type = image_type
        
        msg.image_data = image_data
        msg.original_width = original_frame.shape[1]
        msg.original_height = original_frame.shape[0]
        
        msg.compression_info.CopyFrom(compression_info)
        
        return msg

    def stop(self) -> None:
        """停止视觉系统，清理所有资源"""
        self.logger.info("视觉系统开始停止，清理资源...")

        self.logger.info("清空所有相机推送回调...")
        with self._camera_lock:
            for camera_id, camera in self.camera_instances.items():
                try:
                    camera.set_push_callbacks(frame_callback=None, status_callback=None)
                except Exception as e:
                    self.logger.warning(f"清空相机 {camera_id} 回调失败: {e}")

        self.logger.info("停止所有相机采集线程...")
        with self._camera_lock:
            for camera_id, camera in self.camera_instances.items():
                try:
                    camera.stop()
                except Exception as e:
                    self.logger.warning(f"停止相机 {camera_id} 失败: {e}")

        self._config_rep_running = False
        if self.config_rep_thread and self.config_rep_thread.is_alive():
            self.config_rep_thread.join(timeout=1.0)
            if self.config_rep_thread.is_alive():
                self.logger.warning("ZMQ REP 服务线程未在超时内结束")

        if hasattr(self.ros2_node, 'get_logger'):
            self.ros2_node.get_logger().set_level(50)

        self.logger.info("清理相机通信资源...")
        for camera_id in list(self.camera_instances.keys()):
            self._cleanup_camera_communication(camera_id)

        for camera_id in list(self.config_mgr.active_camera_configs.keys()):
            self.config_mgr.remove_camera_config(camera_id)

        self.comm_mgr.destroy_all()
        self.sync_mgr.reset()

        self.logger.info("视觉系统停止完成，所有资源已清理")

def _load_static_config(vision_system: VisionSystem):
    """从配置文件加载静态配置"""
    config_paths = []
    
    try:
        package_share_dir = get_package_share_directory('humanoid_vision_system')
        config_paths.append(os.path.join(package_share_dir, 'manual_config', 'manual_camera.json'))
    except Exception:
        pass
    
    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    
    if 'install' in current_dir:
        install_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
        config_paths.append(os.path.join(install_root, "share", "humanoid_vision_system", "manual_config", "manual_camera.json"))
    else:
        workspace_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
        config_paths.append(os.path.join(workspace_root, "manual_config", "manual_camera.json"))
    
    config_path = None
    for path in config_paths:
        if os.path.exists(path):
            config_path = path
            break
    
    if not config_path:
        logger.error("未找到配置文件，请检查以下路径:")
        for path in config_paths:
            logger.error(f"  - {path}")
        return

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        for camera_id, camera_config in config.items():
            if camera_id == "global" or not camera_config.get('enabled', False):
                continue

            vision_config = {
                'action': 'add',
                'camera_id': camera_id,
                'camera_config': {
                    'camera_type': camera_config.get('camera_type', 'realsensecamera'),
                    'model': camera_config.get('model', ''),
                    'serial_number': camera_config.get('serial_number', ''),
                    'device_index': camera_config.get('device_index', -1),
                    'position': camera_config.get('position', camera_id.upper()),
                    'enabled': camera_config.get('enabled', False),
                    'binocular': camera_config.get('binocular', False),
                    'streams': {
                        'color': {
                            'enabled': camera_config.get('streams', {}).get('color', {}).get('enabled', False),
                            'capture_width': camera_config.get('streams', {}).get('color', {}).get('capture_width', 640),
                            'capture_height': camera_config.get('streams', {}).get('color', {}).get('capture_height', 480),
                            'publish_width': camera_config.get('streams', {}).get('color', {}).get('publish_width', 640),
                            'publish_height': camera_config.get('streams', {}).get('color', {}).get('publish_height', 480),
                            'fps': camera_config.get('streams', {}).get('color', {}).get('fps', 60)
                        },
                        'depth': {
                            'enabled': camera_config.get('streams', {}).get('depth', {}).get('enabled', False),
                            'capture_width': camera_config.get('streams', {}).get('depth', {}).get('capture_width', 640),
                            'capture_height': camera_config.get('streams', {}).get('depth', {}).get('capture_height', 480),
                            'publish_width': camera_config.get('streams', {}).get('depth', {}).get('publish_width', 640),
                            'publish_height': camera_config.get('streams', {}).get('depth', {}).get('publish_height', 480),
                            'fps': camera_config.get('streams', {}).get('depth', {}).get('fps', 60)
                        }
                    },
                    'compression': {
                        'rgb': {
                            'quality': camera_config.get('compression', {}).get('rgb', {}).get('quality', 85),
                            'format': camera_config.get('compression', {}).get('rgb', {}).get('format', 'JPEG')
                        },
                        'depth': {
                            'quantization_bits': camera_config.get('compression', {}).get('depth', {}).get('quantization_bits', 12),
                            'zstd_compression_level': camera_config.get('compression', {}).get('depth', {}).get('zstd_compression_level', 3)
                        }
                    },
                    'communication': {
                        'zeromq': {
                            'enabled': camera_config.get('communication', {}).get('zeromq', {}).get('enabled', True),
                            'image_publish_port': camera_config.get('communication', {}).get('zeromq', {}).get('image_publish_port', 5555),
                            'status_publish_port': camera_config.get('communication', {}).get('zeromq', {}).get('status_publish_port', 5556)
                        },
                        'websocket': {
                            'enabled': camera_config.get('communication', {}).get('websocket', {}).get('enabled', True),
                            'host': camera_config.get('communication', {}).get('websocket', {}).get('host', '0.0.0.0'),
                            'port': camera_config.get('communication', {}).get('websocket', {}).get('port', 8765)
                        },
                        'webrtc': {
                            'enabled': camera_config.get('communication', {}).get('webrtc', {}).get('enabled', True),
                            'video_codec': camera_config.get('communication', {}).get('webrtc', {}).get('video_codec', 'VP8')
                        }
                    }
                }
            }

            pub_comp_raw = camera_config.get('publisher_compression', {})
            if pub_comp_raw:
                publisher_compression: Dict[str, Any] = {}
                for pub_type, pub_data in pub_comp_raw.items():
                    pub_entry: Dict[str, Any] = {}
                    if 'rgb' in pub_data:
                        pub_entry['rgb'] = {
                            'quality': pub_data['rgb'].get('quality', 85),
                            'format': pub_data['rgb'].get('format', 'JPEG')
                        }
                    if 'depth' in pub_data:
                        pub_entry['depth'] = {
                            'quantization_bits': pub_data['depth'].get('quantization_bits', 12),
                            'zstd_compression_level': pub_data['depth'].get('zstd_compression_level', 3)
                        }
                    if pub_entry:
                        publisher_compression[pub_type] = pub_entry
                if publisher_compression:
                    vision_config['camera_config']['publisher_compression'] = publisher_compression

            vision_system.dynamic_config_handler.apply_config_update(vision_config)
            logger.info(f"已加载相机配置: {camera_id}")
    except FileNotFoundError:
        logger.warning(f"配置文件不存在: {config_path}")
    except Exception as e:
        logger.error(f"加载配置失败: {e}")


def main(args=None):
    """主函数"""
    parsed_args = parse_args()
    rclpy.init(args=None)
    ros2_initialized = True
    ros2_root_node = rclpy.create_node("humanoid_vision_system")
    logger.info(f"视觉系统 v{__version__} 启动, ROS2节点: {ros2_root_node.get_name()}")

    vision_system = VisionSystem(ros2_node=ros2_root_node, auto_detect=parsed_args.auto_detect)

    try:
        rclpy.spin(ros2_root_node)
    except KeyboardInterrupt:
        logger.info("接收到停止信号，关闭视觉系统")
    except Exception as e:
        logger.error(f"视觉系统运行异常: {e}", exc_info=True)
        ros2_initialized = False
    finally:
        _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
        vision_system.stop()
        if ros2_root_node:
            ros2_root_node.destroy_node()
        if ros2_initialized and rclpy.ok():
            rclpy.shutdown()
        logger.info("视觉系统已停止")

if __name__ == "__main__":
    main()