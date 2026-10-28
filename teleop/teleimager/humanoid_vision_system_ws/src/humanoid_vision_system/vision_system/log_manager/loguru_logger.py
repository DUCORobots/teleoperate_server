#!/usr/bin/env python3
"""Loguru日志记录器"""
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger
import json

class LoguruLogger:
    """Loguru日志记录器类"""
    
    def __init__(self, log_directory: str = "./logs", 
                 log_level: str = "INFO",
                 rotation_size_mb: int = 120,
                 retention_days: int = 60,
                 compression_enabled: bool = True,
                 encoding: str = "utf-8"):
        self.log_directory = Path(log_directory)
        self.log_level = log_level
        self.rotation_size_mb = rotation_size_mb
        self.retention_days = retention_days
        self.compression_enabled = compression_enabled
        self.encoding = encoding
        
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self._configure_default_logger()
        
    def _configure_default_logger(self) -> None:
        """配置默认日志记录器"""
        logger.remove()
        
        logger.add(
            sys.stderr,
            level=self.log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: ^8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True
        )
        
        system_log_path = self.log_directory / "vision_system" / "system.log"
        system_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            str(system_log_path),
            level=self.log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: ^8} | {name}:{function}:{line} - {message}",
            rotation=f"{self.rotation_size_mb} MB",
            retention=f"{self.retention_days} days",
            compression="zip" if self.compression_enabled else None,
            encoding=self.encoding,
            backtrace=True,
            diagnose=True
        )
        
    def setup_camera_logger(self, camera_id: str) -> None:
        """设置相机日志记录器"""
        camera_log_dir = self.log_directory / "cameras" / camera_id
        camera_log_dir.mkdir(parents=True, exist_ok=True)
        
        processing_log_path = camera_log_dir / "processing.log"
        logger.add(
            str(processing_log_path),
            level=self.log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: ^8} | {name}:{function}:{line} - {message}",
            filter=lambda record: record["extra"].get("camera_id") == camera_id and record["extra"].get("log_type") == "processing",
            rotation=f"{self.rotation_size_mb} MB",
            retention=f"{self.retention_days} days",
            compression="zip" if self.compression_enabled else None,
            encoding=self.encoding,
        )
        
        communication_log_path = camera_log_dir / "communication.log"
        logger.add(
            str(communication_log_path),
            level=self.log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: ^8} | {name}:{function}:{line} - {message}",
            filter=lambda record: record["extra"].get("camera_id") == camera_id and record["extra"].get("log_type") == "communication",
            rotation=f"{self.rotation_size_mb} MB",
            retention=f"{self.retention_days} days",
            compression="zip" if self.compression_enabled else None,
            encoding=self.encoding,
        )
        
        error_log_path = camera_log_dir / "errors.log"
        logger.add(
            str(error_log_path),
            level="ERROR",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: ^8} | {name}:{function}:{line} - {message}",
            filter=lambda record: record["extra"].get("camera_id") == camera_id and record["level"].no >= logger.level("ERROR").no,
            rotation=f"{self.rotation_size_mb} MB",
            retention=f"{self.retention_days} days",
            compression="zip" if self.compression_enabled else None,
            encoding=self.encoding,
            backtrace=True,
            diagnose=True
        )
        
    def get_camera_logger(self, camera_id: str, log_type: str = "processing") -> 'logger':
        """获取相机日志记录器"""
        return logger.bind(camera_id=camera_id, log_type=log_type)
        
    def log_system_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """记录系统事件"""
        logger.info(f"系统事件 - {event_type}: {json.dumps(data)}")
        
    def log_camera_event(self, camera_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """记录相机事件"""
        camera_logger = self.get_camera_logger(camera_id, "processing")
        camera_logger.info(f"相机事件 - {event_type}: {json.dumps(data)}")
        
    def log_performance_metrics(self, camera_id: str, metrics: Dict[str, Any]) -> None:
        """记录性能指标"""
        camera_logger = self.get_camera_logger(camera_id, "processing")
        camera_logger.debug(f"性能指标: {json.dumps(metrics)}")
        
    def log_communication_event(self, camera_id: str, channel: str, event_type: str, data: Dict[str, Any]) -> None:
        """记录通信事件"""
        comm_logger = self.get_camera_logger(camera_id, "communication")
        comm_logger.info(f"通信事件 - {channel}.{event_type}: {json.dumps(data)}")