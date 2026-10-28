import datetime
import json
import os
import time
from typing import Dict, Optional
from pathlib import Path
from copy import deepcopy
from queue import Empty, Queue
from threading import Thread

import cv2
import numpy as np

from .rerun_visualizer import RerunLogger

from teleop.log_manager import get_logger
_logger = get_logger(__name__)


class EpisodeWriter:
    """异步录制器：保存 colors/depths/states/actions 到 episode 目录。"""

    def __init__(
        self,
        task_dir,
        frequency=30,
        rerun_log=False,
        save_config=None,
        camera_config=None,
    ):
        self.task_dir = task_dir
        self.frequency = frequency
        self.image_sizes = {}
        if camera_config:
            for cam_id, cam_info in camera_config.items():
                streams = cam_info.get("streams", {})
                color = streams.get("color", {})
                pw = color.get("publish_width")
                ph = color.get("publish_height")
                if pw and ph:
                    self.image_sizes[cam_id] = (pw, ph)

        self.save_config = save_config or {}
        self.camera_config = camera_config or {}

        self.rerun_log = bool(self.save_config.get("rerun_log", rerun_log))
        self.save_audio = bool(self.save_config.get("save_audio", True))
        self.skip_blank_images = bool(self.save_config.get("skip_blank_images", True))
        self.color_format = str(self.save_config.get("color_format", "jpg"))
        self.depth_format = str(self.save_config.get("depth_format", "png"))

        self._build_camera_mapping()
        self.text = self._build_text_config()
        self.info = self._build_info_config()
        if self.rerun_log:
            self.rerun_logger = RerunLogger(prefix="online/", IdxRangeBoundary=60, memory_limit="300MB")

        self.item_id = -1
        self.episode_id = self._discover_episode_id()
        self.episode_start_time = None
        self.last_item_enqueue_time = None
        self.episode_data = []
        self.is_available = True
        self.need_save = False
        self.stop_worker = False
        self.item_data_queue = Queue(-1)
        self.worker_thread = Thread(target=self.process_queue, daemon=True)
        self.worker_thread.start()

    def _build_camera_mapping(self):
        """构建相机存储映射"""
        head_cfg = self.camera_config.get("head_camera", {})
        self.binocular = head_cfg.get("binocular", False)

        self.color_mapping = {}
        self.color_mapping["color_0"] = "head_left"
        if self.binocular:
            self.color_mapping["color_1"] = "head_right"
        self.color_mapping["color_2"] = "wrist_left"
        self.color_mapping["color_3"] = "wrist_right"
        self.color_mapping["color_4"] = "chest_front"
        self.color_mapping["color_5"] = "chest_back"

        self.depth_mapping = {
            "depth_0": "head",
            "depth_2": "wrist_left",
            "depth_3": "wrist_right",
        }

        self.required_dirs = []
        for subdir in list(self.color_mapping.values()):
            self.required_dirs.append(("colors", subdir))
        for subdir in list(self.depth_mapping.values()):
            self.required_dirs.append(("depths", subdir))

        _logger.info(f"相机映射构建完成，双目={self.binocular}，所需目录: {self.required_dirs}")

    def _build_text_config(self):
        """
        构建任务文本配置：目标、描述、步骤
        读取 `text` 配置。
        """
        text_cfg = deepcopy(self.save_config.get("text", {}))
        return {
            "goal": str(text_cfg.get("goal", "")),
            "desc": str(text_cfg.get("desc", "")),
            "steps": str(text_cfg.get("steps", "")),
        }

    def _build_info_config(self):
        """
        构建数据集元信息：版本、尺寸、关节名称等
        读取 `info` 配置，并补齐固定结构。
        """
        info_cfg = deepcopy(self.save_config.get("info", {}))
        return {
            "version": str(info_cfg.get("version", "")),
            "date": "",
            "author": str(info_cfg.get("author", "")),
            "image": {
                "head_width": int(info_cfg.get("image", {}).get("head_width", 0)),
                "head_height": int(info_cfg.get("image", {}).get("head_height", 0)),
                "fps": float(info_cfg.get("image", {}).get("fps", 0)),
            },
            "depth": {
                "head_width": int(info_cfg.get("depth", {}).get("head_width", 0)),
                "head_height": int(info_cfg.get("depth", {}).get("head_height", 0)),
                "fps": float(info_cfg.get("depth", {}).get("fps", 0)),
            },
            "audio": {
                "sample_rate": int(info_cfg.get("audio", {}).get("sample_rate", 16000)),
                "channels": int(info_cfg.get("audio", {}).get("channels", 1)),
                "format": str(info_cfg.get("audio", {}).get("format", "PCM")),
                "bits": int(info_cfg.get("audio", {}).get("bits", 16)),
            },
            "joint_names": {
                "left_arm": list(info_cfg.get("joint_names", {}).get("left_arm", [])),
                "left_ee": list(info_cfg.get("joint_names", {}).get("left_ee", [])),
                "right_arm": list(info_cfg.get("joint_names", {}).get("right_arm", [])),
                "right_ee": list(info_cfg.get("joint_names", {}).get("right_ee", [])),
                "waist": list(info_cfg.get("joint_names", {}).get("waist", [])),
            },
            "tactile_names": {
                "left_ee": list(info_cfg.get("tactile_names", {}).get("left_ee", [])),
                "right_ee": list(info_cfg.get("tactile_names", {}).get("right_ee", [])),
            },
            "sim_state": info_cfg.get("sim_state", ""),
            "binocular": self.binocular,
            "camera_mapping": {
                "colors": self.color_mapping,
                "depths": self.depth_mapping,
            },
        }

    def _refresh_runtime_info(self):
        """刷新运行时元信息：日期、图像尺寸"""
        self.info["date"] = datetime.date.today().strftime("%Y-%m-%d")

        camera_sizes = {}
        for cam_id, size in self.image_sizes.items():
            camera_sizes[cam_id] = {
                "width": int(size[0]),
                "height": int(size[1]),
            }
        if camera_sizes:
            self.info["camera_sizes"] = camera_sizes

    def _discover_episode_id(self):
        """发现最大 episode 编号"""
        if not os.path.exists(self.task_dir):
            os.makedirs(self.task_dir, exist_ok=True)
            return 0
        max_id = 0
        for name in os.listdir(self.task_dir):
            if name.startswith("episode_") and not name.endswith(".zip"):
                try:
                    num = int(name.split("_")[1])
                    if num > max_id:
                        max_id = num
                except ValueError:
                    continue
        return max_id

    def is_ready(self):
        """对外接口：判断录制器是否空闲可开始新录制"""
        return self.is_available

    def create_episode(self, task_info: Optional[Dict[str, str]] = None):
        """
        创建新的录制片段
        自动在 self.task_dir 下创建文件夹:episode_0001 → colors / depths / audios
        """
        if not self.is_available:
            _logger.info("当前仍有未完成的数据保存任务，请等待")
            return False

        self.item_id = -1
        self.episode_data = []
        self.episode_id = self._discover_episode_id() + 1
        self.last_item_enqueue_time = None
        self.episode_dir = os.path.join(self.task_dir, f"episode_{str(self.episode_id).zfill(4)}")
        self.json_path = os.path.join(self.episode_dir, "data.json")
        self.episode_start_time = time.monotonic()
        self._refresh_runtime_info()

        try:
            self._prepare_episode_dirs()
        except Exception as exc:
            _logger.exception(f"创建录制目录失败: episode={self.episode_id}, error={exc}")
            self._mark_episode_idle()
            return False

        if task_info:
            self._apply_task_info(task_info)

        self.is_available = False
        _logger.info(
            f"新录制片段已创建: episode={str(self.episode_id).zfill(4)}, dir={self.episode_dir}"
        )
        return True

    def _prepare_episode_dirs(self):
        for root, subdir in self.required_dirs:
            full_path = os.path.join(self.episode_dir, root, subdir)
            os.makedirs(full_path, exist_ok=True)
        if self.save_audio:
            os.makedirs(os.path.join(self.episode_dir, "audios"), exist_ok=True)

    def _apply_task_info(self, task_info: Dict[str, str]):
        self.text["goal"] = task_info.get("goal", self.text["goal"])
        self.text["desc"] = task_info.get("desc", self.text["desc"])
        self.text["steps"] = task_info.get("steps", self.text["steps"])
        _logger.info(f"录制任务信息已更新: goal={self.text['goal']}")

    @staticmethod
    def _is_blank_image(image):
        """判断彩色图像是否为空或全黑"""
        if image is None:
            return True
        image = np.asarray(image)
        if image.size == 0:
            return True
        return not np.any(image)

    @staticmethod
    def _is_blank_depth(depth_image, min_valid_ratio=0.01):
        """
        判断深度图是否有效(非全0)。
        深度图中像素值为0表示该点深度无效(超出探测范围或遮挡)
        min_valid_ratio: 有效像素最低比例，默认 1%,仅当有效像素比例低于阈值时才视为"空白"
        """
        if depth_image is None:
            return True
        depth_image = np.asarray(depth_image)
        if depth_image.size == 0:
            return True
        valid_ratio = np.count_nonzero(depth_image) / depth_image.size
        return valid_ratio < min_valid_ratio

    def _save_image(self, image, directory, filename, suffix, is_depth=False):
        """保存单张图像"""
        if self.skip_blank_images:
            if is_depth:
                if self._is_blank_depth(image):
                    _logger.warning(
                        f"[帧 {filename}] 跳过空白深度图: {directory}/{filename}.{suffix} "
                        f"(有效像素不足，可能相机距离物体过近或超出探测范围)"
                    )
                    return None
            else:
                if self._is_blank_image(image):
                    _logger.debug(f"[帧 {filename}] 跳过空白图像: {directory}/{filename}.{suffix}")
                    return None
        file_path = os.path.join(directory, f"{filename}.{suffix}")
        if cv2.imwrite(file_path, image):
            rel_path = os.path.relpath(file_path, self.episode_dir)
            return rel_path
        else:
            _logger.warning(f"保存图像失败: {file_path}")
            return None

    def _save_images_by_mapping(self, image_map, mapping, root_dir, suffix, idx):
        """
        根据映射关系保存图像。
        :param image_map: dict {key: image}
        :param mapping: dict {key: subdir_name}
        :param root_dir: episode_dir 下的根目录(如 "colors" 或 "depths")
        :param suffix: 文件扩展名（不含点）
        :param idx: 帧序号
        :return: dict {camera_name: relative_path}
        """
        if not image_map:
            return {}
        saved = {}

        for key, subdir in mapping.items():
            if key not in image_map:
                continue
            image = image_map[key]
            if image is None:
                continue
            dir_path = os.path.join(self.episode_dir, root_dir, subdir)
            filename = f"{str(idx).zfill(6)}"
            is_depth = (root_dir == "depths")
            rel_path = self._save_image(image, dir_path, filename, suffix, is_depth=is_depth)
            if rel_path:
                saved[subdir] = rel_path

        return saved

    def add_item(self, colors=None, depths=None, states=None, actions=None, tactiles=None, audios=None, sim_state=None):
        """向录制器添加一帧数据（后台异步保存）"""
        if self.is_available or not hasattr(self, "episode_dir"):
            _logger.warning("录制尚未开始,忽略 add_item 调用")
            return
        if self.stop_worker:
            _logger.warning("录制器已关闭，忽略 add_item 调用")
            return

        self.item_id += 1
        self.item_data_queue.put({
            "idx": self.item_id,
            "enqueue_time_monotonic": time.monotonic(),
            "colors": colors or {},
            "depths": depths or {},
            "states": states or {},
            "actions": actions or {},
            "tactiles": tactiles or {},
            "audios": audios or {},
            "sim_state": sim_state or {},
        })

    def process_queue(self):
        """后台线程消费帧队列"""
        while not self.stop_worker or not self.item_data_queue.empty():
            try:
                item_data = self.item_data_queue.get(timeout=1)
            except Empty:
                item_data = None

            if item_data is not None:
                try:
                    self._process_item_data(item_data)
                except Exception as exc:
                    _logger.exception(f"处理录制数据失败(idx={item_data['idx']}): {exc}")
                self.item_data_queue.task_done()

            if self.need_save and self.item_data_queue.empty():
                self._save_episode()

    def _process_item_data(self, item_data):
        """保存单帧图像与音频"""
        idx = item_data["idx"]
        enqueue_time_monotonic = item_data.pop("enqueue_time_monotonic", None)

        saved_colors = self._save_images_by_mapping(
            item_data.get("colors", {}),
            self.color_mapping,
            "colors",
            self.color_format,
            idx
        )

        saved_depths = self._save_images_by_mapping(
            item_data.get("depths", {}),
            self.depth_mapping,
            "depths",
            self.depth_format,
            idx
        )

        saved_audios = {}
        if self.save_audio:
            for mic_name, audio in (item_data.get("audios") or {}).items():
                if audio is None:
                    continue
                audio_name = f"audio_{str(idx).zfill(6)}_{mic_name}.npy"
                audio_path = os.path.join(self.episode_dir, "audios", audio_name)
                np.save(audio_path, np.asarray(audio, dtype=np.int16))
                saved_audios[mic_name] = os.path.join("audios", audio_name)

        relative_time_sec = 0.0
        if self.episode_start_time is not None and enqueue_time_monotonic is not None:
            relative_time_sec = max(0.0, enqueue_time_monotonic - self.episode_start_time)
        elif self.episode_start_time is not None:
            relative_time_sec = max(0.0, time.monotonic() - self.episode_start_time)

        frame_data = {
            "frame_id": idx,
            "timestamp": relative_time_sec,
            "states": item_data.get("states", {}),
            "actions": item_data.get("actions", {}),
            "tactiles": item_data.get("tactiles", {}),
            "sim_state": item_data.get("sim_state", {}),
            "images": saved_colors,
            "depths": saved_depths,
            "audios": saved_audios,
        }
        self.episode_data.append(frame_data)

        if self.rerun_log:
            rerun_frame = dict(frame_data)
            rerun_frame["images"] = item_data.get("colors", {}) or {}
            rerun_frame["depths"] = item_data.get("depths", {}) or {}
            self.rerun_logger.log_item_data(rerun_frame)

        saved_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        current_fps = 0.0
        if enqueue_time_monotonic is not None and self.last_item_enqueue_time is not None:
            frame_interval_sec = enqueue_time_monotonic - self.last_item_enqueue_time
            if frame_interval_sec > 0:
                current_fps = 1.0 / frame_interval_sec
        if enqueue_time_monotonic is not None:
            self.last_item_enqueue_time = enqueue_time_monotonic

        log_msg = (
            f"idx={str(idx).zfill(4)} 数据保存成功: "
            f"time={saved_time}, relative_time={relative_time_sec:.3f}, fps={current_fps:.2f}, "
            f"episode={str(self.episode_id).zfill(4)}"
        )
        # 默认场景只保留采样日志，逐帧日志降级到 debug。
        if idx % max(1, int(self.frequency)) == 0:
            _logger.info(log_msg)
        else:
            _logger.debug(log_msg)

    def save_episode(self):
        """【对外接口】触发保存当前录制片段"""
        if self.is_available:
            _logger.debug("录制器当前空闲，无需保存。")
            return
        self.need_save = True
        _logger.info("开始保存录制片段")

    def _save_episode(self):
        """将内存中的所有数据写入 data.json"""
        try:
            payload = {
                "info": self.info,
                "text": self.text,
                "data": self.episode_data,
            }
            frames_index = self._write_json_with_index(payload)
            self._write_frame_index(frames_index)
            _logger.info(f"录制片段已保存: {self.json_path}")
        except Exception as e:
            _logger.exception(f"保存录制片段失败: {e}")
        finally:
            self._mark_episode_idle()

    def _mark_episode_idle(self):
        self.need_save = False
        self.is_available = True
        self.episode_start_time = None

    def _write_json_with_index(self, payload):
        """同步写入JSON文件并生成索引"""
        frames_index = []
        
        with open(self.json_path, "w", encoding="utf-8") as json_file:
            header = '{"info": ' + json.dumps(
                payload["info"], 
                ensure_ascii=False, 
                separators=(',', ':')
            ) + ', "text": ' + json.dumps(
                payload["text"], 
                ensure_ascii=False, 
                separators=(',', ':')
            ) + ', "data": ['
            
            json_file.write(header)
            current_offset = len(header.encode("utf-8"))
            
            frames_data = payload["data"]
            for i, frame_data in enumerate(frames_data):
                frame_json = json.dumps(
                    frame_data, 
                    ensure_ascii=False, 
                    separators=(',', ':')
                )
                frame_index = {
                    "offset": current_offset,
                    "length": len(frame_json.encode("utf-8")),
                    "timestamp": frame_data.get("timestamp", 0),
                    "frame_id": frame_data.get("frame_id", i)
                }
                frames_index.append(frame_index)
                json_file.write(frame_json)
                current_offset += len(frame_json.encode("utf-8"))
                if i < len(frames_data) - 1:
                    json_file.write(",")
                    current_offset += 1
            json_file.write("]}")
        
        return frames_index

    def _write_frame_index(self, frames_index):
        """写入帧索引文件"""
        try:
            episode_dir = Path(self.json_path).parent
            index_data = {
                "total_frames": len(frames_index),
                "frames": frames_index,
                "created_time": time.time(),
                "version": "1.0",
                "data_file": "data.json"
            }
            index_file = episode_dir / "frames_index.json"
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
            _logger.info(f"索引文件生成完成: {index_file}，共{len(frames_index)}帧")
            
        except Exception as e:
            _logger.error(f"写入索引文件失败: {e}")

    def close(self):
        """【对外接口】关闭录制器：等待所有数据保存完成，销毁线程"""
        self.item_data_queue.join()
        if not self.is_available:
            self.save_episode()
        while not self.is_available:
            time.sleep(0.01)
        self.stop_worker = True
        self.worker_thread.join(timeout=1.0)