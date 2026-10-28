#!/usr/bin/env python3
"""端口管理器"""
import threading
import hashlib
from typing import Dict, Set, Optional, Tuple
from loguru import logger

class PortAllocationError(Exception):
    """端口分配异常"""
    pass

class PortManager:
    """端口管理器类"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(PortManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
            
    def __init__(self):
        if self._initialized:
            return
            
        self._lock = threading.RLock()
        self.allocated_ports: Set[int] = set()
        self.camera_ports: Dict[str, Dict[str, int]] = {}
        
        # 默认端口
        self.zeromq_base_image_port = 5555
        self.zeromq_base_status_port = 5556
        self.zeromq_port_increment = 10
        
        self.websocket_base_port = 8765
        self.websocket_port_increment = 1
        
        # 备选端口范围
        self.fallback_port_range = (20000, 30000)
        
        self._initialized = True
        logger.info("端口管理器初始化完成")
        
    def configure(self, port_config: Dict[str, any]) -> None:
        """配置端口分配参数"""
        with self._lock:
            zeromq_config = port_config.get('zeromq', {})
            websocket_config = port_config.get('websocket', {})
            
            self.zeromq_base_image_port = zeromq_config.get('base_image_port', 5555)
            self.zeromq_base_status_port = zeromq_config.get('base_status_port', 5556)
            self.zeromq_port_increment = zeromq_config.get('port_increment', 10)
            
            self.websocket_base_port = websocket_config.get('base_port', 8765)
            self.websocket_port_increment = websocket_config.get('port_increment', 1)
            
            fallback_range = port_config.get('fallback_range', [20000, 30000])
            self.fallback_port_range = (fallback_range[0], fallback_range[1])

            logger.info(f"端口管理器配置: ZeroMQ基础端口={self.zeromq_base_image_port}-{self.zeromq_base_status_port}, "
                       f"WebSocket基础端口={self.websocket_base_port}, "
                       f"WebSocket端口增量={self.websocket_port_increment},"
                       f"备选端口范围={self.fallback_port_range}")
                       
    def allocate_ports_for_camera(self, camera_id: str, 
                                 external_ports: Optional[Dict[str, int]] = None) -> Dict[str, int]:
        """为相机分配端口"""
        with self._lock:
            if camera_id in self.camera_ports:
                logger.warning(f"相机 {camera_id} 已分配端口，返回现有端口")
                return self.camera_ports[camera_id].copy()

            if external_ports:
                return self._use_external_ports(camera_id, external_ports)

            return self._allocate_auto_ports(camera_id)
            
    def _use_external_ports(self, camera_id: str, external_ports: Dict[str, int]) -> Dict[str, int]:
        """使用外部指定的端口"""
        zmq_ports = external_ports.get('zeromq', {})
        websocket_port = external_ports.get('websocket', {}).get('port')
        
        # 提取端口号
        zmq_image_port = zmq_ports.get('image_publish_port')
        zmq_status_port = zmq_ports.get('status_publish_port')
        
        # 验证端口是否可用
        ports_to_check = []
        if zmq_image_port:
            ports_to_check.append(zmq_image_port)
        if zmq_status_port:
            ports_to_check.append(zmq_status_port)
        if websocket_port:
            ports_to_check.append(websocket_port)
            
        # 检查端口冲突
        conflicting_ports = []
        for port in ports_to_check:
            if port in self.allocated_ports:
                conflicting_ports.append(port)
                
        if conflicting_ports:
            warning_msg = f"端口 {conflicting_ports} 已被占用，无法分配给相机 {camera_id}"
            logger.warning(warning_msg)
            raise PortAllocationError(warning_msg)
        
        # 分配端口
        allocated_ports = {}
        
        if zmq_image_port:
            allocated_ports['zeromq_image'] = zmq_image_port
            self.allocated_ports.add(zmq_image_port)
        else:
            allocated_ports['zeromq_image'] = self._find_available_zeromq_image_port()
            
        if zmq_status_port:
            allocated_ports['zeromq_status'] = zmq_status_port
            self.allocated_ports.add(zmq_status_port)
        else:
            allocated_ports['zeromq_status'] = self._find_available_zeromq_status_port()
            
        if websocket_port:
            allocated_ports['websocket'] = websocket_port
            self.allocated_ports.add(websocket_port)
        else:
            allocated_ports['websocket'] = self._find_available_websocket_port()
            
        self.camera_ports[camera_id] = allocated_ports
        
        logger.info(f"为相机 {camera_id} 分配外部指定端口: {allocated_ports}")
        return allocated_ports
        
    def _allocate_auto_ports(self, camera_id: str) -> Dict[str, int]:
        """自动分配端口"""
        allocated_ports = {
            'zeromq_image': self._find_available_zeromq_image_port(),
            'zeromq_status': self._find_available_zeromq_status_port(),
            'websocket': self._find_available_websocket_port()
        }
        
        # 记录分配的端口
        for port in allocated_ports.values():
            self.allocated_ports.add(port)
            
        self.camera_ports[camera_id] = allocated_ports
        
        logger.info(f"为相机 {camera_id} 自动分配端口: {allocated_ports}")
        return allocated_ports
        
    def _find_available_zeromq_image_port(self) -> int:
        """查找可用的ZeroMQ图像端口"""
        port = self.zeromq_base_image_port
        max_attempts = 100
        
        for _ in range(max_attempts):
            if port not in self.allocated_ports:
                return port
            port += self.zeromq_port_increment
            
        # 如果正常范围找不到，使用备选范围
        return self._find_available_fallback_port()
        
    def _find_available_zeromq_status_port(self) -> int:
        """查找可用的ZeroMQ状态端口"""
        port = self.zeromq_base_status_port
        max_attempts = 100
        
        for _ in range(max_attempts):
            if port not in self.allocated_ports:
                return port
            port += self.zeromq_port_increment
            
        return self._find_available_fallback_port()
        
    def _find_available_websocket_port(self) -> int:
        """查找可用的WebSocket端口"""
        port = self.websocket_base_port
        max_attempts = 100
        
        for _ in range(max_attempts):
            if port not in self.allocated_ports:
                return port
            port += self.websocket_port_increment
            
        return self._find_available_fallback_port()
        
    def _find_available_fallback_port(self) -> int:
        """在备选范围内查找可用端口"""
        start_port, end_port = self.fallback_port_range
        
        for port in range(start_port, end_port):
            if port not in self.allocated_ports:
                return port
                
        # 如果备选范围也找不到，抛出异常
        raise PortAllocationError(f"在范围 {self.fallback_port_range} 内找不到可用端口")
        
    def generate_fallback_ports(self, camera_id: str) -> Dict[str, int]:
        """为相机生成安全的备选端口（基于相机ID哈希）"""
        hash_obj = hashlib.sha256(camera_id.encode())
        hash_int = int(hash_obj.hexdigest()[:8], 16)  # 使用前8位
        
        start_port, end_port = self.fallback_port_range
        port_range_size = end_port - start_port
        
        # 基于哈希值生成基础端口
        base_port = start_port + (hash_int % port_range_size)
        
        # 确保基础端口不会导致后续端口超出范围
        if base_port > end_port - 4:
            base_port = end_port - 4
            
        allocated_ports = {
            'zeromq_image': base_port,
            'zeromq_status': base_port + 1,
            'websocket': base_port + 2
        }
        
        # 检查端口是否已被占用
        retry_count = 0
        max_retries = 10
        
        while retry_count < max_retries:
            conflict_found = False
            for port in allocated_ports.values():
                if port in self.allocated_ports:
                    conflict_found = True
                    break
                    
            if not conflict_found:
                break
                
            offset = (hash_int + retry_count * 100) % 1000 + 10
            base_port = start_port + (offset % port_range_size)
            
            if base_port > end_port - 4:
                base_port = end_port - 4
                
            allocated_ports = {
                'zeromq_image': base_port,
                'zeromq_status': base_port + 1,
                'websocket': base_port + 2,
                'webrtc': base_port + 3
            }
            retry_count += 1
            
        if retry_count == max_retries:
            logger.warning(f"为相机 {camera_id} 生成备选端口时检测到冲突，使用最后尝试的端口: {allocated_ports}")
            
        return allocated_ports
        
    def release_ports(self, camera_id: str) -> None:
        """释放相机占用的端口"""
        with self._lock:
            if camera_id in self.camera_ports:
                ports = self.camera_ports[camera_id]
                for port in ports.values():
                    self.allocated_ports.discard(port)
                del self.camera_ports[camera_id]
                logger.info(f"释放相机 {camera_id} 的端口: {ports}")
            else:
                logger.warning(f"尝试释放不存在的相机端口: {camera_id}")
                
    def get_camera_ports(self, camera_id: str) -> Optional[Dict[str, int]]:
        """获取相机的端口分配"""
        with self._lock:
            return self.camera_ports.get(camera_id, None)
            
    def get_all_allocations(self) -> Dict[str, Dict[str, int]]:
        """获取所有端口分配"""
        with self._lock:
            return self.camera_ports.copy()
            
    def is_port_available(self, port: int) -> bool:
        """检查端口是否可用"""
        with self._lock:
            return port not in self.allocated_ports
            
    def reset(self) -> None:
        """重置端口管理器"""
        with self._lock:
            self.allocated_ports.clear()
            self.camera_ports.clear()
            logger.info("端口管理器已重置")