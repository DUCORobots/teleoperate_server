#!/usr/bin/env python3
"""
相机管理器：与图像服务端通过 ZMQ 通信，负责发现与配置相机。
"""

import zmq
import threading
from typing import Dict, Any
from teleop.log_manager import get_logger

_logger = get_logger(__name__)

class CameraManager:
    """图像服务端 ZMQ 客户端"""

    def __init__(self, server_ip: str = "localhost", server_port: int = 60000):
        self.server_ip = server_ip
        self.server_port = server_port
        self._context = zmq.Context()
        self._lock = threading.Lock()
        self._socket = self._create_socket()

    def _create_socket(self):
        socket = self._context.socket(zmq.REQ)
        socket.connect(f"tcp://{self.server_ip}:{self.server_port}")
        socket.setsockopt(zmq.RCVTIMEO, 8000)
        socket.setsockopt(zmq.SNDTIMEO, 8000)
        socket.setsockopt(zmq.LINGER, 0)
        return socket

    def _reset_socket(self):
        """REQ/REP 流程异常后重建 socket"""
        try:
            self._socket.close()
        except Exception:
            pass
        self._socket = self._create_socket()

    def _send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """发送 ZMQ 请求并返回响应"""
        request_type = request.get("type", "unknown")
        with self._lock:
            try:
                self._socket.send_json(request)
                response = self._socket.recv_json()
                return response
            except zmq.Again:
                _logger.warning(f"ZMQ 请求超时: type={request_type}")
                self._reset_socket()
                return {"error": "请求超时"}
            except Exception as e:
                _logger.warning(f"ZMQ 通信异常: type={request_type}, error={e}")
                self._reset_socket()
                return {"error": str(e)}

    def discover_cameras(self) -> Dict[str, Any]:
        """请求服务端重新发现并返回可用设备列表。"""
        request = {"type": "discover"}
        return self._send_request(request)

    def get_active_cameras(self) -> Dict[str, Any]:
        """获取当前已启动的相机配置。"""
        request = {"type": "get_config"}
        return self._send_request(request)

    def add_camera(self, camera_id: str, camera_config: Dict[str, Any]) -> Dict[str, Any]:
        """添加/启动一个相机。"""
        request = {
            "type": "update",
            "action": "add",
            "camera_id": camera_id,
            "camera_config": camera_config
        }
        return self._send_request(request)

    def remove_camera(self, camera_id: str) -> Dict[str, Any]:
        """移除/停止一个相机。"""
        request = {
            "type": "update",
            "action": "remove",
            "camera_id": camera_id
        }
        return self._send_request(request)

    def update_camera(self, camera_id: str, camera_config: Dict[str, Any]) -> Dict[str, Any]:
        """更新相机配置。"""
        request = {
            "type": "update",
            "action": "update",
            "camera_id": camera_id,
            "camera_config": camera_config
        }
        return self._send_request(request)

    def close(self):
        """关闭 ZMQ 连接"""
        with self._lock:
            self._socket.close()
            self._context.term()
