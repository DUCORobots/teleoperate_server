from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import Optional, List, Dict, Any
import time
import os
import tempfile
import aiofiles

from .shared_state import SharedState, TeleopCommand
from .dataset_manager import DatasetManager
from .models import (
    SystemStatusResponse, DatasetListResponse, FramesResponse,
    StartRecordRequest, DeleteDatasetRequest, RebuildIndexResponse,
    XRStatusResponse, CameraStatusResponse, TeleopState, RecordTaskInfo, RecordStatusResponse,
    TaskInfo, CreateTaskRequest, UpdateTaskRequest, SetActiveTaskRequest, TaskListResponse, ExportTaskInfo,
    ExportRequest, ExportTaskListResponse, ExportStatusResponse, ExportStatus, ImportTaskInfo,
    ImportStatusResponse, ImportStatus, ImportExportStatistics, CameraAddRequest, CameraRemoveRequest, 
    CameraUpdateRequest, RobotJointsResponse
)
from utils.dataset_io import DatasetIOManager
from utils.camera_manager import CameraManager
from teleop.log_manager import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["teleoperation"])

def get_shared_state(request: Request) -> SharedState:
    return request.app.state.shared_state

def get_dataset_manager(request: Request) -> DatasetManager:
    return request.app.state.dataset_manager

def get_dataset_io_manager(request: Request) -> DatasetIOManager:
    return request.app.state.dataset_io_manager

def _paginate(items: List[Any], page: int, page_size: int) -> List[Any]:
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    return items[start_idx:end_idx]

@router.get("/health", summary="健康检查")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}

@router.get("/status", response_model=SystemStatusResponse, summary="获取系统状态")
async def get_system_status(shared_state: SharedState = Depends(get_shared_state)):
    state_dict = shared_state.to_dict()
    xr_status = XRStatusResponse(**state_dict["xr_status"])
    record_status = RecordStatusResponse(**state_dict["record_status"])
    return SystemStatusResponse(
        teleop_state=state_dict["teleop_state"],                # 遥操状态
        xr_status=xr_status,                                    # XR设备状态
        record_status=record_status,                            # 记录状态
        config=state_dict["config"],                            # 配置信息
        control_source=state_dict.get("control_source"),        # 控制源 
        control_lock=state_dict.get("control_lock", False),     # 控制锁状态
        emergency_stop=state_dict.get("emergency_stop", False), # 紧急停止状态
        active_task=state_dict.get("active_task", None)         # 当前激活任务
    )

@router.get("/xr/status", response_model=XRStatusResponse, summary="获取XR设备状态")
async def get_xr_status(shared_state: SharedState = Depends(get_shared_state)):
    return XRStatusResponse(
        xr_active=shared_state.xr_status.xr_active,
        xr_web_connected=shared_state.xr_status.xr_web_connected,
        last_pose_time=shared_state.xr_status.last_pose_time,
        timeout=shared_state.xr_status.timeout
    )

@router.get("/tasks", response_model=TaskListResponse, summary="获取所有任务列表")
async def get_tasks(
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    tasks = dataset_manager.scan_tasks()
    return TaskListResponse(tasks=tasks, total_count=len(tasks))

@router.post("/tasks", response_model=TaskInfo, summary="创建新任务")
async def create_task(
    req: CreateTaskRequest,
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    task = dataset_manager.create_task(
        task_name=req.task_name,
        description=req.description,
        creator=req.creator
    )
    if task is None:
        raise HTTPException(status_code=500, detail="创建任务失败")
    return task

@router.get("/tasks/{task_id}", response_model=TaskInfo, summary="获取任务详情")
async def get_task(
    task_id: str,
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    task = dataset_manager.get_task_info(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task

@router.put("/tasks/{task_id}", response_model=TaskInfo, summary="编辑任务信息")
async def update_task(
    task_id: str,
    req: UpdateTaskRequest,
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    success = dataset_manager.update_task(task_id, req.task_name, req.description)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在或更新失败")
    task = dataset_manager.get_task_info(task_id)
    return task

@router.delete("/tasks/{task_id}", summary="删除任务(软删除到回收站)")
async def delete_task(
    task_id: str,
    shared_state: SharedState = Depends(get_shared_state),
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    # 检查是否是当前活动任务
    if shared_state.get_active_task() == task_id:
        raise HTTPException(status_code=409, detail="不能删除当前活动任务，请先切换任务")
    success = dataset_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"message": f"任务 {task_id} 已删除"}

@router.get("/active_task", summary="获取当前活动任务")
async def get_active_task(shared_state: SharedState = Depends(get_shared_state)):
    task_id = shared_state.get_active_task()
    if task_id is None:
        return {"active_task": None}
    # 极简只返回任务ID
    return {"active_task": task_id}

@router.post("/active_task", summary="设置当前活动任务")
async def set_active_task(
    req: SetActiveTaskRequest,
    shared_state: SharedState = Depends(get_shared_state),
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    # 检查任务是否存在
    task_info = dataset_manager.get_task_info(req.task_id)
    if task_info is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 检查是否正在录制（由 SharedState 内部判断）
    if not shared_state.set_active_task(req.task_id):
        raise HTTPException(status_code=409, detail="正在录制中，无法切换任务，请先停止录制")
    return {"message": f"活动任务已切换为 {req.task_id}", "active_task": req.task_id}

@router.post("/teleop/init_reset", summary="开机复位(首次复位)")
async def init_reset(shared_state: SharedState = Depends(get_shared_state)):
    """
    发送开机复位命令。
    该命令仅在系统处于 INACTIVE 状态时有效，
    用于完成机器人首次复位并进入待机状态。
    """
    shared_state.push_command(TeleopCommand.INIT_RESET)
    return {"message": "开机复位命令已发送"}

@router.post("/teleop/start", summary="启动遥操作")
async def start_teleop(shared_state: SharedState = Depends(get_shared_state)):
    shared_state.push_command(TeleopCommand.START_TELEOP)
    return {"message": "遥操作启动命令已发送"}

@router.post("/teleop/stop", summary="停止遥操作")
async def stop_teleop(shared_state: SharedState = Depends(get_shared_state)):
    shared_state.push_command(TeleopCommand.STOP_TELEOP)
    return {"message": "遥操作停止命令已发送"}

@router.post("/record/start", summary="开始录制")
async def start_record(
    request: StartRecordRequest,
    shared_state: SharedState = Depends(get_shared_state)
):
    shared_state.push_command(TeleopCommand.START_RECORD, {
        "task_info": request.task_info.dict() if request.task_info else None
    })
    return {"message": "录制启动命令已发送"}

@router.post("/record/stop", summary="停止录制")
async def stop_record(shared_state: SharedState = Depends(get_shared_state)):
    shared_state.push_command(TeleopCommand.STOP_RECORD)
    return {"message": "录制停止命令已发送"}

@router.post("/teleop/emergency_stop", summary="紧急停止机器人")
async def emergency_stop(shared_state: SharedState = Depends(get_shared_state)):
    """
    立即停止机器人所有运动，并触发回零。
    此命令无视当前控制源锁定，强制生效。
    """
    shared_state.push_command(TeleopCommand.EMERGENCY_STOP)
    return {"message": "紧急停止命令已发送"}

@router.post("/teleop/go_home", summary="机器人回零")
async def go_home(shared_state: SharedState = Depends(get_shared_state)):
    """
    使机器人双臂（及腰部/头部,若启用）回到 home 位置。
    如果在 ACTIVE_CONTROL 状态下，会自动释放控制权。
    """
    shared_state.push_command(TeleopCommand.GO_HOME)
    return {"message": "回零命令已发送"}

@router.get("/robot/joints", response_model=RobotJointsResponse, summary="获取机器人关节位置")
async def get_robot_joints(shared_state: SharedState = Depends(get_shared_state)):
    robot_status = shared_state.get_robot_status()
    return RobotJointsResponse(**robot_status)

@router.get("/control/status", summary="获取当前控制源状态")
async def get_control_status(shared_state: SharedState = Depends(get_shared_state)):
    return {
        "control_source": shared_state.get_control_source(),
        "control_lock": shared_state.control_lock,
        "emergency_stop": shared_state.emergency_stop_flag
    }

@router.get("/tasks/{task_id}/datasets", response_model=DatasetListResponse, summary="获取指定任务下的数据集列表")
async def get_task_datasets(
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    task_info = dataset_manager.get_task_info(task_id)
    if task_info is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    datasets = dataset_manager.scan_datasets(task_id=task_id)

    page_datasets = _paginate(datasets, page, page_size)
    
    return DatasetListResponse(
        datasets=page_datasets,
        total_count=len(datasets),
        page=page,
        page_size=page_size
    )

@router.get("/tasks/{task_id}/datasets/{episode_id}/frames", response_model=FramesResponse, summary="获取数据集的帧数据")
async def get_dataset_frames(
    task_id: str,
    episode_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    start_time: Optional[float] = Query(None),
    end_time: Optional[float] = Query(None),
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    try:
        frames, total_frames = dataset_manager.get_dataset_frames(
            task_id, episode_id, page, page_size, start_time, end_time
        )
        return FramesResponse(
            frames=frames,
            total_frames=total_frames,
            page=page,
            page_size=page_size
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取帧数据失败: {e}")
        raise HTTPException(status_code=500, detail="内部服务器错误")

@router.delete("/tasks/{task_id}/datasets/{episode_id}", summary="删除数据集(软删除到回收站)")
async def delete_dataset(
    task_id: str,
    episode_id: str,
    request: DeleteDatasetRequest,
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    if not request.confirm:
        raise HTTPException(status_code=400, detail="请确认删除操作")
    success = dataset_manager.soft_delete_dataset(task_id, episode_id)
    if not success:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return {"message": f"数据集 {task_id}/{episode_id} 已删除"}

@router.post("/tasks/{task_id}/datasets/{episode_id}/rebuild_index", response_model=RebuildIndexResponse, summary="重建索引文件")
async def rebuild_index(
    task_id: str,
    episode_id: str,
    dataset_manager: DatasetManager = Depends(get_dataset_manager)
):
    try:
        result = dataset_manager.rebuild_index(task_id, episode_id)
        return RebuildIndexResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"重建索引失败: {e}")
        raise HTTPException(status_code=500, detail="内部服务器错误")

# 导入导出端点

@router.post("/export", response_model=ExportTaskInfo, summary="创建导出任务")
async def create_export_task(
    request: ExportRequest,
    dataset_manager: DatasetManager = Depends(get_dataset_manager),
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    创建一个新的导出任务,将指定任务的所有数据集打包成指定格式的文件(支持zip或tar.gz)。
    """
    # 检查任务是否存在
    task_info = dataset_manager.get_task_info(request.task_id)
    if task_info is None:
        raise HTTPException(status_code=404, detail=f"任务 {request.task_id} 不存在")
    
    try:
        export_task = await dataset_io_manager.create_export_task(request.task_id, request.format)
        return export_task
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建导出任务失败: {e}")
        raise HTTPException(status_code=500, detail="创建导出任务失败")

@router.get("/export/tasks", response_model=ExportTaskListResponse, summary="获取导出任务列表")
async def get_export_tasks(
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    获取所有导出任务的任务列表。
    """
    export_tasks = dataset_io_manager.list_export_tasks()
    return ExportTaskListResponse(
        tasks=export_tasks,
        total_count=len(export_tasks)
    )

@router.get("/export/{export_id}", response_model=ExportTaskInfo, summary="获取导出任务详情")
async def get_export_task(
    export_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    获取指定导出任务的详细信息。
    """
    export_task_info = dataset_io_manager.get_export_task(export_id)
    if export_task_info is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {export_id} 不存在")
    return export_task_info

@router.get("/export/{export_id}/status", response_model=ExportStatusResponse, summary="获取导出状态")
async def get_export_status(
    export_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    获取指定导出任务的当前状态和进度。
    """
    export_task_info = dataset_io_manager.get_export_task(export_id)
    if export_task_info is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {export_id} 不存在")
    
    status, progress = dataset_io_manager.get_export_status(export_id)
    return ExportStatusResponse(
        export_id=export_id,
        status=status,
        progress=progress,
        file_size=export_task_info.file_size,
        episode_count=export_task_info.episode_count,
        created_time=export_task_info.created_time,
        completed_time=export_task_info.completed_time,
        error_message=export_task_info.error_message,
        retry_suggestion=export_task_info.retry_suggestion
    )

@router.get("/export/{export_id}/download", summary="下载导出文件")
async def download_export_file(
    export_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    下载导出任务的文件。
    """
    task = dataset_io_manager.get_export_task(export_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {export_id} 不存在")
    
    if task.status != ExportStatus.READY:
        raise HTTPException(status_code=400, detail=f"导出任务状态为 {task.status}，无法下载")
    
    file_path = task.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="导出文件不存在")
    
    # 更新下载计数
    dataset_io_manager.increment_download_count(export_id)
    
    # 返回文件
    filename = os.path.basename(file_path)
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/zip" if task.format == "zip" else "application/tar.gz"
    )

@router.post("/export/{export_id}/confirm", summary="确认下载完成")
async def confirm_export_download(
    export_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    确认已成功下载导出文件,系统将在30分钟后自动清理该文件。
    """
    task = dataset_io_manager.get_export_task(export_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {export_id} 不存在")
    
    if task.status != ExportStatus.READY:
        raise HTTPException(status_code=400, detail=f"导出任务状态为 {task.status}，无法确认")
    
    success = dataset_io_manager.confirm_export_download(export_id)
    if not success:
        raise HTTPException(status_code=400, detail="确认失败")
    
    return {"message": f"导出任务 {export_id} 已确认,将在30分钟后自动清理"}

@router.delete("/export/{export_id}", summary="取消导出任务")
async def cancel_export_task(
    export_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    取消正在进行的导出任务，并清理相关文件。
    """
    task = dataset_io_manager.get_export_task(export_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {export_id} 不存在")
    
    if task.status in [ExportStatus.READY, ExportStatus.CONFIRMED]:
        raise HTTPException(status_code=400, detail="任务已完成，无法取消")
    
    success = dataset_io_manager.cancel_export_task(export_id)
    if not success:
        raise HTTPException(status_code=400, detail="取消失败")
    
    return {"message": f"导出任务 {export_id} 已取消"}

@router.post("/import", response_model=ImportTaskInfo, summary="上传并创建导入任务")
async def create_import_task(
    file: UploadFile = File(..., description="要导入的zip或tar.gz文件"),
    task_name: str = Form(..., description="导入后的任务名称，必填"),
    description: str = Form(default="这是一个默认任务描述", description="导入后的任务描述"),
    creator: str = Form(default="系统用户", description="导入后的创建者"),
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    上传zip或tar.gz文件并创建导入任务,将数据集导入到系统中。
    需要传入 task_name(必填)、description、creator 作为导入后任务的基本信息。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if not (file.filename.endswith('.zip') or file.filename.endswith('.tar.gz')):
        raise HTTPException(status_code=400, detail="只支持zip或tar.gz格式的文件")
    
    MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024
    file_suffix = '.zip' if file.filename.endswith('.zip') else '.tar.gz'

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=file_suffix,
        dir=str(dataset_io_manager.import_dir)
    )
    os.close(temp_fd)
    
    try:
        file_size = 0
        async with aiofiles.open(temp_path, 'wb') as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail="文件大小超过限制(最大10GB)"
                    )
                await f.write(chunk)

        import_task = await dataset_io_manager.create_import_task(
            file.filename,
            file_size,
            temp_path,
            task_name=task_name,
            description=description,
            creator=creator
        )
        return import_task
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"创建导入任务失败: {e}")
        raise HTTPException(status_code=500, detail="创建导入任务失败")

@router.get("/import/tasks", response_model=List[ImportTaskInfo], summary="获取导入任务列表")
async def get_import_tasks(
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    获取所有导入任务的列表。
    """
    import_tasks = dataset_io_manager.get_import_tasks()
    return import_tasks

@router.get("/import/{import_id}", response_model=ImportTaskInfo, summary="获取导入任务详情")
async def get_import_task(
    import_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    获取指定导入任务的详细信息。
    """
    detail_import_task = dataset_io_manager.get_import_task()
    if detail_import_task is None or detail_import_task.import_id != import_id:
        raise HTTPException(status_code=404, detail=f"导入任务 {import_id} 不存在")
    return detail_import_task

@router.get("/import/{import_id}/status", response_model=ImportStatusResponse, summary="获取导入状态")
async def get_import_status(
    import_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    获取指定导入任务的当前状态和进度。
    """
    task = dataset_io_manager.get_import_task()
    if task is None or task.import_id != import_id:
        raise HTTPException(status_code=404, detail=f"导入任务 {import_id} 不存在")
    
    status, progress = dataset_io_manager.get_import_status(import_id)
    return ImportStatusResponse(
        import_id=import_id,
        status=status,
        progress=progress,
        file_name=task.file_name,
        file_size=task.file_size,
        episode_count=task.episode_count,
        target_task_id=task.target_task_id,
        created_time=task.created_time,
        completed_time=task.completed_time,
        error_message=task.error_message,
        retry_suggestion=task.retry_suggestion
    )

@router.delete("/import/{import_id}", summary="取消导入任务")
async def cancel_import_task(
    import_id: str,
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    取消正在进行的导入任务，并清理相关文件。
    """
    task = dataset_io_manager.get_import_task()
    if task is None:
        raise HTTPException(status_code=404, detail=f"导入任务 {import_id} 不存在")
    
    if task.status == ImportStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务已完成，无法取消")
    
    success = dataset_io_manager.cancel_import(import_id)
    if not success:
        raise HTTPException(status_code=400, detail="取消失败")
    
    return {"message": f"导入任务 {import_id} 已取消"}

@router.get("/import_export/stats", response_model=ImportExportStatistics, summary="获取导入导出统计信息")
async def get_import_export_stats(
    dataset_io_manager: DatasetIOManager = Depends(get_dataset_io_manager)
):
    """
    获取导入导出相关的统计信息，包括任务数量、磁盘使用情况等。
    """
    stats = dataset_io_manager.get_statistics()
    return ImportExportStatistics(**stats)

# 相机管理端点
@router.get("/cameras/discover", summary="发现相机设备")
async def discover_cameras(shared_state: SharedState = Depends(get_shared_state)):
    """
    触发图像服务端重新扫描硬件，返回所有可用相机设备列表。
    """
    try:
        mgr = _get_camera_manager(shared_state)
        result = mgr.discover_cameras()
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"发现相机失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cameras/active", summary="获取当前已启动的相机")
async def get_active_cameras(shared_state: SharedState = Depends(get_shared_state)):
    """
    获取图像服务端当前已启动的相机列表及其配置。
    """
    try:
        mgr = _get_camera_manager(shared_state)
        result = mgr.get_active_cameras()
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取活跃相机失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cameras/add", summary="添加并启动相机")
async def add_camera(
    req: CameraAddRequest,
    shared_state: SharedState = Depends(get_shared_state)
):
    """
    根据用户选择的设备和参数，动态添加并启动相机。
    """
    camera_config = {
        "camera_type": req.camera_type,
        "model": req.model,
        "serial_number": req.serial_number,
        "device_index": req.device_index,
        "position": req.position,
        "enabled": req.enabled,
        "binocular": req.binocular,
        "streams": {
            "color": {
                "enabled": req.color_enabled,
                "capture_width": req.color_width,
                "capture_height": req.color_height,
                "publish_width": req.color_width,
                "publish_height": req.color_height,
                "fps": req.color_fps
            },
            "depth": {
                "enabled": req.depth_enabled,
                "capture_width": req.depth_width,
                "capture_height": req.depth_height,
                "publish_width": req.depth_width,
                "publish_height": req.depth_height,
                "fps": req.depth_fps
            }
        },
        "compression": {
            "rgb": {
                "quality": req.rgb_compress_quality,
                "format": req.rgb_compress_format
                },
            "depth": {
                "quantization_bits": req.depth_compress_quantization_bits,
                "zstd_compression_level": req.depth_zstd_compress_level
                }
        },
        "communication": {
            'zeromq': {
                'enabled': req.communication_enable_zmq,
                'image_publish_port': req.communication_zmq_image_port,
                'status_publish_port': req.communication_zmq_status_port
            },
            'websocket': {
                'enabled': req.communication_enable_websocket,
                'host': req.communication_websocket_host,
                'port': req.communication_websocket_port
            },
            'webrtc': {
                'enabled': req.communication_enable_webrtc,
                'video_codec': req.communication_webrtc_video_codec
            }
        }
    }

    publisher_compression: Dict[str, Any] = {}
    zmq_pub: Dict[str, Any] = {}
    if req.publisher_zmq_rgb_compress_quality is not None:
        zmq_pub.setdefault("rgb", {})["quality"] = req.publisher_zmq_rgb_compress_quality
    if req.publisher_zmq_rgb_compress_format is not None:
        zmq_pub.setdefault("rgb", {})["format"] = req.publisher_zmq_rgb_compress_format
    if req.publisher_zmq_depth_compress_quantization_bits is not None:
        zmq_pub.setdefault("depth", {})["quantization_bits"] = req.publisher_zmq_depth_compress_quantization_bits
    if req.publisher_zmq_depth_zstd_compress_level is not None:
        zmq_pub.setdefault("depth", {})["zstd_compression_level"] = req.publisher_zmq_depth_zstd_compress_level
    if zmq_pub:
        publisher_compression["zeromq"] = zmq_pub

    webrtc_pub: Dict[str, Any] = {}
    if req.publisher_webrtc_rgb_compress_quality is not None:
        webrtc_pub.setdefault("rgb", {})["quality"] = req.publisher_webrtc_rgb_compress_quality
    if req.publisher_webrtc_rgb_compress_format is not None:
        webrtc_pub.setdefault("rgb", {})["format"] = req.publisher_webrtc_rgb_compress_format
    if webrtc_pub:
        publisher_compression["webrtc"] = webrtc_pub

    if publisher_compression:
        camera_config["publisher_compression"] = publisher_compression

    try:
        mgr = _get_camera_manager(shared_state)
        result = mgr.add_camera(req.camera_id, camera_config)
        shared_state.push_command(TeleopCommand.REFRESH_CAMERA_CONFIG)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return {"message": f"相机 {req.camera_id} 添加请求已发送", "detail": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"添加相机失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/cameras/remove", summary="移除并停止相机")
async def remove_camera(
    req: CameraRemoveRequest,
    shared_state: SharedState = Depends(get_shared_state)
):
    """
    停止并移除指定的相机。
    """
    try:
        mgr = _get_camera_manager(shared_state)
        result = mgr.remove_camera(req.camera_id)
        shared_state.push_command(TeleopCommand.REFRESH_CAMERA_CONFIG)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return {"message": f"相机 {req.camera_id} 移除请求已发送", "detail": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"移除相机失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 

@router.put("/cameras/update", summary="更新相机配置")
async def update_camera(
    req: CameraUpdateRequest,
    shared_state: SharedState = Depends(get_shared_state)
):
    """
    更新指定相机的配置
    仅传递用户实际提供的字段(非None),未提供的字段沿用原有配置,更新需符合相机配置规范。
    """
    camera_config: Dict[str, Any] = {}

    if req.camera_type is not None:
        camera_config["camera_type"] = req.camera_type
    if req.model is not None:
        camera_config["model"] = req.model
    if req.serial_number is not None:
        camera_config["serial_number"] = req.serial_number
    if req.device_index is not None:
        camera_config["device_index"] = req.device_index
    if req.position is not None:
        camera_config["position"] = req.position
    if req.enabled is not None:
        camera_config["enabled"] = req.enabled
    if req.binocular is not None:
        camera_config["binocular"] = req.binocular

    streams: Dict[str, Any] = {}
    color_stream: Dict[str, Any] = {}
    depth_stream: Dict[str, Any] = {}
    if req.color_enabled is not None:
        color_stream["enabled"] = req.color_enabled
    if req.depth_enabled is not None:
        depth_stream["enabled"] = req.depth_enabled
    if req.color_width is not None:
        color_stream["capture_width"] = req.color_width
        color_stream["publish_width"] = req.color_width
    if req.color_height is not None:
        color_stream["capture_height"] = req.color_height
        color_stream["publish_height"] = req.color_height
    if req.color_fps is not None:
        color_stream["fps"] = req.color_fps
    if req.depth_width is not None:
        depth_stream["capture_width"] = req.depth_width
        depth_stream["publish_width"] = req.depth_width
    if req.depth_height is not None:
        depth_stream["capture_height"] = req.depth_height
        depth_stream["publish_height"] = req.depth_height
    if req.depth_fps is not None:
        depth_stream["fps"] = req.depth_fps
    if color_stream:
        streams["color"] = color_stream
    if depth_stream:
        streams["depth"] = depth_stream
    if streams:
        camera_config["streams"] = streams

    compression: Dict[str, Any] = {}
    rgb_comp: Dict[str, Any] = {}
    depth_comp: Dict[str, Any] = {}
    if req.rgb_compress_quality is not None:
        rgb_comp["quality"] = req.rgb_compress_quality
    if req.rgb_compress_format is not None:
        rgb_comp["format"] = req.rgb_compress_format
    if req.depth_compress_quantization_bits is not None:
        depth_comp["quantization_bits"] = req.depth_compress_quantization_bits
    if req.depth_zstd_compress_level is not None:
        depth_comp["zstd_compression_level"] = req.depth_zstd_compress_level
    if rgb_comp:
        compression["rgb"] = rgb_comp
    if depth_comp:
        compression["depth"] = depth_comp
    if compression:
        camera_config["compression"] = compression

    publisher_compression: Dict[str, Any] = {}
    zmq_pub: Dict[str, Any] = {}
    zmq_pub_rgb: Dict[str, Any] = {}
    zmq_pub_depth: Dict[str, Any] = {}
    if req.publisher_zmq_rgb_compress_quality is not None:
        zmq_pub_rgb["quality"] = req.publisher_zmq_rgb_compress_quality
    if req.publisher_zmq_rgb_compress_format is not None:
        zmq_pub_rgb["format"] = req.publisher_zmq_rgb_compress_format
    if req.publisher_zmq_depth_compress_quantization_bits is not None:
        zmq_pub_depth["quantization_bits"] = req.publisher_zmq_depth_compress_quantization_bits
    if req.publisher_zmq_depth_zstd_compress_level is not None:
        zmq_pub_depth["zstd_compression_level"] = req.publisher_zmq_depth_zstd_compress_level
    if zmq_pub_rgb:
        zmq_pub["rgb"] = zmq_pub_rgb
    if zmq_pub_depth:
        zmq_pub["depth"] = zmq_pub_depth
    if zmq_pub:
        publisher_compression["zeromq"] = zmq_pub

    webrtc_pub: Dict[str, Any] = {}
    webrtc_pub_rgb: Dict[str, Any] = {}
    if req.publisher_webrtc_rgb_compress_quality is not None:
        webrtc_pub_rgb["quality"] = req.publisher_webrtc_rgb_compress_quality
    if req.publisher_webrtc_rgb_compress_format is not None:
        webrtc_pub_rgb["format"] = req.publisher_webrtc_rgb_compress_format
    if webrtc_pub_rgb:
        webrtc_pub["rgb"] = webrtc_pub_rgb
    if webrtc_pub:
        publisher_compression["webrtc"] = webrtc_pub
    if publisher_compression:
        camera_config["publisher_compression"] = publisher_compression

    communication: Dict[str, Any] = {}
    zmq_comm: Dict[str, Any] = {}
    if req.communication_enable_zmq is not None:
        zmq_comm["enabled"] = req.communication_enable_zmq
    if req.communication_zmq_image_port is not None:
        zmq_comm["image_publish_port"] = req.communication_zmq_image_port
    if req.communication_zmq_status_port is not None:
        zmq_comm["status_publish_port"] = req.communication_zmq_status_port
    if zmq_comm:
        communication["zeromq"] = zmq_comm

    ws_comm: Dict[str, Any] = {}
    if req.communication_enable_websocket is not None:
        ws_comm["enabled"] = req.communication_enable_websocket
    if req.communication_websocket_host is not None:
        ws_comm["host"] = req.communication_websocket_host
    if req.communication_websocket_port is not None:
        ws_comm["port"] = req.communication_websocket_port
    if ws_comm:
        communication["websocket"] = ws_comm

    webrtc_comm: Dict[str, Any] = {}
    if req.communication_enable_webrtc is not None:
        webrtc_comm["enabled"] = req.communication_enable_webrtc
    if req.communication_webrtc_video_codec is not None:
        webrtc_comm["video_codec"] = req.communication_webrtc_video_codec
    if webrtc_comm:
        communication["webrtc"] = webrtc_comm
    if communication:
        camera_config["communication"] = communication

    try:
        mgr = _get_camera_manager(shared_state)
        result = mgr.update_camera(req.camera_id, camera_config)
        shared_state.push_command(TeleopCommand.REFRESH_CAMERA_CONFIG)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return {"message": f"相机 {req.camera_id} 更新请求已发送", "detail": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"更新相机失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
def _get_camera_manager(shared_state: SharedState) -> CameraManager:
    """从 SharedState 获取 CameraManager,若未初始化则抛出异常"""
    mgr = shared_state.camera_manager
    if mgr is None:
        raise HTTPException(status_code=503, detail="CameraManager 未初始化")
    return mgr
