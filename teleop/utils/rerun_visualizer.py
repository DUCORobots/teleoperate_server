import os
import rerun as rr
import rerun.blueprint as rrb
from datetime import datetime

os.environ.setdefault("RUST_LOG", "error")

class RerunLogger:
    """基于 Rerun 的在线时序可视化工具"""

    def __init__(self, prefix="", IdxRangeBoundary=30, memory_limit=None):
        self.prefix = prefix
        self.IdxRangeBoundary = IdxRangeBoundary
        rr.init(datetime.now().strftime("Runtime_%Y%m%d_%H%M%S"))
        if memory_limit:
            rr.spawn(memory_limit=memory_limit, hide_welcome_screen=True)
        else:
            rr.spawn(hide_welcome_screen=True)

        # 在线模式默认配置布局
        if self.IdxRangeBoundary:
            self.setup_blueprint()

    def setup_blueprint(self):
        """自定义可视化界面布局"""
        views = []

        data_plot_paths = [
                           f"{self.prefix}left_arm", 
                           f"{self.prefix}right_arm", 
                           f"{self.prefix}left_ee", 
                           f"{self.prefix}right_ee"
        ]
        for plot_path in data_plot_paths:
            view = rrb.TimeSeriesView(
                origin=plot_path,
                time_ranges=[
                    rrb.VisibleTimeRange(
                        "frame_id",
                        start=rrb.TimeRangeBoundary.cursor_relative(seq=-self.IdxRangeBoundary),
                        end=rrb.TimeRangeBoundary.cursor_relative(),
                    )
                ],
                plot_legend=rrb.PlotLegend(visible=True),
            )
            views.append(view)

        grid = rrb.Grid(contents=views,
                        grid_columns=2,               
                        column_shares=[1, 1],
                        row_shares=[1, 1], 
        )
        rr.send_blueprint(grid)


    def log_item_data(self, item_data: dict):
        """记录单帧状态与动作曲线。"""
        rr.set_time_sequence("frame_id", item_data.get('frame_id', 0))

        states = item_data.get('states', {}) or {}
        for part, state_info in states.items():
            if state_info:
                values = state_info.get('qpos', [])
                for i, val in enumerate(values):
                    rr.log(f"{self.prefix}{part}/states/qpos/{i}", rr.Scalar(val))

        actions = item_data.get('actions', {}) or {}
        for part, action_info in actions.items():
            if action_info:
                values = action_info.get('qpos', [])
                for i, val in enumerate(values):
                    rr.log(f"{self.prefix}{part}/actions/qpos/{i}", rr.Scalar(val))