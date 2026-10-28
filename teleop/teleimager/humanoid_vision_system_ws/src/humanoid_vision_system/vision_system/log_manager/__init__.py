"""
日志系统模块

基于Loguru的日志记录系统,支持按相机ID分类存储和自动轮转。
"""

from .loguru_logger import LoguruLogger

__all__ = [
    'LoguruLogger'
]