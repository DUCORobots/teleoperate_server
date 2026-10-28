#!/usr/bin/env python3
"""WebRTC发布器"""
import asyncio
import time
import threading
import cv2
import numpy as np
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor
from loguru import logger

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
    from aiortc.sdp import candidate_from_sdp
    from av import VideoFrame
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False
    logger.warning("aiortc库未安装,WebRTC功能将不可用")

from ..proto.vision_messages_pb2 import CompressedImage, CameraStatus


class WebRTCVideoTrack(MediaStreamTrack):
    """WebRTC视频轨道"""
    kind = "video"

    def __init__(self, camera_id: str, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.camera_id = camera_id
        self.loop = loop
        self.latest_frame: Optional[VideoFrame] = None
        self.frame_lock = threading.Lock()
        self.frame_condition = asyncio.Condition()

    def update_frame(self, compressed_image: CompressedImage):
        """更新视频帧"""
        try:
            if compressed_image.image_type != CompressedImage.RGB:
                return

            if not compressed_image or not hasattr(compressed_image, 'image_data'):
                logger.warning(f"[{self.camera_id}] 无效的压缩图像数据")
                return
                
            if not compressed_image.image_data:
                logger.warning(f"[{self.camera_id}] 图像数据为空")
                return
                
            # 解码JPEG图像数据,转换为numpy数组
            jpeg_data = np.frombuffer(compressed_image.image_data, dtype=np.uint8)
            
            # 检查数据长度和有效性
            if len(jpeg_data) == 0:
                logger.warning(f"[{self.camera_id}] JPEG数据长度为0")
                return
                
            # 检查JPEG文件头有效性（SOI标记）
            if len(jpeg_data) < 2 or jpeg_data[0] != 0xFF or jpeg_data[1] != 0xD8:
                logger.warning(f"[{self.camera_id}] JPEG数据格式无效,缺少SOI标记")
                return
                
            # 检查JPEG文件尾有效性（EOI标记）
            if len(jpeg_data) >= 2 and (jpeg_data[-2] != 0xFF or jpeg_data[-1] != 0xD9):
                logger.warning(f"[{self.camera_id}] JPEG数据格式无效，缺少EOI标记")
                # 尝试修复：添加EOI标记
                jpeg_data = np.append(jpeg_data, [0xFF, 0xD9])
                
            # 尝试多种解码方式
            frame = None
            decode_methods = [
                (cv2.IMREAD_COLOR, "IMREAD_COLOR"),
                (cv2.IMREAD_UNCHANGED, "IMREAD_UNCHANGED"),
                (cv2.IMREAD_ANYCOLOR, "IMREAD_ANYCOLOR")
            ]
            
            for decode_flag, method_name in decode_methods:
                try:
                    frame = cv2.imdecode(jpeg_data, decode_flag)
                    if frame is not None:
                        logger.debug(f"[{self.camera_id}] 使用{method_name}成功解码JPEG图像")
                        break
                except Exception as e:
                    logger.debug(f"[{self.camera_id}] {method_name}解码失败: {e}")
                    continue
                    
            if frame is None:
                # 如果所有方法都失败，尝试使用PIL作为备选方案
                try:
                    from PIL import Image
                    import io
                    pil_image = Image.open(io.BytesIO(compressed_image.image_data))
                    frame = np.array(pil_image)
                    if frame is not None:
                        logger.info(f"[{self.camera_id}] 使用PIL成功解码JPEG图像")
                except ImportError:
                    logger.warning(f"[{self.camera_id}] PIL库未安装，无法使用备选解码方案")
                except Exception as e:
                    logger.warning(f"[{self.camera_id}] PIL解码也失败: {e}")
                    
            if frame is None:
                return
                
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            else:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            
            video_frame = VideoFrame.from_ndarray(frame_rgb, format='rgb24')
            video_frame.pts = int(self.loop.time() * 1000000)

            async def _update():
                    async with self.frame_condition:
                        self.latest_frame = video_frame
                        self.frame_condition.notify_all()

            asyncio.run_coroutine_threadsafe(_update(), self.loop)
                    
        except ImportError as e:
            logger.error(f"缺少依赖库: {e}")
        except Exception as e:
            logger.error(f"帧更新失败: {e}")

    async def recv(self):
        """接收视频帧"""
        try:
            async with self.frame_condition:
                await self.frame_condition.wait_for(lambda: self.latest_frame is not None)
                frame = self.latest_frame
                self.latest_frame = None

            if frame:
                # 更新时间戳
                now = asyncio.get_event_loop().time()
                frame.pts = int(now * 1000000)  # 微秒
                return frame
            else:
                logger.warning(f"[{self.camera_id}] 返回空帧")
                now = asyncio.get_event_loop().time()
                default_frame = VideoFrame(width=640, height=480)
                default_frame.pts = int(now * 1000000)
                return default_frame
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"recv异常: {e}")
            now = asyncio.get_event_loop().time()
            default_frame = VideoFrame(width=640, height=480)
            default_frame.pts = int(now * 1000000)
            return default_frame

class WebRTCPublisher:
    """WebRTC发布器"""
    def __init__(self, camera_id: str, host: str = "0.0.0.0",
                 stun_servers: List[str] = None, turn_servers: List[str] = None, 
                 max_bitrate_kbps: int = 2000, min_bitrate_kbps: int = 300,
                 max_fps: int = 60, video_codec: str = "H264",
                 audio_enabled: bool = False, max_queue_size: int = 50, 
                 max_connections: int = 10, logger=None):
        self.camera_id = camera_id
        self.host = host
        self.logger = logger
        self.video_track = None
        
        if not WEBRTC_AVAILABLE:
            self.logger.error(f"WebRTC功能不可用,请安装aiortc库")
            return
            
        self.stun_servers = stun_servers or ["stun:stun.l.google.com:19302"]
        self.turn_servers = turn_servers or []
        self.max_bitrate_kbps = max_bitrate_kbps
        self.min_bitrate_kbps = min_bitrate_kbps
        self.max_fps = max_fps
        self.video_codec = video_codec
        self.audio_enabled = audio_enabled
        self.max_queue_size = max_queue_size
        self.max_connections = max_connections
        
        self.connections: Dict[str, RTCPeerConnection] = {}
        self.connection_lock = threading.Lock()
        
        self.loop = None
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.running = False
        
        self.logger.info(f"WebRTC发布器初始化完成: {camera_id}")      

    def initialize(self) -> bool:
        if not WEBRTC_AVAILABLE:
            return False
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            self.running = True
            self.executor.submit(self._run_event_loop)

            start_time = time.time()
            while not self.loop.is_running() and time.time() - start_time < 1:
                time.sleep(0.01)
            
            self.video_track = WebRTCVideoTrack(self.camera_id, self.loop)
            self.logger.info(f"WebRTC发布器初始化成功: {self.camera_id}")
            return True
        except Exception as e:
            self.logger.error(f"WebRTC发布器初始化失败: {e}")
            return False


    def _run_event_loop(self):
        """运行异步事件循环"""
        try:
            self.loop.run_forever()
        except Exception as e:
            self.logger.error(f"事件循环异常: {e}")
        finally:
            self.loop.close()

    async def _create_peer_connection(self, connection_id: str) -> RTCPeerConnection:
        """创建RTCPeerConnection"""
        pc = RTCPeerConnection()
        pc.addTrack(self.video_track)

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                @track.on("ended")
                def on_ended():
                    self.logger.warning(f"[{self.camera_id}] 视频轨道 ended")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc.connectionState == "failed" or pc.connectionState == "closed":
                await self._remove_connection(connection_id)

        return pc

    async def _handle_offer(self, connection_id: str, offer_data: dict) -> dict:
        """处理WebRTC offer"""
        try:
            offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
            pc = await self._create_peer_connection(connection_id)
            await pc.setRemoteDescription(offer)
            
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            
            with self.connection_lock:
                if len(self.connections) < self.max_connections:
                    self.connections[connection_id] = pc
                else:
                    await pc.close()
                    return {"error": "连接数已达上限"}
            
            return {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }
            
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 处理offer失败: {e}")
            return {"error": str(e)}

    async def _handle_ice_candidate(self, connection_id: str, candidate_data: dict):
        """处理ICE候选"""
        try:
            with self.connection_lock:
                pc = self.connections.get(connection_id)
                
            if pc and pc.remoteDescription:
                sdp = candidate_data.get("candidate", "")
                if not sdp:
                    return
                candidate = candidate_from_sdp(sdp)
                candidate.sdpMid = candidate_data.get("sdpMid")
                candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex")
                await pc.addIceCandidate(candidate)
                
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 处理ICE候选失败: {e}")

    async def _remove_connection(self, connection_id: str):
        """移除连接"""
        try:
            with self.connection_lock:
                pc = self.connections.pop(connection_id, None)
                
            if pc:
                await pc.close()
                
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 移除连接失败: {e}")

    def handle_signaling_message(self, connection_id: str, message: dict) -> dict:
        """处理信令消息"""

        if not self.running or not self.loop:
            return {"error": "WebRTC发布器未运行"}
            
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._handle_signaling_message_async(connection_id, message), 
                self.loop
            )
            return future.result(timeout=10)
            
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] 处理信令消息失败: {e}")
            return {"error": str(e)}

    async def _handle_signaling_message_async(self, connection_id: str, message: dict) -> dict:
        """异步处理信令消息"""
        msg_type = message.get("type")
        
        if msg_type == "offer":
            return await self._handle_offer(connection_id, message)
        elif msg_type == "ice-candidate":
            await self._handle_ice_candidate(connection_id, message)
            return {"status": "ok"}
        else:
            return {"error": f"不支持的消息类型: {msg_type}"}

    def publish_image(self, compressed_image: CompressedImage):
        """发布图像到WebRTC视频轨道"""
        if not self.running:
            return
            
        try:
            self.video_track.update_frame(compressed_image)
            
        except Exception as e:
            self.logger.error(f"[{self.camera_id}] WebRTC图像发布失败: {e}")

    def publish_status(self, camera_status: CameraStatus):
        """发布相机状态"""
        pass

    def start(self) -> bool:
        """启动WebRTC发布器"""
        if not WEBRTC_AVAILABLE:
            return False
            
        self.running = True
        self.logger.info(f"WebRTC发布器已启动: {self.camera_id}")
        return True

    def stop(self):
        """停止WebRTC发布器"""
        self.running = False

        if self.loop:
            # 异步关闭所有连接
            close_futures = []
            with self.connection_lock:
                for conn_id, pc in list(self.connections.items()):
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self._remove_connection(conn_id),
                            self.loop
                        )
                        close_futures.append(future)
                    except Exception as e:
                        self.logger.warning(f"[{self.camera_id}] 提交关闭连接 {conn_id} 失败: {e}")
                self.connections.clear()

            # 等待异步关闭任务完成
            for future in close_futures:
                try:
                    future.result(timeout=2)
                except TimeoutError:
                    self.logger.warning(f"[{self.camera_id}] 关闭连接超时")
                except (RuntimeError, asyncio.CancelledError) as e:
                    self.logger.warning(f"[{self.camera_id}] 关闭连接失败: {e}")

            # 停止事件循环
            if self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)

        self.executor.shutdown(wait=True)
        self.logger.info(f"WebRTC发布器已停止: {self.camera_id}")


    def destroy(self):
        """销毁WebRTC发布器"""
        self.stop()
