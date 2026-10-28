# DUCOROBOTS RICO XR Teleoperation System

[中文](README_zh.md) | [English](README.md)

This repository implements an integrated XR teleoperation system for the DUCOROBOTS RICO dual-arm robot, supporting Ubuntu 22.04 (ARM64 / X86) deployments. The current code focuses on the components that are fully wired and functional:

| Component                        | Status    | Description                                                   |
| -------------------------------- | --------- | ------------------------------------------------------------- |
| RICO Dual-Arm Teleoperation      | Completed | Driven by `teleop/teleop_hand_and_arm.py` top-level state machine |
| Waist / External Axis Control    | Completed | Can be disabled via `--no-waist` (enabled by default)          |
| Head / External Axis Control    | Completed | Can be disabled via `--no-head` (enabled by default)          |
| BChand Dexterous Hand Control    | Completed | Open/close logic based on trigger / pinch thresholds         |
| TeleImager Multi-Camera Service  | Completed | Supports cameras for the head, wrist, and chest, with ZMQ/WebRTC multi-protocol. The chest camera is only supported locally |
| TeleVuer XR Bridge               | Completed | Provides HTTPS / WSS XR page on port `8012`                  |
| Episode Recording                | Completed | Saves color images, depth images, states and actions to task directories |
| FastAPI Data Management API      | Completed | RESTful API for task management, recording import/export     |
| In-Process Simulation Mode       | Completed | Enabled by `--sim`, reuses XR / recording pipeline, suitable for debugging without hardware |

Roles in a typical deployment:

- `Host`: Runs `python3 teleop/teleop_hand_and_arm.py`, provides TeleVuer and FastAPI.
- `Vision Server`: Runs `humanoid_vision_system_ws`, connects multiple cameras and publishes streams.
- `XR Headset`: Opens the TeleVuer page from the Host, and trusts the image server certificate on first connection as needed.
- `RICO Robot`: Receives dual-arm, waist, head, and dexterous hand control commands from the Host.

Signal chain:

1. `HumanoidVisionSystem` publishes head, wrist, chest color and depth image streams.
2. `ImageClient` reads these streams via ZMQ.
3. `TeleVuer` provides the XR page at `https://<host-ip>:8012/?ws=wss://<host-ip>:8012`.
4. `TeleVuerWrapper` converts XR poses and buttons into robot control targets.
5. `EpisodeWriter` saves image frames and robot states to `data/task_xxxx/episode_xxxx/`.
6. `FastAPI` provides REST APIs for task management and recording import/export.

## Table of Contents

- [DUCOROBOTS RICO XR Teleoperation System](#ducorobots-rico-xr-teleoperation-system)
  - [Table of Contents](#table-of-contents)
- [1. System Requirements](#1-system-requirements)
- [2. Installation](#2-installation)
  - [2.1 Basic Installation](#21-basic-installation)
  - [2.2 TeleImager Vision Server](#22-teleimager-vision-server)
  - [2.3 TeleVuer and Certificates](#23-televuer-and-certificates)
  - [2.4 Environment Variables and Firewall](#24-environment-variables-and-firewall)
- [3. Quick Start](#3-quick-start)
  - [3.1 Start Vision Server](#31-start-vision-server)
  - [3.2 Teleoperation Launch Parameters](#32-teleoperation-launch-parameters)
  - [3.3 Launch Teleoperation on Host](#33-launch-teleoperation-on-host)
  - [3.4 Operation Guide](#34-operation-guide)
    - [FastAPI Control](#fastapi-control)
  - [3.5 State Machine Transition Diagram](#35-state-machine-transition-diagram)
  - [3.6 Hibernation](#36-hibernation)
- [4. Configuration Guide](#4-configuration-guide)
  - [4.1 xr\_teleoperate\_rico/config/system.json](#41-xr_teleoperate_ricoconfigsystemjson)
    - [4.1.1 Network Configuration](#411-network-configuration)
    - [4.1.2 Runtime Configuration](#412-runtime-configuration)
    - [4.1.3 XR/VR Configuration](#413-xrvr-configuration)
    - [4.1.4 Paths Configuration](#414-paths-configuration)
    - [4.1.5 Log Manager Configuration](#415-log-manager-configuration)
    - [4.1.6 Recording Configuration](#416-recording-configuration)
    - [4.1.7 recording.text Task Text Information](#417-recordingtext-task-text-information)
    - [4.1.8 recording.info Dataset Metadata](#418-recordinginfo-dataset-metadata)
  - [4.2 xr\_teleoperate\_rico/config/robot.json](#42-xr_teleoperate_ricoconfigrobotjson)
    - [4.2.1 Robot Body Configuration](#421-robot-body-configuration)
    - [4.2.2 robot.home\_arm\_joint\_deg / robot.home\_arm\_joint\_deg\_p Home Joint Angles(degrees)](#422-robothome_arm_joint_deg--robothome_arm_joint_deg_p-home-joint-anglesdegrees)
    - [4.2.3 robot.home\_head\_rad Head Home Target (radians)](#423-robothome_head_rad-head-home-target-radians)
    - [4.2.4 robot.home\_half\_waist\_rad / robot.home\_full\_waist\_rad Waist Home Target (radians)](#424-robothome_half_waist_rad--robothome_full_waist_rad-waist-home-target-radians)
    - [4.2.5 robot.servo Servo Control Parameters](#425-robotservo-servo-control-parameters)
    - [4.2.6 end\_effector End Effector (Dexterous Hand) Configuration](#426-end_effector-end-effector-dexterous-hand-configuration)
  - [4.3 manual\_camera.json Vision Configuration](#43-manual_camerajson-vision-configuration)
    - [4.3.1 Top-Level Fields](#431-top-level-fields)
    - [4.3.2 Global Configuration](#432-global-configuration)
    - [4.3.3 Common Camera Fields](#433-common-camera-fields)
    - [4.3.4 Streams Video Stream Configuration](#434-streams-video-stream-configuration)
    - [4.3.5 Compression Configuration](#435-compression-configuration)
    - [4.3.6 publisher\_compression Publisher-Level Compression Override](#436-publisher_compression-publisher-level-compression-override)
    - [4.3.7 Communication Configuration](#437-communication-configuration)
      - [ZeroMQ Configuration](#zeromq-configuration)
      - [WebSocket Configuration](#websocket-configuration)
      - [WebRTC Configuration](#webrtc-configuration)
      - [ROS2 Configuration](#ros2-configuration)
    - [4.3.8 Camera Communication Port Quick Reference](#438-camera-communication-port-quick-reference)
    - [4.3.9 Complete Configuration Example](#439-complete-configuration-example)
  - [4.4 global\_config.json Configuration Parameters](#44-global_configjson-configuration-parameters)
- [5. API Reference](#5-api-reference)
- [6. Code Structure](#6-code-structure)
- [7. Acknowledgments](#7-acknowledgments)

---

# 1. System Requirements

- Ubuntu 22.04 LTS (ARM64 or X86)
- ROS2 Humble
- Python 3.10+
- RealSense cameras (supports D435 / D405, etc.)
- Both ARM64 and X86 architectures are supported; dependencies are adapted for dual architectures
- The simplest integration approach is to use a shared Python `3.10` conda environment for Host-side tools

---

# 2. Installation

## 2.1 Basic Installation

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
```

```bash
# Create and activate Python 3.10 environment
conda create -n rico_xr python=3.10 numpy=1.26.4 -y
conda activate rico_xr

# Navigate to repository root
cd /path/to/xr_teleoperate_rico

# Install dependencies and run in conda environment
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 2.2 TeleImager Vision Server

The vision server runs on a separate machine or the same machine, driving multiple cameras via ROS2 or FastAPI.

```bash
# Run outside conda environment
cd /path/to/xr_teleoperate_rico

# Add ROS2 source
# Import ROS 2 GPG Public Key
sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | sudo gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg
# Add Tsinghua ROS 2 image source
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu jammy main" | sudo tee /etc/apt/sources.list.d/ros2.list

# Install ROS2 dependencies
sudo apt update
sudo apt install ros-humble-desktop \
    ros-humble-sensor-msgs \
    ros-humble-vision-msgs \
    ros-humble-tf2-ros \
    ros-humble-image-transport \
    v4l-utils \
    python3-colcon-common-extensions \
    protobuf-compiler

# Compile Protocol Buffers
cd teleop/teleimager/humanoid_vision_system_ws/src/humanoid_vision_system
bash scripts/compile_proto.sh

# Build ROS2 workspace
cd ../../ # back to teleop/teleimager/humanoid_vision_system_ws/ directory
source /opt/ros/humble/setup.bash
rm -rf build/ install/ log/ # ensure directory structure is correct and clean old cache
colcon build --packages-select humanoid_vision_system
source install/setup.bash

cd ../ # Back to the teleop/teleimager/ directory
cp -r humanoid_vision_system_ws/src/humanoid_vision_system/vision_system/proto src/teleimager/
# Note: Ensure the proto files of the vision server and vision client are consistent
```

## 2.3 TeleVuer and Certificates

Certificate search order:

1. `XR_TELEOP_CERT` and `XR_TELEOP_KEY` environment variables
2. `~/.config/xr_teleoperate/cert.pem` and `key.pem`
3. The `cert.pem` and `key.pem` files located in the built-in `xr_teleoperate_rico/teleop/televuer/` directory (only suitable for local testing and need to be replaced with the certificates you generate)

Generate self-signed certificates:

```bash
Install mkcert and generate certificates
# e.g., execute in the download folder to generate certificates, choose one for ARM64 or X86
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

# Generate and install local CA certificate
mkcert -install

# Generate certificate for local IP and localhost
# Note: replace 192.168.120.44 with your actual IP address
mkcert 192.168.120.44 localhost

# Replace certificates (note: mkcert-generated certificate name format: <IP>+<number>.pem)
# e.g.: 192.168.120.44+1.pem, adjust the copy command based on the actual generated filename
mkdir -p ~/.config/xr_teleoperate
cp 192.168.120.44+1.pem ~/.config/xr_teleoperate/cert.pem
cp 192.168.120.44+1-key.pem ~/.config/xr_teleoperate/key.pem
# Replace the `cert.pem` and `key.pem` files in the xr_teleoperate_rico/teleop/televuer/ directory with your own,eg:
cp 192.168.120.44+1.pem ../../../televuer/cert.pem
cp 192.168.120.44+1-key.pem ../../../televuer/key.pem
```

## 2.4 Environment Variables and Firewall

```bash
# Certificate environment variables (optional)
echo 'export XR_TELEOP_CERT="$HOME/.config/xr_teleoperate/cert.pem"' >> ~/.bashrc
echo 'export XR_TELEOP_KEY="$HOME/.config/xr_teleoperate/key.pem"' >> ~/.bashrc
source ~/.bashrc

# Open firewall ports
sudo apt install ufw
sudo ufw allow 8012   # TeleVuer HTTPS/WSS
sudo ufw allow 8000   # FastAPI
sudo ufw allow 60000  # Vision server configuration requests
sudo ufw allow 5555   # ZMQ image streams, all ports must be opened
```

---

# 3. Quick Start

## 3.1 Start Vision Server

On the vision server machine (or the same machine):

```bash
cd teleop/teleimager/humanoid_vision_system_ws

conda activate rico_xr
source /opt/ros/humble/setup.bash
source install/setup.bash

# Start (auto-detect and start head camera by default)
ros2 run humanoid_vision_system vision_system_main.py --auto-detect

# Or use manual configuration (requires manual_config/manual_camera.json to be configured first)
ros2 run humanoid_vision_system vision_system_main.py --no-auto-detect
```

In the context of this repository's current implementation, please note:

- `[teleop/teleimager/humanoid_vision_system_ws/manual_config/manual_camera.json]` is the main integrated camera configuration. Please refer to Section 4.3.
- `humanoid_vision_system_ws` does not enable discovery when started with --no-auto-detect, so you need to set the camera configuration first. Note:
 - `type: realsense` and provide `serial_number`
 - `type: opencv` and provide `video_id`
- If humanoid_vision_system_ws fails to respond, humanoid_image_client will fallback to the default configuration

Regarding display paths, there is one very important note:

- Treat `head_camera.enable_webrtc: true` and local `immersive` / `ego` image push as mutually exclusive deployment choices.
- When `head_camera.enable_webrtc: true`, the head view in the headset comes from the humanoid_vision_system_ws WebRTC endpoint.
- When `head_camera.enable_webrtc: false`, `teleop_hand_and_arm.py` will first read head images via ZMQ, then `TeleVuer` will push them itself in `immersive` / `ego` mode.
- Do not configure these two paths as two parallel head display chains within the same session.

Simulation notes:

- `--sim` is a pipeline placeholder mode, not a full simulator backend.
- It reuses the same XR page, recorder, and optional image service pipeline, only replacing robot / waist / BChand hardware access with in-process placeholder backends.
- If you are only practicing the XR control flow, you can set `xr.display_mode` to `pass-through`, which completely bypasses the image service.
- If you want the simulation pipeline to also cover the image chain, start humanoid_vision_system_ws exactly as described in this section and point the Host to that service.

## 3.2 Teleoperation Launch Parameters

Top-level CLI is defined in `[teleop/teleop_hand_and_arm.py](./teleop/teleop_hand_and_arm.py)`.


| Parameter           | Description                                                | Options            | Default                            |
| ------------------- | ---------------------------------------------------------- | ------------------ | ---------------------------------- |
| `--config-dir`      | Directory containing `system.json` and `robot.json` configs | Any valid path     | `./config`                         |
| `--task-dir`        | Recording output directory                                 | Any valid path     | `system.paths.task_dir`            |
| `--headless`        | Disable local OpenCV preview window                        | flag               | Off                                |
| `--full-body`       | Full-body humanoid robot, affects waist control            | flag               | Off                                |
| `--sim`             | Replace dual-arm / waist / hand hardware control with in-process placeholder backend | flag | Off                                |
| `--no-waist`        | Disable waist / external axis control                      | flag               | Follows `runtime.waist_enabled_default` |
| `--no-head`         | Disable head / external axis control                      | flag               | Follows `runtime.head_enabled_default` |
| `--image-server-ip` | Override TeleImager Host address                           | IPv4               | `system.network.image_server_ip`   |
| `--frequency`       | Override main loop frequency and recording FPS             | Any reasonable float | `system.runtime.frequency`       |
| `--no-image-server` | Disable image service                                        | flag               | Follows `runtime.enable_image_server`|



The current RICO main entry does not have XR mode-related CLI parameters. These two values are driven by configuration in `[config/system.json](./config/system.json)`:


| Config Key         | Description                        | Options                                      | Default       |
| ------------------ | ---------------------------------- | -------------------------------------------- | ------------- |
| `xr.input_mode`    | Select XR input interpretation mode | `controller`, `hand`                         | `controller`  |
| `xr.display_mode`  | Select robot view display mode in headset | `immersive`, `ego`, `pass-through`     | `immersive`   |

>**Note:** Hand control is currently a placeholder mode; only controller control is supported.

A few easily confusing behavior notes:

- `--sim`, `--image-server-ip`, `--frequency`, `--no-image-server`, `--task-dir`, `--full-body`, `--no-waist` and `--no-head` all override JSON configuration at runtime.
- `paths.task_dir` is resolved relative to the project root `xr_teleoperate_rico` directory, keep the default value.
- `--no-image-server` means disabling the image server, and the remote control main program will run in no image mode, which does not affect robot remote control. Data recording will only record robot data.

## 3.3 Launch Teleoperation on Host

```bash
# Launch teleoperation
cd /path/to/xr_teleoperate_rico

conda activate rico_xr

python3 teleop/teleop_hand_and_arm.py
```

Open in the XR device browser:

```
https://<host-ip>:8012/?ws=wss://<host-ip>:8012
```

Where:

- `<host-ip>` is the machine running `teleop_hand_and_arm.py`
- `<server-ip>` is the machine running the vision server
- For single-machine deployment, both can be the same

Some common Host-side launch variants:

- Disable waist / external axis: with `runtime.waist_enabled_default` set to `true` in `config/system.json`, waist is enabled by default; add `--no-waist` to disable it
- Disable head / external axis: with `runtime.head_enabled_default` set to `true` in `config/system.json`, head is enabled by default; add `--no-head` to disable it
- Disable Image Server: If the `runtime.enable_image_server` in the configuration item `config/system.json` is set to `true`, the image server will be enabled by default. If the `--no-image-server` is added, the image server will be disabled. The remote control main program will run in no image mode and will not affect robot remote control. Data recording will only record robot data. At this time, the `xr.display mode` in `config/system.json` should be modified to `pass—through`
- Disable local OpenCV preview window: add `--headless`
- Full-body robot, affects waist control: add `--full-body`, which enables full-body control. The full-body robot has 4 waist joints; the half-body robot has 1 waist joint.
- Switch image server without modifying JSON: add `--image-server-ip <server-ip>`

Simulation note: If you want to practice the same workflow without touching real hardware, simply add `--sim` to the Host command:

```bash
python3 teleop/teleop_hand_and_arm.py \
  --sim \
  --image-server-ip <server-ip>
```

If in `--sim` mode you also set `xr.display_mode` to `pass-through` and completely disable the image service, then `--image-server-ip` can be omitted.

For both physical deployment and `--sim`, the recommended startup order on the headset side is the same:

1. Ensure the XR headset and Host are on the same local network.
2. If `head_camera.enable_webrtc: true`, first open `https://<server-ip>:<head_camera.webrtc_port>/` in the headset browser, trust the certificate as prompted, click `Start`, and confirm the image service is working.

<p align="center">
  <img src="./image/webrtc_unsafe.jpg" alt="Camera WebRTC Browser Certificate Warning Example" width="45%">
</p>

3. Open the Host-side XR page:

```text
https://<host-ip>:8012/?ws=wss://<host-ip>:8012
```

4. If the browser shows a certificate warning, trust the Host certificate.

<p align="center">
  <img src="./image/vuer_unsafe.png" alt="TeleVuer Browser Certificate Warning Example" width="45%">
</p>

5. On the `TeleVuer` page, click `Virtual Reality` and allow all XR-related permission requests from the browser.

6. Once the XR session is established, you should see the robot's first-person view in the headset, and the terminal will print connection logs similar to:

```bash
websocket is connected. id:dbb8537d-a58c-4c57-b49d-cbb91bd25b90
default socket worker is up, adding clientEvents
Uplink task running. id:dbb8537d-a58c-4c57-b49d-cbb91bd25b90
```

7. Before starting teleoperation, align both arms to the robot's initial pose to avoid sudden jumps when control begins.

<p align="center">
  <img src="./image/initial_pose.png" alt="Suggested Initial Arm Pose Before Teleoperation" width="25%">
</p>

## 3.4 Operation Guide

| Operation | Device    | Valid States                           | Function                                                                                                                   |
| --------- | --------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Right A   | XR Controller | INACTIVE only                      | Wake up and return to home, enters IDLE after homing completes                                                             |
| Right B   | XR Controller | IDLE / ACTIVE_CONTROL               | Exit teleoperation, first enters RETURNING_HOME to home, enters INACTIVE after homing completes                            |
| Left X    | XR Controller | IDLE (start) / ACTIVE_CONTROL (stop) | Start teleoperation (enters ACTIVE_CONTROL); stop teleoperation (returns to IDLE, automatically stops recording and saves) |
| Left Y    | XR Controller | ACTIVE_CONTROL only                  | Toggle recording on/off                                                                                                    |
| Left X+Y  | XR Controller | IDLE / ACTIVE_CONTROL                | Manual home, enters RETURNING_HOME, returns to IDLE after homing completes; if recording, the homing process is also recorded, auto-saves after homing completes |
| Left trigger button | XR controller | Only ACTIVE_CONTROL | Switches based on the state of the trigger button: pressed = gripped, released = released (requires dexterous hands) |
| Right Hand Trigger | XR Controller | ACTIVE_CONTROL Only | Switches based on the state of the trigger: pressed = gripped, released = released (requires dexterous hand) |
| Squat/Stand | XR Headset & Controller | ACTIVE_CONTROL Only | Body lifting (full-body robot only, requires waist control enabled) |
| Move forward/backward | XR Headset & Controller | ACTIVE_CONTROL Only | Forward leaning/backward sitting movement (only applicable to the whole body, waist control needs to be turned on, not recommended) |
| Nod/Tilt Head | XR Headset & Controller | ACTIVE_CONTROL Only | Body pitch (full-body robot only, requires waist control enabled) |
| Head twisting | XR Headset & Controller | ACTIVE_CONTROL Only | Waist rotation |
| Move Arms   | XR Controller | ACTIVE_CONTROL only                  | Head movement (requires head control enabled) |
| Keyboard e | Keyboard   | Any non-INACTIVE state                | Emergency stop, first enters RETURNING_HOME to home, enters INACTIVE after homing completes                                |

> Note:
> Try not to perform forward or backward movement operations, and keep the position of the human body fixed for operation
> For detailed information on waist and head control, please refer to [Section 3.3](README.md#33-Launch-Teleoperation-on-Host) and [Section 4.1.2](README.md#412-Runtime-Configuration). By default, waist control and head control are enabled.

### FastAPI Control

Recording and task management can be controlled via REST API:

```bash
# Frontend page control, note that FastAPI control and XR control are mutually exclusive
```

## 3.5 State Machine Transition Diagram

The system has 4 main states. All exit/stop transitions must first go through `RETURNING_HOME` to complete homing, then determine the final landing state based on the `exit_pending` flag:

- `exit_pending = True` → Enters `INACTIVE` after homing completes (full exit)
- `exit_pending = False` → Enters `IDLE` after homing completes (home only, no exit)

```
                           ┌──────────────────────────────────────────┐
                           │       Right B / XR Disconnect / Keyboard e │
                           │  (exit_pending=True → INACTIVE after home) │
                           ▼                                          │
INACTIVE ──[Right A]──> RETURNING_HOME ──[exit_pending=False]──> IDLE │
   ▲                                    ▲                      │  │  │
   │                                    │                      │  │  │
   │                Left X+Y / API      │ GO_HOME              │  │  │
   │               (exit_pending        │ =False)              │  │  │
   │                                    │                      │  │  │
   │              ┌─────────────────────┘                      │  │  │
   │              │                                            ▼  │  │
   │              │                           ACTIVE_CONTROL ─────┘  │
   │              │                                │  │              │
   │              │              ┌─────────────────┘  │              │
   │              │              │                    │              │
   │              │     [Left X] │        [Left Y]    │              │
   │              │   Stop Teleop│    Rec On/Off      │              │
   │              │   Stop Record│                    │              │
   │              │              ▼                    ▼              │
   │              │            IDLE              ACTIVE_CONTROL      │
   │              │            (state unchanged)                     │
   │              │                                                  │
   └──────────────┘  RETURNING_HOME ──[exit_pending=True]── Home OK ─┘
```

<p align="center">
  <img src="./image/teleop_state_machine_xr.png" alt="state machine transfer diagram" width="70%">
</p>

<a id="physical-deployment"></a>

**State Descriptions:**

| State            | Description                                                                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `INACTIVE`       | System hibernation, waiting for wake-up. Only responds to Right A or API `INIT_RESET` wake-up.                                              |
| `IDLE`           | Standby state, ready to accept control requests. Waits for Left X to enter active control (must acquire control lock), responds to Left X+Y manual home, responds to Right B exit. |
| `ACTIVE_CONTROL` | Active teleoperation state. XR controller or API controls the robot, recording (optional) in progress. Responds to Left X stop teleop, Left Y toggle recording, Left X+Y manual home, Right B exit. |
| `RETURNING_HOME` | Homing in progress. Both arms and (if enabled) waist automatically return to home pose. If recording, continues recording during the homing process. After homing completes, enters `INACTIVE` or `IDLE` based on `exit_pending`, auto-saves the episode being recorded. |

**Recording and Homing Interaction Logic:**

```
IDLE (not recording)
  Left X
    -> Acquire XR control → Enter ACTIVE_CONTROL

  Left X+Y
    -> Enter RETURNING_HOME (exit_pending=False)
    -> Enters IDLE after homing completes (not recording, no save)

  Right B / Keyboard e
    -> Enter RETURNING_HOME (exit_pending=True)
    -> Enters INACTIVE after homing completes

ACTIVE_CONTROL
  Left X (stop teleoperation)
    -> Release control
    -> If recording → save current episode → stop recording
    -> Return to IDLE

  Left Y (toggle recording)
    -> If not recording → create new episode → start recording
    -> If recording → save current episode → stop recording
    -> Teleoperation state remains ACTIVE_CONTROL

  Left X+Y (manual home)
    -> Release control
    -> Enter RETURNING_HOME (exit_pending=False)
    -> If recording → continue recording the homing process
    -> After homing completes → auto-save episode (if recording) → enter IDLE

  Right B (exit teleoperation)
    -> Release control
    -> Enter RETURNING_HOME (exit_pending=True)
    -> If recording → continue recording the homing process
    -> After homing completes → auto-save episode → enter INACTIVE

  Keyboard e (emergency stop)
    -> Immediately release control + force stop both arms
    -> Enter RETURNING_HOME (exit_pending=True)
    -> Enters INACTIVE after homing completes
```

**API Command Effects on State:**

| API Command      | Trigger Condition                 | Behavior and State Transition                                                                                         |
| ---------------- | -------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `EMERGENCY_STOP` | Any state (non-INACTIVE)         | Release control + stop arms → RETURNING_HOME (`exit_pending=True`), then → INACTIVE after home                      |
| `INIT_RESET`     | INACTIVE state only              | → RETURNING_HOME (`exit_pending=False`), then → IDLE after home                                                     |
| `GO_HOME`        | Not in INACTIVE / RETURNING_HOME | If in ACTIVE_CONTROL, release control → RETURNING_HOME (`exit_pending=False`), then → IDLE after home               |
| `START_TELEOP`   | IDLE + control lock free         | Acquire API control → ACTIVE_CONTROL                                                                                  |
| `STOP_TELEOP`    | ACTIVE_CONTROL + API holds control | Release control; if recording, save episode and stop recording → IDLE                                               |
| `START_RECORD`   | ACTIVE_CONTROL + not recording   | Create new episode → start recording                                                                                  |
| `STOP_RECORD`    | Recording in progress            | Save current episode → stop recording                                                                                 |

**XR Web Page Disconnect Handling:**

- When XR web page disconnect is detected (falling edge), if not in `INACTIVE` or `RETURNING_HOME`:
  - Release control (if in ACTIVE_CONTROL)
  - Enter `RETURNING_HOME` (`exit_pending = True`)
  - Enters `INACTIVE` after homing completes

## 3.6 Hibernation

"Hibernation" (i.e., entering `INACTIVE` state) is triggered by any of the following: Right B, Keyboard e, XR web disconnect, API `EMERGENCY_STOP`.

Complete flow when entering hibernation:

1. **State transition**: Current state (`IDLE` or `ACTIVE_CONTROL`) → Enter `RETURNING_HOME` (`exit_pending = True`)
2. **Release control**: If in `ACTIVE_CONTROL`, automatically release the control lock
3. **Mechanical homing**: Both arms and (if enabled) waist automatically return to home pose
4. **Continue recording**: If recording before homing started, each frame during the homing process is still recorded to the current episode
5. **Save episode**: After homing completes, if recording, automatically save the episode and stop recording
6. **Final state**: Enter `INACTIVE`, waiting for next wake-up (Right A or API `INIT_RESET`)

---

# 4. Configuration Guide

## 4.1 xr_teleoperate_rico/config/system.json

### 4.1.1 Network Configuration

| Key                          | Description                                                                 | Type / Options / Default           |
| ---------------------------- | --------------------------------------------------------------------------- | ---------------------------------- |
| `network.image_server_ip`    | Vision server IP, address used by `ImageClient`, also used for default `webrtc_url` passed to `TeleVuer` | IPv4 / hostname / `192.168.120.44` |
| `network.image_request_port` | Camera configuration request port, fixed at 60000 for retrieving vision server camera config | integer / `60000`                  |
| `network.fastapi_host`       | FastAPI listen address                                                     | string / `0.0.0.0`                 |
| `network.fastapi_port`       | FastAPI port                                                               | integer / `8000`                   |

### 4.1.2 Runtime Configuration

| Key                             | Description                                                    | Type / Options / Default |
| ------------------------------- | -------------------------------------------------------------- | ------------------------ |
| `runtime.frequency`             | Main loop frequency, also used as FPS written into episode header info by the recorder | float / `60.0`           |
| `runtime.headless`              | Whether to disable local image preview window                  | boolean / `false`        |
| `runtime.sim_enabled_default`   | Before CLI override, determines whether to enable in-process simulation placeholder mode by default | boolean / `false`        |
| `runtime.waist_enabled_default` | Determines whether to initialize (enable) waist / external axis controller by default | boolean / `true` |
| `runtime.head_enabled_default`  | Determines whether to initialize (enable) head / external axis controller by default | boolean / `true` |
| `runtime.enable_image_server`   | Whether to enable image server by default | boolean / `true` |

> If the image server is not enabled or fails to be enabled, the remote control main program will run in no image mode, which does not affect the robot's remote control. Data recording will only record robot data.

### 4.1.3 XR/VR Configuration

| Key               | Description                                                                       | Type / Options / Default                         |
| ----------------- | --------------------------------------------------------------------------------- | ------------------------------------------------ |
| `xr.input_mode`   | XR input mode: `controller`=controller control (trigger→dexterous hand, head offset→waist); `hand`=hand tracking (pinch→dexterous hand, no waist control, currently a placeholder implementation only) | `controller`, `hand` / `controller`              |
| `xr.display_mode` | XR display mode: `immersive`=full-screen immersive robot view; `pass-through`=pass-through mode with no image overlay; `ego`=center window + surrounding pass-through | `immersive`, `ego`, `pass-through` / `immersive` |

> For detailed waist control information, see [Sections 4.2.4-4.2.5](#424-robothome_half_waist_radrobothome_full_waist_rad-waist-home-target-radians)

### 4.1.4 Paths Configuration

| Key               | Description             | Type / Options / Default   |
| ----------------- | ----------------------- | -------------------------- |
| `paths.task_dir`  | Task data root directory | string / `data`            |
| `paths.trash_dir` | Trash/recycle bin directory | string / `data/.trash` |

### 4.1.5 Log Manager Configuration

| Key               | Description             | Type / Options / Default   |
| ----------------- | ----------------------- | -------------------------- |
| `log_manager.log_dir` | Log directory | string / `logs`            |
| `log_manager.level` | Log level | string / `INFO`            |
| `log_manager.console` | Whether to enable console logging | boolean / `true`        |
| `log_manager.rotation_size_mb` | Log rotation size in MB | float / `120.0`        |
| `log_manager.retention_days` | Log retention days | float / `60.0`        |
| `log_manager.compression_enabled` | Whether to enable log file compression | boolean / `true`        |
| `log_manager.encoding` | Log file encoding | string / `utf-8` |

### 4.1.6 Recording Configuration

| Key                           | Description                                       | Type / Options / Default |
| ----------------------------- | ------------------------------------------------- | ------------------------ |
| `recording.rerun_log`         | Whether to enable Rerun visualization             | boolean / `false`        |
| `recording.save_audio`        | Whether to save audio data                        | boolean / `false`        |
| `recording.skip_blank_images` | Whether to skip blank/all-black images (smart filtering of invalid frames) | boolean / `true`         |
| `recording.color_format`      | Color image save format                           | string / `jpg`           |
| `recording.depth_format`      | Depth image save format                           | string / `png`           |

### 4.1.7 recording.text Task Text Information

| Key                    | Description                                     | Type / Options / Default             |
| ---------------------- | ----------------------------------------------- | ------------------------------------ |
| `recording.text.goal`  | Task goal text written into episode header info | string / `RICO Robot Teleoperation Task` |
| `recording.text.desc`  | Task description text written into episode header info | string / (empty)                |
| `recording.text.steps` | Task steps text written into episode header info | string / (empty)                    |

### 4.1.8 recording.info Dataset Metadata

| Key                                     | Description                                                               | Type / Options / Default |
| --------------------------------------- | ------------------------------------------------------------------------- | ------------------------ |
| `recording.info.version`                | Version number written into episode header info                           | string / `1.0.0`         |
| `recording.info.author`                 | Author info written into episode header info                              | string / `rico`          |
| `recording.info.image.head_width`       | Fallback only; overridden by actual runtime image width when recording starts | integer / `640`          |
| `recording.info.image.head_height`      | Fallback only; overridden by actual runtime image height when recording starts | integer / `480`          |
| `recording.info.image.fps`              | Fallback only; overridden by actual runtime frequency when recording starts | integer or float / `30`  |
| `recording.info.depth.head_width`       | Fallback only; overridden by actual runtime image width when recording starts | integer / `640`          |
| `recording.info.depth.head_height`      | Fallback only; overridden by actual runtime image height when recording starts | integer / `480`          |
| `recording.info.depth.fps`              | Fallback only; overridden by actual runtime frequency when recording starts | integer or float / `30`  |
| `recording.info.audio.sample_rate`      | Audio metadata written into episode header info, sample rate (Hz)         | integer / `16000`        |
| `recording.info.audio.channels`         | Audio metadata written into episode header info, channel count            | integer / `1`            |
| `recording.info.audio.format`           | Audio metadata written into episode header info, audio format             | string / `PCM`           |
| `recording.info.audio.bits`             | Audio metadata written into episode header info, bit depth                | integer / `16`           |
| `recording.info.joint_names.left_arm`   | Metadata only; copied directly to episode header info, left arm joint name list | string list / `[]`       |
| `recording.info.joint_names.left_ee`    | Metadata only; copied directly to episode header info, left end-effector joint name list | string list / `[]`       |
| `recording.info.joint_names.right_arm`  | Metadata only; copied directly to episode header info, right arm joint name list | string list / `[]`       |
| `recording.info.joint_names.right_ee`   | Metadata only; copied directly to episode header info, right end-effector joint name list | string list / `[]`       |
| `recording.info.joint_names.waist`      | Metadata only; copied directly to episode header info, waist joint name list | string list / `[]`       |
| `recording.info.joint_names.body`       | Metadata only; copied directly to episode header info, body joint name list | string list / `[]`       |
| `recording.info.tactile_names.left_ee`  | Metadata only; copied directly to episode header info, left end-effector tactile sensor name list | string list / `[]`       |
| `recording.info.tactile_names.right_ee` | Metadata only; copied directly to episode header info, right end-effector tactile sensor name list | string list / `[]`       |
| `recording.info.sim_state`              | Default metadata field written into episode header info, simulation state identifier | Any JSON-serializable value (empty) |

## 4.2 xr_teleoperate_rico/config/robot.json

### 4.2.1 Robot Body Configuration

| Key                          | Description                                                       | Type / Options / Default        |
| ---------------------------- | ----------------------------------------------------------------- | ------------------------------- |
| `robot.name`                 | Only as metadata in current implementation, robot name            | string / `rico`                 |
| `robot.ip`                   | Target address for `DucoCobot` RPC connection                     | IPv4 / hostname / `127.0.0.1`   |
| `robot.type`                 | Robot type, default is `p_arm`                                        | string / `p_arm`                    |
| `robot.upper_body`           | Whether the robot is a half-body humanoid robot                   | boolean / `true`                |
| `robot.left_arm_port`        | Left arm control port                                             | integer / `7003`                |
| `robot.right_arm_port`       | Right arm control port                                            | integer / `7004`                |
| `robot.waist_port`           | Waist/external axis control port                                  | integer / `7020`                |
| `robot.head_port`            | Head control port                                                 | integer / `7021`                |
| `robot.left_arm_tcp_frame`   | Tool coordinate frame name passed to left arm `servoj_pose()`    | string / `tcp_1`                |
| `robot.right_arm_tcp_frame`  | Tool coordinate frame name passed to right arm `servoj_pose()`   | string / `tcp_2`                |
| `robot.left_arm_base_frame`  | Base coordinate frame name passed to left arm `servoj_pose()`    | string / `arm_1_base`           |
| `robot.right_arm_base_frame` | Base coordinate frame name passed to right arm `servoj_pose()`   | string / `arm_2_base`           |

### 4.2.2 robot.home_arm_joint_deg / robot.home_arm_joint_deg_p Home Joint Angles(degrees)

| Key                          | Description                                                  | Type / Options / Default             |
| ---------------------------- | ------------------------------------------------------------ | ------------------------------------ |
| `robot.home_arm_joint_deg.left`  | Left arm home joint target, used by `ctrl_dual_arm_go_home()` | `[0, -40, 90, 80, -50, 30, 0]`      |
| `robot.home_arm_joint_deg.right` | Right arm home joint target, used by `ctrl_dual_arm_go_home()` | `[0, -40, -90, 80, 50, 30, 0]`      |
| `robot.home_arm_joint_deg_p.left`  | Left arm home joint target, used by `ctrl_dual_arm_go_home()` | `[20, 40, 45, 80, -90, -30, -20]`      |
| `robot.home_arm_joint_deg_p.right` | Right arm home joint target, used by `ctrl_dual_arm_go_home()` | `[20, 40, 45, 80, -90, -30, -20]`      |

> ***Note***
```
arm_type:Robot dual arm model, different models use different dual arm return angles, default uses p series, keep default value
home_arm_joint_deg:For non P series dual arm return to zero angle
home_arm_joint_deg_p:For P series dual arm return to zero angle
```

### 4.2.3 robot.home_head_rad Head Home Target (radians)

| Key                    | Description                                                      | Type / Options / Default                        |
| ---------------------- | ---------------------------------------------------------------- | ----------------------------------------------- |
| `robot.home_head_rad` | Head home target, used by `ctrl_head_go_home()` | List of 2 radian values / `[0.0, 0.0]` |

### 4.2.4 robot.home_half_waist_rad / robot.home_full_waist_rad Waist Home Target (radians)

| Key                      | Description                                                                                                        | Type / Options / Default                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| `robot.home_half_waist_rad` | Waist / external axis home target, half-body humanoid robot: 1 joint, used by `ctrl_waist_go_home()`             | List of 1 radian value / `[0.0]`                                     |
| `robot.home_full_waist_rad`  | Waist home target, full-body humanoid robot: 4 joints, used by `ctrl_waist_go_home()`                           | List of 4 radian values / `[0.523599, -1.047198, 0.523599, 0.0]`     |

> ***Note***
```
Half-body humanoid: waist has 1 joint, half-body control uses joint target control
Full-body humanoid: waist has 4 joints, full-body control uses cartesian target control
Homing uses joint target control in both modes
```

### 4.2.5 robot.servo Servo Control Parameters

| Key                                | Description                                                                                                                  | Type / Options / Default                  |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `robot.servo.arm_speed_min_cart`   | Dual-arm pose servo starting minimum speed (rad/s), passed as dual-arm speed vector to `servoj_pose()`                       | float / `0.2`                             |
| `robot.servo.arm_speed_max_cart`   | Dual-arm pose servo maximum speed (rad/s), passed as dual-arm speed vector to `servoj_pose()`                               | float / `0.8`                             |
| `robot.servo.arm_acceleration_cart`| Dual-arm pose servo acceleration (m/s²), passed as dual-arm acceleration vector to `servoj_pose()`                          | float / `10.0`                            |
| `robot.servo.ramp_steps`           | Speed ramp-up frame count                                                                                                    | integer / `100`                           |
| `robot.servo.home_velocity`        | Homing movement speed (m/s)                                                                                                  | float / `1.0`                             |
| `robot.servo.home_acceleration`    | Homing movement acceleration (m/s²)                                                                                          | float / `10.0`                            |
| `robot.servo.lookahead_time_ms`    | Servo lookahead time (ms), passed as lookahead parameter to `servoj_pose() or servoj()`                                      | integer / `200`                           |
| `robot.servo.gain`                 | Control gain passed to `servoj_pose() or servoj()`                                                                           | integer / `25`                            |
| `robot.servo.blend`                | Blend parameter passed to `servoj_pose() or servoj()`                                                                        | integer / `50`                            |
| `robot.servo.waist_speed_min_joint`      | Half-body humanoid waist 1-axis servo starting minimum speed (m/s), passed to `servoj()`                                | float / `0.2`                             |
| `robot.servo.waist_speed_max_joint`      | Half-body humanoid waist 1-axis servo maximum speed (m/s), passed to `servoj()`                                        | float / `0.8`                             |
| `robot.servo.waist_acceleration_joint`   | Half-body humanoid waist 1-axis servo acceleration (m/s²), passed to `servoj()`                                       | float / `5.0`                             |
| `robot.servo.waist_speed_min_cart`       | Full-body humanoid waist 4-axis servo starting minimum speed (rad/s), passed to `servoj_pose()`                       | float / `0.2`                             |
| `robot.servo.waist_speed_max_cart`       | Full-body humanoid waist 4-axis servo maximum speed (rad/s), passed to `servoj_pose()`                              | float / `1.2`                             |
| `robot.servo.waist_acceleration_cart`    | Full-body humanoid waist 4-axis servo acceleration (m/s²), passed to `servoj_pose()`                                 | float / `4.0`                             |
| `robot.servo.head_speed_min_joint`       | Humanoid head 2-axis servo starting minimum speed (m/s), passed to `servoj()`                                       | float / `0.2`                             |
| `robot.servo.head_speed_max_joint`       | Humanoid head 2-axis servo maximum speed (m/s), passed to `servoj()`                                               | float / `0.8`                             |
| `robot.servo.head_acceleration_joint`    | Humanoid head 2-axis servo acceleration (m/s²), passed to `servoj()`                                              | float / `5.0`                             |

### 4.2.6 end_effector End Effector (Dexterous Hand) Configuration

| Key                                   | Description                                                       | Type / Options / Default                                   |
| ------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------- |
| `end_effector.name`                   | Only as metadata in current implementation; actual code path is fixed to BChand controller | string / `bchand`                                          |
| `end_effector.trigger_open_threshold` | Trigger value open/close threshold, >threshold=open, ≤threshold=close, input values are clipped to `[0, 10]` | float / `5.0`                                              |
| `end_effector.left_open_primary`      | Left hand open primary command, first group of register instructions for left hand open action | List of 6 integers / `[0, 0, 0, 0, 0, 0]`                 |
| `end_effector.left_open_secondary`    | Left hand open secondary command, second group of register instructions for left hand open action | List of 6 integers / `[0, 0, 0, 0, 0, 0]`                 |
| `end_effector.left_close_primary`     | Left hand close primary command, first group of register instructions for left hand close action | List of 6 integers / `[0, 150, 1000, 1000, 1000, 1000]`   |
| `end_effector.left_close_secondary`   | Left hand close secondary command, second group of register instructions for left hand close action | List of 6 integers / `[800, 1000, 1000, 1000, 1000, 1000]` |
| `end_effector.right_open_primary`     | Right hand open primary command, first group of register instructions for right hand open action | List of 6 integers / `[0, 0, 0, 0, 0, 0]`                 |
| `end_effector.right_open_secondary`   | Right hand open secondary command, first group of register instructions for right hand open action | List of 6 integers / `[0, 0, 0, 0, 0, 0]`                 |
| `end_effector.right_close_primary`    | Right hand close primary command, first group of register instructions for right hand close action | List of 6 integers / `[0, 150, 1000, 1000, 1000, 1000]`   |
| `end_effector.right_close_secondary`  | Right hand close secondary command, first group of register instructions for right hand close action | List of 6 integers / `[800, 150, 1000, 1000, 1000, 1000]` |
| `end_effector.velocity_profile`       | Dexterous hand per-finger movement speed, per-finger velocity list used in every BChand command packet | List of 6 integers / `[500, 500, 500, 500, 500, 500]`     |
| `end_effector.cooldown_seconds`       | Delay between first and second BChand command groups, cooldown time between primary and secondary commands (seconds) | float / `1.0`                                              |

## 4.3 manual_camera.json Vision Configuration

Camera configuration file is located at `[teleop/teleimager/humanoid_vision_system_ws/manual_config/manual_camera.json](teleop/teleimager/humanoid_vision_system_ws/manual_config/manual_camera.json)`.

### 4.3.1 Top-Level Fields

```json
// Strictly by: head: head_camera, hands: left/right_wrist_camera, chest: front/back_chest_camera, matching webrtc transport
{
  "global": { ... },       // Global configuration
  "head_camera": { ... },   // Head camera
  "left_wrist_camera": { ... },  // Left wrist camera
  "right_wrist_camera": { ... }, // Right wrist camera
  "front_chest_camera": { ... }, // Front chest camera
  "back_chest_camera": { ... }   // Back chest camera
}
```

### 4.3.2 Global Configuration

| Field                                       | Type   | Description                                        |
| ------------------------------------------- | ------ | -------------------------------------------------- |
| `global.vision_system.node_name`            | string | ROS2 node name, default `humanoid_vision_system`   |
| `global.synchronization.sync_tolerance_ms`  | float  | Multi-camera sync tolerance (ms), default `5.0`    |

### 4.3.3 Common Camera Fields

The following fields are available in all camera configurations:

| Field            | Type   | Description                                                                           | Example Values                                                |
| ---------------- | ------ | ------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `camera_type`    | string | Camera driver type: `realsensecamera` and `realsense` (ROS2 RealSense driver), `opencv` (OpenCV V4L2) | `realsense`                                                   |
| `model`          | string | Camera model identifier, for metadata and logging only                                | `D435`, `D405`, `fisheye`                                     |
| `serial_number`  | string | RealSense camera serial number, for precise device matching                           | `254622075259`                                                |
| `device_index`   | int    | OpenCV camera device index (e.g., `/dev/video12` corresponds to `12`), OpenCV type only | `12`                                                          |
| `position`       | string | Camera mounting position, used for identification and recording directory naming      | `HEAD`, `LEFT_WRIST`, `RIGHT_WRIST`, `FRONT_CHEST`, `BACK_CHEST` |
| `enabled`        | bool   | Whether to enable this camera                                                         | `true`                                                        |
| `binocular`      | bool   | Whether it is a binocular camera. When `true`, for head cameras: color images are split into `color_0` and `color_1` | `false`                                                       |

### 4.3.4 Streams Video Stream Configuration

```json
"streams": {
  "color": { ... },   // Color stream
  "depth": { ... }    // Depth stream (RealSense cameras only)
}
```

| Field                   | Type | Description                          | Example Value |
| ----------------------- | ---- | ------------------------------------ | ------------- |
| `color.enabled`         | bool | Whether to enable color stream       | `true`        |
| `color.capture_width`   | int  | Image width actually captured by camera (pixels) | `640`         |
| `color.capture_height`  | int  | Image height actually captured by camera (pixels) | `480`         |
| `color.publish_width`   | int  | Image width scaled to when publishing (pixels) | `640`         |
| `color.publish_height`  | int  | Image height scaled to when publishing (pixels) | `480`         |
| `color.fps`             | int  | Color stream target frame rate       | `30`          |
| `depth.enabled`         | bool | Whether to enable depth stream (RealSense only) | `true`        |
| `depth.capture_width`   | int  | Depth image capture width            | `640`         |
| `depth.capture_height`  | int  | Depth image capture height           | `480`         |
| `depth.publish_width`   | int  | Depth image publish width            | `640`         |
| `depth.publish_height`  | int  | Depth image publish height           | `480`         |
| `depth.fps`             | int  | Depth stream target frame rate       | `30`          |

```
Note:
- When both color and depth streams are enabled simultaneously, due to the color-depth alignment mechanism of the RealSense camera requiring timestamp matching,
 The actual frame rate of the acquisition loop is determined by the slower stream, which is `min(color.fps, depth.fps)`.
 It is recommended to set the values of color.fps and depth.fps to be the same to avoid frames generated by high-frequency abortion being discarded.
- The current image is collected in RGB format for color images and Z16 format for depth images. It is recommended to maintain the same resolution for color and depth images
 The capture resolution should be the same as the publishing resolution. The current design scales the captured image to the publishing resolution. If the capture resolution is different from the publishing resolution, it may cause image blur or distortion
 Not conducive to data training, it is recommended to maintain consistent resolution
```

### 4.3.5 Compression Configuration

```json
"compression": {
  "rgb": { ... },   // Color image compression
  "depth": { ... }  // Depth image compression
}
```

| Field                           | Type   | Description                                                         | Example Value |
| ------------------------------- | ------ | ------------------------------------------------------------------- | ------------- |
| `rgb.quality`                   | int    | JPEG compression quality (0-100), PNG compression quality (0-9), the higher the value, the higher the quality and the lower the compression ratio | `85`          |
| `rgb.format`                    | string | Color image compression format: `JPEG` (lossy) or `PNG` (lossless)  | `JPEG`        |
| `depth.quantization_bits`       | int    | Depth image quantization bits (1-16), 16 = lossless, lower value = lower precision but higher compression ratio | `12`          |
| `depth.zstd_compression_level`  | int    | ZSTD compression level (1-22), higher value = higher compression ratio but slower speed | `3`           |

### 4.3.6 publisher_compression Publisher-Level Compression Override

Optional configuration to override compression parameters for specific publishers. Structure is the same as `compression`; unconfigured parameters inherit from `compression`.

```json
"publisher_compression": {
  "zeromq": {
    "rgb": { "quality": 90, "format": "JPEG" },
    "depth": { "quantization_bits": 16, "zstd_compression_level": 6 }
  },
  "webrtc": {
    "rgb": { "quality": 85, "format": "JPEG" }
  }
}
```

### 4.3.7 Communication Configuration

```json
"communication": {
  "zeromq": { ... },    // ZeroMQ publishing
  "websocket": { ... }, // WebSocket publishing
  "webrtc": { ... },    // WebRTC publishing
  "ros2": { ... }       // ROS2 publishing
}
```

#### ZeroMQ Configuration

| Field                         | Type | Description                     | Example Value |
| ----------------------------- | ---- | ------------------------------- | ------------- |
| `zeromq.enabled`              | bool | Whether to enable ZMQ publishing | `true`        |
| `zeromq.image_publish_port`   | int  | Color/depth image ZMQ PUB port  | `5555`        |
| `zeromq.status_publish_port`  | int  | Camera status ZMQ PUB port      | `5556`        |
| `zeromq.max_queue_size`       | int  | Maximum queue length            | `200`         |
| `zeromq.high_water_mark`      | int  | ZMQ HWM                         | `100`         |

#### WebSocket Configuration

| Field                          | Type   | Description                          | Example Value |
| ------------------------------ | ------ | ------------------------------------ | ------------- |
| `websocket.enabled`            | bool   | Whether to enable WebSocket publishing | `true`        |
| `websocket.host`               | string | Listen address, `0.0.0.0` means all interfaces | `0.0.0.0`     |
| `websocket.port`               | int    | WebSocket port                       | `8765`        |
| `websocket.max_connections`    | int    | Maximum connections                  | `10`          |
| `websocket.ping_interval_sec`  | float  | Heartbeat interval (seconds)         | `30.0`        |

#### WebRTC Configuration

| Field                      | Type   | Description                             | Example Value                      |
| -------------------------- | ------ | --------------------------------------- | ---------------------------------- |
| `webrtc.enabled`           | bool   | Whether to enable WebRTC publishing      | `true`                             |
| `webrtc.host`              | string | Listen address                          | `0.0.0.0`                          |
| `webrtc.video_codec`       | string | Video codec: `VP8` or `H264`            | `VP8`                              |
| `webrtc.port`              | int    | WebRTC HTTPS port (globally unique, must be consistent across cameras) | `8998`                             |
| `webrtc.stun_servers`      | list   | STUN server list                        | `["stun:stun.l.google.com:19302"]` |
| `webrtc.turn_servers`      | list   | TURN server list (for NAT traversal)    | `[]`                               |
| `webrtc.max_bitrate_kbps`  | int    | Maximum bitrate (kbps)                  | `2000`                             |
| `webrtc.min_bitrate_kbps`  | int    | Minimum bitrate (kbps)                  | `500`                              |
| `webrtc.max_fps`           | int    | Maximum frame rate                      | `60`                               |
| `webrtc.audio_enabled`     | bool   | Whether to enable audio                 | `false`                            |
| `webrtc.max_connections`   | int    | Maximum connections                     | `5`                                |

#### ROS2 Configuration

| Field                     | Type   | Description                               | Example Value           |
| ------------------------- | ------ | ----------------------------------------- | ----------------------- |
| `ros2.enabled`            | bool   | Whether to enable ROS2 publishing          | `true`                  |
| `ros2.camera_info_topic`  | string | Camera info topic                         | `/vision/camera_info`   |
| `ros2.status_topic`       | string | Camera status topic                       | `/vision/camera_status` |
| `ros2.tf_frame_prefix`    | string | TF frame prefix                           | `vision`                |
| `ros2.qos_depth`          | int    | QoS queue depth                           | `10`                    |
| `ros2.qos_reliability`    | string | QoS reliability: `RELIABLE` or `BEST_EFFORT` | `RELIABLE`              |

### 4.3.8 Camera Communication Port Quick Reference

| Camera               | ZMQ Image Port | ZMQ Status Port | WebSocket Port |
| -------------------- | -------------- | --------------- | -------------- |
| `head_camera`        | `5555`         | `5556`          | `8765`         |
| `left_wrist_camera`  | `5557`         | `5558`          | `8766`         |
| `right_wrist_camera` | `5559`         | `5560`          | `8767`         |
| `front_chest_camera` | `5561`         | `5562`          | `8768`         |
| `back_chest_camera`  | `5563`         | `5564`          | `8769`         |

- **WebRTC Port**: All cameras share `8998` (globally unique)
- **TeleVuer HTTPS/WSS**: Independent port `8012`

### 4.3.9 Complete Configuration Example

```json
{
  "head_camera": {
    "camera_type": "realsensecamera",
    "model": "D435",
    "serial_number": "254622075259",
    "position": "HEAD",
    "enabled": true,
    "binocular": false,
    "streams": {
      "color": {
        "enabled": true,
        "capture_width": 640,
        "capture_height": 480,
        "publish_width": 640,
        "publish_height": 480,
        "fps": 30
      },
      "depth": {
        "enabled": true,
        "capture_width": 640,
        "capture_height": 480,
        "publish_width": 640,
        "publish_height": 480,
        "fps": 30
      }
    },
    "compression": {
      "rgb": { "quality": 85, "format": "JPEG" },
      "depth": { "quantization_bits": 12, "zstd_compression_level": 3 }
    },
    "communication": {
      "zeromq": { "enabled": true, "image_publish_port": 5555, "status_publish_port": 5556 },
      "websocket": { "enabled": true, "host": "0.0.0.0", "port": 8765 },
      "webrtc": { "enabled": true, "video_codec": "VP8", "port": 8998 }
    }
  }
}
```

In the context of this repository's current implementation, please note:

- If using `type: realsense`, provide the `serial_number`,note that the camera serial number needs to correspond to the physical installation location.
- If using `type: opencv`, provide `video_id`; this is the recommended direct launch path for non-RealSense cameras.
- `left_wrist_camera.enable_webrtc` and `right_wrist_camera.enable_webrtc` are mainly for preview / debugging capabilities; the top-level RICO teleoperation main pipeline does not depend on them.
- `head_camera.enable_webrtc` changes the image source path in the headset:
  - `true`: `TeleVuer` uses the WebRTC URL
  - `false`: Host first reads head images via ZMQ, then `TeleVuer` pushes them itself in `immersive` / `ego` mode


## 4.4 global_config.json Configuration Parameters

The global configuration file for the image server is located at `[teleop/teleimager/humanoid_vision_system_ws/src/humanoid_vision_system/config/global_config.json](teleop/teleimager/humanoid_vision_system_ws/src/humanoid_vision_system/config/global_config.json)`。

camera_config.json is the camera configuration template file located at `[teleop/teleimager/humanoid_vision_system_ws/src/humanoid_vision_system/config/camera_config.json](teleop/teleimager/humanoid_vision_system_ws/src/humanoid_vision_system/config/camera_config.json)`。

| Parameter | Description | Example Value |
|------|------|--------|
| vision_system.node_name | Vision system node name | humanoid_vision_system |
| synchronization.sync_tolerance_ms | Synchronization tolerance in milliseconds | 5.0 |
| log_manager.log_directory | Log directory path | ./logs |
| log_manager.log_level | Log level | INFO |
| log_manager.rotation_size_mb | Log file rotation size in MB | 120 |
| log_manager.retention_days | Log file retention period in days | 60 |
| log_manager.compression_enabled | Compression enabled | true |
| log_manager.encoding | Log encoding | utf-8 |
| port_allocation.zeromq.base_image_port | ZMQ image port base | 5555 |
| port_allocation.zeromq.base_status_port | ZMQ status port base | 5556 |
| port_allocation.zeromq.config_rep_port | ZMQ configuration port base | 60000 |
| port_allocation.zeromq.port_increment | ZMQ port increment base | 10 |
| port_allocation.websocket.base_port | WebSocket base port | 8765 |
| port_allocation.websocket.port_increment | WebSocket port increment base | 1 |
| port_allocation.webrtc.base_port | WebRTC base port number (global unique)  | 8998 |
| port_allocation.fallback_range | WebRTC fallback range | [20000, 30000] |


---

# 5. API Reference

The FastAPI service provides the following endpoints on port `8000`:

| Function Name           | Method | API Path                                              | Description                                                              |
| ----------------------- | ------ | ----------------------------------------------------- | ------------------------------------------------------------------------ |
| health_check            | GET    | `health`                                              | Health check                                                             |
| get_system_status       | GET    | `status`                                              | Get system status (teleop state, XR status, recording status, etc.)      |
| get_xr_status           | GET    | `xr/status`                                           | Get XR device status                                                     |
| get_tasks               | GET    | `tasks`                                               | Get all task list                                                        |
| create_task             | POST   | `tasks`                                               | Create new task                                                          |
| get_task                | GET    | `tasks/{task_id}`                                     | Get task details                                                         |
| update_task             | PUT    | `tasks/{task_id}`                                     | Edit task information                                                    |
| delete_task             | DELETE | `tasks/{task_id}`                                     | Delete task (soft delete to trash)                                       |
| get_active_task         | GET    | `active_task`                                         | Get current active task                                                  |
| set_active_task         | POST   | `active_task`                                         | Set current active task                                                  |
| init_reset              | POST   | `teleop/init_reset`                                   | Power-on reset (first reset)                                             |
| start_teleop            | POST   | `teleop/start`                                        | Start teleoperation                                                      |
| stop_teleop             | POST   | `teleop/stop`                                         | Stop teleoperation                                                       |
| start_record            | POST   | `record/start`                                        | Start recording                                                          |
| stop_record             | POST   | `record/stop`                                         | Stop recording                                                           |
| emergency_stop          | POST   | `teleop/emergency_stop`                               | Emergency stop robot                                                     |
| go_home                 | POST   | `teleop/go_home`                                      | Robot go home                                                            |
| get_control_status      | GET    | `control/status`                                      | Get current control source status                                        |
| get_task_datasets       | GET    | `tasks/{task_id}/datasets`                            | Get dataset list under specified task                                    |
| get_dataset_frames      | GET    | `tasks/{task_id}/datasets/{episode_id}/frames`        | Get dataset frame data (supports pagination and time filtering)          |
| delete_dataset          | DELETE | `tasks/{task_id}/datasets/{episode_id}`               | Delete dataset (soft delete to trash)                                    |
| rebuild_index           | POST   | `tasks/{task_id}/datasets/{episode_id}/rebuild_index` | Rebuild index file                                                       |
| create_export_task      | POST   | `export`                                              | Create export task, package datasets under specified task as zip/tar.gz  |
| get_export_tasks        | GET    | `export/tasks`                                        | Get all export task list in the system                                   |
| get_export_task         | GET    | `export/{export_id}`                                  | Get single export task details by export task ID                         |
| get_export_status       | GET    | `export/{export_id}/status`                           | Query export task run status, progress, file size, errors, etc.          |
| download_export_file    | GET    | `export/{export_id}/download`                         | Download the compressed file generated by the export task, only accessible when task is ready |
| confirm_export_download | POST   | `export/{export_id}/confirm`                          | Confirm file download complete, system will auto-clean the export file after 30 minutes |
| cancel_export_task      | DELETE | `export/{export_id}`                                  | Cancel an ongoing export task and clean up corresponding temp files, completed tasks cannot be cancelled |
| create_import_task      | POST   | `import`                                              | Upload zip/tar.gz file, create import task and start importing dataset, max single file 10GB |
| get_import_tasks        | GET    | `import/tasks`                                        | Get all import task list in the system                                   |
| get_import_task         | GET    | `import/{import_id}`                                  | Get single import task details by import task ID                         |
| get_import_status       | GET    | `import/{import_id}/status`                           | Query import task run status, progress, file info, errors, etc.          |
| cancel_import_task      | DELETE | `import/{import_id}`                                  | Cancel an ongoing import task and clean up corresponding temp files, completed tasks cannot be cancelled |
| get_import_export_stats | GET    | `import_export/stats`                                 | Get overall import/export statistics, including task count, disk usage, etc. |
| discover_cameras        | GET    | `cameras/discover`                                    | Trigger image server to rescan hardware, return available camera device list |
| get_active_cameras      | GET    | `cameras/active`                                      | Get currently active camera list and their configurations                |
| add_camera              | POST   | `cameras/add`                                         | Dynamically add and start a camera based on parameters                   |
| remove_camera           | DELETE | `cameras/remove`                                      | Stop and remove specified camera                                         |
| update_camera           | PUT    | `cameras/update`                                      | Update specified camera configuration (only update provided fields)      |
| get_robot_joints        | GET    | `robot/joints`                                        | Get robot joint positions, joint angles / TCP end-effector pose, unit: rad |

---

# 6. Code Structure

```
xr_teleoperate_rico/            # Main project root directory
├── config/                     # Configuration files directory
│   ├── system.json             # System configuration
│   └── robot.json              # Robot configuration
│
├── docs/                       # Documentation directory
│   ├── meta_quest_setup.md     # Meta Quest device setup guide
│   └── meta_quest_setup_zh.md  # Meta Quest device setup guide (Chinese)
│
├── teleop/                     # Core teleoperation module
│   ├── teleop_hand_and_arm.py  # Main entry point (state machine + main loop)
│   ├── config_loader.py        # Configuration loader
│   │
│   ├── DucoCobot.py            # Robot dual-arm interface
│   ├── DucoCobotHead.py        # Robot head interface
│   ├── DucoCobotWaist.py       # Robot waist interface
│   ├── gen_py/robot/           # Thrift auto-generated code
│   │   └── ...
│   │
│   ├── log_manager/            # Log manager
│   │   ├── __init__.py
│   │   └── loguru_logger.py                   # Loguru logging wrapper
│   │
│   ├── robot_control/          # Robot control layer
│   │   ├── robot_arm.py       # Dual-arm controller
│   │   ├── robot_arm_ik.py    # Inverse kinematics
│   │   ├── robot_hand_bchand.py  # BChand dexterous hand controller
│   │   ├── robot_head.py      # Head controller
│   │   └── robot_waist.py     # Waist/external axis controller
│   │
│   ├── televuer/               # TeleVuer XR bridge
│   │   ├── cert.pem           # SSL certificate
│   │   ├── key.pem            # SSL private key
│   │   └── src/televuer/
│   │       ├── televuer.py     # TeleVuer base (Vuer service + pose reception)
│   │       └── tv_wrapper.py   # TeleVuerWrapper (VR→Robot coordinate transformation)
│   │
│   ├── teleimager/             # Image acquisition system
│   │   ├── src/teleimager/
│   │   │   └── humanoid_image_client.py  # Image client
│   │   └── humanoid_vision_system_ws/     # Image server ROS2 workspace
│   │       ├── src/humanoid_vision_system/
│   │       │   └── vision_system/
│   │       │       ├── camera_nodes/     # Camera driver nodes
│   │       │       ├── communication/    # Communication modules (ZMQ/WebRTC/ROS2)
│   │       │       ├── config/           # Configuration management
│   │       │       ├── scripts/          # Launch scripts
│   │       │       └── utils/            # Utility functions
│   │       ├── manual_config/            # Manual camera configuration
│   │       ├── build/                    # Build directory
│   │       └── install/                  # Install directory
│   │
│   ├── api/                    # FastAPI Web interface layer
│   │   ├── app.py              # FastAPI app creation + server startup
│   │   ├── routers.py          # API routes
│   │   ├── shared_state.py     # Thread-safe shared state
│   │   ├── models.py           # Data models
│   │   ├── dataset_manager.py  # Dataset management
│   │   ├── dataset_io.py       # Dataset import/export
│   │   └── requirements.txt    # API module dependencies
│   │
│   └── utils/                  # Utility modules
│       ├── episode_writer.py   # Async recorder
│       ├── camera_manager.py   # Camera manager
│       ├── dataset_io.py       # Dataset import/export
│       ├── rerun_visualizer.py # Rerun visualization
│       └── init_tmp_dirs.py    # Temp directory initialization
│
├── vla_data_util/              # VLA dataset format conversion tool
│   ├── convert.py
│   ├── README.md
│   └── README_zh.md
│
├── tmp/                        # Dataset import/export temporary directory
│   ├── exports/
│   └── imports/
│
├── data/                       # Task data directory
│   └── task_xxxx/
│       └── episode_xxxx/
│
├── download/                   # Certificate download directory
│   └── *.pem
│
├── QUICKSTART.md               # Quick start guide
├── QUICKSTART_zh.md            # Quick start guide (Chinese)
├── requirements.txt            # Environment dependencies
└── README.md / README_zh.md    # Project documentation
```

Recommended reading order:

1. `[teleop/teleop_hand_and_arm.py](./teleop/teleop_hand_and_arm.py)`: Main entry, CLI, state machine, startup sequence, control logic, and recorder integration.
2. `[teleop/config_loader.py](./teleop/config_loader.py)`: Built-in defaults and CLI override merge logic.
3. `[teleop/televuer/src/televuer/televuer.py](./teleop/televuer/src/televuer/televuer.py)` and `[teleop/televuer/src/televuer/tv_wrapper.py](./teleop/televuer/src/televuer/tv_wrapper.py)`: HTTPS XR service, motion state acquisition, display modes, coordinate transformation, and waist derivation.
4. `[teleop/teleimager/src/teleimager/humanoid_image_client.py](./teleop/teleimager/src/teleimager/humanoid_image_client.py)` and `[teleop/teleimager/humanoid_vision_system_ws](./teleop/teleimager/humanoid_vision_system_ws)`: Multi-camera service, WebRTC / ZMQ transport, and configuration requests.
5. `[teleop/robot_control/robot_arm.py](./teleop/robot_control/robot_arm.py)`, `[teleop/robot_control/robot_waist.py](./teleop/robot_control/robot_waist.py)`, `[teleop/robot_control/robot_head.py](./teleop/robot_control/robot_head.py)`, and `[teleop/robot_control/robot_hand_bchand.py](./teleop/robot_control/robot_hand_bchand.py)`: Hardware-facing control backends.
6. `[teleop/utils/episode_writer.py](./teleop/utils/episode_writer.py)`: Async recorder and episode structure.

Current recording output directory structure:

```
task_xxxx/
└── episode_xxxx/
    ├── data.json
    ├── frames_index.json
    ├── colors/
    ├── depths/
    └── audios/      # Only created when recording.save_audio=true
```

Under the default monocular head camera configuration, the recorder typically writes:

- `color_0`: Head color image
- `color_2`: Left wrist color image
- `color_3`: Right wrist color image
- `depth_0`: Head depth image (when enabled)
- `depth_2`: Left wrist depth image
- `depth_3`: Right wrist depth image

When `head_camera.binocular: true`, head images are split into `color_0` and `color_1`.

---

# 7. Acknowledgments

- [unitreerobotics/xr_teleoperate](https://github.com/unitreerobotics/xr_teleoperate)
- [OpenTeleVision/TeleVision](https://github.com/OpenTeleVision/TeleVision)
- [vuer-ai/vuer](https://github.com/vuer-ai/vuer)
