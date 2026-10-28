# Meta Quest 激活指南

[中文](meta_quest_setup_zh.md) | [English](meta_quest_setup.md)

---

## 目录

- [Meta Quest 激活指南](#meta-quest-激活指南)
  - [目录](#目录)
- [1. 所需设备](#1-所需设备)
- [2. 注册 Meta 帐号](#2-注册-meta-帐号)
- [3. 手机 Meta Horizon APP 安装与使用](#3-手机-meta-horizon-app-安装与使用)
- [4. Oculus 助手使用](#4-oculus-助手使用)
- [5. Meta Quest 激活](#5-meta-quest-激活)
- [6. 开发者模式](#6-开发者模式)
    - [6.1 身份验证](#61-身份验证)
    - [6.2 创建组织](#62-创建组织)
    - [6.3 开启开发者模式](#63-开启开发者模式)
- [7. 说明](#7-说明)
- [8. 鸣谢](#8-鸣谢)

---

# 1. 所需设备

| 设备 | 说明 |
|------|------|
| 电脑 | 1 台可无线上网的电脑（台式机/笔记本均可，Win10/Win11 系统） |
| 头显 | Meta Quest 设备 |

---

# 2. 注册 Meta 帐号

1. 电脑或手机浏览器打开官方网站：[https://auth.meta.com/](https://auth.meta.com/)（需外网环境）
2. 选择邮箱注册，输入自己邮箱注册帐号（支持国内邮箱如 QQ 邮箱等）
<p align="center">
  <img src="../image/meta_account_register_1.png" alt="Meta Quest 帐号注册" width="40%">
</p>

3. 填写个人相关信息，姓名最好用英文或拼音，不要用中文，年龄要大于 20 岁，设置登录密码

<p align="center">
  <img src="../image/meta_account_register_2.png" alt="Meta Quest App开启选项1" width="40%">
  <img src="../image/meta_account_register_3.png" alt="Meta Quest App开启选项2" width="40%">
</p>

<p align="center">
  <img src="../image/meta_account_register_4.png" alt="Meta Quest App开启选项3" width="40%">
  <img src="../image/meta_account_register_5.png" alt="Meta Quest App开启选项4" width="40%">
</p>

4. 输入邮件收到的注册验证码，完成验证
<p align="center">
  <img src="../image/meta_account_register_6.png" alt="Meta Quest 帐号注册" width="40%">
</p>

5. 设置帐号用户名与相关隐私设置（不要使用中文）
6. 完成 Meta 注册
7. 如果显示帐号停用，可上传任意一张五官显示清晰的图片解除停用

---

# 3. 手机 Meta Horizon APP 安装与使用

激活必备手机端 APP：**Meta Horizon**

| 平台 | 下载方式 |
|------|---------|
| Android | 浏览器打开：[https://oc-static.xlemon.cn/oculus/Oculus_latest.apk](https://oc-static.xlemon.cn/oculus/Oculus_latest.apk) |
| iPhone | App Store 下载（需要外区 ID） |

下载完毕后，使用邮箱帐号登录手机 Meta Horizon APP。

---

# 4. Oculus 助手使用

Oculus 助手官网：[https://ochelper.xlemon.cn/home.html](https://ochelper.xlemon.cn/home.html)

优先采用 **Oculus 助手 WIFI 版**激活，如果失败再使用 **极速版**。

下载安装完毕后，运行软件确保以下条件：

1. 使用前需要拔出网线，断开有线连接，仅保留 WIFI 网络连接
2. 使用前需要关闭 Windows 自带的防火墙、三方杀毒软件等
3. 打开 Oculus 助手，等待几分钟完成更新和网卡配置

> 注：Oculus 助手的问题可多参考官方文档和教程。

---

# 5. Meta Quest 激活

1. 开启头显电源，按提示操作，语言选择**中文**，根据选择的Oculus 助手版本按照提示，连接 Oculus 助手开放的 WIFI
2. 同时，手机也连接 Oculus 助手的 WIFI
3. 完成资源更新后，会提示与手机上的 Meta Horizon 配对，按照提示界面操作即可（注意此时头显和手机都需要连接 Oculus 助手的热点）
4. 配对完成后，即可正常使用 Meta Quest设备

> 注意：头显有时会断开和热点的连接，需要关注连接状态，重连后可继续下载。

---

# 6. 开发者模式

### 6.1 身份验证

1. 进入开发者模式验证界面：[https://developer.oculus.com/manage/verify/](https://developer.oculus.com/manage/verify/)
<p align="center">
  <img src="../image/meta_develop_mode_1.png" alt="Meta Quest 开发者模式验证" width="40%">
</p>

2. 点击 **设定（Set Up）**
3. 点击双重认证，选择**身份验证应用**
<p align="center">
  <img src="../image/meta_develop_mode_2.png" alt="Meta Quest App开启选项1" width="40%">
  <img src="../image/meta_develop_mode_3.png" alt="Meta Quest App开启选项2" width="40%">
</p>

4. 下载微软验证器：[https://www.microsoft.com/zh-cn/security/mobile-authenticator-app#downloadtheapp](https://www.microsoft.com/zh-cn/security/mobile-authenticator-app#downloadtheapp)


<p align="center">
  <img src="../image/meta_validator_1.png" alt="Meta Quest App开启选项1" width="30%">
  <img src="../image/meta_validator_2.png" alt="Meta Quest App开启选项2" width="30%">
  <img src="../image/meta_validator_3.png" alt="Meta Quest App开启选项3" width="30%">
</p>

5. 使用个人帐号登录，扫描 Meta 网站的二维码，输入微软验证器 APP 中的 Meta 帐号验证码

### 6.2 创建组织

验证完成后，在以下网站创建组织：[https://developer.oculus.com/manage/organizations/create/](https://developer.oculus.com/manage/organizations/create/)，按照提示操作即可。

<p align="center">
  <img src="../image/meta_validator_4.png" alt="微软验证器" width="60%">
</p>

### 6.3 开启开发者模式

成功后可在 Meta APP 中操作：

```
设备 → 设备设置 → 高级设置 → 开发者模式 → 勾选开启
```

<p align="center">
  <img src="../image/meta_enable_option_1.png" alt="Meta Quest App开启选项1" width="23%">
  <img src="../image/meta_enable_option_2.png" alt="Meta Quest App开启选项2" width="23%">
  <img src="../image/meta_enable_option_3.png" alt="Meta Quest App开启选项3" width="23%">
  <img src="../image/meta_enable_option_4.png" alt="Meta Quest App开启选项4" width="23%">
</p>


# 7. 说明

- 本教程基于 Meta Quest 3s 版本，其他版本可能需要根据实际情况调整，
- 本教程旨在提供一个Meta Quest注册使用简单流程，供用户参考

# 8. 鸣谢

- [oculus-helper](https://www.yuque.com/oculus-helper)
- [jayy/Quest-help](https://www.yuque.com/jayy/30)