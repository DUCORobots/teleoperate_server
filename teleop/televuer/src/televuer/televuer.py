from vuer.server import Vuer
from vuer.schemas import ImageBackground, Hands, MotionControllers, WebRTCVideoPlane, WebRTCStereoVideoPlane
from multiprocessing import Value, Array, Process, shared_memory
import numpy as np
import asyncio
import threading
import time
import cv2
import os
import socket
from pathlib import Path
from typing import Literal
from teleop.log_manager import get_logger

_logger = get_logger(__name__)

class TeleVuer:
    def __init__(self, use_hand_tracking: bool, binocular: bool=True, img_shape: tuple=None, display_fps: float=30.0,
                       display_mode: Literal["immersive", "pass-through", "ego"]="immersive", zmq: bool=False, webrtc: bool=False, webrtc_url: str=None, 
                       cert_file: str=None, key_file: str=None,
                       stun_servers=None):
        """
        `TeleVuer` 是 XR 遥操作界面的底层封装

        主要职责：
        - 管理与 Vuer 服务端的通信；
        - 接收头部、手柄、手部跟踪姿态；
        - 在需要时将机器人图像推送到 XR 端显示。

        参数说明：
        - `use_hand_tracking`:"是否使用手部跟踪模式,True=手部跟踪控制, False=手柄控制,注意手部当前仅为占位实现；
        - `binocular`:"头部图像是否为双目拼接图,True=双目图像(VR立体视觉), False=单目；
        - `img_shape`:"头部图像尺寸 `(W, H)`;
        - `display_fps`:"XR 端目标显示帧率；
        - `display_mode`:"显示模式，可选 `"immersive"`、`"pass-through"`、`"ego"`;
        - `zmq`:"是否使用 ZMQ 推送图像；
        - `webrtc`:"是否使用 WebRTC 推送图像；
        - `webrtc_url`:"WebRTC 信令地址，启用时必须提供；
        - `cert_file` / `key_file`:"HTTPS 所需证书路径。

        显示模式说明：
        - `immersive`:"XR 全屏显示机器人视角；
        - `pass-through`:"XR 显示头显透视画面，不叠加机器人图像；
        - `ego`:"XR 中央小窗显示机器人视角，周围保留真实环境透视。

        约定：
        - 图像通道同一时刻只会启用一种；
        - 只有 `immersive` 或 `ego` 模式才会真正向 XR 推图；
        - 若 `zmq` 和 `webrtc` 同时启用，优先使用 `webrtc`。
        """
        # 基础配置
        self.use_hand_tracking = use_hand_tracking
        self.binocular = binocular
        if img_shape is None:
            raise ValueError("[TeleVuer] img_shape must be provided.")
        self.img_shape = (img_shape[0], img_shape[1], 3)  # 图像格式(W,H,3通道)
        self.display_fps = display_fps
        self.img_height = self.img_shape[1]

        self.stun_servers = stun_servers or ["stun:stun.l.google.com:19302"]
        # 双目图像：宽度拆分左右眼
        if self.binocular:
            self.img_width  = self.img_shape[0] // 2
        else:
            self.img_width  = self.img_shape[0]
        self.aspect_ratio = self.img_width / self.img_height

        # 自动加载HTTPS证书(VR连接必须)，证书路径解析顺序：环境变量 -> 用户配置目录 -> 包内默认文件。
        env_cert = os.getenv("XR_TELEOP_CERT")
        env_key = os.getenv("XR_TELEOP_KEY")
        if cert_file is None or key_file is None:
            # 1. 优先读取环境变量。
            if env_cert and env_key:
                cert_file = cert_file or env_cert
                key_file = key_file or env_key
            else:
                # 2. 尝试读取用户目录中的证书。
                user_conf_dir = Path.home() / ".config" / "xr_teleoperate"
                cert_path_user = user_conf_dir / "cert.pem"
                key_path_user = user_conf_dir / "key.pem"

                if cert_path_user.exists() and key_path_user.exists():
                    cert_file = cert_file or str(cert_path_user)
                    key_file = key_file or str(key_path_user)
                else:
                    # 3. 最后回退到包内默认证书。
                    current_module_dir = Path(__file__).resolve().parent.parent.parent
                    cert_file = cert_file or str(current_module_dir / "cert.pem")
                    key_file = key_file or str(current_module_dir / "key.pem")

        # 初始化Vuer服务(监听所有IP, HTTPS加密)
        self.vuer = Vuer(host='0.0.0.0', cert=cert_file, key=key_file, queries=dict(grid=False), queue_len=3)
        # 注册事件处理器：相机(头部)移动
        self.vuer.add_handler("CAMERA_MOVE")(self.on_cam_move)
        # 注册事件处理器：手部/手柄移动
        if self.use_hand_tracking:
            self.vuer.add_handler("HAND_MOVE")(self.on_hand_move)
        else:
            self.vuer.add_handler("CONTROLLER_MOVE")(self.on_controller_move)

        # 显示模式+传输协议配置
        self.display_mode = display_mode
        self.zmq = zmq
        self.webrtc = webrtc
        self.webrtc_url = webrtc_url

        # 根据显示模式选择渲染函数(沉浸式/小窗/透视)
        if self.display_mode == "immersive":
           # 是否启用WebRTC传输
            if self.webrtc:
                fn = self.main_image_binocular_webrtc if self.binocular else self.main_image_monocular_webrtc
            elif self.zmq:
                self.img2display_shm = shared_memory.SharedMemory(create=True, size=np.prod(self.img_shape) * np.uint8().itemsize)
                self.img2display = np.ndarray(self.img_shape, dtype=np.uint8, buffer=self.img2display_shm.buf)
                self.latest_frame = None
                self.new_frame_event = threading.Event()
                self.stop_writer_event = threading.Event()
                self.writer_thread = threading.Thread(target=self._xr_render_loop, daemon=True)
                self.writer_thread.start()
                fn = self.main_image_binocular_zmq if self.binocular else self.main_image_monocular_zmq
            else:
                raise ValueError("[TeleVuer] immersive mode requires zmq=True or webrtc=True.")
        elif self.display_mode == "ego":
            if self.webrtc:
                fn = self.main_image_binocular_webrtc_ego if self.binocular else self.main_image_monocular_webrtc_ego
            elif self.zmq:
                self.img2display_shm = shared_memory.SharedMemory(create=True, size=np.prod(self.img_shape) * np.uint8().itemsize)
                self.img2display = np.ndarray(self.img_shape, dtype=np.uint8, buffer=self.img2display_shm.buf)
                self.latest_frame = None
                self.new_frame_event = threading.Event()
                self.stop_writer_event = threading.Event()
                self.writer_thread = threading.Thread(target=self._xr_render_loop, daemon=True)
                self.writer_thread.start()
                fn = self.main_image_binocular_zmq_ego if self.binocular else self.main_image_monocular_zmq_ego
            else:
                raise ValueError("[TeleVuer] ego mode requires zmq=True or webrtc=True.")
        elif self.display_mode == "pass-through":
            fn = self.main_pass_through
        else:
            raise ValueError(f"[TeleVuer] Unknown display_mode: {self.display_mode}")
        
        self.vuer.spawn(start=False)(fn)

        # 头部/手臂位姿矩阵(4x4展平为16位数组)
        self.head_pose_shared = Array('d', 16, lock=True)
        self.left_arm_pose_shared = Array('d', 16, lock=True)
        self.right_arm_pose_shared = Array('d', 16, lock=True)
        
        # 手部跟踪模式：25个关键点位置/方向/捏合/握紧状态
        if self.use_hand_tracking:
            self.left_hand_position_shared = Array('d', 75, lock=True)
            self.right_hand_position_shared = Array('d', 75, lock=True)
            self.left_hand_orientation_shared = Array('d', 25 * 9, lock=True)
            self.right_hand_orientation_shared = Array('d', 25 * 9, lock=True)

            self.left_hand_pinch_shared = Value('b', False, lock=True)
            self.left_hand_pinchValue_shared = Value('d', 0.0, lock=True)
            self.left_hand_squeeze_shared = Value('b', False, lock=True)
            self.left_hand_squeezeValue_shared = Value('d', 0.0, lock=True)

            self.right_hand_pinch_shared = Value('b', False, lock=True)
            self.right_hand_pinchValue_shared = Value('d', 0.0, lock=True)
            self.right_hand_squeeze_shared = Value('b', False, lock=True)
            self.right_hand_squeezeValue_shared = Value('d', 0.0, lock=True)
        # 手柄控制模式：扳机/握持/摇杆/A/B键状态
        else:
            self.left_ctrl_trigger_shared = Value('b', False, lock=True)
            self.left_ctrl_triggerValue_shared = Value('d', 0.0, lock=True)
            self.left_ctrl_squeeze_shared = Value('b', False, lock=True)
            self.left_ctrl_squeezeValue_shared = Value('d', 0.0, lock=True)
            self.left_ctrl_thumbstick_shared = Value('b', False, lock=True)
            self.left_ctrl_thumbstickValue_shared = Array('d', 2, lock=True)
            self.left_ctrl_aButton_shared = Value('b', False, lock=True)
            self.left_ctrl_bButton_shared = Value('b', False, lock=True)

            self.right_ctrl_trigger_shared = Value('b', False, lock=True)
            self.right_ctrl_triggerValue_shared = Value('d', 0.0, lock=True)
            self.right_ctrl_squeeze_shared = Value('b', False, lock=True)
            self.right_ctrl_squeezeValue_shared = Value('d', 0.0, lock=True)
            self.right_ctrl_thumbstick_shared = Value('b', False, lock=True)
            self.right_ctrl_thumbstickValue_shared = Array('d', 2, lock=True)
            self.right_ctrl_aButton_shared = Value('b', False, lock=True)
            self.right_ctrl_bButton_shared = Value('b', False, lock=True)

        self._last_pose_time_shared = Value('d', 0.0, lock=True)   # 最后收到任意移动事件的时间戳
        self._xr_has_received_event_shared = Value('b', False, lock=True)  # 是否至少收到过一次有效移动事件
        self._active_session = None                                # 保存当前活跃的 session 引用(只在 vuer 进程内使用)
        self._xr_web_connected_shared = Value('b', False, lock=True)  # 网页是否连接的标志(WebSocket 存活)

        # 启动独立进程运行VR服务(不阻塞主程序)
        self.process = Process(target=self._vuer_run)
        self.process.daemon = True
        self.process.start()

    def _vuer_run(self):
        """VR服务独立进程入口"""
        try:
            self.vuer.run()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            _logger.exception(f"Vuer 运行异常: {e}")
        finally:
            if hasattr(self, "stop_writer_event"):
                self.stop_writer_event.set()

    def _xr_render_loop(self):
        """ZMQ模式:图像渲染线程(共享内存写图像)"""
        while not self.stop_writer_event.is_set():
            if not self.new_frame_event.wait(timeout=0.1):
                continue
            self.new_frame_event.clear()
            if self.latest_frame is None:
                continue
            # BGR转RGB（VR显示标准），写入共享内存
            latest_frame = self.latest_frame
            latest_frame = cv2.cvtColor(latest_frame, cv2.COLOR_BGR2RGB)
            self.img2display[:] = latest_frame

    def render_to_xr(self, image):
        """对外接口:将机器人图像推送到VR"""
        if self.webrtc or self.display_mode == "pass-through":
            _logger.debug("当前启用了 WebRTC 或透视模式，忽略 `render_to_xr` 调用。")
            return
        self.latest_frame = image
        self.new_frame_event.set()

    def close(self):
        """关闭VR服务、线程、共享内存"""
        self.process.terminate()
        self.process.join(timeout=2.0)
        if self.display_mode in ("immersive", "ego") and not self.webrtc:
            self.stop_writer_event.set()
            self.new_frame_event.set()
            self.writer_thread.join(timeout=2.0)
            try:
                self.img2display_shm.close()
                self.img2display_shm.unlink()
            except Exception:
                pass

    def _configure_session_tcp_timeout(self, session):
        try:
            ws_socket = session.socket
            sock = ws_socket._req.transport.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 8000)
                _logger.debug("TCP_USER_TIMEOUT set to 8s")
        except Exception as e:
            _logger.debug(f"TCP_USER_TIMEOUT set failed: {e}")

    def _update_connection_heartbeat(self):
        """在收到任何移动事件时调用，更新最后活跃时间和事件接收标志"""
        with self._last_pose_time_shared.get_lock():
            self._last_pose_time_shared.value = time.time()
        with self._xr_has_received_event_shared.get_lock():
            self._xr_has_received_event_shared.value = True

    # 事件处理器:接收VR头显数据
    async def on_cam_move(self, event, session, fps=60):
        """接收头部姿态数据，写入共享内存，并更新心跳"""
        try:
            with self.head_pose_shared.get_lock():
                self.head_pose_shared[:] = event.value["camera"]["matrix"]
            self._update_connection_heartbeat()
        except Exception:
            pass

    async def on_controller_move(self, event, session, fps=60):
        """接收处理手柄模式下的姿态和按钮输入，写入共享内存"""
        try:
            # 先读取左右控制器位姿。
            with self.left_arm_pose_shared.get_lock():
                self.left_arm_pose_shared[:] = event.value["left"]
            with self.right_arm_pose_shared.get_lock():
                self.right_arm_pose_shared[:] = event.value["right"]
            # 再读取按钮和模拟量状态。
            left_controller = event.value["leftState"]
            right_controller = event.value["rightState"]

            def extract_controllers(controllerState, prefix):
                # 扳机键状态
                with getattr(self, f"{prefix}_ctrl_trigger_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_trigger_shared").value = bool(controllerState.get("trigger", False))
                with getattr(self, f"{prefix}_ctrl_triggerValue_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_triggerValue_shared").value = float(controllerState.get("triggerValue", 0.0))
                # 握持键状态
                with getattr(self, f"{prefix}_ctrl_squeeze_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_squeeze_shared").value = bool(controllerState.get("squeeze", False))
                with getattr(self, f"{prefix}_ctrl_squeezeValue_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_squeezeValue_shared").value = float(controllerState.get("squeezeValue", 0.0))
                # 摇杆状态
                with getattr(self, f"{prefix}_ctrl_thumbstick_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_thumbstick_shared").value = bool(controllerState.get("thumbstick", False))
                with getattr(self, f"{prefix}_ctrl_thumbstickValue_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_thumbstickValue_shared")[:] = controllerState.get("thumbstickValue", [0.0, 0.0])
                # A/B 按钮状态
                with getattr(self, f"{prefix}_ctrl_aButton_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_aButton_shared").value = bool(controllerState.get("aButton", False))
                with getattr(self, f"{prefix}_ctrl_bButton_shared").get_lock():
                    getattr(self, f"{prefix}_ctrl_bButton_shared").value = bool(controllerState.get("bButton", False))

            extract_controllers(left_controller, "left")
            extract_controllers(right_controller, "right")

            self._update_connection_heartbeat()
        except Exception:
            pass

    async def on_hand_move(self, event, session, fps=60):
        """处理手部跟踪模式下的关键点与捏合/握紧状态(25个关键点+捏合/握紧)，写入共享内存"""
        try:
            # 读取左右手关键点原始数据。
            left_hand_data = event.value["left"]
            right_hand_data = event.value["right"]
            left_hand = event.value["leftState"]
            right_hand = event.value["rightState"]
            # 再拆出手势状态量。
            def extract_hand_poses(hand_data, arm_pose_shared, hand_position_shared, hand_orientation_shared):
                with arm_pose_shared.get_lock():
                    arm_pose_shared[:] = hand_data[0:16]

                with hand_position_shared.get_lock():
                    for i in range(25):
                        base = i * 16
                        hand_position_shared[i * 3: i * 3 + 3] = [hand_data[base + 12], hand_data[base + 13], hand_data[base + 14]]

                with hand_orientation_shared.get_lock():
                    for i in range(25):
                        base = i * 16
                        hand_orientation_shared[i * 9: i * 9 + 9] = [
                            hand_data[base + 0], hand_data[base + 1], hand_data[base + 2],
                            hand_data[base + 4], hand_data[base + 5], hand_data[base + 6],
                            hand_data[base + 8], hand_data[base + 9], hand_data[base + 10],
                        ]

            def extract_hands(handState, prefix):
                # 捏合状态
                with getattr(self, f"{prefix}_hand_pinch_shared").get_lock():
                    getattr(self, f"{prefix}_hand_pinch_shared").value = bool(handState.get("pinch", False))
                with getattr(self, f"{prefix}_hand_pinchValue_shared").get_lock():
                    getattr(self, f"{prefix}_hand_pinchValue_shared").value = float(handState.get("pinchValue", 0.0))
                # 握紧状态
                with getattr(self, f"{prefix}_hand_squeeze_shared").get_lock():
                    getattr(self, f"{prefix}_hand_squeeze_shared").value = bool(handState.get("squeeze", False))
                with getattr(self, f"{prefix}_hand_squeezeValue_shared").get_lock():
                    getattr(self, f"{prefix}_hand_squeezeValue_shared").value = float(handState.get("squeezeValue", 0.0))

            extract_hand_poses(left_hand_data, self.left_arm_pose_shared, self.left_hand_position_shared, self.left_hand_orientation_shared)
            extract_hand_poses(right_hand_data, self.right_arm_pose_shared, self.right_hand_position_shared, self.right_hand_orientation_shared)
            extract_hands(left_hand, "left")
            extract_hands(right_hand, "right")

            self._update_connection_heartbeat()
        except Exception:
            pass
    
    # VR 渲染函数：沉浸式/小窗/透视
    async def main_image_binocular_zmq(self, session):
        # 保存当前活跃的 session 引用
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            # 渲染手柄/手部模型
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True,
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )
            # 循环推送左右眼图像
            while True:
                session.upsert(
                    [
                        ImageBackground(
                            self.img2display[:, :self.img_width],
                            aspect=self.aspect_ratio,
                            height=1,
                            distanceToCamera=1,
                            # 渲染层使用二进制位掩码区分左右眼。
                            # 这里左图层为 1，右图层为 2，对应左右眼相机。
                            layers=1,
                            format="jpeg",
                            quality=80,
                            key="background-left",
                            interpolate=True,
                        ),
                        ImageBackground(
                            self.img2display[:, self.img_width:],
                            aspect=self.aspect_ratio,
                            height=1,
                            distanceToCamera=1,
                            layers=2,
                            format="jpeg",
                            quality=80,
                            key="background-right",
                            interpolate=True,
                        ),
                    ],
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        finally:
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_image_monocular_zmq(self, session):
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True, 
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )

            while True:
                session.upsert(
                    [
                        ImageBackground(
                            self.img2display,
                            aspect=self.aspect_ratio,
                            height=1,
                            distanceToCamera=1,
                            format="jpeg",
                            quality=80,
                            key="background-mono",
                            interpolate=True,
                        ),
                    ],
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        finally:
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_image_binocular_webrtc(self, session):
        # 保存当前活跃的 session 引用
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            # 双目图像 WebRTC 沉浸式显示模式
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True, 
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )

            while True:
                session.upsert(
                    WebRTCStereoVideoPlane(
                        src=self.webrtc_url,
                        iceServer=None,
                        iceServers=[{"urls": server} for server in self.stun_servers],
                        key="video-quad",
                        aspect=self.aspect_ratio,
                        height = 7,
                        layout="stereo-left-right"
                    ),
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        finally:
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_image_monocular_webrtc(self, session):
        """
        单目图像 WebRTC 沉浸式显示模式
        """
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True, 
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )

            while True:
                session.upsert(
                    WebRTCVideoPlane(
                        src=self.webrtc_url,
                        iceServer=None,
                        iceServers=[{"urls": server} for server in self.stun_servers],
                        key="video-quad",
                        aspect=self.aspect_ratio,
                        height = 7,
                    ),
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        except Exception as e:
            _logger.debug(f"session 渲染循环退出: {e}")
        finally:
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_image_binocular_zmq_ego(self, session):
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True,
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )
            while True:
                session.upsert(
                    [
                        ImageBackground(
                            self.img2display[:, :self.img_width],
                            aspect=self.aspect_ratio,
                            height=0.75,
                            distanceToCamera=2,
                            # 渲染层使用二进制位掩码区分左右眼。
                            # 这里左图层为 1，右图层为 2，对应左右眼相机。
                            layers=1,
                            format="jpeg",
                            quality=80,
                            key="background-left",
                            interpolate=True,
                        ),
                        ImageBackground(
                            self.img2display[:, self.img_width:],
                            aspect=self.aspect_ratio,
                            height=0.75,
                            distanceToCamera=2,
                            layers=2,
                            format="jpeg",
                            quality=80,
                            key="background-right",
                            interpolate=True,
                        ),
                    ],
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        finally:
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_image_monocular_zmq_ego(self, session):
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            """
            单目图像 ZMQ 小窗显示模式
            """
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True, 
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )

            while True:
                session.upsert(
                    [
                        ImageBackground(
                            self.img2display,
                            aspect=self.aspect_ratio,
                            height=0.75,
                            distanceToCamera=2,
                            format="jpeg",
                            quality=80,
                            key="background-mono",
                            interpolate=True,
                        ),
                    ],
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        finally:
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_image_binocular_webrtc_ego(self, session):
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            """
            双目图像 WebRTC 小窗显示模式
            """
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True, 
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )

            while True:
                session.upsert(
                    WebRTCStereoVideoPlane(
                        src=self.webrtc_url,
                        iceServer=None,
                        iceServers=[{"urls": server} for server in self.stun_servers],
                        key="video-quad",
                        aspect=self.aspect_ratio,
                        height=3,
                        layout="stereo-left-right"
                    ),
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        finally:
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_image_monocular_webrtc_ego(self, session):
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            """
            单目图像 WebRTC 小窗显示模式
            """
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True, 
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )

            while True:
                session.upsert(
                    WebRTCVideoPlane(
                        src=self.webrtc_url,
                        iceServer=None,
                        iceServers=[{"urls": server} for server in self.stun_servers],
                        key="video-quad",
                        aspect=self.aspect_ratio,
                        height=3,
                    ),
                    to="bgChildren",
                )
                await asyncio.sleep(1.0 / self.display_fps)
        finally:    
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False

    async def main_pass_through(self, session):
        self._active_session = session
        with self._xr_web_connected_shared.get_lock():
            self._xr_web_connected_shared.value = True

        self._configure_session_tcp_timeout(session)

        try:
            """
            透视显示模式
            """
            if self.use_hand_tracking:
                session.upsert(
                    Hands(
                        stream=True,
                        key="hands",
                        hideLeft=True,
                        hideRight=True
                    ),
                    to="bgChildren",
                )
            else:
                session.upsert(
                    MotionControllers(
                        stream=True, 
                        key="motionControllers",
                        left=True,
                        right=True,
                    ),
                    to="bgChildren",
                )

            while True:
                await asyncio.sleep(1.0 / self.display_fps)
                try:   
                   if getattr(session.socket, 'closed', False):
                        break
                except Exception:
                    break
        finally:    
            # 渲染循环退出（客户端断开或异常）
            self._active_session = None
            with self._xr_web_connected_shared.get_lock():
                self._xr_web_connected_shared.value = False


    # 对外属性：读取共享内存中的姿态与按钮数据
    @property
    def head_pose(self):
        """头部位姿矩阵，形状为 `(4, 4)`，坐标约定沿用 OpenXR。"""
        with self.head_pose_shared.get_lock():
            return np.array(self.head_pose_shared[:]).reshape(4, 4, order="F")

    @property
    def left_arm_pose(self):
        """左手控制位姿矩阵，形状为 `(4, 4)`。"""
        with self.left_arm_pose_shared.get_lock():
            return np.array(self.left_arm_pose_shared[:]).reshape(4, 4, order="F")

    @property
    def right_arm_pose(self):
        """右手控制位姿矩阵，形状为 `(4, 4)`。"""
        with self.right_arm_pose_shared.get_lock():
            return np.array(self.right_arm_pose_shared[:]).reshape(4, 4, order="F")

    @property
    def left_hand_positions(self):
        """左手 25 个关键点的三维位置，形状为 `(25, 3)`。"""
        with self.left_hand_position_shared.get_lock():
            return np.array(self.left_hand_position_shared[:]).reshape(25, 3)

    @property
    def right_hand_positions(self):
        """右手 25 个关键点的三维位置，形状为 `(25, 3)`。"""
        with self.right_hand_position_shared.get_lock():
            return np.array(self.right_hand_position_shared[:]).reshape(25, 3)

    @property
    def left_hand_orientations(self):
        """左手 25 个关键点的方向矩阵，形状为 `(25, 3, 3)`。"""
        with self.left_hand_orientation_shared.get_lock():
            return np.array(self.left_hand_orientation_shared[:]).reshape(25, 9).reshape(25, 3, 3, order="F")

    @property
    def right_hand_orientations(self):
        """右手 25 个关键点的方向矩阵，形状为 `(25, 3, 3)`。"""
        with self.right_hand_orientation_shared.get_lock():
            return np.array(self.right_hand_orientation_shared[:]).reshape(25, 9).reshape(25, 3, 3, order="F")

    @property
    def left_hand_pinch(self):
        """左手当前是否处于捏合状态。"""
        with self.left_hand_pinch_shared.get_lock():
            return self.left_hand_pinch_shared.value

    @property
    def left_hand_pinchValue(self):
        """左手捏合强度。"""
        with self.left_hand_pinchValue_shared.get_lock():
            return self.left_hand_pinchValue_shared.value

    @property
    def left_hand_squeeze(self):
        """左手当前是否处于握紧状态。"""
        with self.left_hand_squeeze_shared.get_lock():
            return self.left_hand_squeeze_shared.value

    @property
    def left_hand_squeezeValue(self):
        """左手握紧强度。"""
        with self.left_hand_squeezeValue_shared.get_lock():
            return self.left_hand_squeezeValue_shared.value

    @property
    def right_hand_pinch(self):
        """右手当前是否处于捏合状态。"""
        with self.right_hand_pinch_shared.get_lock():
            return self.right_hand_pinch_shared.value

    @property
    def right_hand_pinchValue(self):
        """右手捏合强度。"""
        with self.right_hand_pinchValue_shared.get_lock():
            return self.right_hand_pinchValue_shared.value

    @property
    def right_hand_squeeze(self):
        """右手当前是否处于握紧状态。"""
        with self.right_hand_squeeze_shared.get_lock():
            return self.right_hand_squeeze_shared.value

    @property
    def right_hand_squeezeValue(self):
        """右手握紧强度。"""
        with self.right_hand_squeezeValue_shared.get_lock():
            return self.right_hand_squeezeValue_shared.value

    @property
    def left_ctrl_trigger(self):
        """左手柄扳机键是否按下。"""
        with self.left_ctrl_trigger_shared.get_lock():
            return self.left_ctrl_trigger_shared.value

    @property
    def left_ctrl_triggerValue(self):
        """左手柄扳机模拟量，范围约为 `0.0 ~ 1.0`。"""
        with self.left_ctrl_triggerValue_shared.get_lock():
            return self.left_ctrl_triggerValue_shared.value

    @property
    def left_ctrl_squeeze(self):
        """左手柄握持键是否按下。"""
        with self.left_ctrl_squeeze_shared.get_lock():
            return self.left_ctrl_squeeze_shared.value

    @property
    def left_ctrl_squeezeValue(self):
        """左手柄握持键模拟量，范围约为 `0.0 ~ 1.0`。"""
        with self.left_ctrl_squeezeValue_shared.get_lock():
            return self.left_ctrl_squeezeValue_shared.value

    @property
    def left_ctrl_thumbstick(self):
        """左手柄摇杆是否被触碰或按下。"""
        with self.left_ctrl_thumbstick_shared.get_lock():
            return self.left_ctrl_thumbstick_shared.value

    @property
    def left_ctrl_thumbstickValue(self):
        """左手柄摇杆二维轴值，形状为 `(2,)`。"""
        with self.left_ctrl_thumbstickValue_shared.get_lock():
            return np.array(self.left_ctrl_thumbstickValue_shared[:])

    @property
    def left_ctrl_aButton(self):
        """左手柄 A 键是否按下。"""
        with self.left_ctrl_aButton_shared.get_lock():
            return self.left_ctrl_aButton_shared.value

    @property
    def left_ctrl_bButton(self):
        """左手柄 B 键是否按下。"""
        with self.left_ctrl_bButton_shared.get_lock():
            return self.left_ctrl_bButton_shared.value

    @property
    def right_ctrl_trigger(self):
        """右手柄扳机键是否按下。"""
        with self.right_ctrl_trigger_shared.get_lock():
            return self.right_ctrl_trigger_shared.value

    @property
    def right_ctrl_triggerValue(self):
        """右手柄扳机模拟量，范围约为 `0.0 ~ 1.0`。"""
        with self.right_ctrl_triggerValue_shared.get_lock():
            return self.right_ctrl_triggerValue_shared.value

    @property
    def right_ctrl_squeeze(self):
        """右手柄握持键是否按下。"""
        with self.right_ctrl_squeeze_shared.get_lock():
            return self.right_ctrl_squeeze_shared.value

    @property
    def right_ctrl_squeezeValue(self):
        """右手柄握持键模拟量，范围约为 `0.0 ~ 1.0`。"""
        with self.right_ctrl_squeezeValue_shared.get_lock():
            return self.right_ctrl_squeezeValue_shared.value

    @property
    def right_ctrl_thumbstick(self):
        """右手柄摇杆是否被触碰或按下。"""
        with self.right_ctrl_thumbstick_shared.get_lock():
            return self.right_ctrl_thumbstick_shared.value

    @property
    def right_ctrl_thumbstickValue(self):
        """右手柄摇杆二维轴值，形状为 `(2,)`。"""
        with self.right_ctrl_thumbstickValue_shared.get_lock():
            return np.array(self.right_ctrl_thumbstickValue_shared[:])

    @property
    def right_ctrl_aButton(self):
        """右手柄 A 键是否按下。"""
        with self.right_ctrl_aButton_shared.get_lock():
            return self.right_ctrl_aButton_shared.value

    @property
    def right_ctrl_bButton(self):
        """右手柄 B 键是否按下。"""
        with self.right_ctrl_bButton_shared.get_lock():
            return self.right_ctrl_bButton_shared.value

    @property
    def last_pose_time(self) -> float:
        """最后一次收到任何移动事件的时间戳(秒),0 表示从未收到"""
        with self._last_pose_time_shared.get_lock():
            return self._last_pose_time_shared.value

    @property
    def has_received_event(self) -> bool:
        """是否至少收到过一次有效的移动事件"""
        with self._xr_has_received_event_shared.get_lock():
            return self._xr_has_received_event_shared.value

    def is_active(self, timeout: float = 10.0) -> bool:
        """
        判断 XR 设备是否活跃（基于事件接收）：
        1. 至少收到过一次事件；
        2. 最后事件时间在超时范围内。
        """
        if not self.has_received_event:
            return False
        last = self.last_pose_time
        if last == 0.0:
            return False
        return (time.time() - last) < timeout
    
    @property
    def is_web_connected(self) -> bool:
        """WebSocket 连接是否存活（网页是否还开着）"""
        with self._xr_web_connected_shared.get_lock():
            return self._xr_web_connected_shared.value
