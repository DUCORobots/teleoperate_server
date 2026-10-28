#!/usr/bin/env python3
"""
WebSocket发布器 - 基于 websockets 库的实时图像/状态推送
"""

import asyncio
import threading
import websockets
from typing import Optional, Set, List
from loguru import logger
from queue import Queue, Empty
import time
import json
from google.protobuf.json_format import MessageToDict
import base64

from ..proto.vision_messages_pb2 import CompressedImage, CameraStatus

class WebSocketConnectionHandler:
    """WebSocket 连接处理器,__call__ 方法签名与 websockets.serve 要求一致"""
    def __init__(self, publisher):
        self.publisher = publisher

    async def __call__(self, websocket: websockets.WebSocketServerProtocol, path: str = ""):
        if len(self.publisher.connected_clients) >= self.publisher.max_connections:
            self.publisher.logger.warning(
                f"达到最大连接数({self.publisher.max_connections})，拒绝连接: {websocket.remote_address}"
            )
            await websocket.close(code=1008, reason="Max connections reached")
            return

        self.publisher.connected_clients.add(websocket)
        client_count = len(self.publisher.connected_clients)
        self.publisher.logger.info(
            f"WebSocket连接: {websocket.remote_address}, 当前连接数: {client_count}"
        )

        try:
            await websocket.wait_closed()
        except Exception as e:
            self.publisher.logger.error(f"与 {websocket.remote_address} 的连接异常: {e}")
        finally:
            if websocket in self.publisher.connected_clients:
                self.publisher.connected_clients.remove(websocket)
                self.publisher.logger.info(
                    f"WebSocket断开: {websocket.remote_address}, 剩余连接数: {len(self.publisher.connected_clients)}"
                )

class WebSocketPublisher:
    """WebSocket 发布器，管理服务器生命周期、消息队列和广播"""

    def __init__(self, camera_id: str, host: str = "0.0.0.0", port: int = 8765,
                 max_connections: int = 10, max_queue_size: int = 200,
                 ping_interval: float = 30.0, logger=None):
        self.camera_id = camera_id
        self.logger = logger or logger.bind(module="websocket_publisher")
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.max_queue_size = max_queue_size
        self.ping_interval = ping_interval
        
        self.server: Optional[websockets.Server] = None
        self.connected_clients: Set[websockets.WebSocketServerProtocol] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.handler = WebSocketConnectionHandler(self)
        self._server_future: Optional[asyncio.Future] = None
        
        self.image_queue = Queue(maxsize=max_queue_size)
        self.status_queue = Queue(maxsize=max_queue_size)
        
        self._running = False
        self._server_thread: Optional[threading.Thread] = None
        self._publishing_thread: Optional[threading.Thread] = None
        self._initialized = False

    def initialize(self) -> bool:
        """初始化 WebSocket 服务器"""
        try:
            self.logger.info(f"[{self.camera_id}] WebSocket发布器初始化: {self.host}:{self.port}")
            self._initialized = True
            return True
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] WebSocket发布器初始化失败: {e}")
            return False

    async def _server_coroutine(self):
        """WebSocket 服务器异步协程"""
        try:
            async with websockets.serve(
                self.handler,
                self.host,
                self.port,
                ping_interval=self.ping_interval,
                ping_timeout=60.0
            ) as self.server:
                self.logger.info(f"WebSocket服务器监听 {self.host}:{self.port}")
                self.loop = asyncio.get_running_loop()
                self._server_future = asyncio.Future()
                await self._server_future
        except asyncio.CancelledError:
            self.logger.info("服务器任务被取消")
        except Exception as e:
            self.logger.error(f"WebSocket服务器异常: {e}", exc_info=True)
            raise
        finally:
            self._server_future = None

    def _server_loop(self):
        """服务器线程循环"""
        try:
            asyncio.run(self._server_coroutine())
        except KeyboardInterrupt:
            self.logger.info("WebSocket服务器接收到中断信号")
        except Exception as e:
            self.logger.error(f"WebSocket服务器线程异常: {e}", exc_info=True)
        finally:
            self.logger.info("WebSocket服务器线程退出")

    def start(self) -> bool:
        """启动 WebSocket 服务器和发布线程"""
        if not self._initialized:
            self.logger.error(f"[{self.camera_id}] WebSocket发布器未初始化,请先调用initialize()")
            return False
            
        self._running = True
        
        self._server_thread = threading.Thread(target=self._server_loop, daemon=True, name="WebSocketServer")
        self._server_thread.start()

        server_start_time = time.time()
        while time.time() - server_start_time < 3.0:
            if self.loop and self.server:
                self.logger.info(f"WebSocket服务器启动完成 ({self.host}:{self.port})")
                break
            time.sleep(0.1)
        else:
            self.logger.warning("WebSocket服务器启动较慢,继续运行")

        self._publishing_thread = threading.Thread(target=self._publishing_loop, daemon=True, name="WebSocketPublisher")
        self._publishing_thread.start()
        
        self.logger.info(f"[{self.camera_id}] WebSocket发布器已启动")
        return True
    
    def stop(self) -> None:
        """停止 WebSocket 发布器"""
        self.logger.info(f"[{self.camera_id}] 停止WebSocket发布器...")
        self._running = False
        
        if self._publishing_thread and self._publishing_thread.is_alive():
            self._publishing_thread.join(timeout=2.0)

        if self.loop and self.loop.is_running():
            try:
                if self._server_future and not self._server_future.done():
                    self.loop.call_soon_threadsafe(self._server_future.cancel)
                self.loop.call_soon_threadsafe(self._cancel_all_tasks)
                self.loop.call_soon_threadsafe(self._close_all_clients)
                time.sleep(0.5)
            except Exception as e:
                self.logger.warning(f"[{self.camera_id}] 关闭事件循环失败: {e}")

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5.0)

        self.connected_clients.clear()
        self.image_queue.queue.clear()
        self.status_queue.queue.clear()
        self.server = None
        self.loop = None

        self.logger.info(f"[{self.camera_id}] WebSocket发布器已停止")

    def _cancel_all_tasks(self):
        """取消事件循环中所有未完成的任务"""
        if not self.loop:
            return
        try:
            tasks: List[asyncio.Task] = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
            for task in tasks:
                task.cancel()
        except Exception as e:
            self.logger.warning(f"[{self.camera_id}] 取消任务失败: {e}")

    def _close_all_clients(self):
        """关闭所有客户端连接"""
        if not self.loop or not self.connected_clients:
            return
        try:
            for client in list(self.connected_clients):
                if not client.closed:
                    asyncio.ensure_future(client.close(code=1000, reason="Server stopping"))
        except Exception as e:
            self.logger.warning(f"[{self.camera_id}] 关闭客户端连接失败: {e}")

    def publish_image(self, compressed_image: CompressedImage) -> bool:
        """发布压缩图像到队列"""
        if not self.connected_clients:
            return True

        if self.image_queue.full():
            dropped = self._handle_queue_overflow()
            if dropped > 0:
                self.logger.warning(f"[{self.camera_id}] 图像队列已满，丢弃 {dropped} 条旧消息")

        try:
            self.image_queue.put(compressed_image, block=False)
            return True
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 图像入队失败: {e}")
            return False
    
    def publish_status(self, camera_status: CameraStatus) -> bool:
        """发布相机状态到队列"""
        if self.status_queue.full():
            try:
                self.status_queue.get_nowait()
            except Empty:
                pass
        try:
            self.status_queue.put(camera_status, block=False)
            return True
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 状态入队失败: {e}")
            return False

    def _publishing_loop(self):
        """发布线程循环"""
        self.logger.info(f"[{self.camera_id}] 发布线程启动")
        time.sleep(0.5)
        while self._running:
            try:
                try:
                    img = self.image_queue.get(block=True, timeout=0.05)
                    self._broadcast_image(img)
                except Empty:
                    pass

                try:
                    status = self.status_queue.get(block=False)
                    self._broadcast_status(status)
                except Empty:
                    pass

                time.sleep(0.01)
            except Exception as e:
                self.logger.error(f"[{self.camera_id}] 发布循环异常: {e}", exc_info=True)
                time.sleep(0.1)
    
    def _handle_queue_overflow(self) -> int:
        """处理图像队列溢出"""
        dropped = 0
        max_drop = min(10, self.max_queue_size // 4)
        try:
            for _ in range(max_drop):
                self.image_queue.get_nowait()
                dropped += 1
                if self.image_queue.empty():
                    break
        except Empty:
            pass
        return dropped

    async def _async_send_message(self, client, message: str):
        """异步发送消息给单个客户端"""
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed as e:
            raise RuntimeError(f"连接已关闭: {e}")
        except websockets.exceptions.WebSocketException as e:
            raise RuntimeError(f"WebSocket异常: {e}")
        except Exception as e:
            raise RuntimeError(f"发送消息失败: {e}")

    def _broadcast_image(self, compressed_image: CompressedImage):
        """广播图像到所有已连接的客户端"""
        if not self.connected_clients:
            return

        loop_to_use = self.loop
        if loop_to_use is None or not loop_to_use.is_running():
            try:
                loop_to_use = asyncio.get_event_loop()
            except RuntimeError as e:
                self.logger.error(f"[{self.camera_id}] 无法获取事件循环: {e}")
                return

        try:
            image_dict = {
                'camera_id': compressed_image.camera_id,
                'image_type': compressed_image.image_type,
                'original_width': compressed_image.original_width,
                'original_height': compressed_image.original_height,
                'compression_info': MessageToDict(compressed_image.compression_info.compression_type),
                'type': 'image'
            }

            if hasattr(compressed_image, 'image_data') and compressed_image.image_data:
                image_dict['image_data'] = base64.b64encode(compressed_image.image_data).decode('utf-8')
            else:
                self.logger.warning(f"[{self.camera_id}] 压缩图像缺少 image_data")
                return

            message = json.dumps(image_dict)
            success_count = 0
            failed_count = 0

            for client in list(self.connected_clients):
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._async_send_message(client, message),
                        loop_to_use
                    )
                    future.result(timeout=2.0)
                    success_count += 1
                except asyncio.TimeoutError:
                    failed_count += 1
                    self.logger.warning(f"[{self.camera_id}] 发送超时，移除连接")
                    self.connected_clients.discard(client)
                except RuntimeError as e:
                    failed_count += 1
                    self.logger.warning(f"[{self.camera_id}] 连接异常: {e}")
                    self.connected_clients.discard(client)
                except Exception as e:
                    failed_count += 1
                    self.logger.error(f"[{self.camera_id}] 发送失败: {e}")
                    self.connected_clients.discard(client)

            if failed_count > 0:
                self.logger.warning(f"[{self.camera_id}] 广播: 成功={success_count}, 失败={failed_count}")

        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 广播异常: {e}", exc_info=True)


    def _broadcast_status(self, camera_status: CameraStatus):
        """广播相机状态到所有已连接的客户端"""
        if not self.connected_clients or not self.loop:
            return

        loop_to_use = self.loop
        if loop_to_use is None or not loop_to_use.is_running():
            try:
                loop_to_use = asyncio.get_event_loop()
            except RuntimeError as e:
                self.logger.error(f"[{self.camera_id}] 无法获取事件循环: {e}")
                return

        try:
            status_dict = {
                'type': 'status',
                'camera_id': camera_status.camera_id,
                'health_status': camera_status.health_status,
                'frame_rate': camera_status.frame_rate
            }
            message = json.dumps(status_dict)

            for client in list(self.connected_clients):
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._async_send_message(client, message),
                        loop_to_use
                    )
                    future.result(timeout=1.0)
                except Exception:
                    self.connected_clients.discard(client)

        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 状态广播异常: {e}", exc_info=True)