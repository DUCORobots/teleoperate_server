#!/usr/bin/env python3
"""相机发现模块"""
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
except ImportError:
    REALSENSE_AVAILABLE = False

try:
    import uvc
    UVC_AVAILABLE = True
except ImportError:
    UVC_AVAILABLE = False

REALSENSE_PIDS = {"0b07", "0b3a", "0b5b", "0b5c", "0b52", "0b53"}

from loguru import logger


def list_video_paths() -> List[str]:
    """列出所有 /dev/video* 设备路径"""
    base = Path("/sys/class/video4linux")
    if not base.exists():
        return []
    def key(item: Path) -> int:
        match = re.search(r"video(\d+)$", item.name)
        return int(match.group(1)) if match else 9999
    return [f"/dev/{p.name}" for p in sorted(base.iterdir(), key=key) if p.name.startswith("video")]


def read_text(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def video_name_from_path(path: str) -> str:
    """获取设备名称"""
    return read_text(f"/sys/class/video4linux/{Path(path).name}/name") or Path(path).name


def physical_path_for_video(path: str) -> Optional[str]:
    """获取设备的物理路径(USB 拓扑)"""
    sysfs_path = Path("/sys/class/video4linux") / Path(path).name / "device"
    try:
        return str(sysfs_path.resolve())
    except Exception:
        return None


def parent_usb_device_dir(path: str) -> Optional[str]:
    """获取 USB 设备根目录"""
    current = Path(path)
    for _ in range(12):
        if not current.exists() or current == current.parent:
            break
        if (current / "idVendor").exists() and (current / "idProduct").exists():
            return str(current)
        current = current.parent
    return None


def usb_info_for_video(path: str) -> Dict[str, Optional[str]]:
    """获取 USB 设备信息"""
    physical = physical_path_for_video(path)
    usb_dir = parent_usb_device_dir(physical or "")
    if not usb_dir:
        return {"vendor": None, "product": None, "serial": None, "manufacturer": None}
    return {
        "vendor": read_text(Path(usb_dir) / "idVendor"),
        "product": read_text(Path(usb_dir) / "idProduct"),
        "serial": read_text(Path(usb_dir) / "serial"),
        "manufacturer": read_text(Path(usb_dir) / "manufacturer"),
    }


def normalize_modes(modes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """去重并按分辨率排序"""
    seen = set()
    normalized = []
    for mode in modes:
        w, h, fps, fmt = mode["width"], mode["height"], mode["fps"], mode["format"]
        key = (w, h, fps, fmt)
        if key not in seen:
            seen.add(key)
            normalized.append(mode)
    normalized.sort(key=lambda x: (x["width"] * x["height"], x["fps"], x["format"]))
    return normalized


def preferred_mode(modes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """选择首选模式640x480@30,若不可用选最近似"""
    if not modes:
        return {"width": 640, "height": 480, "fps": 30, "format": "MJPG"}
    for mode in modes:
        if mode["width"] == 640 and mode["height"] == 480 and mode["fps"] == 30:
            return mode
    for mode in modes:
        if mode["width"] <= 1280 and mode["height"] <= 720:
            return mode
    return modes[0]

def probe_opencv_modes(video_id: int) -> List[Dict[str, Any]]:
    """通过 v4l2-ctl 查询设备支持的 MJPG 模式（设备被占用时仍可查询）"""
    device_path = f"/dev/video{video_id}"
    try:
        result = subprocess.run(
            ["v4l2-ctl", "-d", device_path, "--list-formats-ext"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            logger.debug(f"v4l2-ctl 查询 {device_path} 失败: {result.stderr.strip()}")
            return []
        return _parse_v4l2_mjpg_modes(result.stdout)
    except FileNotFoundError:
        logger.debug("v4l2-ctl 未安装，无法查询设备模式")
        return []
    except subprocess.TimeoutExpired:
        logger.debug(f"v4l2-ctl 查询 {device_path} 超时")
        return []
    except Exception as e:
        logger.debug(f"v4l2-ctl 查询 {device_path} 异常: {e}")
        return []


def _parse_v4l2_mjpg_modes(output: str) -> List[Dict[str, Any]]:
    """解析 v4l2-ctl --list-formats-ext 输出，仅提取 MJPG 格式的分辨率和帧率"""
    modes = []
    in_mjpg_section = False
    pending_size = None

    for line in output.splitlines():
        stripped = line.strip()

        fmt_match = re.search(r"\[\d+\]:\s+'(\S+)'\s+\(", stripped)
        if fmt_match:
            fmt_code = fmt_match.group(1)
            in_mjpg_section = (fmt_code == "MJPG")
            pending_size = None
            continue

        if not in_mjpg_section:
            continue

        size_match = re.search(r"Size:\s+Discrete\s+(\d+)x(\d+)", stripped)
        if size_match:
            pending_size = (int(size_match.group(1)), int(size_match.group(2)))
            continue

        if pending_size:
            fps_match = re.search(r"Interval:\s+Discrete\s+[\d.]+s\s+\(([\d.]+)\s+fps\)", stripped)
            if fps_match:
                fps = int(float(fps_match.group(1)))
                modes.append({
                    "width": pending_size[0],
                    "height": pending_size[1],
                    "fps": fps,
                    "format": "MJPG",
                })

    return normalize_modes(modes)

def probe_uvc_modes(uid: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """使用 UVC 库探测设备模式"""
    if not UVC_AVAILABLE:
        return [], "uvc library not installed"
    try:
        cap = uvc.Capture(uid)
        modes = []
        for mode in cap.available_modes:
            modes.append({
                "width": int(mode.width),
                "height": int(mode.height),
                "fps": int(mode.fps),
                "format": str(mode.format_name),
            })
        cap.close()
        return normalize_modes(modes), None
    except Exception as e:
        return [], str(e)


def probe_realsense_color_modes(serial: str) -> List[Dict[str, Any]]:
    """使用 pyrealsense2 探测彩色流支持的模式"""
    if not REALSENSE_AVAILABLE:
        return []
    try:
        ctx = rs.context()
        devices = ctx.query_devices()
        dev = None
        for d in devices:
            if d.get_info(rs.camera_info.serial_number) == serial:
                dev = d
                break
        if not dev:
            return []
        modes = []
        for sensor in dev.query_sensors():
            for profile in sensor.get_stream_profiles():
                if profile.stream_type() != rs.stream.color:
                    continue
                video_profile = profile.as_video_stream_profile()
                fmt = str(profile.format()).split(".")[-1].upper()
                modes.append({
                    "width": int(video_profile.width()),
                    "height": int(video_profile.height()),
                    "fps": int(profile.fps()),
                    "format": fmt,
                })
        return normalize_modes(modes)
    except Exception:
        return []

def probe_realsense_depth_modes(serial: str) -> List[Dict[str, Any]]:
    """使用 pyrealsense2 探测深度流支持的模式"""
    if not REALSENSE_AVAILABLE:
        return []
    try:
        ctx = rs.context()
        devices = ctx.query_devices()
        dev = None
        for d in devices:
            if d.get_info(rs.camera_info.serial_number) == serial:
                dev = d
                break
        if not dev:
            return []
        modes = []
        for sensor in dev.query_sensors():
            for profile in sensor.get_stream_profiles():
                if profile.stream_type() != rs.stream.depth:
                    continue
                video_profile = profile.as_video_stream_profile()
                fmt = str(profile.format()).split(".")[-1].upper()
                modes.append({
                    "width": int(video_profile.width()),
                    "height": int(video_profile.height()),
                    "fps": int(profile.fps()),
                    "format": fmt,
                })
        return normalize_modes(modes)
    except Exception:
        return []

def get_realsense_model(dev) -> str:
    """获取 RealSense 设备型号（如 D435, D405）"""
    try:
        name = dev.get_info(rs.camera_info.name).lower()
        if "d435" in name:
            return "D435"
        elif "d405" in name:
            return "D405"
        elif "d455" in name:
            return "D455"
        else:
            return "Unknown"
    except Exception:
        return "Unknown"


class CameraDiscovery:
    """相机发现器"""

    @staticmethod
    def discover() -> Dict[str, Any]:
        """发现所有相机设备"""
        devices = []
        warnings = []

        video_paths = list_video_paths()
        nodes_by_uid: Dict[str, List[Dict[str, Any]]] = {}
        
        for path in video_paths:
            physical = physical_path_for_video(path)
            if not physical:
                continue
            # 获取 USB 唯一标识（bus:dev）
            usb_dir = parent_usb_device_dir(physical)
            uid = None
            if usb_dir:
                bus = read_text(Path(usb_dir) / "busnum")
                dev = read_text(Path(usb_dir) / "devnum")
                if bus and dev:
                    uid = f"{int(bus)}:{int(dev)}" if bus.isdigit() and dev.isdigit() else f"{bus}:{dev}"
            if not uid:
                uid = str(hash(physical))
            video_id = int(re.search(r"video(\d+)$", path).group(1))
            node = {
                "video_path": path,
                "video_id": video_id,
                "name": video_name_from_path(path),
                "physical_path": physical,
                "usb_info": usb_info_for_video(path),
            }
            nodes_by_uid.setdefault(uid, []).append(node)
        
        # 记录已经被占用的 uid 和 video_id
        used_uids = set()
        claimed_video_ids = set()
        
        if REALSENSE_AVAILABLE:
            try:
                ctx = rs.context()
                for dev in ctx.query_devices():
                    serial = dev.get_info(rs.camera_info.serial_number)
                    name = dev.get_info(rs.camera_info.name)
                    model = get_realsense_model(dev)
                    matched_uid = None
                    matched_nodes = []
                    # 优先通过 VID/PID 匹配
                    for uid, nodes in nodes_by_uid.items():
                        if uid in used_uids:
                            continue
                        for node in nodes:
                            usb_info = node["usb_info"]
                            if (usb_info.get("vendor") == "8086" and
                                    usb_info.get("product") in REALSENSE_PIDS):
                                matched_uid = uid
                                matched_nodes = nodes
                                break
                        if matched_uid:
                            break
                    # VID/PID 未匹配时，尝试序列号匹配
                    if not matched_uid:
                        for uid, nodes in nodes_by_uid.items():
                            if uid in used_uids:
                                continue
                            for node in nodes:
                                if node["usb_info"].get("serial") == serial:
                                    matched_uid = uid
                                    matched_nodes = nodes
                                    break
                            if matched_uid:
                                break
                    if matched_uid:
                        used_uids.add(matched_uid)
                        for node in matched_nodes:
                            claimed_video_ids.add(node["video_id"])
                    else:
                        matched_nodes = []
                    color_modes = probe_realsense_color_modes(serial)
                    if not color_modes:
                        color_modes = [{"width": 640, "height": 480, "fps": 30, "format": "BGR8"}]
                    depth_modes = probe_realsense_depth_modes(serial)
                    if not depth_modes:
                        depth_modes = [{"width": 640, "height": 480, "fps": 30, "format": "Z16"}]
                    color_default = preferred_mode(color_modes)
                    depth_default = preferred_mode(depth_modes)

                    suggested_id = None
                    suggested_position = "UNKNOWN"
                    if model == "D435":
                        suggested_id = "head_camera"
                        suggested_position = "HEAD"
                    elif model == "D405":
                        suggested_id = "left/right_wrist_camera"
                        suggested_position = "LEFT/RIGHT_WRIST"

                    backends = [{
                        "id": "realsense",
                        "label": "RealSense SDK",
                        "supports_depth": True,
                        "available": True,
                        "serial": serial,
                        "model": model,
                        "color_modes": color_modes,
                        "depth_modes": depth_modes,
                        "color_default": color_default,
                        "depth_default": depth_default,
                        "format_options": ["BGR8"],
                    }]
                    devices.append({
                        "id": f"realsense:{serial}",
                        "family": "realsense",
                        "label": f"RealSense {name} (S/N {serial})",
                        "suggested_id": suggested_id,
                        "suggested_position": suggested_position,
                        "model": model,
                        "default_backend": "realsense",
                        "serial": serial,
                        "available": True,
                        "nodes": matched_nodes,
                        "backends": backends,
                    })
            except Exception as e:
                warnings.append(f"RealSense enumeration error: {e}")
        
        if UVC_AVAILABLE:
            try:
                uvc_devices = uvc.device_list()
                for uv in uvc_devices:
                    uid = str(uv.get("uid"))
                    if uid in used_uids:
                        continue
                    nodes = nodes_by_uid.get(uid, [])
                    if any(node["video_id"] in claimed_video_ids for node in nodes):
                        continue
                    used_uids.add(uid)
                    for node in nodes:
                        claimed_video_ids.add(node["video_id"])
                    name = str(uv.get("name", "UVC Camera"))
                    modes, err = probe_uvc_modes(uid)
                    if err:
                        warnings.append(f"UVC device {uid} mode probe failed: {err}")
                    if not modes:
                        # UVC 模式探测为空时，回退到 V4L2(MJPG) 探测，保证跨平台模式信息可用。
                        for node in nodes:
                            video_id = node.get("video_id")
                            if not isinstance(video_id, int):
                                continue
                            fallback_modes = probe_opencv_modes(video_id)
                            if fallback_modes:
                                modes = fallback_modes
                                warnings.append(
                                    f"UVC device {uid} mode probe fallback to /dev/video{video_id} (MJPG)"
                                )
                                break
                    if not modes:
                        modes = [{"width": 640, "height": 480, "fps": 30, "format": "MJPG"}]
                        warnings.append(f"UVC device {uid} mode probe empty, use default MJPG 640x480@30")
                    default = preferred_mode(modes) if modes else {"width": 640, "height": 480, "fps": 30, "format": "MJPG"}
                    backends = [{
                        "id": "uvc",
                        "label": "UVC library",
                        "available": not err,
                        "uid": uid,
                        "modes": modes,
                        "default": default,
                        "format_options": ["MJPG"],
                        "reason": err if err else None,
                    }]
                    devices.append({
                        "id": f"uvc:{uid}",
                        "family": "uvc",
                        "label": f"UVC {name}",
                        "default_backend": None,
                        "uid": uid,
                        "serial": uv.get("serialNumber"),
                        "vendor": uv.get("idVendor"),
                        "product": uv.get("idProduct"),
                        "manufacturer": uv.get("manufacturer"),
                        "nodes": nodes,
                        "available": not err,
                        "suggested_id": None,
                        "suggested_position": None,
                        "backends": backends,
                    })
            except Exception as e:
                warnings.append(f"UVC enumeration error: {e}")
        
        for uid, nodes in nodes_by_uid.items():
            if uid in used_uids:
                continue
            if all(node["video_id"] in claimed_video_ids for node in nodes):
                continue
            # 过滤已知属于 RealSense 的 V4L2 节点（匹配失败不应降级为 opencv）
            is_realsense_v4l2 = any(
                node["usb_info"].get("vendor") == "8086" and
                node["usb_info"].get("product") in REALSENSE_PIDS
                for node in nodes
            )
            if is_realsense_v4l2:
                warnings.append(
                    f"RealSense V4L2 节点 {uid} 未被成功匹配，跳过（不应降级为 opencv 设备）"
                )
                for node in nodes:
                    claimed_video_ids.add(node["video_id"])
                used_uids.add(uid)
                continue
            node = nodes[0]
            video_id = node["video_id"]
            for n in nodes:
                claimed_video_ids.add(n["video_id"])
            used_uids.add(uid)
            modes = probe_opencv_modes(video_id) if OPENCV_AVAILABLE else []
            default = preferred_mode(modes) if modes else {"width": 640, "height": 480, "fps": 30, "format": "MJPG"}
            backends = [{
                "id": "opencv",
                "label": f"OpenCV /dev/video{video_id}",
                "available": OPENCV_AVAILABLE,
                "video_id": video_id,
                "modes": modes,
                "default": default,
                "format_options": ["MJPG"],
            }]
            devices.append({
                "id": f"opencv:{video_id}",
                "family": "opencv",
                "label": f"V4L2 {node['name']}",
                "default_backend": None,
                "available": OPENCV_AVAILABLE,
                "nodes": nodes,
                "suggested_id": None,
                "suggested_position": None,
                "backends": backends,
            })

        return {
            "devices": devices,
            "warnings": warnings,
            "counts": {
                "realsense": sum(1 for d in devices if d["family"] == "realsense"),
                "uvc": sum(1 for d in devices if d["family"] == "uvc"),
                "opencv": sum(1 for d in devices if d["family"] == "opencv"),
                "total": len(devices),
            }
        }