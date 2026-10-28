"""
遥操服务端统一日志模块

日志文件路径：
    {log_dir}/
        system.log        # 系统层事件(FastAPI、状态机、配置加载等)
        robot.log         # 机器人控制(robot_control、televuer)
        recording.log     # 录制相关(utils.episode_writer、utils.dataset_io)
        image_client.log  # 图像客户端(teleimager)
        errors.log        # 所有error信息
"""

from .loguru_logger import get_logger, setup_logging, shutdown_logging

__all__ = ["get_logger", "setup_logging", "shutdown_logging"]