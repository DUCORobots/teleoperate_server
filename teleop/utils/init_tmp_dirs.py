#!/usr/bin/env python3
"""临时目录初始化脚本

默认把数据目录视为项目根xr_teleoperate_rico/ 目录下的 data/ 目录，
可显式 --base-dir 覆盖。
"""

import sys
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # utils/ -> teleop/ -> 项目根
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def init_tmp_dirs(base_dir: str = None):
    """初始化临时目录结构

        base_dir: 数据目录路径,None 时默认到项目根的 data/
    """
    base_path = Path(base_dir).expanduser().resolve() if base_dir else DEFAULT_DATA_DIR
    tmp_dir = base_path.parent / "tmp"

    # 创建主临时目录
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 创建导出目录
    export_dir = tmp_dir / "exports"
    export_dir.mkdir(exist_ok=True)

    # 创建导入目录
    import_dir = tmp_dir / "imports"
    import_dir.mkdir(exist_ok=True)

    # 创建 .gitignore 文件
    gitignore_path = tmp_dir / ".gitignore"
    with open(gitignore_path, "w", encoding="utf-8") as f:
        f.write("# 临时文件，不应提交到版本控制\n")
        f.write("*\n")
        f.write("!.gitignore\n")

    print(f"临时目录结构已创建:")
    print(f"  - 项目根: {PROJECT_ROOT}")
    print(f"  - 数据目录: {base_path}")
    print(f"  - 主目录: {tmp_dir}")
    print(f"  - 导出目录: {export_dir}")
    print(f"  - 导入目录: {import_dir}")
    print(f"  - .gitignore: {gitignore_path}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="初始化导入导出功能的临时目录",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="基础数据目录路径。默认走项目根的 data/ 目录",
    )

    args = parser.parse_args()

    try:
        init_tmp_dirs(args.base_dir)
        print("\n初始化成功!")
        return 0
    except Exception as e:
        print(f"\n初始化失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
