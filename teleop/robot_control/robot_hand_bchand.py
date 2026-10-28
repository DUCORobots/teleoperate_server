import os
import sys
import time
from typing import Dict, Tuple

import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
teleop_dir = os.path.dirname(current_dir)
if teleop_dir not in sys.path:
    sys.path.append(teleop_dir)
for dependency_dir in ("gen_py", "lib"):
    dependency_path = os.path.join(teleop_dir, dependency_dir)
    if dependency_path not in sys.path:
        sys.path.append(dependency_path)

from DucoCobot import DucoCobot
from teleop.log_manager import get_logger

_logger = get_logger(__name__)


class Grab:
    """
    BChand 灵巧手 485通信协议封装
    负责:Modbus CRC16校验计算、寄存器地址转换、指令组包、底层串口写入
    硬件直接通信的核心类
    """

    def __init__(self, robot=None):
        # 传入机械臂控制对象（通过机械臂的工具口485通信）
        self.robot = robot
        # 打开机械臂485串口
        self.robot.open()

    @staticmethod
    def _concat_lists(list1, list2):
        """工具函数：合并两个字节列表"""
        return list1 + list2

    @staticmethod
    def _cal_addr(addr):
        """工具函数:将寄存器地址拆分为 低8位+高8位(Modbus协议要求)"""
        return addr % 256, addr // 256

    @staticmethod
    def _crc16_modbus(data):
        """
        核心:Modbus CRC16校验算法
        工业485通信必备:校验数据传输完整性,防止指令出错
        :return: 校验码的低字节,高字节
        """
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        crc &= 0xFFFF
        return crc & 0xFF, (crc >> 8) & 0xFF

    @staticmethod
    def _decimal_to_little_endian(num):
        """工具函数:十进制转小端模式(低字节在前,Modbus协议标准)"""
        return num % 256, num // 256

    @staticmethod
    def _uchar_to_char_list(ulist):
        """工具函数:无符号char转有符号char列表(硬件通信格式要求)"""
        result = []
        for value in ulist:
            result.append(value if value < 128 else value - 256)
        return result

    def write_register(self, hand_id, addr, register_list):
        """
        向灵巧手指定寄存器地址写入数据(Modbus 0x10功能码:写多个寄存器)
        :param hand_id: 灵巧手设备ID(固定1)
        :param addr: 寄存器起始地址
        :param register_list: 待写入的寄存器数据
        """
        # 拆分寄存器地址
        low_addr, high_addr = self._cal_addr(addr)
        # 组Modbus协议基础帧
        valid_list = [hand_id, 0x10, high_addr, low_addr, 0x00, len(register_list) // 2, len(register_list)]
        # 拼接待写入数据
        valid_list = self._concat_lists(valid_list, register_list)
        # 计算CRC校验码
        low_crc, high_crc = self._crc16_modbus(valid_list)
        # 拼接校验码（Modbus协议结尾必须加CRC）
        valid_list.append(low_crc)
        valid_list.append(high_crc)
        # 清空串口缓存 + 写入指令到灵巧手
        self.robot.tool_read_raw_data_485(4096)
        self.robot.tool_write_raw_data_485(self._uchar_to_char_list(valid_list))

    def set_cmd_position_one(self, hand_id, index, position, velocity):
        """
	    设置单个手指位置与速度。
        控制**单个手指**：设置目标位置+运动速度
        :param index: 手指索引
        :param position: 手指目标位置(0-1000)
        :param velocity: 手指运动速度
        """
        register_list = []
        # 将参数转为小端字节，组寄存器数据
        for value in [index, position, velocity]:
            low_byte, high_byte = self._decimal_to_little_endian(value)
            register_list.append(high_byte)
            register_list.append(low_byte)
        # 写入灵巧手控制寄存器（地址1055是BChand官方定义的单指控制地址）
        self.write_register(hand_id, 1055, register_list)

    def set_cmd_position(self, hand_id, positions, velocities):
        """
	    批量设置当前手的全部手指目标。
        批量控制**所有手指**：一次性设置全部手指的位置+速度
        :param positions: 所有手指的目标位置列表
        :param velocities: 所有手指的运动速度列表
        """
        for index, position in enumerate(positions):
            self.set_cmd_position_one(hand_id, index, int(position), int(velocities[index]))


class BChand_Gripper_Controller:
    """
    BChand 双臂灵巧手 上层控制器
    核心逻辑:手柄扳机值 → 判断张开/闭合 → 下发指令
    对外提供极简接口,屏蔽底层485协议细节
    """

    def __init__(self, robot_config, simulation_mode: bool = False):
        """
        初始化左右灵巧手控制器
        :param robot_config: 配置文件（扳机阈值、冷却时间、开合角度等）
        :param simulation_mode: True=仿真模式, False=真机模式
        """
        self.robot_config = robot_config
        self.simulation_mode = simulation_mode
        self._running = True

        # 状态缓存：记录上一次的扳机值、开合状态、执行动作
        self._last_trigger = {"left": 10.0, "right": 10.0}
        self._last_open_state = {"left": True, "right": True}  # 默认张开
        self._last_action = {"left": [10.0], "right": [10.0]}

        # 动作冷却时间：防止频繁下发指令损坏硬件（配置文件定义）
        self._cooldown_seconds = float(robot_config["end_effector"]["cooldown_seconds"])

        if self.simulation_mode:
            # 仿真模式：不初始化硬件，无通信
            self.left_grab = None
            self.right_grab = None
            return

        # 真机模式：初始化左右臂的灵巧手通信对象
        robot_cfg = robot_config["robot"]
        left_arm = DucoCobot(robot_cfg["ip"], int(robot_cfg["left_arm_port"]))
        right_arm = DucoCobot(robot_cfg["ip"], int(robot_cfg["right_arm_port"]))
        # 绑定左右灵巧手的底层通信类
        self.left_grab = Grab(left_arm)
        self.right_grab = Grab(right_arm)

    def _compute_open_state(self, trigger_value: float) -> bool:
        """
        核心判断逻辑:根据扳机值判断灵巧手状态
        扳机值范围:0.0~10.0
        大于阈值=张开,小于阈值=闭合
        """
        threshold = float(self.robot_config["end_effector"]["trigger_open_threshold"])
        return float(trigger_value) > threshold

    def _get_command_pair(self, side: str, open_state: bool) -> Tuple[np.ndarray, np.ndarray]:
        """
        从配置文件读取 张开/闭合 的手指角度指令
        :param side: left/right 左手/右手
        :param open_state: True=张开, False=闭合
        :return: 主指令+次指令(分两次下发,保证动作流畅)
        """
        ee_cfg = self.robot_config["end_effector"]
        if open_state:
            primary = np.asarray(ee_cfg[f"{side}_open_primary"], dtype=np.int32)
            secondary = np.asarray(ee_cfg[f"{side}_open_secondary"], dtype=np.int32)
        else:
            primary = np.asarray(ee_cfg[f"{side}_close_primary"], dtype=np.int32)
            secondary = np.asarray(ee_cfg[f"{side}_close_secondary"], dtype=np.int32)
        return primary, secondary

    def _send_side(self, side: str, open_state: bool):
        """
        向单侧灵巧手下发开合指令
        :param side: left/right
        :param open_state: 目标状态
        """
        if self.simulation_mode:
            # 仿真模式：仅更新状态，不通信
            self._last_open_state[side] = open_state
            return

        # 获取张开/闭合的手指指令
        primary, secondary = self._get_command_pair(side, open_state)
        # 从配置读取速度曲线
        velocity_profile = list(self.robot_config["end_effector"]["velocity_profile"])
        # 选择左手/右手控制器
        grab = self.left_grab if side == "left" else self.right_grab
        # 分两次下发指令（主指令→冷却→次指令），保证动作稳定
        grab.set_cmd_position(1, primary, velocity_profile)
        time.sleep(self._cooldown_seconds)
        grab.set_cmd_position(1, secondary, velocity_profile)
        # 更新最终状态
        self._last_open_state[side] = open_state

    def set_target(self, left_value: float, right_value: float):
        """
        【对外核心接口】设置左右手扳机目标值，并在开合状态变化时触发真机动作，自动控制灵巧手
        :param left_value: 左手扳机值 0.0~10.0
        :param right_value: 右手扳机值 0.0~10.0
        """
        # 钳位扳机值到合法范围 0.0~10.0
        left_value = float(np.clip(left_value, 0.0, 10.0))
        right_value = float(np.clip(right_value, 0.0, 10.0))

        # 缓存最新扳机值和动作
        self._last_trigger["left"] = left_value
        self._last_trigger["right"] = right_value
        self._last_action["left"] = [left_value]
        self._last_action["right"] = [right_value]

        # 遍历左右手，仅在【状态变化时】下发指令（防抖，不重复发送）
        for side, value in (("left", left_value), ("right", right_value)):
            open_state = self._compute_open_state(value)
            # 状态改变才执行动作，避免无效通信
            if open_state != self._last_open_state[side]:
                self._send_side(side, open_state)

    def get_state(self) -> Dict[str, Dict[str, object]]:
        """
        【对外接口】获取灵巧手当前状态(供录制监控、调试使用)
        :return: 左右手的扳机值、开合状态、动作指令
        """
        return {
            "left": {
                "trigger_value": self._last_trigger["left"],
                "open": self._last_open_state["left"],
                "states": [self._last_trigger["left"]],
                "action": self._last_action["left"],
            },
            "right": {
                "trigger_value": self._last_trigger["right"],
                "open": self._last_open_state["right"],
                "states": [self._last_trigger["right"]],
                "action": self._last_action["right"],
            },
        }

    def close(self):
        """统一关闭接口：保留兼容性，无硬件需要释放"""
        self._running = False
