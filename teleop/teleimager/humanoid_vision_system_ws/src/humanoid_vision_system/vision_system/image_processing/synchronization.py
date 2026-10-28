#!/usr/bin/env python3
"""同步模块"""
import time
import threading
from typing import Dict, List, Optional, Callable
from loguru import logger

class SynchronizationManager:
    """同步管理器类"""
    
    def __init__(self, sync_tolerance_ms: float = 5.0, enable_adaptive_sync: bool = True):
        self.sync_tolerance_ms = sync_tolerance_ms
        self.enable_adaptive_sync = enable_adaptive_sync
        self.sync_points: Dict[str, float] = {}
        self.sync_callbacks: List[Callable] = []
        self._lock = threading.RLock()

    def reset(self) -> None:
        """重置同步管理器"""
        with self._lock:
            self.sync_points.clear()
            self.sync_callbacks.clear()
            logger.info("同步管理器已重置")

    def register_camera(self, camera_id: str) -> None:
        """注册相机"""
        with self._lock:
            if camera_id not in self.sync_points:
                self.sync_points[camera_id] = 0.0
                logger.info(f"注册相机: {camera_id}")
                
    def unregister_camera(self, camera_id: str) -> None:
        """注销相机"""
        with self._lock:
            if camera_id in self.sync_points:
                del self.sync_points[camera_id]
                logger.info(f"注销相机: {camera_id}")
                
    def update_sync_point(self, camera_id: str, timestamp: float) -> bool:
        """更新同步时间点"""
        with self._lock:
            if camera_id not in self.sync_points:
                self.register_camera(camera_id)
                
            self.sync_points[camera_id] = timestamp
            return self._check_synchronization()
            
    def _check_synchronization(self) -> bool:
        """检查同步状态"""
        if len(self.sync_points) < 2:
            return True
            
        timestamps = list(self.sync_points.values())
        max_ts = max(timestamps)
        min_ts = min(timestamps)
        max_diff_ms = (max_ts - min_ts) * 1000.0
        
        synchronized = max_diff_ms <= self.sync_tolerance_ms
        
        if synchronized:
            self._notify_sync_callbacks()
            
        return synchronized
        
    def add_sync_callback(self, callback: Callable) -> None:
        """添加同步回调"""
        with self._lock:
            self.sync_callbacks.append(callback)
            
    def remove_sync_callback(self, callback: Callable) -> None:
        """移除同步回调"""
        with self._lock:
            if callback in self.sync_callbacks:
                self.sync_callbacks.remove(callback)
                
    def _notify_sync_callbacks(self) -> None:
        """通知同步回调"""
        for callback in self.sync_callbacks:
            try:
                callback(self.sync_points.copy())
            except Exception as e:
                logger.error(f"同步回调执行失败: {e}")
                
    def get_sync_status(self) -> Dict[str, any]:
        """获取同步状态"""
        with self._lock:
            timestamps = list(self.sync_points.values())
            if len(timestamps) < 2:
                return {
                    'synchronized': True,
                    'max_diff_ms': 0.0,
                    'camera_count': len(timestamps)
                }
                
            max_ts = max(timestamps)
            min_ts = min(timestamps)
            max_diff_ms = (max_ts - min_ts) * 1000.0
            
            return {
                'synchronized': max_diff_ms <= self.sync_tolerance_ms,
                'max_diff_ms': max_diff_ms,
                'camera_count': len(timestamps),
                'timestamps': self.sync_points.copy()
            }