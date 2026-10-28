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
from gen_py.robot import RPCRobot
from gen_py.robot.ttypes import StateRobot, StateProgram, OperationMode, TaskState, RealTimeControlData, \
    MoveJogTaskParam


class DucoCobot:
    def __init__(self, ip, port):
        self.transport = TSocket.TSocket(ip, port)
        self.transport = TTransport.TFramedTransport(self.transport)
        self.protocol = TBinaryProtocol.TBinaryProtocol(self.transport)
        self.client = RPCRobot.Client(self.protocol)

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
     * @brief 机器人上电
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def power_on(self, block):
        return self.client.power_on(block)

    '''
     * @brief 机器人下电
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def power_off(self, block):
        return self.client.power_off(block)

    '''
     * @brief 机器人上使能
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def enable(self, block):
        return self.client.enable(block)

    '''
     * @brief 机器人下使能
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def disable(self, block):
        return self.client.disable(block)

    '''
     * @brief 机器人关机
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def shutdown(self, block):
        return self.client.shutdown(block)

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
     * @brief 设置工具末端相对于法兰面坐标系的偏移, 设置成功后, 
	 *        后续运动函数中的TCP设置为该TCP或者为空时,使用该TCP参数
     * @param name           工具坐标系的名字    
     * @param tool_offset    工具TCP偏移量 [x_off, y_off,z_off,rx,ry,rz], 单位: m, rad
     * @param payload        末端负载质量, 质心, [mass,x_cog,y_cog,z_cog], 单位: kg, m
     * @param inertia_tensor 末端工具惯量矩阵参数, 参数1-6分别对应矩阵xx、xy、xz、yy、yz、zz元素, 单位: kg*m^2
     * @return 返回当前任务结束时的状态
     '''

    def set_tool_data(self, name, tool_offset, payload, inertia_tensor):
        return self.client.set_tool_data(name, tool_offset, payload, inertia_tensor)

    '''
     * @brief 获取当前设置工具的负载质量及质心位置
     * @return 质量单位: kg,质心位置单位: m,[mass,x_cog,y_cog,z_cog]
     '''

    def get_tool_load(self):
        return self.client.get_tool_load()

    '''
     * @brief 获取当前状态下机械臂有效的末端工具的偏移量
     * @return TCP偏移量信息,单位: m, rad
     '''

    def get_tcp_offset(self):
        return self.client.get_tcp_offset()

    '''
     * @brief 设置工件坐标系
     * @param name 工件坐标系名称
     * @param wobj 工件坐标系
     * @return 返回当前任务结束时的状态
     '''

    def set_wobj(self, name, wobj):
        return self.client.set_wobj(name, wobj)

    '''
     * @brief 获取当前设置的工件坐标系的值
     * @return [x, y, z, rx, ry, rz]工件坐标系相对于基坐标系的位移, 单位: m, rad
     '''

    def get_wobj(self):
        return self.client.get_wobj()

    '''
     * @brief 基于当前的工件坐标系设置一个偏移量, 后续的move类脚本的参考工件坐标系上都将添加这个偏移量
     * @param wobj 工件坐标系相对于基坐标系的位移, 单位: m, rad
     * @param active 是否启用
     * @return 返回当前任务结束时的状态
     '''

    def set_wobj_offset(self, wobj, active=True):
        return self.client.set_wobj_offset(wobj, active)

    '''
     * @brief 计算机械臂的正运动学, 求解给定TCP在给定wobj下的值
     * @param joints_position 需要计算正解的关节角, 单位: rad
     * @param tool            工具坐标系信息,tcp偏移量[x_off,y_off,z_off,rx,ry,rz], 单位:m, rad, 为空使用当前tcp值
     * @param wobj            工件坐标系相对于基坐标系的位移[x, y, z, rx, ry, rz], 单位:m, rad, 为空使用当前wobj
     * @return                末端姿态列表[x,y,z,rx,ry,rz]
     '''

    def cal_fkine(self, joints_position, tool, wobj):
        return self.client.cal_fkine(joints_position, tool, wobj)

    '''
     * @brief 计算运动学逆解, 在求解过程中, 会选取靠近当前机械臂关节位置的解
     * @param p      需要计算的末端位姿在设置工件坐标系的值,包含当前有效的工具偏移量, 单位:m,rad
     * @param q_near 用于计算逆运动学的参考关节位置,为空使用当前关节值
     * @param tool   工具坐标系信息,tcp偏移量[x_off,y_off,z_off,rx,ry,rz], 单位:m, rad, 为空使用当前tcp值
     * @param wobj   工件坐标系相对于基坐标系的位移[x, y, z, rx, ry, rz], 单位:m, rad, 为空使用当前wobj
     * @return       关节位置列表[q1,q2,q3,q4,q5,q6]
     '''

    def cal_ikine(self, p, q_near, tool, wobj):
        return self.client.cal_ikine(p, q_near, tool, wobj)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到目标关节角状态
     * @param joints_list 1-6关节的目标关节角度, 单位: rad
     * @param v 关节角速度, 单位: 系统设定速度的百分比%, 取值范围(0,100]
     * @param a 关节角加速度, 单位: 系统设定加速度的百分比%, 取值范围(0,100]
     * @param r 融合半径, 单位: 系统设定最大融合半径的百分比%, 默认值为 0, 表示无融合, 取值范围[0,50)
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movej(self, joints_list, v, a, r, block, def_acc=False):
        return self.client.movej(joints_list, v, a, r, block, def_acc)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到目标关节角状态
     * @param joints_list 1-6关节的目标关节角度, 单位: rad
     * @param v 关节角速度, 单位: rad/s
     * @param a 关节角加速度, 单位: rad/s^2
     * @param r 融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movej2(self, joints_list, v, a, r, block, def_acc=False):
        return self.client.movej2(joints_list, v, a, r, block, def_acc)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到末端目标位置
     * @param p 对应末端的位姿, 位置单位: m, 姿态以Rx、Ry、Rz表示, 单位: rad
     * @param v 关节角速度, 单位: 系统设定速度的百分比%, 取值范围(0,100]
     * @param a 关节加速度, 单位: 系统设定加速度的百分比%, 取值范围(0,100]
     * @param r 融合半径, 单位: 系统设定最大融合半径的百分比%, 默认值为 0, 表示无融合, 取值范围[0,50)
     * @param q_near 目标点附近位置对应的关节角度, 用于确定逆运动学选解, 为空时使用当前位置
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movej_pose(self, p, v, a, r, q_near, tool, wobj, block, def_acc=False):
        return self.client.movej_pose(p, v, a, r, q_near, tool, wobj, block, def_acc)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到末端目标位置
     * @param p 对应末端的位姿, 位置单位: m, 姿态以Rx、Ry、Rz表示, 单位: rad
     * @param v 关节角速度, 单位: rad/s
     * @param a 关节加速度, 单位: rad/s^2
     * @param r 融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param q_near 目标点附近位置对应的关节角度, 用于确定逆运动学选解, 为空时使用当前位置
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movej_pose2(self, p, v, a, r, q_near, tool, wobj, block, def_acc=False):
        return self.client.movej_pose2(p, v, a, r, q_near, tool, wobj, block, def_acc)

    '''
     * @brief 控制机械臂末端从当前状态按照直线路径移动到目标状态
     * @param p 对应末端的位姿, 位置单位: m, 姿态以Rx、Ry、Rz表示, 单位: rad
     * @param v 末端速度, 单位: m/s
     * @param a 末端加速度, 单位: m/s^2
     * @param r 融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param q_near 目标点附近位置对应的关节角度, 用于确定逆运动学选解, 为空时使用当前位置
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movel(self, p, v, a, r, q_near, tool, wobj, block, def_acc=False):
        return self.client.movel(p, v, a, r, q_near, tool, wobj, block, def_acc)

    '''
     * @brief 控制机械臂做圆弧运动, 起始点为当前位姿点, 途径p1点, 终点为p2点
     * @param p1 圆弧运动中间点
     * @param p2 圆弧运动结束点
     * @param v  末端速度, 单位: m/s
     * @param a  末端加速度, 单位: m/s^2
     * @param r  融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param mode   姿态控制模式  0:姿态与终点保持一致;1:姿态与起点保持一致;2:姿态受圆心约束
     * @param q_near 目标点附近位置对应的关节角度, 用于确定逆运动学选解, 为空时使用当前位置
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def movec(self, p1, p2, v, a, r, mode, q_near, tool, wobj, block, def_acc=False):
        return self.client.movec(p1, p2, v, a, r, mode, q_near, tool, wobj, block, def_acc)

    '''
     * @brief 控制机械臂做圆周运动, 起始点为当前位姿点, 途径p1点和p2点
     * @param p1 圆周运动经过点
     * @param p2 圆周运动经过点
     * @param v  末端速度, 单位: m/s
     * @param a  末端加速度, 单位: m/s^2
     * @param r  融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param mode   姿态控制模式   1:姿态与终点保持一致;  2:姿态受圆心约束
     * @param q_near 目标点附近位置对应的关节角度, 用于确定逆运动学选解, 为空时使用当前位置
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def move_circle(self, p1, p2, v, a, r, mode, q_near, tool, wobj, block, def_acc=False):
        return self.client.move_circle(p1, p2, v, a, r, mode, q_near, tool, wobj, block, def_acc)

    '''
     * @brief 控制机械臂沿工具坐标系直线移动一个增量
     * @param pose_offset 工具坐标系下的位姿偏移量
     * @param v 直线移动的速度, 单位: m/s, 当x、y、z均为0时, 线速度按比例换算成角速度
     * @param a 加速度, 单位: m/s^2
     * @param r 融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def tcp_move(self, pose_offset, v, a, r, tool, block, def_acc=False):
        return self.client.tcp_move(pose_offset, v, a, r, tool, block, def_acc)

    '''
     * @brief 控制机器人沿工具坐标系直线移动一个增量, 增量为p1与p2点之间的差, 运动的目标点为:当前点*p1^-1*p2
     * @param p1 工具坐标系下的位姿偏移量计算点1
     * @param p2 工具坐标系下的位姿偏移量计算点2
     * @param v  直线移动的速度, 单位: m/s, 当x、y、z均为0时, 线速度按比例换算成角速度
     * @param a  加速度, 单位: m/s^2
     * @param r  融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param tool  设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj  设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def tcp_move_2p(self, p1, p2, v, a, r, tool, wobj, block, def_acc=False):
        return self.client.tcp_move_2p(p1, p2, v, a, r, tool, wobj, block, def_acc)

    '''
     * @brief 控制机械臂沿工件坐标系直线移动一个增量
     * @param pose_offset 工件坐标系下的位姿偏移量
     * @param v 直线移动的速度, 单位: m/s, 当x、y、z均为0时, 线速度按比例换算成角速度
     * @param a 加速度, 单位: m/s^2
     * @param r 融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def wobj_move(self, pose_offset, v, a, r, wobj, block, def_acc=False):
        return self.client.wobj_move(pose_offset, v, a, r, wobj, block, def_acc)

    '''
     * @brief 控制机器人沿工件坐标系直线移动一个增量, 增量为p1与p2点之间的差, 运动的目标点为:当前点*p1^-1*p2
     * @param p1 工件坐标系下的位姿偏移量计算点1
     * @param p2 工件坐标系下的位姿偏移量计算点2
     * @param v  直线移动的速度, 单位: m/s, 当x、y、z均为0时, 线速度按比例换算成角速度
     * @param a  加速度, 单位: m/s^2
     * @param r  融合半径, 单位: m, 默认值为 0, 表示无融合.当数值大于0时表示与下一条运动融合
     * @param tool  设置使用的工具坐标系的名称, 为空时默认为当前使用的工具坐标系
     * @param wobj  设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @param op 可缺省参数
     * @param def_acc 是否使用系统默认加速度, false表示使用自定义的加速度值, true表示使用系统自动规划的加速度值, 可缺省, 默认为false
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态, 若无融合为Finished, 若有融合为Interrupt.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def wobj_move_2p(self, p1, p2, v, a, r, tool, wobj, block,  def_acc=False):
        return self.client.wobj_move_2p(p1, p2, v, a, r, tool, wobj, block, def_acc)


    '''
     * @brief 控制机械臂每个关节按照给定的速度一直运动, 函数执行后会直接运行后续指令.
	 *        运行speedj函数后, 机械臂会持续运动并忽略后续运动指令, 直到接收到speed_stop()函数后停止
     * @param joints_list 每个关节的速度, 单位: rad/s
     * @param a 主导轴的关节加速度, 单位: rad/s^2
     * @param time  运行时间, 到达时间后会停止运动,单位: ms.默认-1表示一直运行
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def speedj(self, joints_list, a, time, block):
        return self.client.speedj(joints_list, a, time, block)

    '''
     * @brief 控制机械臂末端按照给定的速度一直运动, 函数执行后会直接运行后续指令.
	 *        运行speedl函数后, 机械臂会持续运动并忽略后续运动指令, 直到接收到speed_stop()函数后停止
     * @param pose_list 末端速度向量, 线速度单位: m/s,角速度单位: rad/s
     * @param a 末端的线性加速度, 单位: rad/s^2
     * @param time  运行时间, 到达时间会停止运动, 单位: ms.默认-1表示一直运行
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def speedl(self, pose_list, a, time, block):
        return self.client.speedl(pose_list, a, time, block)

    '''
     * @brief 停止speedj及speedl函数的运动
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def speed_stop(self, block):
        return self.client.speed_stop(block)

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
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动到目标笛卡尔状态,通过关节空间运动
     * @param pose_list 目标工件坐标系下的末端位姿, 单位: m, rad
     * @param v 关节速度, 单位: rad/s
     * @param a 关节加速度, 单位: m/s^2
     * @param q_near 目标点附近位置对应的关节角度, 用于确定逆运动学选解, 为空时使用当前位置
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回, 可缺省, 默认为非阻塞
     * @param kp 比例参数, 默认值200, 可缺省, 建议使用默认参数
     * @param kd 微分参数, 默认值25, 可缺省, 建议使用默认参数
     * @param smooth_vel 速度平滑参数, 默认值10, 可缺省, 范围[1-10]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数已保证速度的平滑度，否则可根据实际需要降低参数提高精度
     * @param smooth_acc 加速度平滑参数, 默认值10, 可缺省, 范围[0-1]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数以保证加速度的平滑度，否则可根据实际需要降低参数提高跟踪精度
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def servoj_pose(self, pose_list, v, a, q_near, tool, wobj, block, kp=200, kd=25, smooth_vel=10, smooth_acc=1):
        return self.client.servoj_pose(pose_list, v, a, q_near, tool, wobj, block, kp, kd, smooth_vel, smooth_acc)

    '''
     * @brief 控制机械臂从当前状态, 按照关节运动的方式移动一个增量,通过关节空间运动
     * @param pose_offset 目标工件坐标系下的末端位姿, 单位: m, rad
     * @param v 关节速度, 范围(0, 1.25*PI], 单位: rad/s
     * @param a 关节加速度, 范围(0, 12.5*PI], 单位: rad/s^2
     * @param tool  设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回, 默认值false, 可缺省
     * @param kp 比例参数, 默认值200, 可缺省, 建议使用默认参数
     * @param kd 微分参数, 默认值25, 可缺省, 建议使用默认参数
     * @param smooth_vel 速度平滑参数, 默认值10, 可缺省, 范围[1-10]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数已保证速度的平滑度，否则可根据实际需要降低参数提高精度
     * @param smooth_acc 加速度平滑参数, 默认值10, 可缺省, 范围[0-1]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数以保证加速度的平滑度，否则可根据实际需要降低参数提高跟踪精度
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def servo_tcp(self, pose_offset, v, a, tool, block, kp=200, kd=25, smooth_vel=10, smooth_acc=1):
        return self.client.servo_tcp(pose_offset, v, a, tool, block, kp, kd, smooth_vel, smooth_acc)

    '''
     * @brief  控制机械臂末端从当前状态按照直线路径移动到目标状态
     * @param pose_list 对应末端的位姿, 位置单位: m, 姿态以Rx、Ry、Rz表示, 单位: rad
     * @param v 末端速度, 单位: m/s
     * @param a 末端加速度, 单位: m/s^2
     * @param q_near 目标点附近位置对应的关节角度, 用于确定逆运动学选解, 为空时使用当前位置
     * @param tool   设置使用的工具的名称, 为空时默认为当前使用的工具
     * @param wobj   设置使用的工件坐标系的名称, 为空时默认为当前使用的工件坐标系
     * @param block  是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回, 可缺省, 默认为非阻塞
     * @param kp 比例参数, 默认值200, 可缺省, 建议使用默认参数
     * @param kd 微分参数, 默认值25, 可缺省, 建议使用默认参数
     * @param smooth_vel 速度平滑参数, 默认值10, 可缺省, 范围[1-10]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数已保证速度的平滑度，否则可根据实际需要降低参数提高精度
     * @param smooth_acc 加速度平滑参数, 默认值10, 可缺省, 范围[0-1]，当快速连续发送密集离散点位且无法保证点位间隔均匀性时，推荐使用较大参数以保证加速度的平滑度，否则可根据实际需要降低参数提高跟踪精度
     * @return 当配置为阻塞执行, 返回值代表当前任务结束时的状态.
	 *         当配置为非阻塞执行, 返回值代表当前任务的id, 用户可以调用get_noneblock_taskstate(id)函数查询当前任务的执行状态
     '''

    def servol(self, pose_list, v, a, q_near, tool, wobj, block, kp=200, kd=25, smooth_vel=10, smooth_acc=1):
        return self.client.servol(pose_list, v, a, q_near, tool, wobj, block, kp, kd, smooth_vel, smooth_acc)

    '''
     * @brief 控制机器人进入牵引示教模式
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
    '''
    def get_last_error(self):
        return self.client.get_last_error()

    '''
     * @brief 根据id查询当前的任务状态
     * @param id 任务的id
     * @return 任务的当前执行状态
    '''

    def get_noneblock_taskstate(self, id):
        return self.client.get_noneblock_taskstate(id)

    '''
     * @brief 插入log日志, 记录运行问题
     * @param message 日志描述
     '''

    def log_info(self, message):
        self.client.log_info(message)

    '''
     * @brief 在运行过程中产生弹窗, 并暂停当前所有任务
     * @param message 弹窗描述
     '''

    def log_error(self, message):
        self.client.log_error(message)

    '''
     * @brief 设置机器人全局速度
     * @param val 机器人全局速度, 范围[1,100]
     * @return 任务结束时状态
     '''

    def speed(self, val):
        return self.client.speed(val)

    '''
     * @brief 获取当前机器人状态
     * @return 机器人状态信息列表, data[0]表示机器人状态, data [1]表示程序状态, 
	 *             data [2]表示安全控制器状态, data [3]表示操作模式
     '''

    def get_robot_state(self):
        return self.client.get_robot_state()

    '''
     * @brief 获取当前状态下机械臂末端法兰在基坐标系下的位姿
     * @return 末端法兰位置
     '''

    def get_flange_pose(self):
        return self.client.get_flange_pose()

    '''
     * @brief 获取当前状态下机械臂末端法兰在基坐标系下的速度
     * @return 末端法兰速度列表, 单位: m/s,rad/s
     '''

    def get_flange_speed(self):
        return self.client.get_flange_speed()

    '''
     * @brief 获取当前状态下机械臂末端法兰在基坐标系下的加速度
     * @return 末端法兰加速度列表, 单位: m/s^2, rad/s^2
     '''

    def get_flange_acceleration(self):
        return self.client.get_flange_acceleration()

    '''
     * @brief 获取当前状态下机械臂工具末端点在基坐标系下的位姿
     * @return 末端位姿
     '''

    def get_tcp_pose(self):
        return self.client.get_tcp_pose()

    '''
     * @brief 获取当前状态下机械臂工具末端点的速度
     * @return 末端速度列表, 单位: m/s,rad/s
     '''

    def get_tcp_speed(self):
        return self.client.get_tcp_speed()

    '''
     * @brief 获取当前状态下机械臂工具末端点的加速度
     * @return 末端加速度列表, 单位: m/s^2, rad/s^2
     '''

    def get_tcp_acceleration(self):
        return self.client.get_tcp_acceleration()

    '''
     * @brief 获取当前末端的力矩信息
     * @return 末端力矩信息, [Fx,Fy,Fz,Mx,My,Mz],单位: N、N.m
     '''

    def get_tcp_force(self):
        return self.client.get_tcp_force()

    '''
     * @brief 获取当前状态下机械臂各关节的角度
     * @return 1-6轴关节角度列表, 单位: rad
     '''

    def get_actual_joints_position(self):
        return self.client.get_actual_joints_position()

    '''
     * @brief 获取当前状态下机械臂各关节的规划角度
     * @return 1-6轴目标关节角度列表, 单位: rad
     '''

    def get_target_joints_position(self):
        return self.client.get_target_joints_position()

    '''
     * @brief 获取当前状态下机械臂各关节角速度
     * @return 1-6轴关节速度列表, 单位: rad/s
     '''

    def get_actual_joints_speed(self):
        return self.client.get_actual_joints_speed()

    '''
     * @brief 获取当前状态下机械臂各关节规划角速度
     * @return 1-6轴目标关节速度列表, 单位: rad/s
     '''

    def get_target_joints_speed(self):
        return self.client.get_target_joints_speed()

    '''
     * @brief 获取当前状态下机械臂各关节角加速度
     * @return 1-6轴关节加速度列表, 单位: rad/s^2
     '''

    def get_actual_joints_acceleration(self):
        return self.client.get_actual_joints_acceleration()

    '''
     * @brief 取当前状态下机械臂各关节角规划加速度
     * @return 1-6轴关节加速度列表, 单位: rad/s^2
     '''

    def get_target_joints_acceleration(self):
        return self.client.get_target_joints_acceleration()

    '''
     * @brief 获取当前状态下机械臂各关节力矩
     * @return 1-6轴关节力矩列表, 单位: N.m
     '''

    def get_actual_joints_torque(self):
        return self.client.get_actual_joints_torque()

    '''
     * @brief 获取当前状态下机械臂各关节目标力矩
     * @return 1-6轴关节加速度列表, 单位: rad/s^2
     '''

    def get_target_joints_torque(self):
        return self.client.get_target_joints_torque()

    '''
     * @brief 设置碰撞检测等级
     * @param value 0:关闭碰撞检测, 1-5:对应设置碰撞检测等级1到等级5
     * @return 任务结束时状态
     '''

    def collision_detect(self, value):
        return self.client.collision_detect(value)

    '''
     * @brief 重置碰撞检测警告
     * @return 任务结束时状态
     '''

    def collision_detection_reset(self):
        return self.client.collision_detection_reset()

    '''
     * @brief 设置抓取负载.可以在程序运行过程中设置机器人当前的负载(质量、质心)
     * @param value 末端工具抓取负载质量, 质心, {mass,x_cog,y_cog,z_cog}, 
	 *              相对于工具坐标系, 质量范围[0, 35], 单位: kg, m
     * @return 任务结束时状态
     '''

    def set_load_data(self, value):
        return self.client.set_load_data(value)

    '''
     * @brief 开启实时控制模式 (不支持)
     * @param mode  实时控制模式, 1:关节位置, 2:关节速度, 3:空间位置, 4:空间速度
     * @param filter_bandwidth 实时控制指令滤波器带宽, 单位Hz, 默认100Hz
     * @param com_lost_time 实时控制通讯数据丢失监控保护时间, 单位s, 默认0.02s
     * @return 任务结束时的状态
     '''

    def start_realtime_mode(self, mode, filter_bandwidth, com_lost_time):
        return self.client.start_realtime_mode(mode, filter_bandwidth, com_lost_time)

    '''
     * @brief 结束实时控制模式 (不支持)
     * @return 任务结束时的状态
     '''

    def end_realtime_mode(self):
        return self.client.end_realtime_mode()

    '''
     * @brief 实时数据入队 (不支持)
     * @param realtime_data 实时数据
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 任务结束时的状态
     '''

    def realtime_data_enqueue(self, realtime_data, block):
        return self.client.realtime_data_enqueue(realtime_data, block)

    '''
     * @brief 清空实时数据队列 (不支持)
     * @return 任务结束时的状态
     '''

    def clear_realtime_data_queue(self):
        return self.client.clear_realtime_data_queue()

    '''
     * @brief 获取当前实时队列池数据的数量 (不支持)
     * @return 当前实时队列池数据的数量
     '''

    def get_realtime_data_queue_size(self):
        return self.client.get_realtime_data_queue_size()

    '''
     * @brief 将一组points点位信息输入到机器人控制器中的轨迹池
     * @param track 一组points点位信息.每个point以6个double类型数据构成
     * @param block 指令是否阻塞型指令, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def trackEnqueue(self, track, block):
        return self.client.trackEnqueue(track, block)

    '''
     * @brief 将机器人控制器中的轨迹池清空
     * @return 当前任务结束时的状态
     '''

    def trackClearQueue(self):
        return self.client.trackClearQueue()

    '''
     * @brief 获取机器人控制器中的当前轨迹池大小
     * @return 当前轨迹池大小
     '''

    def getQueueSize(self):
        return self.client.getQueueSize()

    '''
     * @brief 执行时, 机器人的各关节将顺序到达轨迹池中的点位值直到轨迹池中无新的点位.
     *        执行过程中, 主导关节(关节位置变化最大的关节)将以speed与acc规划运动, 其他关节按比例缩放.
     *        注:如果已经开始执行停止规划, 将不再重新获取轨迹池中的数据, 直到完成停止.
     *            停止后如果轨迹池中有新的点位, 将重新执行跟随.为保证运动连续性, 建议至少保证轨迹池中有10个数据
     * @param speed 最大关节速度, 单位: rad/s
     * @param acc   最大关节加速度, 单位: rad/s^2
     * @param block 指令是否阻塞型指令, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def trackJointMotion(self, speed, acc, block):
        return self.client.trackJointMotion(speed, acc, block)

    '''
     * @brief 执行时, 机器人的工具末端tool将顺序到达轨迹池中的点位值直到轨迹池中无新的点位.
     *        执行过程中, 工具末端tool将以speed与acc在工件坐标系wobj下规划运动.
     *        注:如果已经开始执行停止规划, 将不再重新获取轨迹池中的数据, 直到完成停止.
                  停止后如果轨迹池中有新的点位, 将重新执行跟随.为保证运动连续性, 建议至少保证轨迹池中有10个数据
     * @param speed 最大末端速度, 单位: m/s
     * @param acc   最大末端加速度, 单位: m/s^2
     * @param block 指令是否阻塞型指令, 如果为false表示非阻塞指令, 指令会立即返回
     * @param tool  设置使用的工件坐标系的名称, 为空字符串时默认为当前使用的工件坐标系
     * @param wobj  设置使用的工具的名称,为空字符串时默认为当前使用的工具
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def trackCartMotion(self, speed, acc, block, tool, wobj):
        return self.client.trackCartMotion(speed, acc, block, tool, wobj, 0.005)

    '''
     * @brief 确保机器人远程连接断开时, 机器人自动产生一条stop指令以停止当前运动.使用该函数需要单独创建一个线程周期性调用
     * @param time 心跳延时时间, 单位: ms
     '''

    def rpc_heartbeat(self, time=1000):
        return self.client.rpc_heartbeat(time)

    '''
     * @brief 获取当前RPC库的版本号
     * @return 当前RPC库的版本号
     '''

    def get_version(self):
        return "3.8.4"

    '''
     * @brief 获取末端法兰在工具坐标系和工件坐标系下的位姿
     * @param tool 工具坐标系名称, 为空字符串默认为当前使用的坐标系
     * @param wobj 工件坐标系名称, 为空字符串默认为当前使用的坐标系
     * @return 末端法兰的位姿
     '''

    def get_tcp_pose_coord(self, tool, wobj):
        return self.client.get_tcp_pose_coord(tool, wobj)


    '''
     * @brief 控制机械臂在关节或者笛卡尔空间做点动
     * @param param Jog运动的相关参数, 参考MoveJogTaskParams
     * @param block 指令是否阻塞型指令, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def move_jog(self, param, block):
        return self.client.move_jog(param, block)

    '''
     * @brief 结束机械臂的关节或者笛卡尔Jog
     * @param block 指令是否阻塞型指令, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def stop_manual_move(self, block):
        return self.client.stop_manual_move(block)

    '''
     * @brief 获取机器人控制器的软件版本号
     * @return 机器人控制器的软件版本号
     '''

    def get_robot_version(self):
        return self.client.get_robot_version()

    '''
     * @brief 获取全局速度的百分比
     * @return 全局速度的百分比
     '''

    def get_global_speed(self):
        return self.client.get_global_speed()

    '''
     * @brief 获取机器人当前的位姿等信息
     * @param status 机器人位姿等信息
     '''

    def get_robot_status(self):
        return self.client.get_robot_status()


    '''
     * @brief 末端485端口读取长度为len的字节数据
     * @param data 读取到的数据, 未读到数据返回空列表
     * @param len  需要读取的长度
    '''
    def tool_read_raw_data_485(self, len):
        return self.client.tool_read_raw_data_485(len)

    '''
     * @brief 末端485匹配头head后读取到长度为len的一帧数据
     * @param data 读取到的数据, 未读到数据返回空列表
     * @param head 需要匹配的头数据
     * @param len  需要读取的长度
    '''
    def tool_read_raw_data_485_h(self, head, len):
        return self.client.tool_read_raw_data_485_h(head, len)

    '''
     * @brief 末端485匹配头head和尾tail读取到一帧匹配的数据
     * @param data 读取到的数据, 未读到数据返回空列表
     * @param head 需要匹配的头数据
     * @param tail 需要匹配的尾数据
    '''
    def tool_read_raw_data_485_ht(self, head, tail):
        return self.client.tool_read_raw_data_485_ht(head, tail)

    '''
     * @brief 末端485写原生数据, 将data写入485端口
     * @param data 写入的数据列表
     * @return true:成功, false:失败
    '''
    def tool_write_raw_data_485(self, data):
        return self.client.tool_write_raw_data_485(data)

    '''
     * @brief 末端485写原生数据, 将data中的数据加上head写入485端口
     * @param data 写入的数据列表
     * @param head 添加的头
     * @return true:成功, false:失败
    '''
    def tool_write_raw_data_485_h(self, data, head):
        return self.client.tool_write_raw_data_485_h(data, head)

    '''
     * @brief 末端485写原生数据, 将value中的数据加上头head和尾tail写入485端口
     * @param data 写入的数据列表
     * @param head 添加的头
     * @param tail 添加的尾
     * @return true:成功, false:失败
    '''
    def tool_write_raw_data_485_ht(self, data, head, tail):
        return self.client.tool_write_raw_data_485_ht(data, head, tail)

    '''
     * @brief 获取pose_list/joint_list类型系统变量
     * @return pose_list/joint_list类型系统变量名称
    '''

    def get_system_value_lists(self, name):
        return self.client.get_system_value_lists(name)

    '''
     * @brief 当前机器人型号原始DH参数
     * @return 原始DH参数, 参数顺序a, alpha, d, theta, 单位m/rad
    '''

    def get_origin_DH(self):
        return self.client.get_origin_DH()

    '''
     * @brief 当前机器人型号标定补偿后DH参数
     * @return 补偿后DH参数, 参数顺序a, alpha, d, theta, 单位m/rad
    '''

    def get_calib_DH(self):
        return self.client.get_calib_DH()

    '''
    * @brief 修改机器人DH参数
    * @param params 机器人DH参数 a alpha d beta
    '''

    def set_kinematic_calibration_params(self, params):
        return self.client.set_kinematic_calibration_params(params)

    '''
    * @brief 修改SJxx-xx-x.json文件的Fric值和零位
    * @param params Fric值和零位
    '''

    def set_dynamic_calibration_params(self, params):
        return self.client.set_dynamic_calibration_params(params)

    '''
     * @brief 获取机器人零位
     * @return 机器人零位
    '''

    def get_pos_bias(self):
        return self.client.get_pos_bias()  

    '''
    * @brief 获取SJxx-xx-x.json文件的Fric值和零位
    * @param params Fric值和零位
    '''

    def get_dynamic_calibration_params(self):
        return self.client.get_dynamic_calibration_params()

    '''
    * @brief 设置运动学标定识别码
    * @param passwd 密码
    * @param version 版本号
    '''

    def set_kinematic_calibration_info(self, passwd, version):
        return self.client.set_kinematic_calibration_info(passwd, version)

    '''
    * @brief 设置动力学标定识别码
    * @param passwd 密码
    * @param version 版本号
    '''

    def set_dynamic_calibration_info(self, passwd, version):
        return self.client.set_dynamic_calibration_info(passwd, version)

    '''
    * @brief 设置震动标定识别码
    * @param passwd 密码
    * @param version 版本号
    '''

    def set_vibration_calibration_info(self, passwd, version):
        return self.client.set_vibration_calibration_info(passwd, version)

    '''
    * @brief 修改传感器零位
    * @param active 是否修改对应自由度零位
    * @param bias_param 传感器零位
    '''

    def set_dynamic_bias_params(self, active, bias_param):
        return self.client.set_dynamic_bias_params(active, bias_param)

    '''
    * @brief 设置辨识的动力学惯量参数最小线性组合
    * @param min_params 惯量参数最小线性组合
    * @param g 重力方向
    * @return 任务结束时的状态
    '''
    def set_dynamic_calibration_minparams(self, min_params, g):
        return self.client.set_dynamic_calibration_minparams(min_params, g)

    '''
    * @brief 获取辨识的动力学惯量参数最小线性组合
    * @param min_params 惯量参数最小线性组合
    * @return 任务结束时的状态
    '''
    def get_dynamic_calibration_minparams(self):
        return self.client.get_dynamic_calibration_minparams()

    '''
    * @brief save辨识的动力学惯量参数最小线性组合
    * @param min_params 惯量参数最小线性组合
    * @return 任务结束时的状态
    '''
    def save_dynamic_calibration_minparams(self, passwd):
        return self.client.save_dynamic_calibration_minparams(passwd)

    '''
    * @brief 获取机器人重力方向
    * @param params 重力方向
    * @return 任务结束时的状态
    '''
    def get_dynamic_g(self):
        return self.client.get_dynamic_g()

    '''
     * @brief 控制机械臂开启末端力控.开启末端力控后所有运动函数除正常运动外,
	 *        会额外基于已配置的末端力控参数进行末端力控运动
     * @return 返回值代表当前任务的id信息
     '''

    def fc_start(self):
        return self.client.fc_start()

    '''
     * @brief 控制机械臂退出末端力控
     * @return 当前任务的id信息
     '''

    def fc_stop(self):
        return self.client.fc_stop()

    '''
     * @brief 修改并配置机器人末端力控参数
     * @param direction 6个笛卡尔空间方向末端力控开关, 开为true, 关为false
     * @param ref_ft 6个笛卡尔空间方向末端力控参考力, 范围[-1000, 1000], X/Y/Z方向单位: N, 
	                 RX/RY/RZ方向单位: Nm, 方向符号参考末端力控参考坐标系方向
     * @param damp  6个笛卡尔空间方向末端力控阻尼, 范围[-10000, 10000], 
	 *              X/Y/Z方向单位: N/(m/s), RX/RY/RZ方向单位: Nm/(°/s)
     * @param max_vel 6个笛卡尔空间方向末端力控最大调整速度, 范围[-5, 5], X/Y/Z方向单位: m/s, 
	 *                范围[-2*PI, 2*PI], RX/RY/RZ方向单位: rad/s
     * @param dead_zone 6个笛卡尔空间方向末端与环境接触力死区, 范围[-1000, 1000], 
	 *                     X/Y/Z方向单位: N, RX/RY/RZ方向单位: Nm
     * @param toolname 设置使用的末端力控工具的名称, 默认为当前使用的工具
     * @param wobjname 设置使用的末端力控工件坐标系的名称, 默认为当前使用的工件坐标系
     * @param value 末端力控参考坐标系选择标志位, 0为参考工具坐标系, 1位参考工件坐标系
     * @return 当前任务的id信息
     '''

    def fc_config(self, direction, ref_ft, damp, max_vel, dead_zone, toolname, wobjname, value):
        return self.client.fc_config(direction, ref_ft, damp, max_vel, dead_zone, toolname, wobjname, value)

    '''
     * @brief 控制机械臂仅产生末端力控运动
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回, 默认为false
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def fc_move(self, block=False):
        return self.client.fc_move(block)

    '''
     * @brief 控制机械臂在末端力控过程中进行力安全监控
     * @param direction 6个笛卡尔空间方向末端力安全监控开关, 开为true, 关为false
     * @param ref_ft 6个笛卡尔空间方向末端力安全监控参考力, X/Y/Z方向单位: N, RX/RY/RZ方向单位: Nm, 
	 *               方向符号参考末端力安全监控参考坐标系方向
     * @param toolname 设置使用的末端力安全监控工具的名称
     * @param wobjname 设置使用的末端力安全监控工件坐标系的名称
     * @param type 末端力安全监控参考坐标系选择标志位, 0为参考工具坐标系, 1位参考工件坐标系
     * @param force_property 监控力属性, 0为末端负载力及外力, 1为末端外力(不含负载),可缺省, 默认为0
     * @return 当前任务的id信息
     '''

    def fc_guard_act(self, direction, ref_ft, toolname, wobjname, type, force_property=0):
        return self.client.fc_guard_act(direction, ref_ft, toolname, wobjname, type, force_property)

    '''
     * @brief 控制机械臂在末端力控过程中禁用力安全监控
     * @return 当前任务的id信息
     '''

    def fc_guard_deact(self):
        return self.client.fc_guard_deact()

    '''
     * @brief 控制机械臂末端力传感器读数设置为指定值
     * @param direction 6个末端力传感器输出力设置标志位, 需要设置为true, 不需要设置为false
     * @param ref_ft 6个末端力传感器输出力设置目标值, X/Y/Z方向单位: N, RX/RY/RZ方向单位: Nm
     * @return 当前任务的id信息
     '''

    def fc_force_set_value(self, direction, ref_ft):
        return self.client.fc_force_set_value(direction, ref_ft)

    '''
     * @brief 控制机械臂在执行fc_start()函数后的末端力控过程中满足指定位置判断条件时自动停止当前运动函数并调过后续运动函数, 
	 *        直到fc_stop()函数被执行停止末端力控
     * @param middle 位置判断条件绝对值, X/Y/Z方向单位: m, RX/RY/RZ方向单位: rad
     * @param range  位置判断条件偏移范围大小, X/Y/Z方向单位: m, RX/RY/RZ方向单位: rad
     * @param absolute 绝对/增量条件判断标志位, true为绝对位置判断, false为增量位置判断
     * @param duration 条件满足触发保持时间, 单位: ms
     * @param timeout  条件满足触发超时时间, 单位: ms
     * @return 当前任务的id信息
     '''

    def fc_wait_pos(self, middle, range, absolute, duration, timeout):
        return self.client.fc_wait_pos(middle, range, absolute, duration, timeout)

    '''
     * @brief 控制机械臂在执行fc_start()函数后的末端力控过程中满足指定速度判断条件时自动停止当前运动函数并跳过后续运动函数, 
	 *        直到fc_stop()函数被执行停止末端力控
     * @param middle 速度判断条件绝对值, X/Y/Z方向范围[-5, 5], 单位: m/s, RX/RY/RZ方向范围[-2*PI, 2*PI], 单位: rad/s
     * @param range  速度判断条件偏移范围大小, X/Y/Z方向单位: m/s, RX/RY/RZ方向单位: rad/s
     * @param absolute 绝对/增量条件判断标志位, true为绝对速度判断, false为增量速度判断
     * @param duration 条件满足触发保持时间, 单位: ms
     * @param timeout  条件满足触发超时时间, 单位: ms
     * @return 当前任务的id信息
     '''

    def fc_wait_vel(self, middle, range, absolute, duration, timeout):
        return self.client.fc_wait_vel(middle, range, absolute, duration, timeout)

    '''
     * @brief 控制机械臂在执行fc_start()函数后的末端力控过程中满足指定力判断条件时自动停止当前运动函数并跳过后续运动函数, 
	 *        直到fc_stop()函数被执行停止末端力控
     * @param middle 力判断条件绝对值, 范围[-1000, 1000], X/Y/Z方向单位: N, RX/RY/RZ方向单位: Nm
     * @param range  力判断条件偏移范围大小, X/Y/Z方向单位: N, RX/RY/RZ方向单位: Nm
     * @param absolute 绝对/增量条件判断标志位, true为绝对力判断, false为增量力判断
     * @param duration 条件满足触发保持时间, 单位: ms
     * @param timeout  条件满足触发超时时间, 单位: ms
     * @return 当前任务的id信息
     '''

    def fc_wait_ft(self, middle, range, absolute, duration, timeout):
        return self.client.fc_wait_ft(middle, range, absolute, duration, timeout)

    '''
     * @brief 控制机械臂在执行fc_start()函数后的末端力控过程中位置条件判断、速度条件判断与力条件判断间的逻辑关系.不配置时默认三个条件判断都禁用
     * @param value 三维整形列表, 0代表不启用, 1代表与逻辑, 2代表或逻辑.例如开启位置条件判断, 禁用速度条件判断, 开启力条件判断, 并且位置与力的关系为或, 则输入[1,0,2]
     * @return 当前任务的id信息
     '''

    def fc_wait_logic(self, value):
        return self.client.fc_wait_logic(value)

    '''
     * @brief 获取当前机器人末端传感器的反馈读数
     * @return 6自由度末端力读数, X/Y/Z方向单位: N, RX/RY/RZ方向单位: Nm
     '''

    def fc_get_ft(self):
        return self.client.fc_get_ft()

    '''
     * @brief 获取当前机器人末端力控功能启用状态
     * @return 机器人末端力控启用返回true, 未启用返回false
     '''

    def fc_mode_is_active(self):
        return self.client.fc_mode_is_active()


    '''
     * @brief 修改伺服参数
     * @param axis_num 关节索引号
     * @param id       参数的ID号
     * @param value    要设置的值
     * @param qfmt     要设置的qfmt值
     * @param block    指令是否阻塞型指令, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def set_servo_config(self, axis_num, id, value, qfmt):
        return self.client.set_servo_config(axis_num, id, value, qfmt)

    '''
     * @brief 将伺服参数应用到实际控制
     * @param axis_num 关节索引号
     * @param block 指令是否阻塞型指令, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def apply_servo_config(self, axis_num, block):
        return self.client.apply_servo_config(axis_num, block)

    '''
     * @brief 获取电机极对数
     * @return 电机极对数
     '''

    def get_motor_pole_pair_number(self):
        return self.client.get_motor_pole_pair_number()

    '''
     * @brief 获取机器人轴电机定子插槽编号
     * @return 轴电机定子插槽编号
     '''

    def get_motor_stator_slots(self):
        return self.client.get_motor_stator_slots()

    '''
     * @brief 获取机器人轴减速器比率
     * @return 轴减速器比率
     '''

    def get_axis_ratio(self):
        return self.client.get_axis_ratio()


    '''
     * @brief 手自动模式切换
     * @param mode 0:手动模式, 1:自动模式.
     * @return 阻塞执行代表任务结束时状态
     '''

    def switch_mode(self, mode):
        return self.client.switch_mode(mode)

    '''
     * @brief 获取机器人关节重力扭矩
     * @param _return 关节重力扭矩
    '''
    def get_joint_gravtorque(self):
        return self.client.get_joint_gravtorque()

    '''
     * @brief 获取机器人关节辅助位置
     * @param _return 关节辅助位置
    '''
    def get_auxiliary_position(self):
        return self.client.get_auxiliary_position()

    '''
     * @brief 获取机器人关节动态扭矩
     * @param num _return 关节动态扭矩
    '''
    def get_joint_dynamic_torque(self):
        return self.client.get_joint_dynamic_torque()

    '''
     * @brief 获取机器人碰撞状态
     * @param _return true：碰撞，false：未碰撞
    '''
    def get_collision_state(self):
        return self.client.get_collision_state()

    '''
     * @brief 获取机器人碰撞轴
     * @param _return 序号
    '''
    def get_collision_num(self):
        return self.client.get_collision_num()


    '''
     * @brief 获取机器人系列号, 型号, ext, SN
     * @param type 机器人系列号, 型号, ext, SN
    '''

    def get_robot_type(self):
        return self.client.get_robot_type()

    '''
     * @brief 获取关节外力矩
     * @param torque 关节外力矩
    '''

    def get_ext_torque(self):
        return self.client.get_ext_torque()

    '''
    * @brief 修改底层伺服配置文件的参数
    * @param axis_num 关节索引号
    * @param id       参数的ID号
    * @param name     参数的名称
    * @param value    要设置的值
    * @param qfmt     要设置的qfmt值
    * @return 任务结束时状态
    '''
    def set_servo_file_params(self, axis_num, id, name, value, qfmt):
        return self.client.set_servo_file_params(axis_num, id, name, value, qfmt)

    '''
     * @brief 获取震动参数
     * @param params 震动参数
    '''

    def get_vibration_calibration_params(self):
        return self.client.get_vibration_calibration_params()

    '''
    * @brief 保存运动学参数到文件
    * @param passwd 密码
    '''

    def save_kinematic_calibration_params(self, passwd):
        return self.client.save_kinematic_calibration_params(passwd)

    '''
    * @brief 保存动力学参数到文件
    * @param passwd 密码
    '''
    def save_dynamic_calibration_params(self, passwd):
        return self.client.save_dynamic_calibration_params(passwd)


    def save_stiffness_calibration_params(self, passwd):
        return self.client.save_stiffness_calibration_params(passwd)

    def get_stiffness_calibration_params(self):
        return self.client.get_stiffness_calibration_params()

    def set_stiffness_calibration_params(self, params):
        return self.client.set_stiffness_calibration_params(params)

    '''
     * @brief 获取机械臂各关节默认速度加速度
     * @return  关节默认速度加速度列表, 单位: rad/s, rad/s^2
    '''

    def get_joint_motion_params(self):
        return self.client.get_joint_motion_params()

    '''
     * @brief 设置机械臂的安装方式
     * @param installation 安装方式。 6个元素
     * @return  返回值代表当前任务结束时的状态
    '''
    def set_installation(self,installation):
        return self.client.set_installation(installation)

    '''
     * @brief set_tool_digital_out
     * @param num   机械臂末端的IO输出口序号, 范围从1-2
     * @param value true为高电平, false为低电平
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
    '''
    def set_tool_digital_out(self, num, value, block):
        return self.client.set_tool_digital_out(num, value, block)
    
    '''
     * @brief 读取机械臂末端的IO输入口的高低电平, 返回true为高电平, false为低电平
     * @param num 机械臂末端的IO输出口序号, 范围从1-2
     * @return true为高电平, false为低电平
    '''
    def get_tool_digital_in(self, num):
        return self.client.get_tool_digital_in(num)

    '''
     * @brief 读取机械臂末端的IO输入口的高低电平, 返回true为高电平, false为低电平
     * @param num 机械臂末端的IO输出口序号, 范围从1-2
     * @return true为高电平, false为低电平
    '''    
    def get_tool_digital_out(self, num):
        return self.client.get_tool_digital_out(num)

    def fc_set_mode(self, mode):
        return self.client.fc_set_mode(mode)

    def fc_config_joint(self, direction, damp, stiff):
        return self.client.fc_config_joint(direction, damp, stiff)
    
    '''
     * @brief 控制机器人进入牵引示教模式
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''
     
    def teach_mode(self, block):
        return self.client.teach_mode(block)

    '''
     * @brief 控制机器人退出牵引示教模式
     * @param block 是否阻塞, 如果为false表示非阻塞指令, 指令会立即返回
     * @return 阻塞执行代表任务结束时状态, 非阻塞执行代表任务的ID
     '''

    def end_teach_mode(self, block):
        return self.client.end_teach_mode(block)

    '''
     * @brief 同步机器人参数到末端
     * @param passwd 密码
    '''

    def upload_robot_param_to_toolboard(self, passwd):
        return self.client.upload_robot_param_to_toolboard(passwd)

    '''
     * @brief 开启servo运动优化相关功能
     * @param vel_limit 是否开启关节速度保护
     * @param pos_limit 是否开启关节位置保护
     * @param kine_limit 是否开启运动学求解保护
     * @return 任务结束时状态
    '''
    def enable_servo_optimization(self, vel_limit, pos_limit, kine_limit):
        return self.client.enable_servo_optimization(vel_limit, pos_limit, kine_limit)

    '''
     * @brief 关闭servo运动优化相关功能
     * @return 任务结束时状态
    '''
    def disable_servo_optimization(self,):
        return self.client.disable_servo_optimization()