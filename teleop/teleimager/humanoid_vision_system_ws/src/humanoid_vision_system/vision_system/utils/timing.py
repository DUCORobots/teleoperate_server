#!/usr/bin/env python3
"""时序工具模块"""

import time
import threading
from typing import Callable, Optional
import statistics

class HighPrecisionTimer:
    """高精度定时器"""
    
    def __init__(self):
        self._start_time = None
        self._elapsed = 0.0
        
    def start(self):
        """开始计时"""
        self._start_time = time.perf_counter()
        
    def stop(self) -> float:
        """停止计时并返回经过的时间(秒)"""
        if self._start_time is None:
            return 0.0

        self._elapsed = time.perf_counter() - self._start_time
        return self._elapsed
        
    def elapsed_ms(self) -> float:
        """返回经过的时间(毫秒)"""
        return self._elapsed * 1000

class FrameRateController:
    """帧率控制器"""
    
    def __init__(self, target_fps: float):
        self.target_fps = target_fps
        self.target_frame_time = 1.0 / target_fps
        self.last_frame_time = time.perf_counter()
        self.frame_times = []
        self.max_history = 100
        
    def wait_for_next_frame(self) -> float:
        """等待下一帧，返回实际帧间隔"""
        current_time = time.perf_counter()
        elapsed = current_time - self.last_frame_time
        sleep_time = max(0, self.target_frame_time - elapsed)
        
        if sleep_time > 0:
            time.sleep(sleep_time)
            
        current_time_after_sleep = time.perf_counter()
        actual_interval = current_time_after_sleep - self.last_frame_time
        self.last_frame_time = current_time_after_sleep
        
        # 记录帧时间
        self.frame_times.append(actual_interval)
        if len(self.frame_times) > self.max_history:
            self.frame_times.pop(0)
            
        return actual_interval
        
    def get_actual_fps(self) -> float:
        """计算实际帧率"""
        if not self.frame_times:
            return 0.0
        return 1.0 / statistics.mean(self.frame_times)