import os
from copy import deepcopy
from typing import Any, Dict

import yaml
import json
from teleop.log_manager import get_logger

_logger = get_logger(__name__)

# 系统兜底配置：配置文件缺失时不影响启动
DEFAULT_CONFIG = {
    "system": {
        # 网络配置：图像服务器IP、端口
        "network": {
            "image_server_ip": "0.0.0.0",
            "image_request_port": 60000,
            "fastapi_host": "0.0.0.0",
            "fastapi_port": 8000
        },
        # 运行时配置：控制频率、是否无头模式、是否默认开启录制/仿真/腰部
        "runtime": {
            "frequency": 60.0,                # 主循环控制频率（Hz）
            "headless": False,                # 是否显示图像窗口
            "sim_enabled_default": False,     # 默认是否使用仿真模式
            "waist_enabled_default": True,    # 默认是否启用腰部控制
            "head_enabled_default": True,     # 默认是否启用头部控制
            "enable_image_server": True,      # 默认是否启用图像服务端
        },
        # XR配置：输入模式（手柄/手追踪）、显示模式
        "xr": {
            "input_mode": "controller",
            "display_mode": "immersive",
        },
        # 文件路径：数据集保存目录
        "paths": {
            "task_dir": "data",
            "trash_dir": "data/.trash",
        },
        # 日志配置：loguru 统一日志系统
        "log_manager": {
            "log_dir": "logs",
            "level": "INFO",
            "console": True,
            "rotation_size_mb": 150,
            "retention_days": 60,
            "compression_enabled": True,
            "encoding": "utf-8",
        },
        # 录制配置
        "recording": {
            "rerun_log": False,
            "save_audio": False,
            "skip_blank_images": True,
            "color_format": "jpg",
            "depth_format": "png",
            # 任务文本信息
            "text": {
                "goal": "RICO 机器人遥操作任务",
                "desc": "",
                "steps": "",
            },
            # 数据集元信息
            "info": {
                "version": "1.0.0",
                "author": "rico",
                "image": {
                    "head_width": 0,
                    "head_height": 0,
                    "fps": 0,
                },
                "depth": {
                    "head_width": 0,
                    "head_height": 0,
                    "fps": 0,
                },
                "audio": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "PCM",
                    "bits": 16,
                },
                "joint_names": {
                    "left_arm": [],
                    "left_ee": [],
                    "right_arm": [],
                    "right_ee": [],
                    "waist": [],
                },
                "tactile_names": {
                    "left_ee": [],
                    "right_ee": [],
                },
                "sim_state": "",
            },
        },
    },
    "robot": {},     # 机器人配置(外部JSON文件填充)
}

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并字典，后者覆盖前者（嵌套配置也支持）"""
    merged = deepcopy(base)
    for key, value in override.items():
        # 如果子项也是字典，递归合并
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        # 普通值直接覆盖
        else:
            merged[key] = value
    return merged

def _load_config_file(path: str) -> Dict[str, Any]:
    """读取单个配置文件,支持YAML和JSON格式,文件不存在则返回空字典"""
    if not os.path.exists(path):
        return {}
    
    # 根据文件扩展名选择解析器
    file_ext = os.path.splitext(path)[1].lower()
    
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            if file_ext == '.json':
                loaded = json.load(file_obj) or {}
            else:
                loaded = yaml.safe_load(file_obj) or {}
        
        if not isinstance(loaded, dict):
            raise ValueError(f"配置文件格式错误，必须是字典: {path}")
        return loaded
    except Exception as e:
        _logger.warning(f"加载配置文件失败 {path}: {e}")
        return {}

def load_all_configs(config_dir: str) -> Dict[str, Dict[str, Any]]:
    """
    加载配置目录下的所有配置文件
    合并顺序：默认配置 → system.yaml/json → robot.yaml/json
    优先使用JSON格式,如果JSON文件不存在则使用YAML文件
    """
    config_dir = os.path.abspath(config_dir)
    config = deepcopy(DEFAULT_CONFIG)
    
    # 定义配置文件优先级
    config_files = {
        'system': ['system.json', 'system.yaml'],
        'robot': ['robot.json', 'robot.yaml']
    }
    
    # 逐层合并配置
    for config_type, file_names in config_files.items():
        loaded_config = {}

        # 按优先级尝试加载配置文件
        for file_name in file_names:
            file_path = os.path.join(config_dir, file_name)
            if os.path.exists(file_path):
                loaded_config = _load_config_file(file_path)
                if loaded_config:
                    _logger.info(f"加载 {file_name} 配置文件成功")
                    break

        # 合并配置
        if loaded_config:
            config[config_type] = _deep_merge(config[config_type], loaded_config)

    _anchor_paths_to_project_root(config, config_dir)

    return config


def _anchor_paths_to_project_root(config: Dict[str, Any], config_dir: str) -> None:
    """
    将 system.paths 下的相对路径解析为基于项目根的绝对路径
    项目根定义为xr_teleoperate_rico/
    """
    project_root = os.path.dirname(os.path.abspath(config_dir))
    paths_cfg = config.get("system", {}).get("paths", {})
    if not isinstance(paths_cfg, dict):
        return

    for key in ("task_dir", "trash_dir"):
        value = paths_cfg.get(key)
        if not value or not isinstance(value, str):
            continue
        if os.path.isabs(value):
            paths_cfg[key] = os.path.normpath(value)
        else:
            paths_cfg[key] = os.path.normpath(os.path.join(project_root, value))
            _logger.info(f"system.paths.{key} 相对路径已锚定到项目根: {paths_cfg[key]}")

def apply_cli_overrides(config: Dict[str, Dict[str, Any]], args) -> Dict[str, Dict[str, Any]]:
    """
    最高优先级：命令行参数覆盖所有配置
    比如命令行输入 --sim,就强制开启仿真模式
    """
    merged = deepcopy(config)
    # 遍历命令行参数，覆盖配置
    if getattr(args, "task_dir", None):
        task_dir = os.path.abspath(args.task_dir)
        merged["system"]["paths"]["task_dir"] = task_dir
        merged["system"]["paths"]["trash_dir"] = os.path.join(task_dir, ".trash")
    if getattr(args, "headless", False):
        merged["system"]["runtime"]["headless"] = True
    if getattr(args, "sim", False):
        merged["system"]["runtime"]["sim_enabled_default"] = True
    if getattr(args, "full_body", None) is not None:
        merged["robot"]["robot"]["upper_body"] = not args.full_body
    if getattr(args, "waist_enabled", None) is not None:
        merged["system"]["runtime"]["waist_enabled_default"] = bool(args.waist_enabled)
    if getattr(args, "head_enabled", None) is not None:
        merged["system"]["runtime"]["head_enabled_default"] = bool(args.head_enabled)
    if getattr(args, "enable_image_server", None) is not None:
        merged["system"]["runtime"]["enable_image_server"] = bool(args.enable_image_server)
    if getattr(args, "image_server_ip", None):
        merged["system"]["network"]["image_server_ip"] = args.image_server_ip
    if getattr(args, "frequency", None) is not None:
        merged["system"]["runtime"]["frequency"] = float(args.frequency)
    return merged
