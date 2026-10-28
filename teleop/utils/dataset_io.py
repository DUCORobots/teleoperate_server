"""
导入导出管理器
负责数据集导入/导出任务管理、压缩解压与临时文件清理。
"""

import os
import json
import time
import shutil
import tarfile
import zipfile
import asyncio
import concurrent.futures
from pathlib import Path
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime
from api.dataset_manager import DatasetManager
from api.models import ExportStatus, ImportStatus, ExportTaskInfo, ImportTaskInfo
from teleop.log_manager import get_logger

_logger = get_logger(__name__)

class DatasetIOManager:
    """导入导出管理器"""
    ACTIVE_EXPORT_STATUSES = (ExportStatus.PENDING, ExportStatus.PACKING)
    ACTIVE_IMPORT_STATUSES = (
        ImportStatus.PENDING,
        ImportStatus.UPLOADING,
        ImportStatus.EXTRACTING,
        ImportStatus.REBUILDING,
        ImportStatus.MOVING,
    )
    CANCELLABLE_IMPORT_STATUSES = (
        ImportStatus.PENDING,
        ImportStatus.UPLOADING,
        ImportStatus.EXTRACTING,
        ImportStatus.REBUILDING,
    )
    
    def __init__(
        self,
        data_dir: str = "data",
        tmp_dir: str = "tmp",
        export_dir: Optional[str] = None,
        import_dir: Optional[str] = None,
        max_concurrent_exports: int = 3,
        max_concurrent_imports: int = 1,
        export_retention_confirmed_minutes: int = 30,
        export_retention_unconfirmed_hours: int = 5,
        disk_space_safety_factor: float = 1.2,
        disk_space_min_free_mb: int = 500,
        _executor: concurrent.futures.ThreadPoolExecutor = None,
        dataset_manager: DatasetManager = None
    ):
        """
        初始化导入导出管理器
        
        Args:
            data_dir: 数据目录
            tmp_dir: 临时目录
            export_dir: 导出文件目录
            import_dir: 导入临时目录
            max_concurrent_exports: 最大并发导出数
            max_concurrent_imports: 最大并发导入数
            export_retention_confirmed_minutes: 确认后保留时间（分钟）
            export_retention_unconfirmed_hours: 未确认保留时间（小时）
            disk_space_safety_factor: 磁盘空间安全因子
            disk_space_min_free_mb: 最小可用磁盘空间(MB)
        """
        self.data_dir = Path(data_dir) if data_dir else Path("data")
        self.tmp_dir = Path(tmp_dir) if tmp_dir else Path("tmp")
        self.export_dir = Path(export_dir) if export_dir else self.tmp_dir / "exports"
        self.import_dir = Path(import_dir) if import_dir else self.tmp_dir / "imports"
        
        self.max_concurrent_exports = max_concurrent_exports
        self.max_concurrent_imports = max_concurrent_imports
        self.export_retention_confirmed_minutes = export_retention_confirmed_minutes
        self.export_retention_unconfirmed_hours = export_retention_unconfirmed_hours
        self.disk_space_safety_factor = disk_space_safety_factor
        self.disk_space_min_free_mb = disk_space_min_free_mb

        self.dataset_manager = dataset_manager
        if _executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        else:
            self._executor = _executor
        
        self.export_tasks: Dict[str, ExportTaskInfo] = {}
        self.import_task: Optional[ImportTaskInfo] = None
        self._ensure_directories()
        self._cleanup_task: Optional[asyncio.Task] = None
        
        _logger.info(f"导入导出管理器初始化完成，导出目录: {self.export_dir}, 导入目录: {self.import_dir}")
    
    def _ensure_directories(self):
        """确保必要的目录存在"""
        directories = [
            self.tmp_dir,
            self.export_dir,
            self.import_dir
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            _logger.debug(f"目录已创建或已存在: {directory}")

    async def initialize(self):
        """
        初始化导入导出管理器
        - 清理启动时的临时文件
        - 启动后台清理任务
        """
        _logger.debug("初始化导入导出管理器...")
        self.cleanup_on_startup()
        await self.start_cleanup_task()
        
        _logger.debug("导入导出管理器初始化完成")

    async def shutdown(self):
        """
        关闭导入导出管理器
        - 取消后台清理任务
        """
        _logger.info("关闭导入导出管理器...")
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                _logger.info("后台清理任务已取消")

        if self._executor is not None:
            self._executor.shutdown(wait=True)
            _logger.info("线程池已关闭")
        
        _logger.info("导入导出管理器已关闭")

    async def create_export_task(self, task_id: str, format: str = "zip") -> ExportTaskInfo:
        """
        创建导出任务
        
        Args:
            task_id: 要导出的任务ID
            
        Returns:
            ExportTaskInfo: 导出任务信息
            
        Raises:
            ValueError: 如果任务不存在或并发限制
        """
        if format not in ["zip", "tar.gz"]:
            raise ValueError(f"无效的导出格式: {format},仅支持zip或tar.gz")

        task_dir = self.data_dir / task_id
        if not task_dir.exists() or not task_dir.is_dir():
            raise ValueError(f"任务不存在: {task_id}")
        
        active_exports = self._count_active_exports()
        if active_exports >= self.max_concurrent_exports:
            raise ValueError(
                f"已达到最大并发导出限制 ({self.max_concurrent_exports})，"
                f"当前活跃导出数: {active_exports}"
            )
        
        export_id = f"export_{int(time.time() * 1000)}"
        export_task = ExportTaskInfo(
            export_id=export_id,
            task_id=task_id,
            status=ExportStatus.PENDING,
            created_time=time.time(),
            completed_time=None,
            file_path=None,
            file_size=0,
            episode_count=0,
            error_message=None,
            retry_suggestion=None,
            format=format
        )
        
        self.export_tasks[export_id] = export_task
        
        _logger.info(f"导出任务已创建: {export_id}, 任务ID: {task_id}")
        
        asyncio.create_task(self._pack_export_task(export_id))
        
        return export_task
    
    async def _pack_export_task(self, export_id: str):
        """
        异步打包导出任务
        
        Args:
            export_id: 导出任务ID
        """
        export_task = self.export_tasks.get(export_id)
        if not export_task:
            _logger.error(f"导出任务不存在: {export_id}")
            return
        
        try:
            export_task.status = ExportStatus.PACKING
            task_dir = self.data_dir / export_task.task_id
            task_size = self._get_directory_size(task_dir)
            required_space = int(task_size * self.disk_space_safety_factor)
            if not self._check_disk_space(self.export_dir, required_space):
                raise IOError(
                    f"磁盘空间不足，需要 {required_space / (1024*1024):.2f} MB，"
                    f"可用空间不足"
                )
            
            episode_count = len(list(task_dir.glob("episode_*")))
            export_task.episode_count = episode_count
            if export_task.format == "zip":
                export_filename = f"{export_task.task_id}.zip"
                export_file_path = self.export_dir / export_filename
                _logger.info(f"开始打包导出任务: {export_id}, 目标文件: {export_file_path}, 格式: zip, episode数量: {episode_count}")
                await self._create_zip(task_dir, export_file_path)
            else:
                export_filename = f"{export_task.task_id}.tar.gz"
                export_file_path = self.export_dir / export_filename
                _logger.info(f"开始打包导出任务: {export_id}, 目标文件: {export_file_path}, 格式: tar.gz, episode数量: {episode_count}")
                await self._create_tar_gz(task_dir, export_file_path)
            
            # 如果打包过程中任务被取消，优先保留取消状态。
            if export_task.status == ExportStatus.CANCELLED:
                export_file_path.unlink(missing_ok=True)
                _logger.info(f"导出任务已取消并清理文件: {export_id}")
                return
            export_task.file_path = str(export_file_path)
            export_task.file_size = export_file_path.stat().st_size
            export_task.status = ExportStatus.READY
            export_task.completed_time = time.time()
            
            _logger.info(
                f"导出任务打包完成: {export_id}, "
                f"文件大小: {export_task.file_size / (1024*1024):.2f} MB, "
                f"episode数量: {episode_count}, "
                f"格式: {export_task.format}"
            )
            
        except Exception as e:
            _logger.error(f"导出任务打包失败: {export_id}, 错误: {e}")
            export_task.status = ExportStatus.FAILED
            export_task.error_message = str(e)
            export_task.retry_suggestion = self._get_export_retry_suggestion(e)
            export_task.completed_time = time.time()

    async def _create_tar_gz(self, source_dir: Path, output_file: Path):
        """
        创建tar.gz压缩文件
        
        Args:
            source_dir: 源目录
            output_file: 输出文件路径
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._create_tar_gz_sync, source_dir, output_file)

    def _create_tar_gz_sync(self, source_dir: Path, output_file: Path):
        """
        同步创建tar.gz压缩文件
        
        Args:
            source_dir: 源目录
            output_file: 输出文件路径
        """
        with tarfile.open(output_file, "w:gz") as tar:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname=item.relative_to(source_dir.parent)
                    tar.add(item, arcname=arcname)

    async def _create_zip(self, source_dir: Path, output_file: Path):
        """
        创建zip压缩文件
        
        Args:
            source_dir: 源目录
            output_file: 输出文件路径
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._create_zip_sync, source_dir, output_file)
    
    def _create_zip_sync(self, source_dir: Path, output_file: Path):
        """
        同步创建zip压缩文件
        
        Args:
            source_dir: 源目录
            output_file: 输出文件路径
        """
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname=item.relative_to(source_dir.parent)
                    zipf.write(item, arcname)

    def get_export_task(self, export_id: str) -> Optional[ExportTaskInfo]:
        """
        获取导出任务信息
        
        Args:
            export_id: 导出任务ID
            
        Returns:
            ExportTaskInfo: 导出任务信息，不存在返回None
        """
        return self.export_tasks.get(export_id)

    def list_export_tasks(self) -> List[ExportTaskInfo]:
        """
        获取所有导出任务的任务列表
        
        Returns:
            List[ExportTaskInfo]: 导出任务列表
        """
        return list(self.export_tasks.values())

    def increment_download_count(self, export_id: str) -> bool:
        """
        增加导出文件下载计数
        
        Args:
            export_id: 导出任务ID
            
        Returns:
            bool: 是否成功
        """
        export_task = self.export_tasks.get(export_id)
        if not export_task:
            return False
        
        export_task.download_count += 1
        _logger.debug(f"导出文件下载计数增加: {export_id}, 当前次数: {export_task.download_count}")
        return True

    def confirm_export_download(self, export_id: str) -> bool:
        """
        确认导出文件下载完成
        
        Args:
            export_id: 导出任务ID
            
        Returns:
            bool: 是否成功
        """
        export_task = self.export_tasks.get(export_id)
        if not export_task:
            return False
        
        if export_task.status != ExportStatus.READY:
            return False
        
        export_task.confirmed = True
        export_task.confirmed_time = time.time()
        export_task.status = ExportStatus.CONFIRMED
        
        _logger.info(f"导出文件下载已确认: {export_id}, 下载次数: {export_task.download_count}")
        return True
    
    def cancel_export_task(self, export_id: str) -> bool:
        """
        取消导出任务
        
        Args:
            export_id: 导出任务ID
            
        Returns:
            bool: 是否成功
        """
        export_task = self.export_tasks.get(export_id)
        if not export_task:
            return False
        
        if export_task.status not in [ExportStatus.PENDING, ExportStatus.PACKING]:
            return False
        
        export_task.status = ExportStatus.CANCELLED
        export_task.completed_time = time.time()
        
        if export_task.file_path and os.path.exists(export_task.file_path):
            try:
                os.remove(export_task.file_path)
                _logger.info(f"已删除导出文件: {export_task.file_path}")
            except Exception as e:
                _logger.error(f"删除导出文件失败: {e}")
        
        _logger.info(f"导出任务已取消: {export_id}")
        return True
    
    def _count_active_exports(self) -> int:
        """
        统计活跃的导出任务数
        
        Returns:
            int: 活跃导出任务数
        """
        return sum(
            1 for task in self.export_tasks.values()
            if task.status in self.ACTIVE_EXPORT_STATUSES
        )
    
    def _get_export_retry_suggestion(self, error: Exception) -> str:
        """
        根据错误类型生成重试建议
        
        Args:
            error: 错误对象
            
        Returns:
            str: 重试建议
        """
        error_msg = str(error).lower()
        
        if "disk" in error_msg or "space" in error_msg:
            return "磁盘空间不足，请清理磁盘空间后重试"
        elif "permission" in error_msg:
            return "权限不足，请检查文件系统权限"
        elif "not found" in error_msg:
            return "任务不存在，请检查任务ID"
        else:
            return "未知错误，请稍后重试或联系管理员"


    async def create_import_task(self, file_name: str, file_size: int, temp_file_path: str,
                                 task_name: str = None, description: str = None, creator: str = None) -> ImportTaskInfo:
        """
        创建导入任务
        
        Args:
            file_name: 导入文件名
            file_size: 文件大小（字节）
            temp_file_path: 临时文件路径
            task_name: 导入后的任务名称
            description: 导入后的任务描述
            creator: 导入后的创建者
            
        Returns:
            ImportTaskInfo: 导入任务信息
            
        Raises:
            ValueError: 如果文件格式不支持或并发限制
        """
        if not (file_name.endswith('.tar.gz') or file_name.endswith('.zip')):
            raise ValueError(f"不支持的文件格式: {file_name}")
        
        if self.import_task is not None and self.import_task.status in self.ACTIVE_IMPORT_STATUSES:
            raise ValueError(
                f"已有导入任务正在进行中，"
                f"当前任务: {self.import_task.import_id}, "
                f"状态: {self.import_task.status.value}"
            )
        
        if self.import_task is not None and self.import_task.status in [
            ImportStatus.COMPLETED,
            ImportStatus.CANCELLED,
            ImportStatus.FAILED
        ]:
            old_temp_dir = Path(self.import_task.temp_dir)
            if old_temp_dir.exists():
                try:
                    shutil.rmtree(old_temp_dir, ignore_errors=True)
                    _logger.info(f"已清理旧导入任务的临时目录: {old_temp_dir}")
                except Exception as e:
                    _logger.error(f"清理旧导入任务的临时目录失败: {e}")
        
        import_id = f"import_{int(time.time() * 1000)}"
        temp_dir = self.import_dir / import_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        import_task = ImportTaskInfo(
            import_id=import_id,
            status=ImportStatus.PENDING,
            created_time=time.time(),
            completed_time=None,
            file_name=file_name,
            file_size=file_size,
            temp_dir=str(temp_dir),
            target_task_id=None,
            episode_count=0,
            rebuild_progress=0.0,
            error_message=None,
            retry_suggestion=None,
            task_name=task_name,
            description=description,
            creator=creator
        )
        
        self.import_task = import_task
        
        _logger.info(f"导入任务已创建: {import_id}, 文件: {file_name}, 大小: {file_size} bytes")
        
        asyncio.create_task(self._process_import_task(import_id, temp_file_path))
        
        return import_task

    async def _process_import_task(self, import_id: str, temp_file_path: str):
        """
        异步处理导入任务
        
        Args:
            import_id: 导入任务ID
            temp_file_path: 临时文件路径
        """
        import_task = self.import_task
        if not import_task or import_task.import_id != import_id:
            _logger.error(f"导入任务不存在: {import_id}")
            return
        
        try:
            import_task.status = ImportStatus.EXTRACTING
            await self._extract_import_file(import_task, temp_file_path)
            if import_task.status == ImportStatus.CANCELLED:
                _logger.info(f"导入任务已取消: {import_id}")
                return

            temp_dir = Path(import_task.temp_dir)
            episodes = list(temp_dir.glob("**/episode_*"))
            import_task.episode_count = len(episodes)

            import_task.status = ImportStatus.REBUILDING
            await self._rebuild_import_indexes(import_task, episodes)
            if import_task.status == ImportStatus.CANCELLED:
                _logger.info(f"导入任务已取消: {import_id}")
                return

            import_task.status = ImportStatus.MOVING
            target_task_id = await self._move_import_data(import_task, temp_dir)
            import_task.target_task_id = target_task_id
            import_task.status = ImportStatus.COMPLETED
            import_task.completed_time = time.time()
            
            _logger.info(
                f"导入任务完成: {import_id}, "
                f"目标任务: {target_task_id}, "
                f"episode数量: {import_task.episode_count}"
            )
            
        except Exception as e:
            _logger.exception(f"导入任务失败: {import_id}, 错误: {e}")
            import_task.status = ImportStatus.FAILED
            import_task.error_message = str(e)
            import_task.retry_suggestion = self._get_import_retry_suggestion(e)
            import_task.completed_time = time.time()
        finally:
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception as e:
                _logger.error(f"清理临时文件失败: {e}")

            try:
                if import_task and import_task.temp_dir and os.path.exists(import_task.temp_dir):
                    shutil.rmtree(import_task.temp_dir, ignore_errors=True)
                    _logger.info(f"已清理解压目录: {import_task.temp_dir}")
            except Exception as e:
                _logger.error(f"清理解压目录失败: {e}")
    
    async def _extract_import_file(self, import_task: ImportTaskInfo, temp_file_path: str):
        """
        解压导入文件到临时目录
        
        Args:
            import_task: 导入任务信息
            temp_file_path: 临时文件路径
        """
        temp_dir = Path(import_task.temp_dir)
        
        try:
            if temp_file_path.endswith('.tar.gz'):
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._extract_tar_gz,
                    temp_file_path,
                    temp_dir
                )
            elif temp_file_path.endswith('.zip'):
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._extract_zip,
                    temp_file_path,
                    temp_dir
                )
            else:
                raise ValueError(f"不支持的文件格式: {temp_file_path}")
            
            _logger.info(f"文件解压完成: {temp_file_path} -> {temp_dir}")
        except Exception as e:
            _logger.error(f"文件解压失败: {e}")
            raise

    def _extract_tar_gz(self, tar_gz_path: str, extract_dir: Path):
        """
        解压tar.gz文件
        
        Args:
            tar_gz_path: tar.gz文件路径
            extract_dir: 解压目标目录
        """
        with tarfile.open(tar_gz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not self._is_safe_extract_member(extract_dir, member.name):
                    raise ValueError(f"不安全的文件路径: {member.name}")
            tar.extractall(extract_dir)
    
    def _extract_zip(self, zip_path: str, extract_dir: Path):
        """
        解压zip文件
        
        Args:
            zip_path: zip文件路径
            extract_dir: 解压目标目录
        """
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                if not self._is_safe_extract_member(extract_dir, member):
                    raise ValueError(f"不安全的文件路径: {member}")
            zip_ref.extractall(extract_dir)

    @staticmethod
    def _is_safe_extract_member(base_dir: Path, member_name: str) -> bool:
        """
        校验压缩包成员路径是否安全，防止路径穿越。
        """
        member_path = Path(member_name)
        if member_path.is_absolute():
            return False
        resolved_base = base_dir.resolve()
        resolved_target = (base_dir / member_path).resolve()
        return resolved_target == resolved_base or resolved_base in resolved_target.parents

    def _allocate_task_id(self) -> str:
        max_id = 0
        for task_dir in self.data_dir.glob("task_*"):
            if not task_dir.is_dir():
                continue
            try:
                num = int(task_dir.name.split("_")[1])
                max_id = max(max_id, num)
            except (IndexError, ValueError):
                continue
        return f"task_{max_id + 1:04d}"

    def _resolve_target_task_dir(self, preferred_task_id: Optional[str] = None) -> Tuple[str, Path]:
        if preferred_task_id:
            preferred_dir = self.data_dir / preferred_task_id
            if not preferred_dir.exists():
                return preferred_task_id, preferred_dir
        task_id = self._allocate_task_id()
        return task_id, self.data_dir / task_id

    @staticmethod
    def _write_import_task_info(task_dir: Path, task_id: str, task_name: str = None,
                         description: str = None, creator: str = None):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task_info_data = {
            "task_id": task_id,
            "task_name": task_name or f"导入任务 {task_id}",
            "description": description or "这是一个默认任务描述",
            "create_time": now_str,
            "last_modified": now_str,
            "creator": creator or "系统用户"
        }
        info_file = task_dir / "task_info.json"
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(task_info_data, f, ensure_ascii=False, indent=2)
    
    async def _rebuild_import_indexes(self, import_task: ImportTaskInfo, episodes: List[Path]):
        """
        重建导入数据的索引文件
        
        Args:
            import_task: 导入任务信息
            episodes: episode目录列表
        """
        total_episodes = len(episodes)
        
        for i, episode_dir in enumerate(episodes):
            if import_task.status == ImportStatus.CANCELLED:
                return
            index_file = episode_dir / "frames_index.json"
            if index_file.exists():
                continue
            try:
                await self._rebuild_single_index(episode_dir)
            except Exception as e:
                _logger.error(f"重建索引失败: {episode_dir}, 错误: {e}")
            import_task.rebuild_progress = (i + 1) / total_episodes
        
        _logger.info(f"索引重建完成: {import_task.import_id}, 总数: {total_episodes}")
    
    async def _rebuild_single_index(self, episode_dir: Path):
        """
        重建单个episode的索引
        
        Args:
            episode_dir: episode目录路径
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._rebuild_single_index_sync, episode_dir)
    
    def _rebuild_single_index_sync(self, episode_dir: Path):
        """
        同步重建单个episode的索引
        
        Args:
            episode_dir: episode目录路径
        """
        data_file = episode_dir / "data.json"
        if not data_file.exists():
            return
        
        with open(data_file, 'r', encoding='utf-8') as f:
            content = f.read()
        data = json.loads(content)
        frames_data = data.get("data", [])

        frames_index = []
        current_offset = 0
        data_marker = '"data": ['
        data_start = content.find(data_marker)
        if data_start == -1:
            raise ValueError("无效的data.json格式:找不到data数组")
        # 这里必须使用字节偏移，避免中文字符导致索引错位。
        current_offset = len(content[: data_start + len(data_marker)].encode("utf-8"))

        for i, frame_data in enumerate(frames_data):
            frame_json = json.dumps(frame_data, ensure_ascii=False, separators=(',', ':'))
            frame_len_bytes = len(frame_json.encode("utf-8"))
            frame_index = {
                "offset": current_offset,
                "length": frame_len_bytes,
                "timestamp": frame_data.get("timestamp", 0)
            }
            frames_index.append(frame_index)
            current_offset += frame_len_bytes
            if i < len(frames_data) - 1:
                current_offset += 1

        index_data = {
            "total_frames": len(frames_index),
            "frames": frames_index,
            "created_time": time.time(),
            "version": "1.0"
        }
        index_file = episode_dir / "frames_index.json"
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
    
    async def _move_import_data(self, import_task: ImportTaskInfo, temp_dir: Path) -> str:
        """
        移动导入数据到目标目录
        
        Args:
            import_task: 导入任务信息
            temp_dir: 临时目录
            
        Returns:
            str: 目标任务ID
        """
        task_dirs = sorted(d for d in temp_dir.glob("task_*") if d.is_dir())
        episode_dirs = sorted(d for d in temp_dir.glob("episode_*") if d.is_dir())

        if task_dirs:
            if len(task_dirs) > 1:
                _logger.warning("检测到多个 task 目录，仅导入第一个: %s", task_dirs[0].name)
            source_task_dir = task_dirs[0]
            task_id, target_task_dir = self._resolve_target_task_dir(source_task_dir.name)
            shutil.move(str(source_task_dir), str(target_task_dir))
            self._write_import_task_info(
                target_task_dir, task_id,
                task_name=import_task.task_name,
                description=import_task.description,
                creator=import_task.creator
            )
            _logger.info(f"导入数据已移动到任务目录: {task_id}")
            return task_id

        if episode_dirs:
            task_id, target_task_dir = self._resolve_target_task_dir()
            target_task_dir.mkdir(parents=True, exist_ok=True)
            self._write_import_task_info(
                target_task_dir, task_id,
                task_name=import_task.task_name,
                description=import_task.description,
                creator=import_task.creator
            )
            for episode_dir in episode_dirs:
                shutil.move(str(episode_dir), str(target_task_dir / episode_dir.name))
            _logger.info(f"导入数据已移动到新任务目录: {task_id}")
            return task_id

        raise ValueError("解压后的目录不包含任何episode或task目录")
    
    def get_import_task(self) -> Optional[ImportTaskInfo]:
        """
        获取当前导入任务信息
        
        Returns:
            ImportTaskInfo: 导入任务信息,不存在返回None
        """
        return self.import_task

    def get_import_tasks(self) -> List[ImportTaskInfo]:
        """
        获取导入任务列表
        
        Returns:
            List[ImportTaskInfo]: 导入任务列表（最多一个）
        """
        if self.import_task:
            return [self.import_task]
        return []

    def get_import_status(self, import_id: str) -> Tuple[str, float]:
        """
        获取导入任务状态和进度
        
        Args:
            import_id: 导入任务ID
            
        Returns:
            Tuple[str, float]: (状态, 进度0.0-1.0)
        """
        if not self.import_task or self.import_task.import_id != import_id:
            return (ImportStatus.FAILED, 0.0)
        
        status = self.import_task.status
        progress = self.import_task.rebuild_progress
        
        return (status, progress)

    def cancel_import(self, import_id: str) -> bool:
        """
        取消导入任务
        
        Args:
            import_id: 导入任务ID
            
        Returns:
            bool: 是否成功
        """
        if not self.import_task or self.import_task.import_id != import_id:
            return False
        
        return self.cancel_import_task()

    def cancel_import_task(self) -> bool:
        """
        取消导入任务
        
        Returns:
            bool: 是否成功
        """
        if not self.import_task:
            return False
        
        if self.import_task.status not in self.CANCELLABLE_IMPORT_STATUSES:
            return False
        
        self.import_task.status = ImportStatus.CANCELLED
        self.import_task.completed_time = time.time()
        
        _logger.info(f"导入任务已取消: {self.import_task.import_id}")
        return True
    
    def _get_import_retry_suggestion(self, error: Exception) -> str:
        """
        根据错误类型生成重试建议
        
        Args:
            error: 错误对象
            
        Returns:
            str: 重试建议
        """
        error_msg = str(error).lower()
        
        if "disk" in error_msg or "space" in error_msg:
            return "磁盘空间不足，请清理磁盘空间后重试"
        elif "permission" in error_msg:
            return "权限不足，请检查文件系统权限"
        elif "format" in error_msg or "invalid" in error_msg:
            return "文件格式不正确，请检查文件是否损坏"
        elif "unsafe" in error_msg:
            return "文件包含不安全的路径，请检查文件来源"
        else:
            return "未知错误，请稍后重试或联系管理员"
    
    def _check_disk_space(self, directory: Path, required_bytes: int) -> bool:
        """
        检查磁盘空间是否足够
        
        Args:
            directory: 目录路径
            required_bytes: 需要的字节数
            
        Returns:
            bool: 是否足够
        """
        try:
            stat = os.statvfs(directory)
            free_bytes = stat.f_bavail * stat.f_frsize
            min_free_bytes = self.disk_space_min_free_mb * 1024 * 1024
            
            return free_bytes >= (required_bytes + min_free_bytes)
        except Exception as e:
            _logger.error(f"检查磁盘空间失败: {e}")
            return False
    
    def _get_directory_size(self, directory: Path) -> int:
        """
        计算目录大小
        
        Args:
            directory: 目录路径
            
        Returns:
            int: 目录大小（字节）
        """
        if self.dataset_manager is not None:
            return self.dataset_manager._get_directory_size(directory)

        total = 0
        for file_path in directory.rglob("*"):
            if file_path.is_file():
                total += file_path.stat().st_size
        return total
    
    async def start_cleanup_task(self):
        """启动后台清理任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            _logger.info("后台清理任务已启动")
    
    async def _cleanup_loop(self):
        """后台清理循环"""
        while True:
            try:
                await self._cleanup_expired_exports()
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                _logger.info("后台清理任务已取消")
                break
            except Exception as e:
                _logger.error(f"后台清理任务出错: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_expired_exports(self):
        """清理过期的导出文件"""
        now = time.time()
        
        confirmed_retention = self.export_retention_confirmed_minutes * 60
        unconfirmed_retention = self.export_retention_unconfirmed_hours * 3600
        
        to_remove = []
        
        for export_id, export_task in self.export_tasks.items():
            if export_task.status not in [ExportStatus.READY, ExportStatus.CONFIRMED]:
                continue
            
            if export_task.confirmed:
                if now - export_task.confirmed_time > confirmed_retention:
                    to_remove.append(export_id)
            else:
                if now - export_task.completed_time > unconfirmed_retention:
                    to_remove.append(export_id)
        
        for export_id in to_remove:
            export_task = self.export_tasks[export_id]
            if export_task.file_path and os.path.exists(export_task.file_path):
                try:
                    os.remove(export_task.file_path)
                    _logger.debug(f"已删除过期导出文件: {export_task.file_path}")
                except Exception as e:
                    _logger.error(f"删除过期导出文件失败: {e}")
            
            del self.export_tasks[export_id]
            _logger.debug(f"已移除过期导出任务: {export_id}")
    
    def cleanup_on_startup(self):
        """启动时清理临时文件"""
        _logger.info("开始清理启动时的临时文件...")
        
        try:
            for ext in ["*.tar.gz", "*.zip"]:
                for file_path in self.export_dir.glob(ext):
                    file_path.unlink()
                    _logger.debug(f"已删除导出文件: {file_path}")
        except Exception as e:
            _logger.error(f"清理导出文件失败: {e}")
        
        try:
            for dir_path in self.import_dir.glob("import_*"):
                shutil.rmtree(dir_path, ignore_errors=True)
                _logger.debug(f"已删除导入临时目录: {dir_path}")
        except Exception as e:
            _logger.error(f"清理导入临时目录失败: {e}")
        
        self.export_tasks.clear()
        self.import_task = None
        
        _logger.info("启动时临时文件清理完成")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取导入导出统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        export_stats = {
            "total": len(self.export_tasks),
            "pending": sum(1 for t in self.export_tasks.values() if t.status == ExportStatus.PENDING),
            "packing": sum(1 for t in self.export_tasks.values() if t.status == ExportStatus.PACKING),
            "ready": sum(1 for t in self.export_tasks.values() if t.status == ExportStatus.READY),
            "downloading": sum(1 for t in self.export_tasks.values() if t.status == ExportStatus.DOWNLOADING),
            "confirmed": sum(1 for t in self.export_tasks.values() if t.status == ExportStatus.CONFIRMED),
            "cancelled": sum(1 for t in self.export_tasks.values() if t.status == ExportStatus.CANCELLED),
            "failed": sum(1 for t in self.export_tasks.values() if t.status == ExportStatus.FAILED),
        }
        
        import_stats = {
            "total": 1 if self.import_task else 0,
            "status": self.import_task.status if self.import_task else None,
            "progress": self.import_task.rebuild_progress if self.import_task else 0.0,
        }
        
        return {
            "exports": export_stats,
            "imports": import_stats,
            "disk_usage": {
                "export_dir_size": self._get_directory_size(self.export_dir),
                "import_dir_size": self._get_directory_size(self.import_dir),
            }
        }

    def get_export_status(self, export_id: str) -> Tuple[str, float]:
        """
        获取导出任务状态和进度
        
        Args:
            export_id: 导出任务ID
            
        Returns:
            Tuple[str, float]: (状态, 进度0.0-1.0)
        """
        export_task = self.export_tasks.get(export_id)
        if not export_task:
            return (ExportStatus.FAILED, 0.0)
        
        status = export_task.status
        progress = 0.0
        
        if status == ExportStatus.PENDING:
            progress = 0.0
        elif status == ExportStatus.PACKING:
            progress = 0.5
        elif status in [ExportStatus.READY, ExportStatus.DOWNLOADING, ExportStatus.CONFIRMED]:
            progress = 1.0
        elif status in [ExportStatus.CANCELLED, ExportStatus.FAILED]:
            progress = 0.0
        
        return (status, progress)
