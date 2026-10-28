# Humanoid Vision System

[中文](README_zh.md) | [English](README.md)

## Table of Contents

- [Humanoid Vision System](#humanoid-vision-system)
  - [Table of Contents](#table-of-contents)
  - [1. System Requirements](#1-system-requirements)
  - [2. Installation](#2-installation)
    - [2.1 Environment Setup](#21-environment-setup)
      - [2.1.1 Install Miniconda3](#211-install-miniconda3)
      - [2.1.2 Create and Activate Conda Environment](#212-create-and-activate-conda-environment)
      - [2.1.3 Upgrade pip](#213-upgrade-pip)
      - [2.1.4 Install Python Dependencies](#214-install-python-dependencies)
    - [2.2 Install mkcert and Generate Certificates](#22-install-mkcert-and-generate-certificates)
    - [2.3 Install ROS2 System Dependencies](#23-install-ros2-system-dependencies)
    - [2.4 Compile Protocol Buffers Files](#24-compile-protocol-buffers-files)
    - [2.5 Build ROS2 Workspace](#25-build-ros2-workspace)
  - [3. Usage](#3-usage)
    - [3.1 Start Vision System](#31-start-vision-system)
    - [3.2 Start Image Frontend Display](#32-start-image-frontend-display)
  - [4. Dependencies](#4-dependencies)
    - [4.1 ROS2 System Dependencies (via apt)](#41-ros2-system-dependencies-via-apt)
    - [4.2 Python Dependencies (via pip)](#42-python-dependencies-via-pip)
    - [4.3 ROS2-Related Python Dependencies](#43-ros2-related-python-dependencies)
  - [5. Configuration File](#5-configuration-file)
    - [5.1 Configuration File Search Priority](#51-configuration-file-search-priority)
    - [5.2 Configuration File Structure](#52-configuration-file-structure)
    - [5.3 Configuration File Description](#53-configuration-file-description)
    - [5.4 Complete Configuration Example](#54-complete-configuration-example)
    - [5.5 Configuration Parameter Reference](#55-configuration-parameter-reference)
  - [6. Code Structure](#6-code-structure)
  - [7. Troubleshooting](#7-troubleshooting)
    - [7.1 RealSense Camera Not Detected](#71-realsense-camera-not-detected)
    - [7.2 Port Conflict](#72-port-conflict)
    - [7.3 Dependency Installation Failure](#73-dependency-installation-failure)
  - [8. License](#8-license)

---

## 1. System Requirements

- Ubuntu 22.04 LTS
- ROS2 Humble
- Python 3.10+
- RealSense cameras (optional)
- ARM64 architecture (for X86, please switch to the corresponding dependencies on your own)

---

## 2. Installation

### 2.1 Environment Setup

#### 2.1.1 Install Miniconda3

```bash
# Install Miniconda3
mkdir -p ~/miniconda3
# Download command - choose one of ARM64 or X86 architecture
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O ~/miniconda3/miniconda.sh #ARM64
# wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda3/miniconda.sh #X86_64
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
rm ~/miniconda3/miniconda.sh
source ~/miniconda3/bin/activate
conda init --all
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Configure Tsinghua mirror source (architecture-agnostic)
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
conda config --set show_channel_urls yes
```

#### 2.1.2 Create and Activate Conda Environment

```bash
conda create -n rico_xr python=3.10 numpy=1.26.4 -y
conda activate rico_xr
```

#### 2.1.3 Upgrade pip

```bash
pip install --upgrade pip
```

#### 2.1.4 Install Python Dependencies

```bash
# Install dependencies inside the conda environment
conda activate rico_xr
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2.2 Install mkcert and Generate Certificates

```bash
# e.g., execute in the download folder to generate certificates, choose ARM64 or X86 architecture
mkdir -p humanoid_vision_system_ws/download
cd humanoid_vision_system_ws/download
sudo apt install libnss3-tools
# ARM64 architecture
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

# Replace cert.pem and key.pem under xr_teleoperate_rico/teleop/televuer/ on your own, eg:
cp 192.168.120.44+1.pem ../../../televuer/cert.pem
cp 192.168.120.44+1-key.pem ../../../televuer/key.pem
```

### 2.3 Install ROS2 System Dependencies

```bash
# Execute outside the conda environment
conda deactivate
cd /path/to/xr_teleoperate_rico

# Add ROS2 source
# Import ROS 2 GPG key
sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | sudo gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg
# Add Tsinghua ROS 2 mirror source
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu jammy main" | sudo tee /etc/apt/sources.list.d/ros2.list

sudo apt update
sudo apt install ros-humble-desktop \
    ros-humble-sensor-msgs \
    ros-humble-vision-msgs \
    ros-humble-tf2-ros \
    ros-humble-image-transport \
    v4l-utils \
    python3-colcon-common-extensions \
    protobuf-compiler

```

### 2.4 Compile Protocol Buffers Files

```bash
cd humanoid_vision_system_ws/src/humanoid_vision_system
bash scripts/compile_proto.sh
```

### 2.5 Build ROS2 Workspace

```bash
# Execute outside the conda environment to build the ROS2 workspace:
source /opt/ros/humble/setup.bash
cd ../../
rm -rf build/ install/ log/ # make sure old caches are properly cleaned
colcon build --packages-select humanoid_vision_system
source install/setup.bash
```

---

## 3. Usage

### 3.1 Start Vision System

```bash
# 1. Navigate to workspace directory
cd humanoid_vision_system_ws

# 2. Activate conda environment
conda activate rico_xr

# 3. Source ROS2 environment
source /opt/ros/humble/setup.bash

# 4. Source workspace
source install/setup.bash

# 5. Start the system
# Start (auto-detect and start head camera by default)
ros2 run humanoid_vision_system vision_system_main.py --auto-detect

# Or use manual configuration (requires manual_config/manual_camera.json to be configured first)
ros2 run humanoid_vision_system vision_system_main.py --no-auto-detect
```

**Parameter Description:**

| Parameter | Description |
|-----------|-------------|
| `--auto-detect` | Auto-detect and start head camera (default) |
| `--no-auto-detect` | Use configuration from `manual_config/manual_camera.json` |

### 3.2 Start Image Frontend Display

```bash
# Start frontend display inside the conda environment
cd humanoid_vision_system_ws/client_test
python3 -m http.server 9000
```

Then access `http://<robot-address>:9000/` in your browser to view the image frontend display, e.g., `http://192.168.120.44:9000/`. On Linux, prefer using a non-snap Chrome browser.

**Operation Steps:**

1. Visit `http://192.168.120.44:9000/`
2. Select `webrtc_viewer.html` to view the image frontend display, and enter the corresponding parameters (server address, port number, and camera ID)
3. Open `https://192.168.120.44:8998/` in another browser tab and trust the certificate
4. Return to the first tab to view the image frontend display

---

## 4. Dependencies

### 4.1 ROS2 System Dependencies (via apt)

- ros-humble-desktop
- ros-humble-sensor-msgs
- ros-humble-vision-msgs
- ros-humble-tf2-ros

### 4.2 Python Dependencies (via pip)

| Dependency | Version | Description |
|------------|---------|-------------|
| numpy | >=1.26.0 | Numerical computation |
| opencv-python | >=4.11.0 | Image processing |
| pyrealsense2 | ==2.56.5.9235 | RealSense camera support |
| PyYAML | ==6.0.3 | YAML configuration file parsing |
| protobuf | ==3.20.3 | Protocol Buffers serialization |
| zstandard | ==0.18.0 | ZSTD compression |
| pyzmq | ==27.1.0 | ZeroMQ communication |
| websockets | >=15.0.1 | WebSocket communication |
| aiortc | ==1.14.0 | WebRTC support |
| aiohttp | ==3.13.3 | Async HTTP server |
| loguru | >=0.6.0 | Logging |
| av | >=16.1.0 | Audio/video codec |
| setuptools | >=58.0.0 | — |
| wheel | >=0.37.0 | — |

### 4.3 ROS2-Related Python Dependencies

| Dependency | Version | Description |
|------------|---------|-------------|
| ament-index-python | — | ROS2 package index; it's fine if installation fails inside conda — activating the ROS2 environment will use the system-installed version |
| catkin_pkg | — | ROS2 package management |
| empy | ==3.3.4 | ROS2 template engine |
| lark | ==1.1.0 | ROS2 parser |

---

## 5. Configuration File

### 5.1 Configuration File Search Priority

1. `humanoid_vision_system_ws/manual_config/manual_camera.json` (user configuration)
2. `install/humanoid_vision_system/share/humanoid_vision_system/manual_config/manual_camera.json` (installed configuration)

The system searches for configuration files in the following priority order (searches in order, uses the first existing file found):

1. **ROS2 standard path** (looked up via `ament_index_python`)
   - `install/humanoid_vision_system/share/humanoid_vision_system/manual_config/manual_camera.json`
   - This is the ROS2 standard approach, available after sourcing `install/setup.bash`

2. **Environment-adaptive paths**
   - **When launched from install**: `install/humanoid_vision_system/share/humanoid_vision_system/manual_config/manual_camera.json`
   - **When launched from source**: `humanoid_vision_system_ws/manual_config/manual_camera.json`

**Note**:
- When launched from install, the install path has the highest priority
- When launched from source, the install path is used preferentially if it exists; otherwise, the workspace root configuration is used
- It is recommended to use the install launch method, which follows ROS2 best practices

### 5.2 Configuration File Structure

```
humanoid_vision_system_ws/
├── manual_config/           # User manual configuration (root directory)
│   └── manual_camera.json
├── src/humanoid_vision_system/
│   ├── config/              # Default configuration (templates, no modification needed)
│   │   ├── global_config.json
│   │   └── camera_config.json
│   └── ...
└── install/
    └── humanoid_vision_system/
        └── share/
            └── humanoid_vision_system/
                └── manual_config/  # User configuration after installation
                    └── manual_camera.json
```

### 5.3 Configuration File Description

| File | Description |
|------|-------------|
| `manual_config/manual_camera.json` | User manual configuration file (configure the contents of this file) |
| `config/global_config.json` | Global system configuration |
| `config/camera_config.json` | Default camera configuration (template, no modification needed) |

global_config.json Configuration Parameters:

| Parameter | Description | Default |
|------|------|--------|
| vision_system.node_name | Vision system node name | humanoid_vision_system |
| synchronization.sync_tolerance_ms | Synchronization tolerance in milliseconds | 5.0 |
| log_manager.log_directory | Log directory path | ./logs |
| log_manager.log_level | Log level | INFO |
| log_manager.rotation_size_mb | Log file rotation size in MB | 120 |
| log_manager.retention_days | Log retention period in days | 60 |
| log_manager.compression_enabled | Enable log compression? | true |
| log_manager.encoding | Log encoding format | utf-8 |
| port_allocation.zeromq.base_image_port | ZMQ image port base | 5555 |
| port_allocation.zeromq.base_status_port | ZMQ status port base | 5556 |
| port_allocation.zeromq.config_rep_port | ZMQ configuration port base | 60000 |
| port_allocation.zeromq.port_increment | ZMQ port increment | 10 |
| port_allocation.websocket.base_port | WebSocket base port number | 8765 |
| port_allocation.websocket.port_increment | WebSocket port increment | 1 |
| port_allocation.webrtc.base_port | WebRTC base port number (global unique)  | 8998 |
| port_allocation.fallback_range | WebRTC fallback range | [20000, 30000] |

### 5.4 Complete Configuration Example

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
      "rgb": {
        "quality": 85,
        "format": "JPEG"
      },
      "depth": {
        "quantization_bits": 12,
        "zstd_compression_level": 3
      }
    },
    "publisher_compression": {
        "zeromq": {
          "rgb": {
            "quality": 90,
            "format": "JPEG"
          },
          "depth": {
            "quantization_bits": 16,
            "zstd_compression_level": 6
          }
        },
        "websocket": {
          "rgb": {
            "quality": 85,
            "format": "JPEG"
          },
          "depth": {
            "quantization_bits": 12,
            "zstd_compression_level": 3
          }
        },
        "webrtc": {
          "rgb": {
            "quality": 85,
            "format": "JPEG"
          }
        },
        "ros2": {
          "rgb": {
            "quality": 95,
            "format": "PNG"
          },
          "depth": {
            "quantization_bits": 12,
            "zstd_compression_level": 3
          }
        }
    },
    "communication": {
      "zeromq": {
        "enabled": true,
        "image_publish_port": 5555,
        "status_publish_port": 5556
      },
      "websocket": {
        "enabled": true,
        "host": "0.0.0.0",
        "port": 8765
      },
      "webrtc": {
        "enabled": true,
        "video_codec": "VP8",
        "port": 8998
      }
    }
  }
}
```

> **Note**: The WebRTC port (`port: 8998`) is globally unique and must remain consistent across multiple camera configurations.

### 5.5 Configuration Parameter Reference

| Parameter | Description | Options |
|-----------|-------------|---------|
| camera_id | Camera ID | Strictly by: head: head_camera, hands: left/right_wrist_camera, chest: front/back_chest_camera |
| camera_type | Camera type | opencv, realsense, realsensecamera |
| model | Camera model | D435, D405, fisheye, etc. |
| serial_number | Serial number | RealSense camera serial number |
| device_index | Device index | OpenCV camera index |
| position | Position identifier | Strictly (HEAD/LEFT_WRIST/RIGHT_WRIST/FRONT_CHEST/BACK_CHEST) |
| enabled | Whether to enable | true, false |
| binocular | Whether it is a binocular camera | true, false |
| streams.color.enabled | Color stream enabled | true, false |
| streams.depth.enabled | Depth stream enabled | true, false |
| streams.color.capture_width | Color stream capture width | 640 |
| streams.color.capture_height | Color stream capture height | 480 |
| streams.color.publish_width | Color stream publish width | 640 |
| streams.color.publish_height | Color stream publish height | 480 |
| streams.color.fps | Color stream frame rate | 15, 30 |
| Depth stream same as color stream | Resolution and frame rate must match actual camera capabilities | — |
| compression.rgb.format | Color stream compression format: JPEG (lossy) / PNG (lossless) | JPEG/PNG |
| compression.rgb.quality | JPEG compression quality or PNG compression level | 0-100; higher value = better quality, lower compression ratio |
| compression.depth.quantization_bits | Depth image quantization bits; 16 = lossless, lower value = lower depth precision but higher compression ratio | 1-16 |
| compression.depth.zstd_compression_level | Depth compression ZSTD compression level; higher value = higher compression ratio but slower speed | 1-22 |
| publisher_compression | Publisher compression configuration for overriding compression parameters of specific publishers. Structure is the same as compression, but only configure parameters that need overriding; unconfigured parameters inherit from compression. When empty, default compression parameters are used | — |
| communication | Communication configuration | — |
| communication.zeromq.enabled | Whether to enable ZeroMQ communication | true, false |
| communication.zeromq.image_publish_port | Image publish port | 5555 |
| communication.zeromq.status_publish_port | Status publish port | 5556 |
| communication.websocket.enabled | Whether to enable WebSocket communication | true, false |
| communication.websocket.host | WebSocket host address | 0.0.0.0 |
| communication.websocket.port | WebSocket port | 8765 |
| communication.webrtc.enabled | Whether to enable WebRTC communication | true, false |
| communication.webrtc.video_codec | WebRTC video codec | VP8 or H264 |
| communication.webrtc.port | WebRTC port | 8998 (globally unique, must be consistent across multiple cameras) |
| Global configuration | Global configuration file | No modification needed, keep default configuration |

---

## 6. Code Structure
```
humanoid_vision_system_ws/
├── README.md                                          # Project documentation
├── manual_config/
│   └── manual_camera.json                             # Manual camera configuration file
├── node_modules/
│   └── zstd-codec/...
├── install/
└── src/
    └── humanoid_vision_system/                        # ROS2 package root directory
        ├── CMakeLists.txt                             # ROS2 ament_cmake build script
        ├── package.xml                                # ROS2 package description
        ├── setup.py                                   # Python package installation script
        ├── setup.cfg                                  # Python package metadata configuration
        ├── requirements.txt                           # Python dependency list
        ├── scripts/
        │   └── compile_proto.sh                       # Protobuf compilation script
        ├── msg/                                       # ROS2 custom message definitions
        │   ├── CompressedImage.msg                    # Compressed image message
        │   ├── CompressionInfo.msg                    # Compression info message
        │   └── CameraStatus.msg                       # Camera status message
        ├── proto/                                     # Protobuf message definitions
        │   └── vision_messages.proto                  # Vision system communication protocol definition
        ├── config/                                    # Default configuration files
        │   ├── global_config.json                     # Global default configuration
        │   └── camera_config.json                     # Camera default configuration
        └── vision_system/                             # Core source code
            ├── __init__.py
            ├── scripts/
            │   ├── __init__.py
            │   └── vision_system_main.py              # Main entry point
            ├── camera_nodes/                          # Camera node layer
            │   ├── __init__.py
            │   ├── base_camera_node.py                # Camera node base class
            │   ├── realsense_camera.py                # RealSense camera node
            │   ├── opencv_camera.py                   # OpenCV camera node
            │   └── camera_factory.py                  # Camera factory
            ├── image_processing/                      # Image processing layer
            │   ├── __init__.py
            │   ├── compression.py                     # Image compression
            │   ├── format_converter.py                # Format conversion
            │   └── synchronization.py                 # Multi-camera time synchronization
            ├── communication/                         # Communication publishing layer
            │   ├── __init__.py
            │   ├── communication_manager.py           # Communication manager
            │   ├── zmq_publisher.py                   # ZMQ publisher
            │   ├── websocket_publisher.py             # WebSocket publisher
            │   ├── webrtc_publisher.py                # WebRTC publisher
            │   ├── webrtc_signaling_server.py         # WebRTC signaling server
            │   └── ros2_publisher.py                  # ROS2 topic publisher
            ├── config/                                # Configuration management layer
            │   ├── config_manager.py                  # Configuration manager
            │   └── dynamic_config_handler.py          # Dynamic configuration handler
            ├── utils/                                 # Utility layer
            │   ├── __init__.py
            │   ├── camera_discovery.py                # Camera auto-discovery
            │   ├── port_manager.py                    # Port management
            │   ├── timing.py                          # Timing utilities
            │   └── ros2_message_converter.py          # ROS2 message converter
            ├── proto/                                 # Protobuf generated code
            │   ├── __init__.py
            │   └── vision_messages_pb2.py             # Compiled Protobuf Python classes
            └── log_manager/                               # Logging layer
                ├── __init__.py
                └── loguru_logger.py                   # Loguru logging wrapper
```
---

## 7. Troubleshooting

### 7.1 RealSense Camera Not Detected

```bash
# Check RealSense devices
realsense-viewer
# Or use the following command to list all RealSense devices:
sudo apt install -y librealsense2-utils librealsense2-dev
rs-enumerate-devices
# List all video devices and their names (requires v4l2-ctl tool)
sudo apt install -y v4l-utils v4l2-ctl
v4l2-ctl --list-devices
```

### 7.2 Port Conflict

Edit the configuration file to modify port settings.

### 7.3 Dependency Installation Failure

```bash
# Use a domestic mirror source
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# If the Tsinghua mirror fails, try other mirror sources:
# https://mirrors.aliyun.com/pypi/simple/
# https://pypi.mirrors.ustc.edu.cn/simple/
# https://mirrors.huaweicloud.com/repository/pypi/simple/
# https://pypi.doubanio.com/simple/
```

---

## 8. License

Apache-2.0
