import json
import os
import time
import shutil
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime

from .models import DatasetInfo, FrameIndexItem, FrameData, RecordTaskInfo, TaskInfo
from teleop.log_manager import get_logger

logger = get_logger(__name__)

class DatasetManager:
    def __init__(self, data_dir: str = "data", trash_dir: str = "data/.trash", reverse: bool = False):
        if data_dir:
            data_dir = os.path.abspath(data_dir)
        if trash_dir:
            trash_dir = os.path.abspath(trash_dir)
        self.data_dir = Path(data_dir)
        self.trash_dir = Path(trash_dir)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.reverse = reverse  # 是否倒序排列，默认升序
        self._cache_ttl = 30  # 缓存有效期 30 秒
        
        # 静态文件服务基础路径
        self.static_base_path = "/static/data"
        
        # 缓存数据集信息
        self._datasets_cache = None
        self._datasets_cache_time = None
        self._tasks_cache = None
        self._tasks_cache_time = None

    @staticmethod
    def _extract_task_number(task_name: str) -> Optional[int]:
        try:
            num_str = task_name.split("_")[1]
            if num_str.isdigit():
                return int(num_str)
        except (IndexError, ValueError):
            return None
        return None

    def scan_tasks(self, force_refresh: bool = True) -> List[TaskInfo]:
        """扫描任务目录，返回任务列表"""
        now = time.time()
        if not force_refresh and self._tasks_cache and (now - self._tasks_cache_time) < self._cache_ttl:
            return self._tasks_cache

        tasks = []
        for task_dir in self.data_dir.glob("task_*"):
            if not task_dir.is_dir():
                continue
            task_info = self._get_task_info(task_dir)
            if task_info:
                tasks.append(task_info)
        
        tasks.sort(key=lambda x: x.create_time, reverse=False)
        
        self._tasks_cache = tasks
        self._tasks_cache_time = now
        return tasks

    def _get_task_info(self, task_dir: Path) -> Optional[TaskInfo]:
        """从任务文件夹读取 task_info.json 并返回 TaskInfo 对象"""
        info_file = task_dir / "task_info.json"
        if not info_file.exists():
            logger.warning(f"任务文件夹缺少 task_info.json: {task_dir}")
            return None
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return TaskInfo(
                task_id=data.get("task_id", task_dir.name),
                task_name=data.get("task_name", task_dir.name),
                description=data.get("description", ""),
                create_time=data.get("create_time", ""),
                last_modified=data.get("last_modified", ""),
                creator=data.get("creator")
            )
        except Exception as e:
            logger.error(f"读取任务信息失败 {task_dir}: {e}")
            return None

    def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """根据 task_id 获取任务详情"""
        task_dir = self.data_dir / task_id
        if not task_dir.exists() or not task_dir.is_dir():
            return None
        return self._get_task_info(task_dir)

    def create_task(self, task_name: str, description: str, creator: Optional[str] = None) -> Optional[TaskInfo]:
        """创建新任务，自动生成 task_id"""
        max_id = 0
        for task_dir in self.data_dir.glob("task_*"):
            if task_dir.is_dir():
                task_num = self._extract_task_number(task_dir.name)
                if task_num is not None:
                    max_id = max(max_id, task_num)
        new_id = max_id + 1
        task_id = f"task_{new_id:04d}"
        task_dir = self.data_dir / task_id
        
        if task_dir.exists():
            max_id = 0
            for d in self.data_dir.glob("task_*"):
                if d.is_dir():
                    task_num = self._extract_task_number(d.name)
                    if task_num is not None:
                        max_id = max(max_id, task_num)
            task_id = f"task_{max_id + 1:04d}"
            task_dir = self.data_dir / task_id
        
        try:
            task_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            logger.error(f"创建任务目录失败，已存在: {task_dir}")
            return None
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task_info_data = {
            "task_id": task_id,
            "task_name": task_name,
            "description": description,
            "create_time": now_str,
            "last_modified": now_str,
            "creator": creator or "unknown"
        }
        info_file = task_dir / "task_info.json"
        try:
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(task_info_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"写入任务信息失败: {e}")
            shutil.rmtree(task_dir, ignore_errors=True)
            return None
        
        self._tasks_cache = None
        self._tasks_cache_time = None
        self._datasets_cache = None
        
        return TaskInfo(**task_info_data)

    def update_task(self, task_id: str, task_name: Optional[str] = None, description: Optional[str] = None) -> bool:
        """更新任务信息，返回是否成功"""
        task_dir = self.data_dir / task_id
        info_file = task_dir / "task_info.json"
        if not info_file.exists():
            return False
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if task_name is not None:
                data["task_name"] = task_name
            if description is not None:
                data["description"] = description
            data["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 清除缓存
            self._tasks_cache = None
            self._tasks_cache_time = None
            return True
        except Exception as e:
            logger.error(f"更新任务信息失败 {task_id}: {e}")
            return False

    def delete_task(self, task_id: str) -> bool:
        """软删除任务（移动到 .trash 并加时间戳），返回是否成功"""
        task_dir = self.data_dir / task_id
        if not task_dir.exists():
            return False
        try:
            timestamp = int(time.time())
            # 目标路径：.trash/task_id_timestamp
            trash_path = self.trash_dir / f"{task_id}_{timestamp}"
            shutil.move(str(task_dir), str(trash_path))
            logger.info(f"任务已移动到回收站: {task_id} -> {trash_path.name}")
            # 清除缓存
            self._tasks_cache = None
            self._tasks_cache_time = None
            self._datasets_cache = None
            return True
        except Exception as e:
            logger.error(f"删除任务失败 {task_id}: {e}")
            return False

    def ensure_default_task(self) -> TaskInfo:
        """
        确保默认任务存在(task_0000)，如果不存在则创建。
        返回默认任务的 TaskInfo
        """
        default_task_id = "task_0000"
        default_dir = self.data_dir / default_task_id
        if default_dir.exists():
            info = self.get_task_info(default_task_id)
            if info:
                return info
        # 创建默认任务
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task_info_data = {
            "task_id": default_task_id,
            "task_name": "默认任务",
            "description": "系统默认任务，可编辑或删除",
            "create_time": now_str,
            "last_modified": now_str,
            "creator": "system"
        }
        default_dir.mkdir(parents=True, exist_ok=True)
        info_file = default_dir / "task_info.json"
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(task_info_data, f, ensure_ascii=False, indent=2)
        logger.info(f"默认任务已创建: {default_task_id}")
        self._tasks_cache = None
        return TaskInfo(**task_info_data)

    def scan_datasets(self, task_id: Optional[str] = None, force_refresh: bool = True) -> List[DatasetInfo]:
        """
        扫描数据集，如果指定 task_id 则只扫描该任务下的数据集，
        否则扫描所有任务下的数据集。
        """
        now = time.time()
        if not force_refresh and self._datasets_cache and (now - self._datasets_cache_time) < self._cache_ttl:
            # 如果有缓存，且未指定 task_id，返回全部；否则需要过滤
            if task_id is None:
                return self._datasets_cache
            else:
                return [d for d in self._datasets_cache if d.task_id == task_id]

        datasets = []
        # 确定要扫描的任务目录列表
        if task_id:
            task_dirs = [self.data_dir / task_id] if (self.data_dir / task_id).exists() else []
        else:
            task_dirs = [d for d in self.data_dir.glob("task_*") if d.is_dir()]
        
        for task_dir in task_dirs:
            task_id_name = task_dir.name
            for episode_dir in task_dir.glob("episode_*"):
                if not episode_dir.is_dir():
                    continue
                dataset_info = self._get_dataset_info(episode_dir, task_id_name)
                if dataset_info:
                    datasets.append(dataset_info)
        
        # 按创建时间升序排序
        datasets.sort(key=lambda x: x.created_time, reverse=self.reverse)
        
        if task_id is None:
            self._datasets_cache = datasets
            self._datasets_cache_time = now
        return datasets

    def _get_dataset_info(self, episode_dir: Path, task_id: str) -> Optional[DatasetInfo]:
        """获取单个数据集的详细信息"""
        try:
            episode_id = episode_dir.name
            
            # 检查索引文件是否存在
            index_file = episode_dir / "frames_index.json"
            if index_file.exists():
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                # 从索引文件获取总帧数
                total_frames = index_data.get("total_frames", 0)
            else:
                # 如果没有索引文件，尝试从data.json获取,会加载整个data.json文件
                data_file = episode_dir / "data.json"
                if data_file.exists():
                    with open(data_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    total_frames = len(data.get("data", []))
                else:
                    total_frames = 0
            
            created_time = datetime.fromtimestamp(episode_dir.stat().st_mtime)
            size = self._get_directory_size(episode_dir)
            task_info_obj = self._get_task_info_for_episode(episode_dir, task_id)
            duration = self._calculate_duration(episode_dir)
            
            return DatasetInfo(
                episode_id=episode_id,
                task_id=task_id,
                name=episode_id,
                created_time=created_time,
                total_frames=total_frames,
                duration=duration,
                task_info=task_info_obj,
                size=size
            )
        except Exception as e:
            logger.error(f"获取数据集信息失败 {episode_dir}: {e}")
            return None

    def _get_task_info_for_episode(self, episode_dir: Path, task_id: str) -> Optional[RecordTaskInfo]:
        """从 data.json 中读取任务信息"""
        try:
            data_file = episode_dir / "data.json"
            if data_file.exists():
                with open(data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                text_info = data.get("text", {})
                return RecordTaskInfo(
                    goal=text_info.get("goal", ""),
                    desc=text_info.get("desc", ""),
                    steps=text_info.get("steps", "")
                )
        except Exception as e:
            logger.error(f"获取数据集任务信息失败 {episode_dir}: {e}")
        return None

    def _calculate_duration(self, episode_dir: Path) -> float:
        """计算数据集持续时间"""
        try:
            index_file = episode_dir / "frames_index.json"
            if index_file.exists():
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                frames = index_data.get("frames", [])
                if frames:
                    first_frame = frames[0]
                    last_frame = frames[-1]
                    return last_frame.get("timestamp", 0) - first_frame.get("timestamp", 0)
        except Exception:
            pass
        return 0.0

    def _get_directory_size(self, directory: Path) -> int:
        """计算目录大小"""
        total_size = 0
        for file_path in directory.rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        return total_size

    def get_dataset_frames(self, task_id: str, episode_id: str, page: int = 1, page_size: int = 50,
                          start_time: Optional[float] = None, end_time: Optional[float] = None) -> Tuple[List[FrameData], int]:
        """分页获取指定任务下某个数据集的帧数据"""
        episode_dir = self.data_dir / task_id / episode_id
        if not episode_dir.exists():
            raise FileNotFoundError(f"数据集不存在: {task_id}/{episode_id}")

        # 读取索引文件
        index_file = episode_dir / "frames_index.json"
        if not index_file.exists():
            raise FileNotFoundError(f"索引文件不存在: {index_file}")

        with open(index_file, 'r', encoding='utf-8') as f:
            index_data = json.load(f)

        total_frames = index_data.get("total_frames", 0)
        frames_index = index_data.get("frames", [])
        
        # 时间过滤
        if start_time or end_time:
            filtered_frames = []
            for i, frame_index in enumerate(frames_index):
                timestamp = frame_index.get("timestamp", 0)
                if start_time and timestamp < start_time:
                    continue
                if end_time and timestamp > end_time:
                    continue
                filtered_frames.append((i, frame_index))
        else:
            filtered_frames = [(i, frame_index) for i, frame_index in enumerate(frames_index)]
        
        # 分页计算
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_frames = filtered_frames[start_idx:end_idx]

        # 读取帧数据
        frames_data = []
        data_file = episode_dir / "data.json"
        with open(data_file, 'rb') as f:
            for frame_idx, frame_index in page_frames:
                f.seek(frame_index["offset"])
                frame_raw = f.read(frame_index["length"])
                frame_data = json.loads(frame_raw.decode("utf-8"))
                
                frame_data_obj = FrameData(
                    frame_id=frame_data.get("frame_id", frame_idx),
                    timestamp=frame_data.get("timestamp", 0),
                    states=frame_data.get("states", {}),
                    actions=frame_data.get("actions", {}),
                    images=frame_data.get("images", {}),
                    depths=frame_data.get("depths", {}),
                    audios=frame_data.get("audios"),
                    tactiles=frame_data.get("tactiles"),
                    sim_state=frame_data.get("sim_state")
                )
                frames_data.append(frame_data_obj)
        
        return frames_data, len(filtered_frames)

    def soft_delete_dataset(self, task_id: str, episode_id: str) -> bool:
        """软删除单个数据集（移动到回收站，保留任务结构）"""
        episode_dir = self.data_dir / task_id / episode_id
        if not episode_dir.exists():
            return False
        try:
            # 移动到回收站，添加时间戳避免重名
            timestamp = int(time.time())
            # 回收站内保持任务层级：.trash/task_id/episode_id_timestamp
            trash_task_dir = self.trash_dir / task_id
            trash_task_dir.mkdir(parents=True, exist_ok=True)
            trash_path = trash_task_dir / f"{episode_id}_{timestamp}"
            shutil.move(str(episode_dir), str(trash_path))
            logger.info(f"数据集已移动到回收站: {task_id}/{episode_id} -> {trash_path}")
            # 清除缓存
            self._datasets_cache = None
            return True
        except Exception as e:
            logger.error(f"删除数据集失败 {task_id}/{episode_id}: {e}")
            return False

    def rebuild_index(self, task_id: str, episode_id: str) -> Dict[str, Any]:
        """重建指定数据集的索引文件"""
        episode_dir = self.data_dir / task_id / episode_id
        if not episode_dir.exists():
            raise FileNotFoundError(f"数据集不存在: {task_id}/{episode_id}")
        
        start_time = time.time()
        try:
            data_file = episode_dir / "data.json"
            if not data_file.exists():
                raise FileNotFoundError(f"数据文件不存在: {data_file}")
            
            with open(data_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            data = json.loads(content)
            frames_data = data.get("data", [])
            
            frames_index = []
            marker = '"data": ['
            data_start = content.find(marker)
            if data_start == -1:
                raise ValueError("无效的data.json格式: 未找到data数组")
            current_offset = len(content[: data_start + len(marker)].encode("utf-8"))
            
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
            
            # 创建索引文件
            index_data = {
                "total_frames": len(frames_index),
                "frames": frames_index,
                "created_time": time.time(),
                "version": "1.0"
            }
            index_file = episode_dir / "frames_index.json"
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
            
            elapsed_time = time.time() - start_time
            self._datasets_cache = None
            return {
                "success": True,
                "message": f"索引重建成功，共处理 {len(frames_index)} 帧",
                "total_frames": len(frames_index),
                "elapsed_time": elapsed_time
            }
        except Exception as e:
            elapsed_time = time.time() - start_time
            return {
                "success": False,
                "message": f"索引重建失败: {str(e)}",
                "total_frames": 0,
                "elapsed_time": elapsed_time
            }