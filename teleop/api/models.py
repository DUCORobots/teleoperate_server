from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class TeleopState(str, Enum):
    INACTIVE = "INACTIVE"                    # 未激活状态
    IDLE = "IDLE"                            # 待机状态
    ACTIVE_CONTROL = "ACTIVE_CONTROL"        # 主动控制状态
    RETURNING_HOME = "RETURNING_HOME"        # 自动回零状态
    ESTOP = "ESTOP"                          # 紧急停止状态

class RecordStatus(str, Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"

class XRStatusResponse(BaseModel):
    xr_active: bool
    xr_web_connected: bool
    last_pose_time: Optional[float]
    timeout: float

class CameraStatusResponse(BaseModel):
    camera_id: str
    fps: float
    last_frame_time: Optional[float]
    connected: bool

class RecordTaskInfo(BaseModel):
    goal: str = ""
    desc: str = ""
    steps: str = ""

class RecordStatusResponse(BaseModel):
    is_recording: bool
    episode_id: Optional[str]
    start_time: Optional[float]
    frame_count: int
    duration: float
    task_info: Optional[RecordTaskInfo]

class SystemStatusResponse(BaseModel):
    teleop_state: TeleopState
    xr_status: XRStatusResponse
    record_status: RecordStatusResponse
    config: Dict[str, Any]
    control_source: Optional[str] = None
    control_lock: bool = False
    emergency_stop: bool = False
    active_task: Optional[str] = None

class RobotJointsResponse(BaseModel):
    head_qpos: Optional[List[float]] = None
    left_arm_qpos: Optional[List[float]] = None
    right_arm_qpos: Optional[List[float]] = None
    left_arm_tcp: Optional[List[float]] = None
    right_arm_tcp: Optional[List[float]] = None
    last_update_time: Optional[float] = None
    waist_qpos: Optional[List[float]] = None

class TaskInfo(BaseModel):
    task_id: str
    task_name: str
    description: str
    create_time: str          # ISO格式字符串，如 "2026-04-08 10:00:00"
    last_modified: str
    creator: Optional[str] = None

class CreateTaskRequest(BaseModel):
    task_name: str = Field(..., min_length=1, max_length=64, description="任务名称，可含中文")
    description: str = Field(default="这是一个默认任务描述", max_length=500)
    creator: Optional[str] = Field(default="系统用户")

class UpdateTaskRequest(BaseModel):
    task_name: Optional[str] = Field(None, min_length=1, max_length=64)
    description: Optional[str] = Field(None, max_length=500)

class SetActiveTaskRequest(BaseModel):
    task_id: str = Field(..., description="任务ID,格式为 task_xxxx,eg: task_0001")

class TaskListResponse(BaseModel):
    tasks: List[TaskInfo]
    total_count: int

class DatasetInfo(BaseModel):
    episode_id: str
    task_id: str              # 所属任务ID
    name: str
    created_time: datetime
    total_frames: int
    duration: float
    task_info: Optional[RecordTaskInfo]
    size: int  # 字节大小

class DatasetListResponse(BaseModel):
    datasets: List[DatasetInfo]
    total_count: int
    page: int
    page_size: int

class FrameIndexItem(BaseModel):
    offset: int
    length: int
    timestamp: float

class FrameIndexResponse(BaseModel):
    total_frames: int
    frames: List[FrameIndexItem]

class FrameData(BaseModel):
    frame_id: int
    timestamp: float
    states: Dict[str, Any]
    actions: Dict[str, Any]
    images: Dict[str, str]
    depths: Dict[str, str]
    audios: Optional[Dict[str, Any]]
    tactiles: Optional[Dict[str, Any]]
    sim_state: Optional[Dict[str, Any]]

class FramesResponse(BaseModel):
    frames: List[FrameData]
    total_frames: int
    page: int
    page_size: int

class StartRecordRequest(BaseModel):
    task_info: Optional[RecordTaskInfo] = None

class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="页码,从1开始")
    page_size: int = Field(50, ge=1, le=1000, description="每页大小,最大1000")

class FrameQueryParams(PaginationParams):
    start_time: Optional[float] = Field(None, description="开始时间戳")
    end_time: Optional[float] = Field(None, description="结束时间戳")

class DeleteDatasetRequest(BaseModel):
    confirm: bool = Field(..., description="确认删除操作")

class RebuildIndexResponse(BaseModel):
    success: bool
    message: str
    total_frames: Optional[int]
    elapsed_time: float

class ExportStatus(str, Enum):
    PENDING = "pending"          # 等待中
    PACKING = "packing"          # 打包中
    READY = "ready"              # 准备就绪，可下载
    DOWNLOADING = "downloading"  # 下载中
    CONFIRMED = "confirmed"      # 已确认下载完成
    CANCELLED = "cancelled"      # 已取消
    FAILED = "failed"            # 失败

class ImportStatus(str, Enum):
    PENDING = "pending"          # 等待中
    UPLOADING = "uploading"      # 上传中
    EXTRACTING = "extracting"    # 解压中
    REBUILDING = "rebuilding"    # 重建索引中
    MOVING = "moving"            # 移动文件中
    COMPLETED = "completed"      # 完成
    CANCELLED = "cancelled"      # 已取消
    FAILED = "failed"            # 失败

class ExportTaskInfo(BaseModel):
    export_id: str                    # 导出任务ID
    task_id: str                      # 要导出的任务ID
    status: ExportStatus              # 状态
    created_time: float               # 创建时间戳
    completed_time: Optional[float]   # 完成时间戳
    file_path: Optional[str]          # 导出文件路径
    file_size: int                    # 文件大小（字节）
    episode_count: int                # 包含的episode数量
    error_message: Optional[str]      # 错误信息
    retry_suggestion: Optional[str]   # 重试建议
    download_count: int = 0           # 下载次数
    confirmed: bool = False           # 是否已确认下载完成
    confirmed_time: Optional[float] = None  # 确认时间戳
    format: str = "zip"               # 导出格式，"zip" 或 "tar.gz"

class ImportTaskInfo(BaseModel):
    import_id: str                    # 导入任务ID
    status: ImportStatus              # 状态
    created_time: float               # 创建时间戳
    completed_time: Optional[float]   # 完成时间戳
    file_name: str                    # 上传的文件名
    file_size: int                    # 文件大小（字节）
    temp_dir: str                     # 临时目录路径
    target_task_id: Optional[str]     # 目标任务ID
    episode_count: int                # 导入的episode数量
    rebuild_progress: float           # 索引重建进度（0.0-1.0）
    error_message: Optional[str]      # 错误信息
    retry_suggestion: Optional[str]   # 重试建议
    task_name: Optional[str] = None   # 导入后的任务名称
    description: Optional[str] = None # 导入后的任务描述
    creator: Optional[str] = None     # 导入后的创建者

class ExportRequest(BaseModel):
    task_id: str = Field(..., description="要导出的任务ID")
    format: str = Field(default="zip", description="导出格式,支持zip或tar.gz,默认为zip")

class ExportTaskListResponse(BaseModel):
    tasks: List[ExportTaskInfo]
    total_count: int

class ExportStatusResponse(BaseModel):
    export_id: str
    status: str
    progress: float                   # 进度（0.0-1.0）
    file_size: int
    episode_count: int
    created_time: float
    completed_time: Optional[float]
    error_message: Optional[str]
    retry_suggestion: Optional[str]

class ImportRequest(BaseModel):
    pass  # 文件上传通过 UploadFile 处理

class ImportStatusResponse(BaseModel):
    import_id: str
    status: str
    progress: float                   # 进度（0.0-1.0）
    file_name: str
    file_size: int
    episode_count: int
    target_task_id: Optional[str]
    created_time: float
    completed_time: Optional[float]
    error_message: Optional[str]
    retry_suggestion: Optional[str]

class ErrorResponse(BaseModel):
    error_code: str
    error_message: str
    retry_suggestion: Optional[str] = None
    timestamp: float

class ImportExportStatistics(BaseModel):
    exports: Dict[str, Any]
    imports: Dict[str, Any]
    disk_usage: Dict[str, Any]

# 相机管理端点,fastapi查询/配置/更新/新增/删除相机
class CameraAddRequest(BaseModel):
    camera_id: str = Field(..., description="相机ID,严格按照头:head_camera,手:left/right_wrist_camera,胸部:front/back_chest_camera")
    camera_type: str = Field(..., description="相机类型:realsensecamera或opencv")
    model: str = Field(default="D435", description="设备型号:D435/D405/fisheye,默认为D435")
    serial_number: str = Field(default="", description="相机序列号,用于realsense相机,默认为空")
    device_index: int = Field(default=-1, description="设备索引,默认为-1,仅用于opencv相机")
    position: str = Field(default="UNKNOWN", description="安装位置严格按照(HEAD/LEFT_WRIST/RIGHT_WRIST/FRONT_CHEST/BACK_CHEST)")
    enabled: bool = Field(default=True, description="是否启用相机,默认为True")
    binocular: bool = Field(default=False, description="是否为双目相机,默认为False")

    # 采集分辨率和帧率
    color_enabled: bool = Field(default=True, description="是否启用彩色图像采集,默认为True")
    color_width: int = Field(default=640, ge=1, le=1920, description="彩色图像宽度")
    color_height: int = Field(default=480, ge=1, le=1080, description="彩色图像高度")
    color_fps: int = Field(default=30, ge=1, le=60, description="彩色图目标帧率，也是帧率计算用的参考值")
    depth_enabled: bool = Field(default=True, description="是否启用深度图像采集,默认为True")
    depth_width: int = Field(default=640, ge=1, le=1280, description="深度图像宽度")
    depth_height: int = Field(default=480, ge=1, le=720, description="深度图像高度")
    depth_fps: int = Field(default=30, ge=1, le=60, description="深度图目标帧率")

    #全局压缩配置选项
    rgb_compress_quality: int = Field(default=85, ge=1, le=100, description="RGB图像压缩量化位数质量JPEG 压缩质量(1-100),PNG压缩质量(1-9)")
    rgb_compress_format: str = Field(default="JPEG", description="RGB图像压缩格式,默认为JPEG,支持JPEG/PNG")
    depth_compress_quantization_bits: int = Field(default=12, ge=1, le=16, description="深度图像压缩量化位数,默认为12,范围1-16")
    depth_zstd_compress_level: int = Field(default=3, ge=0, le=22, description="深度图像压缩Zstd级别,默认为3,范围1-22")
    
    #发布器选项
    publisher_zmq_rgb_compress_quality: Optional[int] = Field(None, ge=1, le=100, description="ZeroMQ发布rgb图像压缩量化位数质量JPEG 压缩质量(1-100),PNG压缩质量(1-9),不提供则使用全局压缩配置")
    publisher_zmq_rgb_compress_format: Optional[str] = Field(None, description="ZeroMQ发布rgb图像压缩格式,不提供则使用全局压缩配置")
    publisher_zmq_depth_compress_quantization_bits: Optional[int] = Field(None, ge=1, le=16, description="ZeroMQ发布深度图像压缩量化位数,不提供则使用全局压缩配置")
    publisher_zmq_depth_zstd_compress_level: Optional[int] = Field(None, ge=0, le=22, description="ZeroMQ发布深度图像压缩Zstd级别,不提供则使用全局压缩配置")
    publisher_webrtc_rgb_compress_quality: Optional[int] = Field(None, ge=1, le=100, description="WebRTC发布rgb图像压缩质量(1-100),不提供则使用全局压缩配置")
    publisher_webrtc_rgb_compress_format: Optional[str] = Field(None, description="WebRTC发布rgb图像压缩格式,不提供则使用全局压缩配置")

    # 发布通道选项
    communication_enable_zmq: bool = Field(default=True, description="是否启用ZeroMQ发布")
    communication_zmq_image_port: int = Field(default=5555, description="ZeroMQ发布图像端口,默认为5555")
    communication_zmq_status_port: int = Field(default=5556, description="ZeroMQ发布状态端口,默认为5556")
    communication_enable_websocket: bool = Field(default=True, description="是否启用WebSocket发布")
    communication_websocket_host: str = Field(default="localhost", description="WebSocket发布主机,默认为localhost")
    communication_websocket_port: int = Field(default=8765, description="WebSocket发布端口,默认为8765")
    communication_enable_webrtc: bool = Field(default=True, description="是否启用WebRTC发布")
    communication_webrtc_video_codec: str = Field(default="VP8", description="WebRTC视频编码器,默认为VP8,支持VP8/H264")
 
class CameraRemoveRequest(BaseModel):
    camera_id: str = Field(..., description="要移除的相机 ID")

class CameraUpdateRequest(BaseModel):
    """更新相机配置请求 - 仅传递需要更新的字段，未提供的字段沿用原有配置"""
    camera_id: str = Field(..., description="要更新的相机 ID")

    camera_type: Optional[str] = Field(None, description="相机类型:realsensecamera或opencv")
    model: Optional[str] = Field(None, description="设备型号:D435/D405/fisheye")
    serial_number: Optional[str] = Field(None, description="相机序列号,用于realsense相机")
    device_index: Optional[int] = Field(None, description="设备索引,仅用于opencv相机")
    position: Optional[str] = Field(None, description="安装位置(HEAD/LEFT_WRIST/RIGHT_WRIST/FRONT_CHEST/BACK_CHEST)")
    enabled: Optional[bool] = Field(None, description="是否启用相机")
    binocular: Optional[bool] = Field(None, description="是否为双目相机")
    
    # 采集分辨率和帧率
    color_enabled: Optional[bool] = Field(None, description="是否启用彩色图像采集,默认为True")
    color_width: Optional[int] = Field(None, ge=1, le=1920, description="彩色图像宽度")
    color_height: Optional[int] = Field(None, ge=1, le=1080, description="彩色图像高度")
    color_fps: Optional[int] = Field(None, ge=1, le=60, description="彩色图目标帧率，也是帧率计算用的参考值")
    depth_enabled: Optional[bool] = Field(None, description="是否启用深度图像采集,默认为True")
    depth_width: Optional[int] = Field(None, ge=1, le=1280, description="深度图像宽度")
    depth_height: Optional[int] = Field(None, ge=1, le=720, description="深度图像高度")
    depth_fps: Optional[int] = Field(None, ge=1, le=60, description="深度图目标帧率")

    #全局压缩配置选项
    rgb_compress_quality: Optional[int] = Field(None, ge=1, le=100, description="RGB图像压缩量化位数质量JPEG 压缩质量(1-100),PNG压缩质量(1-9)")
    rgb_compress_format: Optional[str] = Field(None, description="RGB图像压缩格式,默认为JPEG,支持JPEG/PNG")
    depth_compress_quantization_bits: Optional[int] = Field(None, ge=1, le=16, description="深度图像压缩量化位数,默认为12,范围1-16")
    depth_zstd_compress_level: Optional[int] = Field(None, ge=0, le=22, description="深度图像压缩Zstd级别,默认为3")
    
    #发布器选项
    publisher_zmq_rgb_compress_quality: Optional[int] = Field(None, ge=1, le=100, description="ZeroMQ发布rgb图像压缩量化位数质量JPEG 压缩质量(1-100),PNG 压缩质量(1-9)")
    publisher_zmq_rgb_compress_format: Optional[str] = Field(None, description="ZeroMQ发布rgb图像压缩格式,默认为JPEG,支持JPEG/PNG")
    publisher_zmq_depth_compress_quantization_bits: Optional[int] = Field(None, ge=1, le=16, description="ZeroMQ发布深度图像压缩量化位数,默认为12,范围1-16")
    publisher_zmq_depth_zstd_compress_level: Optional[int] = Field(None, ge=0, le=22, description="ZeroMQ发布深度图像压缩Zstd级别,默认为3")
    publisher_webrtc_rgb_compress_quality: Optional[int] = Field(None, ge=1, le=100, description="WebRTC发布rgb图像压缩量化位数质量JPEG 压缩质量(1-100),PNG 压缩质量(1-9)")
    publisher_webrtc_rgb_compress_format: Optional[str] = Field(None, description="WebRTC发布rgb图像压缩格式,默认为JPEG,支持JPEG/PNG")

    # 发布通道选项
    communication_enable_zmq: Optional[bool] = Field(None, description="是否启用ZeroMQ发布")
    communication_zmq_image_port: Optional[int] = Field(None, description="ZeroMQ发布图像端口,默认为5555")
    communication_zmq_status_port: Optional[int] = Field(None, description="ZeroMQ发布状态端口,默认为5556")
    communication_enable_websocket: Optional[bool] = Field(None, description="是否启用WebSocket发布")
    communication_websocket_host: Optional[str] = Field(None, description="WebSocket发布主机,默认为localhost")
    communication_websocket_port: Optional[int] = Field(None, description="WebSocket发布端口,默认为8765")
    communication_enable_webrtc: Optional[bool] = Field(None, description="是否启用WebRTC发布")
    communication_webrtc_video_codec: Optional[str] = Field(None, description="WebRTC视频编码器,默认为VP8,支持VP8/H264")