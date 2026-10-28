#!/usr/bin/env python3
"""
ZeroMQ 发布器 - 通过 PUB 套接字发布图像和状态数据
"""

import zmq
import threading
from typing import Optional
from loguru import logger
from queue import Queue, Empty
import time

from ..proto.vision_messages_pb2 import CompressedImage, CameraStatus

class ZeroMQPublisher:
    """ZeroMQ 发布器，使用 PUB 套接字发布图像和状态"""

    def __init__(self, camera_id: str, image_port: int = 5598, status_port: int = 5599,
                 max_queue_size: int = 200, high_water_mark: int = 100,
                 logger: logger = None):
        self.camera_id = camera_id
        self.logger = logger
        self.image_port = image_port
        self.status_port = status_port
        self.max_queue_size = max_queue_size
        self.high_water_mark = high_water_mark
        
        self.context: Optional[zmq.Context] = None
        self.image_socket: Optional[zmq.Socket] = None
        self.status_socket: Optional[zmq.Socket] = None
        
        self.image_queue = Queue(maxsize=max_queue_size)
        self.status_queue = Queue(maxsize=max_queue_size)
        
        self._running = False
        self._image_thread: Optional[threading.Thread] = None
        self._status_thread: Optional[threading.Thread] = None
        self._initialized = False

    def initialize(self) -> bool:
        """初始化 ZeroMQ 套接字"""
        if self._initialized:
            self.logger.warning(f"[{self.camera_id}] ZeroMQ发布器已初始化,跳过")
            return True

        try:
            self.context = zmq.Context()
            
            self.image_socket = self.context.socket(zmq.PUB)
            self.image_socket.bind(f"tcp://*:{self.image_port}")
            self.image_socket.setsockopt(zmq.SNDHWM, self.high_water_mark)
            
            self.status_socket = self.context.socket(zmq.PUB)
            self.status_socket.bind(f"tcp://*:{self.status_port}")
            self.status_socket.setsockopt(zmq.SNDHWM, self.high_water_mark)
            
            self._initialized = True
            self.logger.info(f"[{self.camera_id}] ZeroMQ发布器初始化成功: 图像端口={self.image_port}, 状态端口={self.status_port}")
            return True
            
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] ZeroMQ发布器初始化失败: {e}")
            return False
            
    def start(self) -> bool:
        """启动发布线程"""
        if not self._initialized:
            self.logger.error(f"[{self.camera_id}] ZeroMQ发布器未初始化")
            return False
            
        self._running = True
        
        self._image_thread = threading.Thread(target=self._image_publishing_loop, daemon=True)
        self._image_thread.start()
        
        self._status_thread = threading.Thread(target=self._status_publishing_loop, daemon=True)
        self._status_thread.start()
        
        self.logger.info(f"[{self.camera_id}] ZeroMQ发布线程已启动")
        return True
        
    def stop(self) -> None:
        """停止发布器"""
        self._running = False
        
        if self._image_thread and self._image_thread.is_alive():
            self._image_thread.join(timeout=5.0)
            
        if self._status_thread and self._status_thread.is_alive():
            self._status_thread.join(timeout=5.0)
            
        if self.image_socket:
            self.image_socket.close()
            
        if self.status_socket:
            self.status_socket.close()
            
        if self.context:
            self.context.term()
            
        self.logger.info(f"[{self.camera_id}] ZeroMQ发布器已停止")
        
    def publish_image(self, compressed_image: CompressedImage) -> bool:
        """发布压缩图像数据到队列"""
        if self.image_queue.full():
            dropped = self._handle_queue_overflow(self.image_queue)
            if dropped > 0:
                self.logger.warning(f"[{self.camera_id}] 图像队列已满，丢弃 {dropped} 条旧消息")
                
        try:
            self.image_queue.put(compressed_image, block=False)
            return True
        except:
            self.logger.error(f"[{self.camera_id}] 图像队列已满，入队失败")
            return False
            
    def publish_status(self, camera_status: CameraStatus) -> bool:
        """发布相机状态到队列"""
        if self.status_queue.full():
            dropped = self._handle_queue_overflow(self.status_queue)
            if dropped > 0:
                self.logger.warning(f"[{self.camera_id}] 状态队列已满，丢弃 {dropped} 条旧消息")
                
        try:
            self.status_queue.put(camera_status, block=False)
            return True
        except:
            self.logger.error(f"[{self.camera_id}] 状态队列已满，入队失败")
            return False

    def _handle_queue_overflow(self, queue: Queue) -> int:
        """处理队列溢出"""
        dropped = 0
        max_drop = min(10, self.max_queue_size // 4)
        try:
            for _ in range(max_drop):
                queue.get_nowait()
                dropped += 1
                if queue.empty():
                    break
        except Empty:
            pass
        return dropped
            
    def _image_publishing_loop(self) -> None:
        """图像发布线程循环"""
        while self._running:
            try:
                compressed_image = self.image_queue.get(block=True, timeout=0.1)
                serialized_data = compressed_image.SerializeToString()
                topic = compressed_image.camera_id.encode('utf-8')
                self.image_socket.send_multipart([topic, serialized_data])
                
            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"[{self.camera_id}] 图像发布异常: {e}")
                time.sleep(0.01)
                
    def _status_publishing_loop(self) -> None:
        """状态发布线程循环"""
        while self._running:
            try:
                camera_status = self.status_queue.get(block=True, timeout=0.1)
                serialized_data = camera_status.SerializeToString()
                topic = camera_status.camera_id.encode('utf-8')
                self.status_socket.send_multipart([topic, serialized_data])
                
            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"[{self.camera_id}] 状态发布异常: {e}")
                time.sleep(0.01)
