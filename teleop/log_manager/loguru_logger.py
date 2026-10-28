"""
基于 loguru 的统一日志封装
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

from loguru import logger as _loguru_logger


# 模块路由表：根据 module 前缀决定日志去哪个文件,先匹配更具体的前缀
_ROUTE_RULES = (
    ("robot_control", "robot.log"),
    ("televuer", "robot.log"),
    ("utils.episode_writer", "recording.log"),
    ("utils.dataset_io", "recording.log"),
    ("utils.camera_manager", "system.log"),
    ("api", "system.log"),
    ("teleimager", "image_client.log"),
    ("config_loader", "system.log"),
    ("teleop_hand_and_arm", "system.log"),
)

_DEFAULT_ROUTE_FILE = "system.log"


def _resolve_route_file(module_name: str) -> str:
    """根据模块名返回应写入的日志文件名"""
    for prefix, filename in _ROUTE_RULES:
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            return filename
    return _DEFAULT_ROUTE_FILE


# 全局状态：handler id 缓存, 避免重复绑定
_handler_ids: Dict[str, int] = {}
_initialized: bool = False
_console_handler_id: Optional[int] = None


def get_logger(name: str):
    """
    获取绑定 module 标签的 logger 对象
    通过 `module` 字段路由到不同日志文件，调用方无需感知
    """
    return _loguru_logger.bind(module=name)


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """
    初始化日志系统
    """
    global _initialized, _console_handler_id

    if _initialized:
        return

    cfg = config or {}

    # 解析日志目录(默认 logs/)
    log_dir = cfg.get("log_dir", "logs")
    project_root = _resolve_project_root()
    log_dir_abs = log_dir if os.path.isabs(log_dir) else os.path.join(project_root, log_dir)
    os.makedirs(log_dir_abs, exist_ok=True)

    level = str(cfg.get("level", "INFO")).upper()
    rotation_size_mb = int(cfg.get("rotation_size_mb", 120))
    retention_days = int(cfg.get("retention_days", 60))
    compression_enabled = bool(cfg.get("compression_enabled", True))
    encoding = cfg.get("encoding", "utf-8")

    rotation = f"{rotation_size_mb} MB"
    retention = f"{retention_days} days"
    compression = "zip" if compression_enabled else None
    fmt = cfg.get(
        "format",
        "{time:YYYY-MM-DD HH:mm:ss} | {level: ^8} | {name}:{function}:{line} - {message}",
    )

    _loguru_logger.remove()

    # 控制台专用格式
    console_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: ^8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # 控制台 handler
    if cfg.get("console", True):
        _console_handler_id = _loguru_logger.add(
            sys.stderr,
            level=level,
            format=console_fmt,
            colorize=True,
            enqueue=False,
            backtrace=True,
            diagnose=True,
        )

    # 为每个路由目标创建文件 handler
    target_files = sorted({fname for _, fname in _ROUTE_RULES} | {_DEFAULT_ROUTE_FILE})
    for fname in target_files:
        file_path = os.path.join(log_dir_abs, fname)
        handler_id = _loguru_logger.add(
            file_path,
            level=level,
            format=fmt,
            rotation=rotation,
            retention=retention,
            compression=compression,
            encoding=encoding,
            enqueue=False,
            backtrace=True,
            diagnose=True,
            filter=lambda record, _fname=fname: _route_filter(record, _fname),
        )
        _handler_ids[fname] = handler_id

    # 独立的 errors.log
    error_path = os.path.join(log_dir_abs, "errors.log")
    _loguru_logger.add(
        error_path,
        level="ERROR",
        format=fmt,
        rotation=rotation,
        retention=retention,
        compression=compression,
        encoding=encoding,
        enqueue=False,
        backtrace=True,
        diagnose=True,  # ERROR 时可以暴露更多上下文
    )

    _initialized = True
    _loguru_logger.bind(module="teleop.log_manager").info(
        f"日志系统初始化完成 | log_dir={log_dir_abs} | level={level}"
    )


def shutdown_logging() -> None:
    """关闭日志系统,移除所有 handler,仅在进程退出前调用"""
    global _initialized, _console_handler_id

    if not _initialized:
        return

    for handler_id in list(_handler_ids.values()):
        try:
            _loguru_logger.remove(handler_id)
        except Exception:
            pass
    _handler_ids.clear()

    if _console_handler_id is not None:
        try:
            _loguru_logger.remove(_console_handler_id)
        except Exception:
            pass
        _console_handler_id = None

    _initialized = False


def _route_filter(record: Dict[str, Any], target_file: str) -> bool:
    """
    路由过滤：根据 record.extra.module 决定该条日志是否进入 target_file
    """
    module = record.get("extra", {}).get("module", "")
    if not module:
        return target_file == _DEFAULT_ROUTE_FILE

    resolved = _resolve_route_file(module)
    return resolved == target_file


def _resolve_project_root() -> str:
    """
    推断项目根目录
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))