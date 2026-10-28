"""
XR遥操作FastAPI服务模块
提供HTTP API接口用于远程控制遥操作系统
"""

from .shared_state import SharedState, TeleopCommand, RecordTaskInfo, XRStatus, RecordStatus
from .dataset_manager import DatasetManager
from .routers import router
from .app import create_app, run_server

__all__ = [
    "SharedState",
    "TeleopCommand", 
    "RecordTaskInfo",
    "XRStatus",
    "RecordStatus",
    "DatasetManager",
    "router",
    "create_app",
    "run_server"
]

__version__ = "1.0.0"
