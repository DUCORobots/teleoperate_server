# DUCOROBOTS RICO XR 遥操作系统 — 快速使用指南

[中文](README_zh.md) | [English](README.md)

> 本文档为快速使用指南，仅包含核心安装与启动步骤。完整配置说明、API 接口、代码结构等内容请参阅 [完整文档](README_zh.md)。

---

## 目录

- [DUCOROBOTS RICO XR 遥操作系统 — 快速使用指南](#ducorobots-rico-xr-遥操作系统--快速使用指南)
  - [目录](#目录)
- [1. 系统要求](#1-系统要求)
- [2. 安装](#2-安装)
  - [2.1 基础环境](#21-基础环境)
- [安装 Miniconda3](#安装-miniconda3)
  - [2.2 视觉服务端](#22-视觉服务端)
  - [2.3 证书生成](#23-证书生成)
  - [2.4 防火墙](#24-防火墙)
- [3. 快速启动](#3-快速启动)
  - [3.1 启动视觉服务端](#31-启动视觉服务端)
  - [3.2 启动遥操作](#32-启动遥操作)
  - [3.3 XR 头显连接](#33-xr-头显连接)
- [4. 操作说明](#4-操作说明)
  - [4.1 XR 手柄操作](#41-xr-手柄操作)
  - [4.2 状态机](#42-状态机)
- [5. 启动参数速查](#5-启动参数速查)
- [6. 常见问题](#6-常见问题)

---

# 1. 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 22.04 LTS（ARM64 / X86） |
| ROS2 | Humble |
| Python | 3.10+ |
| 相机 | RealSense D435 / D405 等 |

---

# 2. 安装

## 2.1 基础环境
> **注意：** 
> 保证顶层目录为 xr_teleoperate_rico 即`teleop/`上层目录为`/path/to/xr_teleoperate_rico`, 下述命令及代码均基于此目录运行

# 安装 Miniconda3

```bash
# 安装 Miniconda3
mkdir -p ~/miniconda3
#下载命令 ARM64 架构和 X86 架构二选一
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O ~/miniconda3/miniconda.sh #ARM64
# wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh #X86_64
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
source ~/miniconda3/bin/activate
conda init --all
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 配置清华镜像源，架构通用
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
conda config --set show_channel_urls yes

# 创建 Python 环境
conda create -n rico_xr python=3.10 numpy=1.26.4 -y
conda activate rico_xr

# 安装依赖,conda环境下运行
cd /path/to/xr_teleoperate_rico
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 2.2 视觉服务端

```bash
# 添加 ROS2 源
sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | \
    sudo gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
    https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu jammy main" | \
    sudo tee /etc/apt/sources.list.d/ros2.list

# 安装 ROS2 依赖，非conda环境下运行
sudo apt update
sudo apt install ros-humble-desktop \
    ros-humble-sensor-msgs \
    ros-humble-vision-msgs \
    ros-humble-tf2-ros \
    ros-humble-image-transport \
    v4l-utils \
    python3-colcon-common-extensions \
    protobuf-compiler

# 编译 Protobuf
cd teleop/teleimager/humanoid_vision_system_ws/src/humanoid_vision_system
bash scripts/compile_proto.sh

# 构建工作空间，非conda环境下运行
cd ../../   # 回到 humanoid_vision_system_ws/
source /opt/ros/humble/setup.bash
rm -rf build/ install/ log/
colcon build --packages-select humanoid_vision_system
source install/setup.bash

cd ../ #回到teleop/teleimager/目录
cp -r humanoid_vision_system_ws/src/humanoid_vision_system/vision_system/proto src/teleimager/
```

## 2.3 证书生成

```bash
# 安装 mkcert
mkdir -p humanoid_vision_system_ws/download
cd humanoid_vision_system_ws/download
sudo apt install libnss3-tools
# arm64架构
curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/arm64"
chmod +x mkcert-v*-linux-arm64 #替换为你下载的文件名
sudo mv mkcert-v*-linux-arm64 /usr/local/bin/mkcert
# X86 架构证书安装
# curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
# chmod +x mkcert-v*-linux-amd64
# sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
mkcert -install

# 生成证书（替换为实际 IP）
mkcert <your-ip> localhost

# 部署证书
mkdir -p ~/.config/xr_teleoperate
cp <your-ip>+1.pem ~/.config/xr_teleoperate/cert.pem
cp <your-ip>+1-key.pem ~/.config/xr_teleoperate/key.pem
# xr_teleoperate_rico/teleop/televuer/ 目录下的 `cert.pem` 和 `key.pem` 自行替换,eg:
cp <your-ip>+1.pem ../../../televuer/cert.pem
cp <your-ip>+1-key.pem ../../../televuer/key.pem
```

## 2.4 防火墙

```bash
sudo apt install ufw
sudo ufw allow 8012   # TeleVuer HTTPS/WSS
sudo ufw allow 8000   # FastAPI
sudo ufw allow 60000  # 视觉服务端配置
sudo ufw allow 5555   # ZMQ 图像流（多端口需都放开）
```

---

# 3. 快速启动

## 3.1 启动视觉服务端

```bash
cd teleop/teleimager/humanoid_vision_system_ws

conda activate rico_xr
source /opt/ros/humble/setup.bash
source install/setup.bash

# 自动检测相机启动,conda环境下运行
ros2 run humanoid_vision_system vision_system_main.py --auto-detect

# 使用手动配置,conda环境下运行
ros2 run humanoid_vision_system vision_system_main.py --no-auto-detect
```

> 手动配置需先编辑 `manual_config/manual_camera.json`，详见 [完整文档 4.3 节](README_zh.md#43-manual_camerajson-视觉配置)。

## 3.2 启动遥操作

```bash
cd /path/to/xr_teleoperate_rico

conda activate rico_xr

# 默认启动,conda环境下运行
python3 teleop/teleop_hand_and_arm.py

# 常用变体
python3 teleop/teleop_hand_and_arm.py --headless               # 关闭本地预览窗口
python3 teleop/teleop_hand_and_arm.py --sim                    # 仿真模式（无硬件）
python3 teleop/teleop_hand_and_arm.py --full-body              # 全身人形整机,影响腰部控制
python3 teleop/teleop_hand_and_arm.py --no-waist               # 禁用腰部控制
python3 teleop/teleop_hand_and_arm.py --no-head                # 禁用头部控制
python3 teleop/teleop_hand_and_arm.py --image-server-ip <IP>   # 指定图像服务端 IP
python3 teleop/teleop_hand_and_arm.py --no-image-server        # 禁用图像服务端
```
> 禁用图像服务端：配置项 `config/system.json` 中的 `runtime.enable_image_server` 为 `true`的前提下启动则默认开启图像服务端，添加 `--no-image-server`，则禁用图像服务端(若图像服务端获取相机配置失败效果相同)，遥操主程序会以无图像模式运行，不影响机器人遥操作，数据录制将只记录机器人数据,此时应修改`config/system.json`中`xr.display_mode`为`pass-through`

## 3.3 XR 头显连接

1. 确保 XR 头显与 Host 在同一局域网
2. 头显浏览器打开：`https://<host-ip>:8012/?ws=wss://<host-ip>:8012`
3. 信任证书警告（首次连接）
4. 点击 `Virtual Reality` 并允许 XR 权限
5. 终端出现 `websocket is connected` 即连接成功

---

# 4. 操作说明

## 4.1 XR 手柄操作

| 操作 | 按键 | 生效状态 | 功能 |
|------|------|---------|------|
| 唤醒 | 右手 A | INACTIVE | 唤醒并回零，完成后进入 IDLE |
| 退出 | 右手 B | IDLE / ACTIVE_CONTROL | 退出遥操作，回零后进入 INACTIVE |
| 开始/停止遥操作 | 左手 X | IDLE / ACTIVE_CONTROL | 开始或停止遥操作 |
| 录制开关 | 左手 Y | ACTIVE_CONTROL | 开启/关闭录制 |
| 手动回零 | 左手 X+Y | IDLE / ACTIVE_CONTROL | 回零，完成后进入 IDLE |
| 按下/松开   | 左手 扳机键 | 仅 ACTIVE_CONTROL   | 根据扳机键状态切换，按下=握持，松开=松开 (需灵巧手) |
| 按下/松开   | 右手 扳机键 | 仅 ACTIVE_CONTROL   | 根据扳机键状态切换，按下=握持，松开=松开 (需灵巧手) |
| 蹲下/站起  | XR头显&手柄 | 仅 ACTIVE_CONTROL             | 身体升降(仅针对全身整机，需开启腰部控制)                 |
| 前后移动  | XR头显&手柄 | 仅 ACTIVE_CONTROL             | 身体前后倾移动(仅针对全身整机，需开启腰部控制)             |
| 俯仰  | XR头显&手柄 | 仅 ACTIVE_CONTROL             | 身体前倾/后坐移动(仅针对全身整机，需开启腰部控制,不建议此操作)   |
| 扭腰  | XR头显&手柄 | 仅 ACTIVE_CONTROL             | 腰部旋转                                                |
| 移动双臂   | XR 手柄 | 仅 ACTIVE_CONTROL           | 头部运动(需开启头部控制)                              |
| 紧急停止 | 键盘 e | 任意非 INACTIVE 态 | 回零后进入 INACTIVE |

> 注意：
> 尽量不要进行前后移动操作，保持人体位置固定进行操作
> 头部和腰部控制详细看 [完整文档 3.3 节](README_zh.md#33-在-Host-启动遥操作) 和 [完整文档 4.1.2 节](README_zh.md#412-runtime-运行时配置)，默认关闭腰部控制,头部控制

## 4.2 状态机

```
INACTIVE ──[右手 A]──> RETURNING_HOME ──> IDLE ──[左手 X]──> ACTIVE_CONTROL
   ▲                        ▲                 │                    │
   │                        │                 │                    │
   └──[右手 B / 键盘 e]─────┘    [左手 X+Y] ───┘    [左手 X] ───────┘
```

| 状态 | 说明 |
|------|------|
| INACTIVE | 休眠，等待唤醒 |
| RETURNING_HOME | 回零中 |
| IDLE | 就绪，可开始遥操作 |
| ACTIVE_CONTROL | 遥操作中，可录制 |

---

# 5. 启动参数速查

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config-dir` | 配置目录 | `./config` |
| `--task-dir` | 录制输出目录 | `system.paths.task_dir` |
| `--headless` | 关闭本地预览 | 关闭 |
| `--full-body` | 全身人形整机模式 | 关闭 |
| `--sim` | 仿真模式 | 关闭 |
| `--no-head` | 禁用头部控制 | `runtime.head_enabled_default` |
| `--no-waist` | 禁用腰部控制 | `runtime.waist_enabled_default` |
| `--image-server-ip` | 图像服务端 IP | `system.network.image_server_ip` |
| `--frequency` | 主循环频率 | `system.runtime.frequency` |
| `--no-image-server` | 禁用图像服务端 | `runtime.enable_image_server` |

---

# 6. 常见问题

**Q: XR 头显无法连接，遥操服务端端口被占用？**

A: 检查防火墙是否放行 8012 端口，确认证书已正确生成和部署,保证启用时端口没有被占用
```
eg:
查找占用 8012 端口的进程
sudo lsof -i :8012
杀掉占用端口的进程
kill -9 <PID>
```

**Q: 相机无法打开？**

A: 检查相机是否正确连接，查看 `rs-enumerate-devices` 输出确认设备可见。检查 `manual_camera.json` 中的 serial_number 是否正确。

**Q: 如何修改相机分辨率、压缩参数等配置？**

A: 编辑 `teleop/teleimager/humanoid_vision_system_ws/manual_config/manual_camera.json`，详见 [完整文档 4.3 节](README_zh.md#43-manual_camerajson-视觉配置)。

**Q: 如何自定义机器人参数？**

A: 编辑 `config/system.json` 和 `config/robot.json`，详见 [完整文档 4.1-4.2 节](README_zh.md#4-配置说明)。

---

> 更多详细内容（配置说明、API 接口、代码结构等）请参阅 [完整文档](README_zh.md)。