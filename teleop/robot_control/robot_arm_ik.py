import numpy as np
from teleop.log_manager import get_logger

_logger = get_logger(__name__)


class RICO_ArmIK:
    """
    RICO 机械臂 逆运动学(IK) 兼容层
    """

    def __init__(self):
        self._warned = False

    def solve_ik(self, left_target, right_target, current_lr_arm_q=None, current_lr_arm_motor_dq=None):
        """兼容主流程的 IK 接口。

        当前实现优先直接返回当前关节值,保证位姿伺服主流程不受影响；
        后续若接入IK,在这里替换解算逻辑。
        """
        # 当前实现优先复用当前关节值
        if current_lr_arm_q is not None:
            current_lr_arm_q = np.asarray(current_lr_arm_q, dtype=np.float64)
            if current_lr_arm_q.shape == (2, 7):
                return current_lr_arm_q.copy()
        
        # 无有效关节输入时返回零矩阵，并提醒一次
        if not self._warned:
            _logger.warning("RICO_ArmIK 当前使用兼容占位实现,后续可继续替换为完整 IK.")
            self._warned = True
        
        return np.zeros((2, 7), dtype=np.float64)
