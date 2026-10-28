# coding:utf-8 
# !/usr/bin/env python
# from http import client

import sys
import glob
import threading
import time

sys.path.append('gen_py')
sys.path.append('lib')
from thrift import Thrift
from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol
from gen_py.robot import RPCHead
from gen_py.robot.ttypes import StateRobot, StateProgram, TaskState


class DucoCobotHead:
    def __init__(self, ip, port):
        self.transport = TSocket.TSocket(ip, port)
        self.transport = TTransport.TFramedTransport(self.transport)
        self.protocol = TBinaryProtocol.TBinaryProtocol(self.transport)
        self.client = RPCHead.Client(self.protocol)

    '''
    * @brief 连接机器人
    * @return -1:打开失败; 0:打开成功
    '''

    def open(self):
        try:
            self.transport.open()
        except TTransport.TTransportException as e:
            print("open mesg:", repr(e))
            return -1
        else:
            return 0

    '''
    * @brief 断开机器人连接
    * @return -1:打开失败; 0:打开成功
    '''

    def close(self):
        try:
            self.transport.close()
        except Exception as e:
            print("close mesg:", repr(e))
            return -1
        else:
            return 0

    '''
     * @brief 机器人上使能
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def enable(self, axis_num, block):
        return self.client.enable(axis_num, block)

    '''
     * @brief 机器人下使能
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def disable(self, axis_num, block):
        return self.client.disable(axis_num, block)

    '''
     * @brief 停止所有任务
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def stop(self, block):
        return self.client.stop(block)

    '''
     * @brief 暂停所有任务
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def pause(self, block):
        return self.client.pause(block)

    '''
     * @brief 恢复所有暂停的任务
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def resume(self, block):
        return self.client.resume(block)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到目标关节角状态
     * @param joints_list 目标关节角度, 单位: rad
     * @param v 关节角速度, 单位: 系统设定速度的百分比%, 取值范围(0,100]
     * @param a 关节角加速度, 单位: 系统设定加速度的百分比%, 取值范围(0,100]
     * @param r 融合半径, 单位: 系统设定最大融合半径的百分比%, 默认值为 0, 表示无融合, 取值范围[0,50)
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movej(self, joints_list, v, a, r, block, def_acc=False):
        return self.client.movej(joints_list, v, a, r, block, def_acc)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到目标关节角状态
     * @param joints_list 目标关节角度, 单位: rad
     * @param v 关节角速度, 单位: rad/s
     * @param a 关节角加速度, 单位: rad/s^2
     * @param r 融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movej2(self, joints_list, v, a, r, block, def_acc=False):
        return self.client.movej2(joints_list, v, a, r, block, def_acc)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到目标关节角状态,运动过程中不考虑笛卡尔空间路径
     * @param joints_list 目标关节角度, 单位: rad
     * @param v 最大关节角速度, 单位: m/s
     * @param a 最大关节加速度, 单位: m/s^2
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回, 可缺省, 默认为非阻塞
     * @param kp 比例参数, 默认值200, 可缺省, 建议使用默认参数
     * @param kd 微分参数, 默认值25, 可缺省, 建议使用默认参数
     * @param smooth_vel 速度平滑参数, 默认值10, 可缺省, 范围[1-10]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数已保证速度的平滑度，否则可根据实际需要降低参数提高精度
     * @param smooth_acc 加速度平滑参数, 默认值10, 可缺省, 范围[0-1]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数以保证加速度的平滑度，否则可根据实际需要降低参数提高跟踪精度
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''
    def servoj(self, joints_list, v, a, block, kp=200, kd=25, smooth_vel=10, smooth_acc=1):
        return self.client.servoj(joints_list, v, a, block, kp, kd, smooth_vel, smooth_acc)

    '''
     * @brief 根据id查询当前的任务状态
     * @param id 任务的id
     * @return 任务的当前执行状态
     '''

    def get_noneblock_taskstate(self, id):
        return self.client.get_noneblock_taskstate(id)

    '''
     * @brief 获取当前机器人状态
     * @return 机器人状态信息列表, data[0]表示机器人状态, data [1]表示程序状态, 
	 *             data [2]表示安全控制器状态, data [3]表示操作模式
     '''

    def get_robot_state(self):
        return self.client.get_robot_state()

    '''
     * @brief 获取当前状态下机械臂各关节的角度
     * @return 1-2轴关节角度列表, 单位: rad
     '''

    def get_actual_joints_position(self):
        return self.client.get_actual_joints_position()

    '''
     * @brief 获取当前状态下机械臂各关节的规划角度
     * @return 1-2轴目标关节角度列表, 单位: rad
     '''

    def get_target_joints_position(self):
        return self.client.get_target_joints_position()

    '''
     * @brief 获取当前状态下机械臂各关节角速度
     * @return 1-2轴关节速度列表, 单位: rad/s
     '''

    def get_actual_joints_speed(self):
        return self.client.get_actual_joints_speed()

    '''
     * @brief 获取当前状态下机械臂各关节规划角速度
     * @return 1-2轴目标关节速度列表, 单位: rad/s
     '''

    def get_target_joints_speed(self):
        return self.client.get_target_joints_speed()

    '''
     * @brief 获取当前状态下机械臂各关节角加速度
     * @return 1-2轴关节加速度列表, 单位: rad/s^2
     '''

    def get_actual_joints_acceleration(self):
        return self.client.get_actual_joints_acceleration()

    '''
     * @brief 取当前状态下机械臂各关节角规划加速度
     * @return 1-2轴关节加速度列表, 单位: rad/s^2
     '''

    def get_target_joints_acceleration(self):
        return self.client.get_target_joints_acceleration()

    '''
     * @brief 确保机器人远程连接断开时, 机器人自动产生一条stop指令以停止当前运动.使用该函数需要单独创建一个线程周期性调用
     * @param time 心跳延时时间, 单位: ms
     '''

    def rpc_heartbeat(self, time=1000):
        return self.client.rpc_heartbeat(time)

    def get_robot_status(self):
        return self.client.get_robot_status()
