# DUCOROBOTS RICO XR Teleoperation System — Quick Start Guide

[中文](QUICKSTART_zh.md) | [English](QUICKSTART.md)

> This document is a quick start guide containing only the core installation and startup steps. For complete configuration details, API references, and code structure, please refer to the [full documentation](README.md).

---

## Table of Contents

- [DUCOROBOTS RICO XR Teleoperation System — Quick Start Guide](#ducorobots-rico-xr-teleoperation-system--quick-start-guide)
  - [Table of Contents](#table-of-contents)
- [1. System Requirements](#1-system-requirements)
- [2. Installation](#2-installation)
  - [2.1 Base Environment](#21-base-environment)
  - [2.2 Vision Server](#22-vision-server)
  - [2.3 Certificate Generation](#23-certificate-generation)
  - [2.4 Firewall](#24-firewall)
- [3. Quick Start](#3-quick-start)
  - [3.1 Start Vision Server](#31-start-vision-server)
  - [3.2 Start Teleoperation](#32-start-teleoperation)
  - [3.3 XR Headset Connection](#33-xr-headset-connection)
- [4. Controls](#4-controls)
  - [4.1 XR Controller Operations](#41-xr-controller-operations)
  - [4.2 State Machine](#42-state-machine)
- [5. CLI Arguments Quick Reference](#5-cli-arguments-quick-reference)
- [6. FAQ](#6-faq)

---

# 1. System Requirements

| Item | Requirement |
|------|-------------|
| OS | Ubuntu 22.04 LTS (ARM64 / X86) |
| ROS2 | Humble |
| Python | 3.10+ |
| Camera | RealSense D435 / D405, etc. |

---

# 2. Installation

## 2.1 Base Environment

> **Note:**
> Ensure that the top-level directory is xr_teleoperate_rico, i.e. 'teleop/'. The top-level directory is '/path/to/xr_teleoperate_rico '. The following commands and code are executed based on this directory.


```bash
# Install Miniconda3
mkdir -p ~/miniconda3
# wget command: choose one for ARM64 or X86
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O ~/miniconda3/miniconda.sh #ARM64
# wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh #X86_64
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
source ~/miniconda3/bin/activate
conda init --all
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Configure Tsinghua mirror (architecture-independent)
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
conda config --set show_channel_urls yes

# Create Python environment
conda create -n rico_xr python=3.10 numpy=1.26.4 -y
conda activate rico_xr

# Install dependencies and run in conda environment
cd /path/to/xr_teleoperate_rico
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 2.2 Vision Server

```bash
# Add ROS2 repository
sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | \
    sudo gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
    https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu jammy main" | \
    sudo tee /etc/apt/sources.list.d/ros2.list

# Install ROS2 dependencies for running in a non-conda environment
sudo apt update
sudo apt install ros-humble-desktop \
    ros-humble-sensor-msgs \
    ros-humble-vision-msgs \
    ros-humble-tf2-ros \
    ros-humble-image-transport \
    v4l-utils \
    python3-colcon-common-extensions \
    protobuf-compiler

# Compile Protobuf
cd teleop/teleimager/humanoid_vision_system_ws/src/humanoid_vision_system
bash scripts/compile_proto.sh

# Build workspace and run it in a non-conda environment
cd ../../   # back to humanoid_vision_system_ws/
source /opt/ros/humble/setup.bash
rm -rf build/ install/ log/
colcon build --packages-select humanoid_vision_system
source install/setup.bash

cd ../ # Back to the teleop/teleimager/ directory
cp -r humanoid_vision_system_ws/src/humanoid_vision_system/vision_system/proto src/teleimager/
```

## 2.3 Certificate Generation

```bash
# Install mkcert
mkdir -p humanoid_vision_system_ws/download
cd humanoid_vision_system_ws/download
sudo apt install libnss3-tools
# arm64 architecture
curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/arm64"
chmod +x mkcert-v*-linux-arm64 # replace with your downloaded filename
sudo mv mkcert-v*-linux-arm64 /usr/local/bin/mkcert
# X86 architecture certificate installation
# curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
# chmod +x mkcert-v*-linux-amd64
# sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
mkcert -install

# Generate certificate (replace with your actual IP)
mkcert <your-ip> localhost

# Deploy certificate
mkdir -p ~/.config/xr_teleoperate
cp <your-ip>+1.pem ~/.config/xr_teleoperate/cert.pem
cp <your-ip>+1-key.pem ~/.config/xr_teleoperate/key.pem
# Replace the 'cert.pem' and 'key.pem' files in the xr_teleoperate_rico/teleop/televuer/ directory by yourself, eg:
cp <your-ip>+1.pem ../../../televuer/cert.pem
cp <your-ip>+1-key.pem ../../../televuer/key.pem
```

## 2.4 Firewall

```bash
sudo apt install ufw
sudo ufw allow 8012   # TeleVuer HTTPS/WSS
sudo ufw allow 8000   # FastAPI
sudo ufw allow 60000  # Vision server configuration
sudo ufw allow 5555   # ZMQ image streams (open all required ports)
```

---

# 3. Quick Start

## 3.1 Start Vision Server

```bash
cd teleop/teleimager/humanoid_vision_system_ws

conda activate rico_xr
source /opt/ros/humble/setup.bash
source install/setup.bash

# Automatically detect camera startup and run in conda environment
ros2 run humanoid_vision_system vision_system_main.py --auto-detect

# Use manual configuration and run in the conda environment
ros2 run humanoid_vision_system vision_system_main.py --no-auto-detect
```

> Manual configuration requires editing `manual_config/manual_camera.json` first. See [full documentation section 4.3](README.md#43-manual_camerajson-visual-configuration).

## 3.2 Start Teleoperation

```bash
cd /path/to/xr_teleoperate_rico

conda activate rico_xr

# Default startup, run in conda environment
python3 teleop/teleop_hand_and_arm.py

# Common variants
python3 teleop/teleop_hand_and_arm.py --headless               # Disable local preview window
python3 teleop/teleop_hand_and_arm.py --sim                    # Simulation mode (no hardware)
python3 teleop/teleop_hand_and_arm.py --full-body              # Full-body humanoid robot, affects waist control
python3 teleop/teleop_hand_and_arm.py --no-waist               # Disable waist control
python3 teleop/teleop_hand_and_arm.py --no-head                # Disable head control
python3 teleop/teleop_hand_and_arm.py --image-server-ip <IP>   # Specify image server IP
python3 teleop/teleop_hand_and_arm.py --no-image-server        # Disable image server
```
> Disable Image Server: If the `runtime.enable_image_server` in the configuration item `config/system.json` is set to `true`, the image server will be enabled by default. If the `--no-image-server` is added, the image server will be disabled. The remote control main program will run in no image mode and will not affect robot remote control. Data recording will only record robot data. At this time, the `xr.display mode` in `config/system.json` should be modified to `pass—through`


## 3.3 XR Headset Connection

1. Ensure the XR headset and Host are on the same local network
2. Open in the headset browser: `https://<host-ip>:8012/?ws=wss://<host-ip>:8012`
3. Trust the certificate warning (first connection only)
4. Click `Virtual Reality` and allow XR permissions
5. The terminal will show `websocket is connected` when the connection is established

---

# 4. Controls

## 4.1 XR Controller Operations

| Action | Button | Valid State | Function |
|--------|--------|-------------|----------|
| Wake Up | Right A | INACTIVE | Wake up and home, then enter IDLE |
| Exit | Right B | IDLE / ACTIVE_CONTROL | Exit teleoperation, home then enter INACTIVE |
| Start/Stop Teleop | Left X | IDLE / ACTIVE_CONTROL | Start or stop teleoperation |
| Toggle Recording | Left Y | ACTIVE_CONTROL | Toggle recording on/off |
| Manual Home | Left X+Y | IDLE / ACTIVE_CONTROL | Home, then enter IDLE |
| Press/Release | Left Hand Trigger | ACTIVE_CONTROL Only | Switch based on trigger status, Press = grip, Release = release (requires dexterous hand) |
| Press/Release | Right Hand Trigger | ACTIVE_CONTROL Only | Switch based on trigger status, press = grip, release = release (requires dexterous hand) |
| Squat/Stand | XR Headset & Controller | ACTIVE_CONTROL Only | Body lifting (full-body robot only, requires waist control enabled) |
| Move forward/backward | XR Headset & Controller | ACTIVE_CONTROL Only | Forward leaning/backward sitting movement (only applicable to the whole body, waist control needs to be turned on, not recommended) |
| Nod/Tilt Head | XR Headset & Controller | ACTIVE_CONTROL Only | Body pitch (full-body robot only, requires waist control enabled) |
| Head twisting | XR Headset & Controller | ACTIVE_CONTROL Only | Waist rotation |
| Move Arms | XR Controller | ACTIVE_CONTROL only | Head movement (requires head control enabled) |
| Emergency Stop | Keyboard e | Any non-INACTIVE state | Home then enter INACTIVE |

> Note:
> Try not to perform forward or backward movement operations, and keep the position of the human body fixed for operation
> For detailed information on waist and head control, please refer to [Complete document Section 3.3](README.md#33-Launch-Teleoperation-on-Host) and [Complete document Section 4.1.2](README.md#412-Runtime-Configuration). By default, waist control and head control are enabled.

## 4.2 State Machine

```
INACTIVE ──[Right A]──> RETURNING_HOME ──> IDLE ──[Left X]──> ACTIVE_CONTROL
   ▲                        ▲                 │                    │
   │                        │                 │                    │
   └──[Right B / Key e]─────┘    [Left X+Y] ───┘    [Left X] ───────┘
```

| State | Description |
|-------|-------------|
| INACTIVE | Sleeping, waiting for wake-up |
| RETURNING_HOME | Homing in progress |
| IDLE | Ready, can start teleoperation |
| ACTIVE_CONTROL | Teleoperation active, recording available |

---

# 5. CLI Arguments Quick Reference

| Argument | Description | Default |
|----------|-------------|---------|
| `--config-dir` | Configuration directory | `./config` |
| `--task-dir` | Recording output directory | `system.paths.task_dir` |
| `--headless` | Disable local preview | Off |
| `--full-body` | Full-body humanoid robot mode | Off |
| `--sim` | Simulation mode | Off |
| `--no-head` | Disable head control | Follow `runtime.head_enabled_default` |
| `--no-waist` | Disable waist control | Follow `runtime.waist_enabled_default` |
| `--image-server-ip` | Image server IP | `system.network.image_server_ip` |
| `--frequency` | Main loop frequency | `system.runtime.frequency` |.
| `--no-image-server` | Disable image server | Follow `runtime.enable_image_server` |

---

# 6. FAQ

**Q: XR headset cannot connect, port 8012 is occupied?**

A: Check that the firewall allows port 8012, verify that the certificate has been correctly generated and deployed, and ensure the port is not occupied when enabling.
```
eg:
Check for processes using port 8012
sudo lsof -i :8012
Kill the process occupying the port
kill -9 <PID>
```

**Q: Camera cannot be opened?**

A: Check that the camera is properly connected. Run `rs-enumerate-devices` to confirm the device is visible. Verify that the `serial_number` in `manual_camera.json` is correct.

**Q: How to modify camera resolution, compression parameters, etc.?**

A: Edit `teleop/teleimager/humanoid_vision_system_ws/manual_config/manual_camera.json`. See [full documentation section 4.3](README.md#43-manual_camerajson-visual-configuration).

**Q: How to customize robot parameters?**

A: Edit `config/system.json` and `config/robot.json`. See [full documentation sections 4.1-4.2](README.md#4-configuration).

---

> For more detailed content (configuration, API references, code structure, etc.), please refer to the [full documentation](README.md).