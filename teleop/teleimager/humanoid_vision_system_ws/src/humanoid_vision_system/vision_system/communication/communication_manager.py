#!/usr/bin/env python3
"""全局通信管理器"""
import asyncio
import ssl
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Any

from loguru import logger

from .ros2_publisher import ROS2Publisher
from .zmq_publisher import ZeroMQPublisher
from .websocket_publisher import WebSocketPublisher
from .webrtc_publisher import WebRTCPublisher
from .webrtc_signaling_server import WebRTCSignalingServer
from ..config.config_manager import ConfigManager, CameraConfig
from ..utils.ros2_message_converter import ROS2MessageConverter
from ..image_processing.synchronization import SynchronizationManager
from ..log_manager.loguru_logger import LoguruLogger
from ..proto.vision_messages_pb2 import CompressedImage, CameraStatus

class CommunicationManager:
    def __init__(self, ros2_node, loguru_logger: LoguruLogger, sync_mgr: SynchronizationManager, config_manager: ConfigManager):
        self.ros2_node = ros2_node
        self.loguru_logger = loguru_logger
        self.sync_mgr = sync_mgr
        self.config_manager = config_manager
        global_webrtc_config = self.config_manager.get_global_config("port_allocation", {}).get("webrtc", {})
        self.signaling_port = global_webrtc_config.get("base_port", 8998)

        self.signaling_loop: Optional[asyncio.AbstractEventLoop] = None
        self.signaling_server_task: Optional[threading.Thread] = None

        self.camera_comm_state: Dict[str, Dict[str, Any]] = {}
        self.msg_converter = ROS2MessageConverter()
        self.signaling_server: Optional[WebRTCSignalingServer] = None
        self._webrtc_enabled = False
        logger.info("通信管理器初始化完成")

    def init_camera_communication(self, camera_config: CameraConfig) -> bool:
        """初始化相机通信"""
        camera_id = camera_config.camera_id
        comm_config = camera_config.communication
        try:
            self.sync_mgr.register_camera(camera_id)
            self.loguru_logger.setup_camera_logger(camera_id)
            camera_logger = self.loguru_logger.get_camera_logger(camera_id, "communication")

            camera_publishers = {}
            camera_ros2_pub = None  # 相机级ROS2发布器

            if comm_config.zeromq_enabled:
                zmq_pub = ZeroMQPublisher(
                    camera_id=camera_id,
                    image_port=comm_config.zeromq_image_port,
                    status_port=comm_config.zeromq_status_port,
                    max_queue_size=comm_config.zeromq_max_queue_size,
                    high_water_mark=comm_config.zeromq_high_water_mark,
                    logger=camera_logger
                )
                if not zmq_pub.initialize() or not zmq_pub.start():
                    camera_logger.error(f"相机{camera_id} ZMQ发布器启动失败")
                    return False
                camera_publishers["zmq"] = zmq_pub
                camera_logger.info(f"[{camera_id}] ZeroMQ发布器启动成功(图像端口：{comm_config.zeromq_image_port}，状态端口：{comm_config.zeromq_status_port})")


            if comm_config.websocket_enabled:
                ws_pub = WebSocketPublisher(
                    camera_id=camera_id,
                    host=comm_config.websocket_host,
                    port=comm_config.websocket_port,
                    max_connections=comm_config.websocket_max_connections,
                    max_queue_size=comm_config.websocket_max_queue_size,
                    ping_interval=comm_config.websocket_ping_interval,
                    logger=camera_logger
                )
                if not ws_pub.initialize() or not ws_pub.start():
                    camera_logger.error(f"相机{camera_id} WebSocket发布器启动失败")
                    return False
                camera_publishers["websocket"] = ws_pub
                camera_logger.info(f"相机[{camera_id}] WebSocket发布器启动成功({comm_config.websocket_host}:{comm_config.websocket_port})")

            if comm_config.webrtc_enabled:
                self._webrtc_enabled = True
                webrtc_pub = WebRTCPublisher(
                    camera_id=camera_id,
                    host=comm_config.webrtc_host,
                    stun_servers=comm_config.webrtc_stun_servers,
                    turn_servers=comm_config.webrtc_turn_servers,
                    max_bitrate_kbps=comm_config.webrtc_max_bitrate_kbps,
                    min_bitrate_kbps=comm_config.webrtc_min_bitrate_kbps,
                    max_fps=comm_config.webrtc_max_fps,
                    video_codec=comm_config.webrtc_video_codec,
                    audio_enabled=comm_config.webrtc_audio_enabled,
                    max_queue_size=comm_config.webrtc_max_queue_size,
                    logger=camera_logger
                )

                if not webrtc_pub.initialize() or not webrtc_pub.start():
                    camera_logger.error(f"相机{camera_id} WebRTC发布器启动失败")
                    return False
                camera_publishers["webrtc"] = webrtc_pub
                camera_logger.info(f"相机[{camera_id}] WebRTC发布器启动成功({comm_config.webrtc_host})")

                self.ensure_signaling_server()
                timeout = 5
                start_time = time.time()
                while self.signaling_server is None and time.time() - start_time < timeout:
                    time.sleep(0.1)
                if self.signaling_server:
                    self.signaling_server.register_publisher(camera_id, webrtc_pub)
                else:
                    camera_logger.warning(f"相机{camera_id} 信令服务器未启动")

            if comm_config.ros2_enabled:
                camera_ros2_pub = ROS2Publisher(
                    node=self.ros2_node,
                    qos_depth=comm_config.ros2_qos_depth,
                    qos_reliability=comm_config.ros2_qos_reliability,
                    logger=camera_logger
                )
                camera_ros2_pub.create_camera_info_publisher(camera_id)
                camera_ros2_pub.create_status_publisher(camera_id)
                camera_publishers["ros2"] = camera_ros2_pub
                camera_logger.info(f"相机{camera_id} ROS2发布器启动成功")

            self.camera_comm_state[camera_id] = {
                "publishers": camera_publishers,
                "enabled": True,
                "ros2_qos": comm_config.ros2_qos_depth,
                "camera_logger": camera_logger
            }

            camera_logger.info(f"相机{camera_id} 通信初始化成功")
            return True

        except Exception as e:
            logger.error(f"相机{camera_id} 通信初始化失败: {e}")
            self.destroy_camera_communication(camera_id)
            return False

    def publish_data(self, camera_id: str, data_type: str, data: Any, publisher_type: str = None) -> bool:
        """统一发布入口"""
        if camera_id not in self.camera_comm_state or not self.camera_comm_state[camera_id]["enabled"]:
            logger.debug(f"[{camera_id}] 通信未初始化，跳过发布")
            return False

        comm_state = self.camera_comm_state[camera_id]
        publishers = comm_state["publishers"]
        camera_logger = comm_state["camera_logger"]
        publish_success = True

        try:
            if data_type == "image" and isinstance(data, CompressedImage) and hasattr(data, "timestamp"):
                ts_seconds = data.timestamp.seconds + data.timestamp.nanos / 1e9
                self.sync_mgr.update_sync_point(camera_id, ts_seconds)

            if publisher_type and publisher_type in publishers:
                publishers_to_process = {publisher_type: publishers[publisher_type]}
            else:
                publishers_to_process = publishers

            for pub_type, pub in publishers_to_process.items():
                if pub_type == "ros2":
                    ros2_pub: ROS2Publisher = pub
                    if data_type == "status" and isinstance(data, CameraStatus):
                        ros2_pub.publish_status(camera_id, data)
                    elif data_type == "camera_info" and hasattr(ros2_pub, "publish_camera_info"):
                        ros2_pub.publish_camera_info(camera_id, data)

                elif pub_type == "zmq":
                    zmq_pub: ZeroMQPublisher = pub
                    if data_type == "image" and isinstance(data, CompressedImage):
                        zmq_pub.publish_image(data)
                    elif data_type == "status" and isinstance(data, CameraStatus):
                        zmq_pub.publish_status(data)

                elif pub_type == "websocket":
                    ws_pub: WebSocketPublisher = pub
                    if data_type == "image" and isinstance(data, CompressedImage):
                        ws_pub.publish_image(data)
                    elif data_type == "status" and isinstance(data, CameraStatus):
                        ws_pub.publish_status(data)

                elif pub_type == "webrtc":
                    webrtc_pub: WebRTCPublisher = pub
                    if data_type == "image" and isinstance(data, CompressedImage):
                        if data.image_type == CompressedImage.RGB:
                            webrtc_pub.publish_image(data)
                    elif data_type == "status" and isinstance(data, CameraStatus):
                        webrtc_pub.publish_status(data)

        except Exception as e:
            camera_logger.error(f"相机{camera_id} 发布失败: {e}")
            publish_success = False

        return publish_success

    async def _start_signaling_server(self, port: int):
        self.signaling_loop = asyncio.get_running_loop()
        
        # 加载证书(优先从用户目录读取)
        cert_path = Path.home() / ".config" / "xr_teleoperate" / "cert.pem"
        key_path = Path.home() / ".config" / "xr_teleoperate" / "key.pem"
        
        # 如果用户目录没有，尝试从项目目录读取,需要根据实际情况结构调整路径
        if not cert_path.exists() or not key_path.exists():
            current_dir = Path(__file__).parent.parent
            cert_path = current_dir / "cert.pem"
            key_path = current_dir / "key.pem"

        ssl_context = None
        if cert_path.exists() and key_path.exists():
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(cert_path, key_path)
            logger.info(f"加载证书: {cert_path}, {key_path}")
        else:
            logger.warning("未找到证书,使用HTTP")
        
        self.signaling_server = WebRTCSignalingServer(host="0.0.0.0", port=port, ssl_context=ssl_context, config_manager=self.config_manager)
        success = await self.signaling_server.start()
        if not success:
            self.signaling_server = None
            return
        await asyncio.Future()

    def ensure_signaling_server(self):
        """确保信令服务器已启动"""
        if not self._webrtc_enabled:
            return
        if self.signaling_server is None:
            def run_signaling():
                asyncio.run(self._start_signaling_server(self.signaling_port))
            self.signaling_server_task = threading.Thread(target=run_signaling, daemon=True)
            self.signaling_server_task.start()
            timeout = 5
            start = time.time()
            while self.signaling_server is None and time.time() - start < timeout:
                time.sleep(0.1)

    def destroy_camera_communication(self, camera_id: str) -> None:
        """销毁相机通信资源"""
        if camera_id not in self.camera_comm_state:
            logger.warning(f"[{camera_id}] 通信未初始化，跳过销毁")
            return

        comm_state = self.camera_comm_state[camera_id]
        camera_logger = comm_state.get("camera_logger", logger)
        try:
            for pub_type, pub in comm_state["publishers"].items():
                try:
                    camera_logger.info(f"[{camera_id}] 销毁{pub_type}发布器")
                    pub.stop()
                    if hasattr(pub, "destroy"):
                        pub.destroy()
                except Exception as e:
                    camera_logger.warning(f"[{camera_id}] 销毁{pub_type}发布器失败：{e}")

            del self.camera_comm_state[camera_id]
            self.sync_mgr.unregister_camera(camera_id)
            camera_logger.info(f"相机{camera_id} 通信资源销毁完成")

        except Exception as e:
            logger.error(f"相机{camera_id} 销毁失败: {e}")

    def destroy_all(self) -> None:
        """销毁所有通信资源"""
        logger.info("开始销毁所有通信资源")
        for camera_id in list(self.camera_comm_state.keys()):
            self.destroy_camera_communication(camera_id)

        if self.signaling_server and self.signaling_loop:
            stop_future = asyncio.run_coroutine_threadsafe(
                self.signaling_server.stop(),
                self.signaling_loop
            )
            try:
                stop_future.result(timeout=5)
            except Exception as e:
                logger.warning(f"信令服务器停止异常: {e}")
            if self.signaling_server_task and self.signaling_server_task.is_alive():
                self.signaling_server_task.join(timeout=5)
            self.signaling_server = None
            self.signaling_loop = None
            logger.info("WebRTC信令服务器已停止")

        logger.info("所有通信资源已销毁")