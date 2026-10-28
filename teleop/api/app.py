from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import time
from pathlib import Path

from .routers import router
from .shared_state import SharedState
from .dataset_manager import DatasetManager
from utils.dataset_io import DatasetIOManager
from teleop.log_manager import get_logger

logger = get_logger(__name__)

def create_app(shared_state: SharedState, host: str = "0.0.0.0", port: int = 8000) -> FastAPI:
    """创建FastAPI应用"""

    app = FastAPI(
        title="XR遥操作API",
        description="人形机器人XR遥操作控制系统API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    data_dir = Path(shared_state.task_dir).resolve()
    trash_dir = Path(shared_state.trash_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    trash_dir.mkdir(parents=True, exist_ok=True)

    app.mount("/static/data", StaticFiles(directory=str(data_dir)), name="data")
    app.mount("/static/trash", StaticFiles(directory=str(trash_dir)), name="trash")

    dataset_manager = DatasetManager(str(data_dir), str(trash_dir))
    try:
        default_task = dataset_manager.ensure_default_task()
        logger.info(f"默认任务已就绪: {default_task.task_id}")
    except Exception as e:
        logger.exception(f"默认任务创建失败: {e}")

    tmp_dir = str(data_dir.parent / "tmp")
    dataset_io_manager = DatasetIOManager(
        data_dir=str(data_dir),
        tmp_dir=tmp_dir,
        export_dir=str(Path(tmp_dir) / "exports"),
        import_dir=str(Path(tmp_dir) / "imports"),
        dataset_manager=dataset_manager
    )

    app.state.shared_state = shared_state
    app.state.dataset_manager = dataset_manager
    app.state.dataset_io_manager = dataset_io_manager

    app.include_router(router)

    @app.on_event("startup")
    async def startup_event():
        logger.info(f"FastAPI服务启动在 {host}:{port}")
        logger.info(f"数据目录: {data_dir}")
        logger.info(f"回收站目录: {trash_dir}")
        logger.info(f"临时目录: {tmp_dir}")
        logger.info("静态文件服务已配置: /static/data/* -> 数据集文件访问")
        try:
            await dataset_io_manager.initialize()
            logger.info("数据集IO管理器初始化成功")
        except Exception as e:
            logger.exception(f"数据集IO管理器初始化失败: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("FastAPI服务关闭")
        try:
            await dataset_io_manager.shutdown()
            logger.info("数据集IO管理器已停止")
        except Exception as e:
            logger.exception(f"数据集IO管理器停止失败: {e}")

    @app.get("/")
    async def root():
        return {
            "message": "XR遥操作API服务运行中",
            "timestamp": time.time(),
            "version": "1.0.0"
        }

    return app

def run_server(shared_state: SharedState, host: str = "0.0.0.0", port: int = 8000):
    """运行FastAPI服务器"""

    app = create_app(shared_state, host, port)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=True
    )

    server = uvicorn.Server(config)

    try:
        server.run()
    except Exception as e:
        logger.exception(f"FastAPI服务器运行失败: {e}")
        raise

if __name__ == "__main__":
    shared_state = SharedState()
    run_server(shared_state)