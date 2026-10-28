#!/usr/bin/env python3
"""
HumanoidImageClient - 适配humanoid_vision_system_ws的ZMQ图像客户端
支持Protobuf数据解压缩,使用JSON配置格式
"""

import cv2
import time
import threading
import zmq
import numpy as np
import os
import sys
from typing import Optional, Dict, Any, Tuple
# 确保脚本直跑时可导入本地 proto 和 teleop 包
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_DIR))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from teleop.log_manager import get_logger

_logger = get_logger(__name__)
import zstandard as zstd

try:
    from proto.vision_messages_pb2 import CompressedImage, CameraStatus, CompressionInfo
except ImportError:
    # 兼容包内相对导入
    try:
        from .proto.vision_messages_pb2 import CompressedImage, CameraStatus, CompressionInfo
    except ImportError as e:
        _logger.error(f"导入依赖失败: {e}")
        raise

class TripleRingBuffer:
    """三重环形缓冲 - 线程安全的最新帧缓存"""
    def __init__(self):
        self.buffer = [None, None, None]
        self.write_index = 0
        self.latest_index = -1
        self.read_index = -1
        self.lock = threading.Lock()

    def write(self, data):
        """写入数据：覆盖旧数据，始终保留最新帧"""
        with self.lock:
            self.buffer[self.write_index] = data
            self.latest_index = self.write_index
            self.write_index = (self.write_index + 1) % 3
            # 避免读写索引冲突，如果刚写入的位置即将被读，跳过该位置
            if self.write_index == self.read_index:
                self.write_index = (self.write_index + 1) % 3

    def read(self):
        """读取数据：永远读最新一帧"""
        with self.lock:
            if self.latest_index == -1:
                return None
            self.read_index = self.latest_index
        return self.buffer[self.read_index]

class ZMQ_SubscriberThread(threading.Thread):
    """ZMQ订阅线程 - 负责接收和解压缩Protobuf数据,区分RGB和深度"""
    
    def __init__(self, camera_id: str, image_port: int, status_port: int, 
                 server_ip: str = "localhost", context: Optional[zmq.Context] = None):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.image_port = image_port
        self.status_port = status_port
        self.server_ip = server_ip
        self.context = context or zmq.Context()
        
        # 分离缓存彩色/深度/状态
        self.rgb_buffer = TripleRingBuffer()
        self.depth_buffer = TripleRingBuffer()
        self.status_buffer = TripleRingBuffer()

        self._image_color_fps = 0.0
        self._image_depth_fps = 0.0
        self._last_color_time = time.time()
        self._last_depth_time = time.time()        
        self._color_frame_count = 0
        self._depth_frame_count = 0
        
        self._running = True
        self._connected = False
        
        self.zstd_decompressor = zstd.ZstdDecompressor()
        
        self.image_socket = self.context.socket(zmq.SUB)
        self.status_socket = self.context.socket(zmq.SUB)
        
        # 服务端按 camera_id 作为 topic 发布
        self.image_socket.setsockopt_string(zmq.SUBSCRIBE, camera_id)
        self.status_socket.setsockopt_string(zmq.SUBSCRIBE, camera_id)

    def connect(self) -> bool:
        """连接到ZMQ发布器"""
        try:
            self.image_socket.connect(f"tcp://{self.server_ip}:{self.image_port}")
            self.status_socket.connect(f"tcp://{self.server_ip}:{self.status_port}")
            self._connected = True
            _logger.info(f"[{self.camera_id}] 成功连接到图像服务端: {self.server_ip}:{self.image_port}/{self.status_port}")
            return True
        except Exception as e:
            _logger.error(f"[{self.camera_id}] 连接失败: {e}")
            return False
    
    def stop(self):
        """停止订阅线程"""
        self._running = False
        self.image_socket.close()
        self.status_socket.close()
        self.join(timeout=2.0)
        
    def run(self):
        """主循环:接收和处理Protobuf消息"""
        if not self.connect():
            return

        poller = zmq.Poller()
        poller.register(self.image_socket, zmq.POLLIN)
        poller.register(self.status_socket, zmq.POLLIN)

        while self._running:
            try:
                socks = dict(poller.poll(100))  # 100ms超时

                if self.image_socket in socks and socks[self.image_socket] == zmq.POLLIN:
                    topic, message = self.image_socket.recv_multipart()
                    self._process_image_message(message)

                if self.status_socket in socks and socks[self.status_socket] == zmq.POLLIN:
                    topic, message = self.status_socket.recv_multipart()
                    self._process_status_message(message)
                    
            except zmq.ZMQError as e:
                if self._running:
                    _logger.error(f"[{self.camera_id}] ZMQ错误: {e}")
            except Exception as e:
                if self._running:
                    _logger.error(f"[{self.camera_id}] 处理消息时出错: {e}")
    
    def _process_image_message(self, message: bytes):
        """处理压缩图像消息,根据image_type分发"""
        try:
            compressed_image = CompressedImage()
            compressed_image.ParseFromString(message)
            
            if compressed_image.image_type == CompressedImage.RGB:
                self._update_color_fps()
                frame = self._decode_rgb(compressed_image)
                if frame is not None:
                    self.rgb_buffer.write(frame)
                    
            elif compressed_image.image_type == CompressedImage.DEPTH:
                self._update_depth_fps()
                depth = self._decode_depth(compressed_image)
                if depth is not None:
                    self.depth_buffer.write(depth)
                    
            else:
                _logger.debug(f"[{self.camera_id}] 未知图像类型: {compressed_image.image_type}")
                
        except Exception as e:
            _logger.error(f"[{self.camera_id}] 图像消息处理失败: {e}")
    
    def _decode_rgb(self, compressed_image: CompressedImage) -> Optional[np.ndarray]:
        """解码RGB图像,返回BGR格式的numpy数组"""
        try:
            if compressed_image.compression_info.compression_type == CompressionInfo.JPEG:
                nparr = np.frombuffer(compressed_image.image_data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                return frame
                
            elif compressed_image.compression_info.compression_type == CompressionInfo.PNG:
                nparr = np.frombuffer(compressed_image.image_data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
                if frame is not None and len(frame.shape) == 2:
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                return frame
                
            elif compressed_image.compression_info.compression_type in [
                CompressionInfo.ZSTD_LOSSLESS,
                CompressionInfo.ZSTD_LOSSY
            ]:
                decompressed_data = self.zstd_decompressor.decompress(compressed_image.image_data)
                nparr = np.frombuffer(decompressed_data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                return frame
                
            else:
                _logger.warning(f"[{self.camera_id}] 不支持的RGB压缩格式: {compressed_image.compression_info.compression_type}")
                return None
                
        except Exception as e:
            _logger.error(f"[{self.camera_id}] RGB解码失败: {e}")
            return None
    
    def _decode_depth(self, compressed_image: CompressedImage) -> Optional[np.ndarray]:
        """解码深度图,返回uint16的numpy数组"""
        try:
            if compressed_image.compression_info.compression_type in [
                CompressionInfo.ZSTD_LOSSLESS,
                CompressionInfo.ZSTD_LOSSY
            ]:
                decompressed_data = self.zstd_decompressor.decompress(compressed_image.image_data)
                depth_array = np.frombuffer(decompressed_data, dtype=np.uint16)
                depth_array = depth_array.reshape((compressed_image.original_height, compressed_image.original_width))
                return depth_array
                
            else:
                _logger.warning(f"[{self.camera_id}] 不支持的深度压缩格式: {compressed_image.compression_info.compression_type}")
                return None
                
        except Exception as e:
            _logger.error(f"[{self.camera_id}] 深度解码失败: {e}")
            return None
    
    def _process_status_message(self, message: bytes):
        """处理相机状态消息"""
        try:
            camera_status = CameraStatus()
            camera_status.ParseFromString(message)
            self.status_buffer.write(camera_status)
        except Exception as e:
            _logger.error(f"[{self.camera_id}] 状态消息处理失败: {e}")

    def _update_color_fps(self):
        self._color_frame_count += 1
        current_color_time = time.time()
        # 每1秒计算一次FPS
        if current_color_time - self._last_color_time >= 1.0:
            self._image_color_fps = self._color_frame_count / (current_color_time - self._last_color_time)
            self._color_frame_count = 0
            self._last_color_time = current_color_time

    def _update_depth_fps(self):
        self._depth_frame_count += 1
        current_depth_time = time.time()
        if current_depth_time - self._last_depth_time >= 1.0:
            self._image_depth_fps = self._depth_frame_count / (current_depth_time - self._last_depth_time)
            self._depth_frame_count = 0
            self._last_depth_time = current_depth_time

    def get_color_fps(self) -> float:
        """获取当前图像接收帧率"""
        return round(self._image_color_fps, 1)

    def get_depth_fps(self) -> float:
        """获取当前深度图接收帧率"""
        return round(self._image_depth_fps, 1)

    def get_rgb_frame(self) -> Optional[np.ndarray]:
        """获取最新RGB帧"""
        return self.rgb_buffer.read()
    
    def get_depth_frame(self) -> Optional[np.ndarray]:
        """获取最新深度帧"""
        return self.depth_buffer.read()

    def get_latest_status(self) -> Optional[CameraStatus]:
        """获取最新相机状态"""
        return self.status_buffer.read()


class HumanoidImageClient:
    """
    HumanoidImageClient - 适配humanoid_vision_system_ws的图像客户端
    配置优先级：网络配置 > 默认配置
    """
    
    def __init__(self, image_server_ip: str = "localhost", image_request_port: int = 60000):
        """
        初始化客户端
        image_server_ip: 图像服务端IP地址
        image_request_port: 图像配置请求端口(用于配置请求,默认60000)
        """
        self.image_server_ip = image_server_ip
        self.image_request_port = image_request_port
        
        self._lock = threading.Lock()
        
        # 相机ID到订阅线程的映射
        self.subscribers: Dict[str, ZMQ_SubscriberThread] = {}
        self.camera_config: Dict[str, Any] = {}
        
        self.config_context = zmq.Context()
        self.config_socket = self._create_config_socket()

        self.camera_config = self._initialize_config()

        _logger.info(f"HumanoidImageClient初始化完成,服务端: {image_server_ip}:{image_request_port}")

    def _create_config_socket(self):
        socket = self.config_context.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, 8000)
        socket.setsockopt(zmq.SNDTIMEO, 8000)
        socket.connect(f"tcp://{self.image_server_ip}:{self.image_request_port}")
        time.sleep(0.2)
        return socket

    def _reset_config_socket(self):
        try:
            self.config_socket.close()
        except Exception:
            pass
        self.config_socket = self._create_config_socket()

    def _initialize_config(self) -> Dict[str, Any]:
        """初始化配置，从网络获取相机配置，失败则抛出异常由上层处理"""
        config = self._get_config_from_network()
        _logger.info("成功从网络获取相机配置")
        return config

    def _fetch_config_from_network(self) -> Dict[str, Any]:
        """通过网络从服务端获取配置"""
        with self._lock:
            try:
                self.config_socket.send_json({"type": "get_config"})
                response = self.config_socket.recv_json()
            except Exception:
                self._reset_config_socket()
                raise
        if not isinstance(response, dict):
            raise ValueError("网络返回的相机配置格式非法")
        return response

    def _get_config_from_network(self) -> Dict[str, Any]:
        """通过网络从服务端获取配置并创建订阅线程，空配置或获取失败均抛出异常"""
        response = self._fetch_config_from_network()
        if not response:
            raise ValueError("服务端返回空配置，无可用相机")
        self._create_subscribers_from_config(response)
        return response

    def get_cam_config(self) -> Dict[str, Any]:
        """
        获取相机配置返回相机配置字典，支持重新从网络获取
        """
        try:
            new_config = self._fetch_config_from_network()
            if new_config:
                self.camera_config = new_config
                _logger.info("重新从网络获取相机配置成功")
        except Exception as e:
            _logger.warning(f"重新获取网络配置失败: {e}")

        return self.camera_config
    
    def _create_subscribers_from_config(self, config: Dict[str, Any]):
        """根据配置创建订阅线程,配置顶层为相机ID"""
        if not config:
            return

        # 遍历所有相机
        for camera_id, cam_info in config.items():
            if camera_id in self.subscribers:
                continue

            # 检查是否启用ZMQ
            comm = cam_info.get("communication", {})
            zmq_comm = comm.get("zeromq", {})
            if not zmq_comm.get("enabled", True):
                _logger.info(f"相机 {camera_id} 未启用ZMQ,跳过")
                continue

            image_port = zmq_comm.get("image_publish_port")
            status_port = zmq_comm.get("status_publish_port")
            if not image_port or not status_port:
                _logger.warning(f"相机 {camera_id} 缺少端口配置，跳过")
                continue

            # 创建订阅线程
            subscriber = ZMQ_SubscriberThread(
                camera_id=camera_id,
                image_port=image_port,
                status_port=status_port,
                server_ip=self.image_server_ip
            )
            subscriber.start()
            self.subscribers[camera_id] = subscriber
            _logger.info(f"创建订阅线程: {camera_id} -> 图像端口 {image_port}, 状态端口 {status_port}")

    def refresh_config(self) -> Dict[str, Any]:
        """
        重新从网络获取相机配置，并动态调整订阅线程。返回新的配置字典。
        """
        try:
            new_config = self._fetch_config_from_network()
        except Exception as e:
            _logger.error(f"刷新配置获取失败: {e}")
            return self.camera_config

        if not new_config:
            _logger.warning("刷新配置失败，保持原有配置")
            return self.camera_config

        old_cam_ids = set(self.subscribers.keys())
        new_cam_ids = set(new_config.keys())
        to_remove = old_cam_ids - new_cam_ids
        to_add = new_cam_ids - old_cam_ids
        to_check = old_cam_ids & new_cam_ids

        for cam_id in to_remove:
            _logger.info(f"刷新配置：移除相机 {cam_id}")
            subscriber = self.subscribers.pop(cam_id, None)
            if subscriber:
                subscriber.stop()

        for cam_id in to_add:
            cam_info = new_config[cam_id]
            comm = cam_info.get("communication", {})
            zmq_comm = comm.get("zeromq", {})
            if not zmq_comm.get("enabled", True):
                _logger.info(f"相机 {cam_id} 未启用 ZMQ,跳过")
                continue
            image_port = zmq_comm.get("image_publish_port")
            status_port = zmq_comm.get("status_publish_port")
            if not image_port or not status_port:
                _logger.warning(f"相机 {cam_id} 缺少端口配置,跳过")
                continue
            subscriber = ZMQ_SubscriberThread(
                camera_id=cam_id,
                image_port=image_port,
                status_port=status_port,
                server_ip=self.image_server_ip
            )
            subscriber.start()
            self.subscribers[cam_id] = subscriber
            _logger.info(f"刷新配置：添加相机 {cam_id} -> 图像端口 {image_port}")

        for cam_id in to_check:
            cam_info = new_config[cam_id]
            old_sub = self.subscribers.get(cam_id)
            comm = cam_info.get("communication", {})
            zmq_comm = comm.get("zeromq", {})
            new_enable_zmq = zmq_comm.get("enabled", True)
            new_image_port = zmq_comm.get("image_publish_port")
            new_status_port = zmq_comm.get("status_publish_port")

            if not new_enable_zmq:
                if old_sub:
                    _logger.info(f"刷新配置：相机 {cam_id} ZMQ已禁用,停止订阅")
                    old_sub.stop()
                    del self.subscribers[cam_id]
                continue

            if not old_sub:
                if new_image_port and new_status_port:
                    new_sub = ZMQ_SubscriberThread(
                        camera_id=cam_id,
                        image_port=new_image_port,
                        status_port=new_status_port,
                        server_ip=self.image_server_ip
                    )
                    new_sub.start()
                    self.subscribers[cam_id] = new_sub
                    _logger.info(f"刷新配置：相机 {cam_id} ZMQ已启用,创建订阅")
                continue

            if (old_sub.image_port != new_image_port or
                old_sub.status_port != new_status_port):
                _logger.info(f"刷新配置：相机 {cam_id} 端口变化 "
                               f"({old_sub.image_port}/{old_sub.status_port} -> "
                               f"{new_image_port}/{new_status_port})，重建订阅")
                old_sub.stop()
                self.subscribers.pop(cam_id, None)
                if new_image_port and new_status_port:
                    new_sub = ZMQ_SubscriberThread(
                        camera_id=cam_id,
                        image_port=new_image_port,
                        status_port=new_status_port,
                        server_ip=self.image_server_ip
                    )
                    new_sub.start()
                    self.subscribers[cam_id] = new_sub

        self.camera_config = new_config
        return new_config

    def get_head_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取头部相机RGB图像帧和当前FPS"""
        frame = self._get_rgb_frame_by_camera_id("head_camera")
        fps = self._get_color_fps_by_camera_id("head_camera")
        return frame, fps

    def get_head_depth_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取头部深度图像帧,同时返回当前FPS"""
        frame = self._get_depth_frame_by_camera_id("head_camera")
        fps = self._get_depth_fps_by_camera_id("head_camera")
        return frame, fps
    
    def get_left_wrist_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取左手腕相机RGB图像帧和当前FPS"""
        frame = self._get_rgb_frame_by_camera_id("left_wrist_camera")
        fps = self._get_color_fps_by_camera_id("left_wrist_camera")
        return frame, fps
    
    def get_left_wrist_depth_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取左手腕深度图像帧,同时返回当前FPS"""
        frame = self._get_depth_frame_by_camera_id("left_wrist_camera")
        fps = self._get_depth_fps_by_camera_id("left_wrist_camera")
        return frame, fps
    
    def get_right_wrist_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取右手腕相机RGB图像帧和当前FPS"""
        frame = self._get_rgb_frame_by_camera_id("right_wrist_camera")
        fps = self._get_color_fps_by_camera_id("right_wrist_camera")
        return frame, fps
    
    def get_right_wrist_depth_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取右手腕深度图像帧,同时返回当前FPS"""
        frame = self._get_depth_frame_by_camera_id("right_wrist_camera")
        fps = self._get_depth_fps_by_camera_id("right_wrist_camera")
        return frame, fps

    def get_front_chest_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取正面胸部相机RGB图像帧和当前FPS"""
        frame = self._get_rgb_frame_by_camera_id("front_chest_camera")
        fps = self._get_color_fps_by_camera_id("front_chest_camera")
        return frame, fps
    
    def get_back_chest_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """获取背面胸部相机RGB图像帧和当前FPS"""
        frame = self._get_rgb_frame_by_camera_id("back_chest_camera")
        fps = self._get_color_fps_by_camera_id("back_chest_camera")
        return frame, fps

    def _get_rgb_frame_by_camera_id(self, camera_id: str) -> Optional[np.ndarray]:
        """根据相机ID获取RGB图像帧"""
        if camera_id in self.subscribers:
            return self.subscribers[camera_id].get_rgb_frame()
        return None
    
    def _get_depth_frame_by_camera_id(self, camera_id: str) -> Optional[np.ndarray]:
        """根据相机ID获取深度图像帧"""
        if camera_id in self.subscribers:
            return self.subscribers[camera_id].get_depth_frame()
        return None

    def _get_color_fps_by_camera_id(self, camera_id: str) -> float:
        """根据相机ID获取当前接收帧率"""
        if camera_id in self.subscribers:
            color_fps = self.subscribers[camera_id].get_color_fps()
            return color_fps
        return 0.0

    def _get_depth_fps_by_camera_id(self, camera_id: str) -> float:
        """根据相机ID获取当前接收帧率"""
        if camera_id in self.subscribers:
            depth_fps = self.subscribers[camera_id].get_depth_fps()
            return depth_fps
        return 0.0

    def get_camera_status(self, camera_id: str) -> Optional[CameraStatus]:
        """获取指定相机的状态"""
        if camera_id in self.subscribers:
            return self.subscribers[camera_id].get_latest_status()
        return None
    
    def close(self):
        """关闭客户端"""
        for subscriber in list(self.subscribers.values()):
            subscriber.stop()
        self.subscribers.clear()
        
        try:
            self.config_socket.close()
        finally:
            self.config_context.term()
        _logger.info("HumanoidImageClient已关闭")

ImageClient = HumanoidImageClient

# 测试主函数

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HumanoidImageClient 测试程序")
    parser.add_argument('--host', type=str, default='127.0.0.1', help='图像服务端 IP')
    parser.add_argument('--no-depth', action='store_true', help='不显示深度图窗口')
    args = parser.parse_args()

    # 初始化客户端
    client = HumanoidImageClient(image_server_ip=args.host)
    cam_config = client.get_cam_config()
    
    if not cam_config:
        _logger.error("无法获取相机配置，退出")
        client.close() 
        return

    # 判断哪些相机可用
    head_cfg = cam_config.get("head_camera", {})
    left_cfg = cam_config.get("left_wrist_camera", {})
    right_cfg = cam_config.get("right_wrist_camera", {})
    head_enabled = head_cfg.get("communication", {}).get("zeromq", {}).get("enabled", False)
    left_enabled = left_cfg.get("communication", {}).get("zeromq", {}).get("enabled", False)
    right_enabled = right_cfg.get("communication", {}).get("zeromq", {}).get("enabled", False)
    depth_enabled = head_cfg.get("streams", {}).get("depth", {}).get("enabled", False) and not args.no_depth


    # 创建窗口名称列表
    windows = []
    if head_enabled:
        windows.append(("Head Camera", "head"))
    if left_enabled:
        windows.append(("Left Wrist Camera", "left"))
    if right_enabled:
        windows.append(("Right Wrist Camera", "right"))
    if depth_enabled:
        windows.append(("Head Depth", "depth"))

    if not windows:
        print("没有可用的相机流，请检查配置。")
        client.close()
        return

    # 创建显示FPS信息的函数
    def add_fps_info_bar(image, fps, camera_name):
        """在图像底部添加FPS信息栏"""
        if image is None:
            return None
            
        h, w = image.shape[:2]
        info_bar_height = 30
        new_h = h + info_bar_height
        new_image = np.zeros((new_h, w, 3), dtype=np.uint8)
        new_image[:h, :w] = image

        fps_text = f"{camera_name} - FPS: {fps:.1f}"
        cv2.putText(new_image, fps_text, (10, h + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        return new_image

    try:
        running = True
        while running:
            # 获取并显示 RGB 图像和FPS
            if head_enabled:
                head_img, head_fps = client.get_head_frame()
                if head_img is not None:
                    # 添加FPS信息栏
                    head_img_with_info = add_fps_info_bar(head_img, head_fps, "Head Camera")
                    cv2.imshow("Head Camera", head_img_with_info)
            
            if left_enabled:
                left_img, left_fps = client.get_left_wrist_frame()
                if left_img is not None:
                    left_img_with_info = add_fps_info_bar(left_img, left_fps, "Left Wrist")
                    cv2.imshow("Left Wrist Camera", left_img_with_info)
            
            if right_enabled:
                right_img, right_fps = client.get_right_wrist_frame()
                if right_img is not None:
                    right_img_with_info = add_fps_info_bar(right_img, right_fps, "Right Wrist")
                    cv2.imshow("Right Wrist Camera", right_img_with_info)
            
            # 获取并显示深度图（伪彩色）和FPS
            if depth_enabled:
                depth_frame, depth_fps = client.get_head_depth_frame()
                if depth_frame is not None:
                    # 归一化到0-255
                    depth_norm = cv2.normalize(depth_frame, None, 0, 255, cv2.NORM_MINMAX)
                    depth_8u = depth_norm.astype(np.uint8)
                    depth_color = cv2.applyColorMap(depth_8u, cv2.COLORMAP_JET)
                    depth_with_info = add_fps_info_bar(depth_color, depth_fps, "Head Depth")
                    cv2.imshow("Head Depth", depth_with_info)

            # 按 'q' 退出
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("用户按下 'q'，退出...")
                running = False
                break
    except KeyboardInterrupt:
        print("接收到中断信号，退出...")
    finally:
        client.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()