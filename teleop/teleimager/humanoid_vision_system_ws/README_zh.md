# Humanoid Vision System

[中文](README_zh.md) | [English](README.md)

## 目录

- [Humanoid Vision System](#humanoid-vision-system)
  - [目录](#目录)
  - [1. 系统要求](#1-系统要求)
  - [2. 安装步骤](#2-安装步骤)
    - [2.1 环境配置](#21-环境配置)
      - [2.1.1 安装 Miniconda3](#211-安装-miniconda3)
      - [2.1.2 创建并激活 Conda 环境](#212-创建并激活-conda-环境)
      - [2.1.3 升级pip](#213-升级pip)
      - [2.1.4 安装Python依赖](#214-安装python依赖)
    - [2.2 安装 mkcert并生成证书](#22-安装-mkcert并生成证书)
    - [2.3 安装ROS2系统依赖](#23-安装ros2系统依赖)
    - [2.4 编译Protocol Buffers文件](#24-编译protocol-buffers文件)
    - [2.5 构建ROS2工作空间](#25-构建ros2工作空间)
  - [3. 使用方法](#3-使用方法)
    - [3.1 启动视觉系统](#31-启动视觉系统)
    - [3.2 启动图像前端显示](#32-启动图像前端显示)
  - [4. 依赖说明](#4-依赖说明)
    - [4.1 ROS2系统依赖（通过apt安装）](#41-ros2系统依赖通过apt安装)
    - [4.2 Python依赖（通过pip安装）](#42-python依赖通过pip安装)
    - [4.3 ROS2相关Python依赖](#43-ros2相关python依赖)
  - [5. 配置文件](#5-配置文件)
    - [5.1 配置文件查找优先级](#51-配置文件查找优先级)
    - [5.2 配置文件结构](#52-配置文件结构)
    - [5.3 配置文件说明](#53-配置文件说明)
    - [5.4 完整配置示例](#54-完整配置示例)
    - [5.5 配置参数说明](#55-配置参数说明)
  - [6. 代码结构](#6-代码结构)
  - [7. 故障排除](#7-故障排除)
    - [7.1 RealSense相机无法识别](#71-realsense相机无法识别)
    - [7.2 端口冲突](#72-端口冲突)
    - [7.3 依赖安装失败](#73-依赖安装失败)
  - [8. 许可证](#8-许可证)

---

## 1. 系统要求

- Ubuntu 22.04 LTS
- ROS2 Humble
- Python 3.10+
- RealSense相机（可选）
- ARM64架构（X86请自行切换安装对应依赖）

> **注意**：详细配置说明请查看根目录下的README_zh.md,以根目录下的README_zh.md为准
---

## 2. 安装步骤

### 2.1 环境配置

#### 2.1.1 安装 Miniconda3

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
```

#### 2.1.2 创建并激活 Conda 环境

```bash
conda create -n rico_xr python=3.10 numpy=1.26.4 -y
conda activate rico_xr
```

#### 2.1.3 升级pip

```bash
pip install --upgrade pip
```

#### 2.1.4 安装Python依赖

```bash
# 在conda环境下安装依赖
conda activate rico_xr
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2.2 安装 mkcert并生成证书

```bash
# 例如在download文件夹下执行,生成证书，ARM64 架构和 X86 架构二选一
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

# 生成并安装本地 CA 证书
mkcert -install

# 生成针对本机 IP 和 localhost 的证书
# 注意：请将 192.168.120.44 替换为您的实际IP地址
mkcert 192.168.120.44 localhost

# 替换证书（注意：mkcert生成的证书文件名格式为：<IP>+<数字>.pem）
# 例如：192.168.120.44+1.pem，请根据实际生成的文件名调整复制命令
mkdir -p ~/.config/xr_teleoperate
cp 192.168.120.44+1.pem ~/.config/xr_teleoperate/cert.pem
cp 192.168.120.44+1-key.pem ~/.config/xr_teleoperate/key.pem

# xr_teleoperate_rico/teleop/televuer/ 目录下的 `cert.pem` 和 `key.pem` 自行替换,eg:
cp 192.168.120.44+1.pem ../../../televuer/cert.pem
cp 192.168.120.44+1-key.pem ../../../televuer/key.pem
```

### 2.3 安装ROS2系统依赖

```bash
# 非conda环境下运行
conda deactivate
cd /path/to/xr_teleoperate_rico

# 添加ros2源
# 导入 ROS 2 GPG 公钥
sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | sudo gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg
# 添加清华 ROS 2 镜像源
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

### 2.4 编译Protocol Buffers文件

```bash
cd humanoid_vision_system_ws/src/humanoid_vision_system
bash scripts/compile_proto.sh
```

### 2.5 构建ROS2工作空间

```bash
# 非conda环境下执行,构建ROS2工作空间:
source /opt/ros/humble/setup.bash
cd ../../
rm -rf build/ install/ log/ #确保目录正确清理旧缓存
colcon build --packages-select humanoid_vision_system
source install/setup.bash
```

---

## 3. 使用方法

### 3.1 启动视觉系统

```bash
# 1.切换到工作空间目录
cd humanoid_vision_system_ws

# 2. 激活conda环境
conda activate rico_xr

# 3. 激活ROS2环境
source /opt/ros/humble/setup.bash

# 4. 激活工作空间
source install/setup.bash

# 5. 启动系统
# 启动（自动检测并启动头部相机（默认））
ros2 run humanoid_vision_system vision_system_main.py --auto-detect

# 或使用手动配置(需要先配置manual_config/manual_camera.json)
ros2 run humanoid_vision_system vision_system_main.py --no-auto-detect
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--auto-detect` | 自动检测并启动头部相机（默认） |
| `--no-auto-detect` | 使用 `manual_config/manual_camera.json` 中的配置启动 |

### 3.2 启动图像前端显示

```bash
# 在conda环境下启动前端显示
cd humanoid_vision_system_ws/client_test
python3 -m http.server 9000
```

然后在浏览器中访问 `http://机器人地址:9000/` 查看图像前端显示，例如：`http://192.168.120.44:9000/`，linux优先使用非snap的Chrome浏览器。

**操作步骤：**

1. 访问 `http://192.168.120.44:9000/`
2. 选择 `webrtc_viewer.html` 查看图像前端显示，并输入对应参数（服务器地址、端口号及相机ID）
3. 在另一个网页标签中访问 `https://192.168.120.44:8998/` 并信任证书
4. 返回第一个网页，即可查看图像前端显示

---

## 4. 依赖说明

### 4.1 ROS2系统依赖（通过apt安装）

- ros-humble-desktop
- ros-humble-sensor-msgs
- ros-humble-vision-msgs
- ros-humble-tf2-ros

### 4.2 Python依赖（通过pip安装）

| 依赖 | 版本 | 说明 |
|------|------|------|
| numpy | >=1.26.0 | 数值计算 |
| opencv-python | >=4.11.0 | 图像处理 |
| pyrealsense2 | ==2.56.5.9235 | RealSense相机支持 |
| PyYAML | ==6.0.3 | YAML配置文件解析 |
| protobuf | ==3.20.3 | Protocol Buffers序列化 |
| zstandard | ==0.18.0 | ZSTD压缩 |
| pyzmq | ==27.1.0 | ZeroMQ通信 |
| websockets | >=15.0.1 | WebSocket通信 |
| aiortc | ==1.14.0 | WebRTC支持 |
| aiohttp | ==3.13.3 | 异步HTTP服务器 |
| loguru | >=0.6.0 | 日志记录 |
| av | >=16.1.0 | 音视频编解码 |
| setuptools | >=58.0.0 | — |
| wheel | >=0.37.0 | — |

### 4.3 ROS2相关Python依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| ament-index-python | — | ROS2包索引，conda环境下安装失败也没关系，激活ROS2环境即可使用系统安装的 |
| catkin_pkg | — | ROS2包管理 |
| empy | ==3.3.4 | ROS2模板引擎 |
| lark | ==1.1.0 | ROS2解析器 |

---

## 5. 配置文件

### 5.1 配置文件查找优先级

1. `humanoid_vision_system_ws/manual_config/manual_camera.json` （用户配置）
2. `install/humanoid_vision_system/share/humanoid_vision_system/manual_config/manual_camera.json` （安装配置）

系统按照以下优先级查找配置文件（按顺序查找，找到第一个存在的文件即使用）：

1. **ROS2标准路径**（通过`ament_index_python`查找）
   - `install/humanoid_vision_system/share/humanoid_vision_system/manual_config/manual_camera.json`
   - 这是ROS2标准方式，在source了install/setup.bash后可用

2. **环境自适应路径**
   - **从install启动时**：`install/humanoid_vision_system/share/humanoid_vision_system/manual_config/manual_camera.json`
   - **从源码启动时**：`humanoid_vision_system_ws/manual_config/manual_camera.json`

**说明**：
- 从install启动时，install路径优先级最高
- 从源码启动时，如果install路径存在则优先使用，否则使用工作空间根目录的配置
- 建议使用install方式启动，符合ROS2最佳实践

### 5.2 配置文件结构

```
humanoid_vision_system_ws/
├── manual_config/           # 用户手动配置(根目录)
│   └── manual_camera.json
├── src/humanoid_vision_system/
│   ├── config/              # 默认配置(模板,无需修改)
│   │   ├── global_config.json
│   │   └── camera_config.json
│   └── ...
└── install/
    └── humanoid_vision_system/
        └── share/
            └── humanoid_vision_system/
                └── manual_config/  # 安装后用户配置
                    └── manual_camera.json
```

### 5.3 配置文件说明

| 文件 | 说明 |
|------|------|
| `manual_config/manual_camera.json` | 用户手动配置文件（配置此文件内容） |
| `config/global_config.json` | 全局系统配置 |
| `config/camera_config.json` | 相机默认配置（模板，无需修改） |

global_config.json参数说明:

| 参数 | 说明 | 可选值 |
|------|------|--------|
| vision_system.node_name | 视觉系统节点名称 | humanoid_vision_system |
| synchronization.sync_tolerance_ms | 同步容差（ms） | 5.0 |
| log_manager.log_directory | 日志目录 | ./logs |
| log_manager.log_level | 日志级别 | INFO |
| log_manager.rotation_size_mb | 日志文件大小（MB） | 120 |
| log_manager.retention_days | 日志文件保留天数 | 60 |
| log_manager.compression_enabled | 是否启用日志压缩 | true |
| log_manager.encoding | 日志编码 | utf-8 |
| port_allocation.zeromq.base_image_port | ZMQ 图像端口 | 5555 |
| port_allocation.zeromq.base_status_port | ZMQ 状态端口 | 5556 |
| port_allocation.zeromq.config_rep_port | ZMQ 配置端口 | 60000 |
| port_allocation.zeromq.port_increment | ZMQ 端口增量 | 10 |
| port_allocation.websocket.base_port | WebSocket 基础端口 | 8765 |
| port_allocation.websocket.port_increment | WebSocket 端口增量 | 1 |
| port_allocation.webrtc.base_port | WebRTC 基础端口（全局唯一） | 8998 |
| port_allocation.fallback_range | WebRTC 回退范围 | [20000, 30000] |


### 5.4 完整配置示例

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

> **注意**：WebRTC端口（`port: 8998`）全局唯一(不建议修改，默认即可)，多相机配置时需保持一致。

### 5.5 配置参数说明

| 参数 | 说明 | 可选值 |
|------|------|--------|
| camera_id | 相机ID | 严格按照头:head_camera,手:left/right_wrist_camera,胸部:front/back_chest_camera |
| camera_type | 相机类型 | opencv, realsense, realsensecamera |
| model | 相机型号 | D435, D405, fisheye 等 |
| serial_number | 序列号 | RealSense相机序列号 |
| device_index | 设备索引 | OpenCV相机索引 |
| position | 位置标识 | 严格按照(HEAD/LEFT_WRIST/RIGHT_WRIST/FRONT_CHEST/BACK_CHEST) |
| enabled | 是否启用 | true, false |
| binocular | 是否双目相机 | true, false |
| streams.color.enabled | 彩色流启用 | true, false |
| streams.depth.enabled | 深度流启用 | true, false |
| streams.color.capture_width | 彩色流捕获宽度 | 640 |
| streams.color.capture_height | 彩色流捕获高度 | 480 |
| streams.color.publish_width | 彩色流发布宽度 | 640 |
| streams.color.publish_height | 彩色流发布高度 | 480 |
| streams.color.fps | 彩色流帧率 | 15, 30 |
| 深度流同彩色流 | 分辨率帧率均需符合相机实际能力 | — |
| compression.rgb.format | 彩色流压缩格式 JPEG(有损)/PNG(无损) | JPEG/PNG |
| compression.rgb.quality | JPEG 压缩质量或 PNG 压缩级别 | 0-100 值越大，质量越好，压缩率越小 |
| compression.depth.quantization_bits | 深度图量化位数 16为无损,值越小深度精度越低，但压缩率越高 | 1-16 |
| compression.depth.zstd_compression_level | 深度压缩ZSTD 压缩级别，值越大压缩率越高但速度越慢 | 1-22 |
| publisher_compression | 发布器压缩配置，用于覆盖特定发布器的压缩参数。结构同 compression，但只配置需要覆盖的参数，未配置的继承自 compression,为空时使用默认压缩参数 | — |
| communication | 通信配置 | — |
| communication.zeromq.enabled | 是否启用zeromq通信 | true, false |
| communication.zeromq.image_publish_port | 图像发布端口 | 5555 |
| communication.zeromq.status_publish_port | 状态发布端口 | 5556 |
| communication.websocket.enabled | 是否启用websocket通信 | true, false |
| communication.websocket.host | websocket主机地址 | 0.0.0.0 |
| communication.websocket.port | websocket端口 | 8765 |
| communication.webrtc.enabled | 是否启用webrtc通信 | true, false |
| communication.webrtc.video_codec | webrtc视频编码器 | VP8 或 H264 |
| communication.webrtc.port | webrtc端口 | 8998（全局唯一，多相机需保持一致） |
| 全局配置 | 全局配置文件 | 无需修改，保持默认配置即可 |

---

## 6. 代码结构
```
humanoid_vision_system_ws/
├── README.md                                          # 项目说明文档
├── manual_config/
│   └── manual_camera.json                             # 手动相机配置文件
├── node_modules/
│   └── zstd-codec/...
├── install/
└── src/
    └── humanoid_vision_system/                        # ROS2 功能包根目录
        ├── CMakeLists.txt                             # ROS2 ament_cmake 构建脚本
        ├── package.xml                                # ROS2 包描述
        ├── setup.py                                   # Python 包安装脚本
        ├── setup.cfg                                  # Python 包元数据配置
        ├── requirements.txt                           # Python 依赖列表
        ├── scripts/
        │   └── compile_proto.sh                       # Protobuf 编译脚本
        ├── msg/                                       # ROS2 自定义消息定义
        │   ├── CompressedImage.msg                    # 压缩图像消息
        │   ├── CompressionInfo.msg                    # 压缩信息消息
        │   └── CameraStatus.msg                       # 相机状态消息
        ├── proto/                                     # Protobuf 消息定义
        │   └── vision_messages.proto                  # 视觉系统通信协议定义
        ├── config/                                    # 默认配置文件
        │   ├── global_config.json                     # 全局默认配置
        │   └── camera_config.json                     # 相机默认配置
        └── vision_system/                             # 核心源码
            ├── __init__.py
            ├── scripts/
            │   ├── __init__.py
            │   └── vision_system_main.py              # 主入口
            ├── camera_nodes/                          # 相机节点层
            │   ├── __init__.py
            │   ├── base_camera_node.py                # 相机节点基类
            │   ├── realsense_camera.py                # RealSense 相机节点
            │   ├── opencv_camera.py                   # OpenCV 相机节点
            │   └── camera_factory.py                  # 相机工厂
            ├── image_processing/                      # 图像处理层
            │   ├── __init__.py
            │   ├── compression.py                     # 图像压缩
            │   ├── format_converter.py                # 格式转换
            │   └── synchronization.py                 # 多相机时间同步
            ├── communication/                         # 通信发布层
            │   ├── __init__.py
            │   ├── communication_manager.py           # 通信管理器）
            │   ├── zmq_publisher.py                   # ZMQ 发布器
            │   ├── websocket_publisher.py             # WebSocket 发布器
            │   ├── webrtc_publisher.py                # WebRTC 发布器
            │   ├── webrtc_signaling_server.py         # WebRTC 信令服务器
            │   └── ros2_publisher.py                  # ROS2 话题发布器
            ├── config/                                # 配置管理层
            │   ├── config_manager.py                  # 配置管理器
            │   └── dynamic_config_handler.py          # 动态配置处理
            ├── utils/                                 # 工具层
            │   ├── __init__.py
            │   ├── camera_discovery.py                # 相机自发现
            │   ├── port_manager.py                    # 端口管理
            │   ├── timing.py                          # 时间工具
            │   └── ros2_message_converter.py          # ROS2消息转换器
            ├── proto/                                 # Protobuf 生成代码
            │   ├── __init__.py
            │   └── vision_messages_pb2.py             # 编译后的 Protobuf Python 类
            └── log_manager/                               # 日志层
                ├── __init__.py
                └── loguru_logger.py                   # Loguru 日志封装
```
---

## 7. 故障排除

### 7.1 RealSense相机无法识别

```bash
# 检查RealSense设备
realsense-viewer
# 或者使用以下命令查看所有RealSense设备：
sudo apt install -y librealsense2-utils librealsense2-dev
rs-enumerate-devices
# 列出所有视频设备及其名称，需安装v4l2-ctl工具
sudo apt install -y v4l-utils v4l2-ctl
v4l2-ctl --list-devices
```

### 7.2 端口冲突

编辑配置文件修改端口设置。

### 7.3 依赖安装失败

```bash
# 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 如果清华镜像源失败，尝试使用其他镜像源：
# https://mirrors.aliyun.com/pypi/simple/
# https://pypi.mirrors.ustc.edu.cn/simple/
# https://mirrors.huaweicloud.com/repository/pypi/simple/
# https://pypi.doubanio.com/simple/
```

---

## 8. 许可证

Apache-2.0