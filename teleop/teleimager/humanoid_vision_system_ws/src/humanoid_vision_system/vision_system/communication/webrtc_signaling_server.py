#!/usr/bin/env python3
"""WebRTC信令服务器"""
import asyncio
import ssl
from aiohttp import web
from typing import Dict, Optional
from loguru import logger

from .webrtc_publisher import WebRTCPublisher

class WebRTCSignalingServer:
    """WebRTC信令服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8998, ssl_context: ssl.SSLContext = None, config_manager=None):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.config_manager = config_manager
        self.publishers: Dict[str, WebRTCPublisher] = {}
        self.app = web.Application(middlewares=[self.cors_middleware])
        self.setup_routes()
        self.registered_publishers: Dict[str, WebRTCPublisher] = {}

    @staticmethod
    async def cors_middleware(app, handler):
        """CORS中间件"""
        async def middleware_handler(request):
            if request.method == 'OPTIONS':
                return web.Response(
                    status=200,
                    headers={
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                        'Access-Control-Allow-Headers': 'Content-Type',
                    }
                )
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        return middleware_handler

    def setup_routes(self):
        """设置HTTP路由"""
        self.app.router.add_post('/webrtc/{camera_id}/offer', self.handle_offer)
        self.app.router.add_post('/webrtc/{camera_id}/ice-candidate', self.handle_ice_candidate)
        self.app.router.add_get('/webrtc/{camera_id}/status', self.handle_status)
        self.app.router.add_get('/webrtc/cameras', self.handle_camera_list)
        self.app.router.add_post('/offer', self.handle_offer_generic)

    async def handle_offer_generic(self, request):
        """处理通用offer请求"""
        camera_id = "head_camera"
        try:
            data = await request.json()
            publisher = self.get_or_create_publisher(camera_id)
            if not publisher:
                return web.json_response({"error": "无法创建WebRTC发布器"}, status=500)

            connection_id = data.get('connection_id', f'conn_{camera_id}')
            result = publisher.handle_signaling_message(connection_id, data)
            return web.json_response(result)
        except Exception as e:
            logger.error(f"处理通用 offer 失败: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_offer(self, request):
        """处理WebRTC offer请求"""
        try:
            camera_id = request.match_info['camera_id']
            data = await request.json()

            publisher = self.get_or_create_publisher(camera_id)
            if not publisher:
                return web.json_response({"error": "无法创建WebRTC发布器"}, status=500)

            connection_id = data.get('connection_id', f'conn_{camera_id}')
            result = publisher.handle_signaling_message(connection_id, data)
            return web.json_response(result)
            
        except Exception as e:
            logger.error(f"处理offer失败: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_ice_candidate(self, request):
        """处理ICE候选请求"""
        try:
            camera_id = request.match_info['camera_id']
            data = await request.json()
            
            publisher = self.publishers.get(camera_id)
            if not publisher:
                publisher = self.registered_publishers.get(camera_id)
            if not publisher:
                return web.json_response({"error": "相机未找到"}, status=404)
            
            connection_id = data.get('connection_id', f'conn_{camera_id}')
            result = publisher.handle_signaling_message(connection_id, data)
            return web.json_response(result)
            
        except Exception as e:
            logger.error(f"处理ICE候选失败: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_status(self, request):
        """获取相机状态"""
        camera_id = request.match_info['camera_id']
        publisher = self.publishers.get(camera_id)
        if not publisher:
            return web.json_response({"error": "相机未找到"}, status=404)
        
        return web.json_response({
            "camera_id": camera_id,
            "connected": publisher.running,
            "connections": len(publisher.connections)
        })
    
    async def handle_camera_list(self, request):
        """获取相机列表"""
        return web.json_response({
            "cameras": list(self.publishers.keys()),
            "total": len(self.publishers)
        })

    def register_publisher(self, camera_id: str, publisher: WebRTCPublisher):
        """注册外部创建的发布器"""
        self.registered_publishers[camera_id] = publisher
        logger.info(f"注册WebRTC发布器: {camera_id}")

    def get_or_create_publisher(self, camera_id: str) -> Optional[WebRTCPublisher]:
        """获取或创建WebRTC发布器"""
        if camera_id in self.registered_publishers:
            return self.registered_publishers[camera_id]

        if camera_id not in self.publishers:
            try:
                if self.config_manager is None:
                    logger.warning(f"无法自动创建发布器: 未提供 config_manager")
                    return None

                camera_config = self.config_manager.get_camera_config(camera_id)

                if not camera_config:
                    logger.warning(f"相机配置未找到: {camera_id}")
                    return None

                comm = camera_config.communication
                publisher = WebRTCPublisher(
                    camera_id=camera_id,
                    host=comm.webrtc_host,
                    stun_servers=comm.webrtc_stun_servers,
                    turn_servers=comm.webrtc_turn_servers,
                    max_bitrate_kbps=comm.webrtc_max_bitrate_kbps,
                    max_fps=comm.webrtc_max_fps
                )

                if publisher.initialize():
                    self.publishers[camera_id] = publisher
                    logger.info(f"创建WebRTC发布器: {camera_id}")
                else:
                    logger.error(f"WebRTC发布器初始化失败: {camera_id}")
                    return None

            except Exception as e:
                logger.error(f"创建WebRTC发布器失败: {e}")
                return None

        return self.publishers.get(camera_id) 

    async def start(self):
        try:
            runner = web.AppRunner(self.app)
            await runner.setup()
            if self.ssl_context:
                site = web.TCPSite(runner, self.host, self.port, ssl_context=self.ssl_context)
            else:
                site = web.TCPSite(runner, self.host, self.port)
            await site.start()
            logger.info(f"WebRTC信令服务器启动在 {'https' if self.ssl_context else 'http'}://{self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"启动信令服务器失败: {e}")
            return False
    
    async def stop(self):
        """停止信令服务器"""
        for publisher in self.publishers.values():
            publisher.stop()
        self.publishers.clear()
        logger.info("WebRTC信令服务器已停止")

_signaling_server: Optional[WebRTCSignalingServer] = None

async def start_webrtc_signaling_server(host: str = "0.0.0.0", port: int = 8998):
    """启动全局WebRTC信令服务器"""
    global _signaling_server
    if _signaling_server is None:
        _signaling_server = WebRTCSignalingServer(host, port)
        return await _signaling_server.start()
    return True

async def stop_webrtc_signaling_server():
    """停止全局WebRTC信令服务器"""
    global _signaling_server
    if _signaling_server:
        await _signaling_server.stop()
        _signaling_server = None

def get_webrtc_signaling_server() -> Optional[WebRTCSignalingServer]:
    """获取全局信令服务器实例"""
    return _signaling_server