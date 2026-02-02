# RhinoV2.0 夹爪控制系统

本项目是基于达妙电机和压力传感器的智能夹爪控制系统，支持手动控制和PID闭环控制两种模式。

---

## 目录

- [硬件清单](#硬件清单)
- [环境安装](#环境安装)
- [快速开始](#快速开始)
- [文件结构](#文件结构)
- [主要程序说明](#主要程序说明)
- [配置说明](#配置说明)
- [常见问题](#常见问题)
- [开发说明](#开发说明)
- [安全注意事项](#安全注意事项)

---

## 硬件清单

### 必需硬件

#### 1. 达妙电机
- **型号**：DM4310（或 DM4340、DM6006 等）
- **额定力矩**：4.3 N·m (DM4310)
- **控制模式**：MIT模式、位置速度模式、速度模式
- **通信接口**：CAN总线
- **供电**：24V DC
- **厂商**：达妙科技
- **用途**：夹爪驱动执行器

#### 2. USB-CAN适配器
- **型号**：DM-FDCAN
- **接口**：USB 2.0
- **CAN协议**：CAN 2.0 / CAN-FD
- **波特率**：可配置（默认 1Mbps）
- **厂商**：达妙科技
- **用途**：电脑与电机CAN总线通信

#### 3. 6x6阵列压力传感器（仅作参考）
- **型号**：6x6阵列压力传感器（36点）
- **厂商**：深圳力感科技
- **类型**：电阻式力敏触觉传感器 (FSR)
- **阵列规格**：6×6 = 36个传感点
- **单点尺寸**：2.5mm × 2.5mm
- **单点面积**：6.25 mm²
- **通信接口**：串口 (UART)
- **波特率**：460800
- **数据格式**：自定义协议（帧头 0xFF66，78字节/帧）
- **应用场景**：机器人手指抓握力识别、触觉反馈
- **购买链接**：
【淘宝】退货运费险 https://e.tb.cn/h.7qFeOVKt2sKIyvf?tk=kPtyU7QJ8po MF937 「原厂人形机器人手指识别抓握力大小电阻式力敏多点触觉传感器FSR」
点击链接直接打开 或者 淘宝搜索直接打开

### 可选硬件

- **电源**：24V DC电源适配器（电机供电）
- **CAN终端电阻**：120Ω（CAN总线两端）
- **连接线缆**：
  - USB数据线（连接USB-CAN适配器）
  - CAN总线线缆
  - 串口线（连接压力传感器）

### 硬件连接示意

```
电脑 ──USB── USB-CAN适配器 ──CAN总线── 达妙电机
 │
 └──串口── 压力传感器
```

---

## 环境安装

### 系统要求

- **操作系统**：Linux (推荐 Ubuntu 18.04+)
- **Python 版本**：Python 3.8+
- **硬件要求**：
  - USB-CAN适配器（达妙 DM-FDCAN）
  - 达妙电机（DM4310 或其他型号）
  - 6x6阵列压力传感器（深圳力感科技）

### 安装步骤

#### 1. 克隆或下载项目

```bash
cd /home/wech1ng/Project/
# 如果已有项目，跳过此步
```

#### 2. 安装Python依赖

```bash
cd RhinoV2.0_Gripper_control

# 方法1：使用 requirements.txt（推荐）
pip3 install -r requirements.txt

# 方法2：手动安装
pip3 install PyQt5>=5.15.0
pip3 install numpy>=1.19.0
pip3 install matplotlib>=3.3.0
pip3 install pyserial>=3.5
pip3 install pyusb>=1.2.0
```

#### 3. 配置USB设备权限

```bash
# 添加当前用户到 dialout 组（串口权限）
sudo usermod -a -G dialout $USER

# 设置USB设备权限（USB-CAN适配器）
sudo chmod 666 /dev/bus/usb/*/*

# 注意：需要重新登录或重启才能生效
```

#### 4. 验证安装

```bash
# 检查Python版本
python3 --version

# 检查依赖库
python3 -c "import PyQt5, numpy, matplotlib, serial, usb; print('所有依赖库已安装')"

# 检查USB-CAN设备
python3 dev_sn.py
```

**预期输出：**
```
Found DM-FDCAN, device-id: device:3,21 SN: 818F9E6ACF42F4147B2EE0FE9382AF11
```

---

## 快速开始

### 1. 硬件连接

#### 电机连接
1. 连接USB-CAN适配器到电脑USB口
2. 连接达妙电机到CAN总线
3. 确保电机供电正常（24V）

#### 传感器连接
1. 连接压力传感器到串口（通常是 `/dev/ttyUSB1` 或 `/dev/ttyACM0`）
2. 确认波特率为 460800

**传感器规格：**
- **型号**：6x6阵列压力传感器（36点）
- **厂商**：深圳力感科技
- **类型**：电阻式力敏触觉传感器 (FSR)
- **单点尺寸**：2.5mm × 2.5mm
- **通信接口**：串口 (UART)
- **波特率**：460800
- **应用场景**：机器人手指抓握力识别、触觉反馈

> **购买参考**：淘宝搜索"人形机器人手指识别抓握力大小电阻式力敏多点触觉传感器FSR"

### 2. 读取设备序列号（重要）

每个USB-CAN适配器都有唯一的设备序列号（SN），需要先读取并配置到程序中。

```bash
# 运行设备序列号读取工具
python3 dev_sn.py
```

**输出示例：**
```
Found DM-FDCAN, device-id: device:3,21 SN: 818F9E6ACF42F4147B2EE0FE9382AF11
```

记录下这个 **SN码**：`818F9E6ACF42F4147B2EE0FE9382AF11`

### 3. 修改程序中的设备码

找到程序中的这一行（通常在主函数或初始化部分）：

```python
self.control = Motor_Control(1000000, 5000000,
                            "818F9E6ACF42F4147B2EE0FE9382AF11",  # ← 修改这里
                            init_data)
```

**将SN码替换为你的设备码。**

#### 需要修改的文件：

1. **gripper_ui_integrated.py**（推荐使用）
   - 位置：`init_hardware()` 函数中，约第667行
   - 搜索：`Motor_Control(1000000, 5000000,`

2. **motor_control_pyqt.py**
   - 位置：`init_motor()` 函数中，约第295行

3. **gripper_control_with_visualization.py**
   - 位置：`if __name__ == "__main__":` 部分

#### 修改示例：

**修改前：**
```python
with Motor_Control(1000000, 5000000, "818F9E6ACF42F4147B2EE0FE9382AF11", init_data1) as control:
```

**修改后（假设你的SN是 `AA96DF2EC013B46B1BE4613798544085`）：**
```python
with Motor_Control(1000000, 5000000, "AA96DF2EC013B46B1BE4613798544085", init_data1) as control:
```

### 4. 检查串口设备

```bash
# 查看可用串口
ls -l /dev/ttyUSB* /dev/ttyACM*
```

**输出示例：**
```
/dev/ttyUSB1  # 压力传感器
/dev/ttyACM0  # 其他设备
```

如果传感器不在 `/dev/ttyUSB1`，需要修改程序中的串口配置：

```python
# 在程序开头找到这一行（约第33行）
SERIAL_PORT = '/dev/ttyUSB1'  # 修改为实际串口
```

### 5. 运行程序

#### 推荐：使用整合UI程序

```bash
python3 gripper_ui_integrated.py
```

**操作步骤：**
1. 程序启动，自动初始化电机和传感器
2. 点击 **"使能电机"** 按钮
3. 选择控制模式：
   - **手动控制**：切换到"手动控制"标签页，点击"打开"或"闭合"
   - **PID控制**：切换到"PID控制+可视化"标签页，设置参数后点击"开始PID控制"
4. 使用完毕后点击 **"失能电机"** 或直接关闭窗口

#### 其他程序

```bash
# 手动控制UI
python3 motor_control_pyqt.py

# 压力传感器测试（含可视化）
python3 test_pressure.py

# PID控制+可视化（按'q'退出）
python3 gripper_control_with_visualization.py
```

---

## 文件结构

```
RhinoV2.0_Gripper_control/
├── README.md                                    # 本文档
├── requirements.txt                             # Python依赖库列表
├── dm_README.md                                 # 达妙电机原始文档
├── dev_sn.py                                    # 设备序列号读取工具
│
├── 核心库
│   ├── damiao.py                                # 达妙电机控制库（核心）
│   └── src/                                     # 达妙电机底层驱动
│       ├── __init__.py
│       └── usb_class.*.so                       # USB-CAN通信库（编译后的二进制文件）
│
├── 压力传感器程序
│   └── test_pressure.py                         # 压力传感器测试程序（含可视化）
│
├── 单功能程序
│   └── motor_control_pyqt.py                    # 电机手动控制UI
│
├── 整合程序（推荐使用）
│   └── gripper_ui_integrated.py                 # 整合UI（推荐）★
│
└── docs/                                        # 文档图片资源
    ├── catkin.png
    ├── dev.png
    └── motor_control.png
```

---

## 主要程序说明

### 核心库

#### `damiao.py`
- **作用**：达妙电机控制核心库
- **功能**：
  - 电机初始化和配置
  - MIT模式、位置速度模式、速度模式控制
  - 电机使能/失能
  - 参数读写
  - CAN通信管理

#### `dev_sn.py`
- **作用**：读取USB-CAN适配器设备序列号
- **功能**：枚举USB设备并显示设备SN码
- **使用**：`python3 dev_sn.py`

#### `src/usb_class.*.so`
- **作用**：USB-CAN适配器通信库（编译后的二进制文件）
- **功能**：USB设备枚举、CAN帧收发、波特率配置
- **说明**：针对不同平台和Python版本的预编译库

### 压力传感器程序

#### `test_pressure.py`
- **作用**：压力传感器数据采集、解析和可视化
- **功能**：
  - 串口通信
  - 数据帧解析
  - 压力校准
  - AD值转换为压强/压力
  - 6x6传感器阵列热力图显示
  - 实时数据可视化
  - 统计信息显示

### 单功能程序

#### `motor_control_pyqt.py`
- **作用**：电机手动控制GUI程序
- **功能**：
  - 打开/闭合按钮控制
  - 力矩值设置
  - 使能/失能管理
- **使用场景**：手动操作夹爪

### 整合程序（推荐）

#### `gripper_ui_integrated.py` ★★★
- **作用**：完整的夹爪控制系统（推荐使用）
- **功能**：
  - **标签页1：手动控制**
    - 打开/闭合按钮
    - 力矩值调节
  - **标签页2：PID控制 + 可视化**
    - 左侧：PID参数设置、状态显示、控制按钮
    - 右侧：6x6传感器热力图实时显示
  - 使能/失能管理
  - 资源自动清理
- **优势**：
  - 界面友好
  - 功能完整
  - 性能优化，无卡顿
  - 适合实际使用

---

## 配置说明

### 电机配置

在程序中找到电机初始化部分：

```python
init_data1 = []
canid1 = 0x01  # 电机CAN ID
mstid1 = 0x11  # 主站ID

init_data1.append(DmActData(
    motorType=DM_Motor_Type.DM4310,  # 电机型号
    mode=Control_Mode.MIT_MODE,       # 控制模式
    can_id=canid1,
    mst_id=mstid1))
```

**可配置项：**
- `canid1`：电机的CAN ID（默认 0x01）
- `mstid1`：主站ID（默认 0x11）
- `motorType`：电机型号（DM4310, DM4340, DM6006等）
- `mode`：控制模式（MIT_MODE, POS_VEL_MODE, VEL_MODE）

### 传感器配置

#### 基本配置

```python
SERIAL_PORT = '/dev/ttyUSB1'  # 串口设备
BAUDRATE = 460800              # 波特率（固定，不可修改）
```

#### 传感器参数

```python
# 传感器阵列规格
SENSOR_COUNT = 36              # 传感器点数（6x6）
GRID_SIZE = 6                  # 网格尺寸
SENSOR_AREA_MM2 = 2.5 * 2.5   # 单点面积 (mm²)
SENSOR_AREA_M2 = 6.25e-6      # 单点面积 (m²)

# 数据帧格式
HEADER = b'\xFF\x66'           # 帧头
FRAME_SIZE = 78                # 帧大小（字节）
# 帧结构：帧头(2) + 保留(2) + AD值(72) + 校验和(2)
```

#### 校准参数

每个传感器点都有独立的校准参数（斜率k和截距b），用于将AD值转换为压强：

```python
# 压强计算公式
pressure_kPa = k * ad_value + b

# 压力计算公式
pressure_N = pressure_kPa * 1000 * sensor_area_m2
```

校准参数已内置在程序中（`PressureSensorCalibration` 类），无需手动配置。

#### 偏移校准

PID控制模式下，程序会自动进行偏移校准（零点校准）：
- 采集10帧无负载数据
- 计算每个传感器的平均偏移值
- 后续测量值减去偏移值

**注意**：开始PID控制前，确保传感器表面无外力。

### PID参数

在UI中可以实时调整，或在代码中修改默认值：

```python
self.target_force = 0.15  # 目标夹持力 (N)
kp = 2.0                  # 比例系数
ki = 0.1                  # 积分系数
kd = 0.0                  # 微分系数
```

---

## 常见问题

### 1. 找不到USB-CAN设备

**错误信息：**
```
No DM-FDCAN device found
```

**解决方法：**
- 检查USB-CAN适配器是否连接
- 检查USB线缆
- 运行 `lsusb` 查看设备是否被识别
- 检查设备权限：`sudo chmod 666 /dev/bus/usb/*/*`

### 2. 设备序列号不匹配

**错误信息：**
```
Device SN mismatch
```

**解决方法：**
- 使用 `python3 dev_sn.py` 读取正确的SN码
- 修改程序中的SN码为实际设备的SN码

### 3. 串口连接失败

**错误信息：**
```
could not open port /dev/ttyUSB0: [Errno 2] 没有那个文件或目录
```

**解决方法：**
- 运行 `ls -l /dev/ttyUSB* /dev/ttyACM*` 查看可用串口
- 修改程序中的 `SERIAL_PORT` 为实际串口
- 检查串口权限：`sudo chmod 666 /dev/ttyUSB1`
- 将用户添加到 dialout 组：`sudo usermod -a -G dialout $USER`（需要重新登录）

### 4. 电机不响应

**可能原因：**
- 电机未使能：点击"使能电机"按钮
- CAN ID配置错误：检查电机实际ID
- 电机供电问题：检查电源
- CAN总线连接问题：检查线缆和终端电阻

### 5. 传感器数据异常

**可能原因：**
- 波特率不匹配：确认为 460800
- 串口设备错误：检查实际串口
- 传感器供电问题
- 数据线接触不良

### 6. 程序无法退出

**解决方法：**
- 在可视化窗口按 'q' 键
- 关闭可视化窗口
- 终端按 Ctrl+C
- 如果卡住，使用 `kill -9 <pid>`

### 7. 依赖库安装失败

**PyQt5 安装失败：**
```bash
# Ubuntu/Debian
sudo apt-get install python3-pyqt5

# 或使用国内镜像
pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple PyQt5
```

**pyusb 权限问题：**
```bash
# 创建udev规则
sudo nano /etc/udev/rules.d/99-usb.rules

# 添加以下内容：
SUBSYSTEM=="usb", MODE="0666"

# 重新加载规则
sudo udevadm control --reload-rules
```

---

## 开发说明

### 依赖库说明

| 库名 | 版本要求 | 用途 |
|------|---------|------|
| PyQt5 | >=5.15.0 | GUI界面框架 |
| numpy | >=1.19.0 | 数值计算 |
| matplotlib | >=3.3.0 | 数据可视化 |
| pyserial | >=3.5 | 串口通信 |
| pyusb | >=1.2.0 | USB设备通信 |

### 添加新电机

在 `damiao.py` 中添加电机配置：

```python
init_data.append(DmActData(
    motorType=DM_Motor_Type.DM4310,
    mode=Control_Mode.MIT_MODE,
    can_id=0x02,  # 新电机ID
    mst_id=0x12))
```

### 修改控制周期

```python
cycle_time = 0.01  # 10ms控制周期（100Hz）
```

### 调试模式

在程序中添加调试输出：

```python
print(f"当前力: {current_force:.3f}N")
print(f"电机输出: {motor_output:.3f}N·m")
```

---

## 安全注意事项

### 1. 首次使用
- 先在无负载情况下测试
- 从小力矩开始测试（建议从0.05 N·m开始）
- 确保急停措施可用
- 熟悉"失能电机"按钮位置

### 2. 运行时
- 确保夹爪周围无障碍物
- 不要超过电机额定力矩（DM4310: 4.3 N·m）
- 注意观察电机温度
- 异常情况立即点击"失能电机"

### 3. 退出程序
- 优先使用"失能电机"按钮
- 确保电机已停止再断电
- 不要强制杀死进程（避免电机处于使能状态）

### 4. 维护保养
- 定期检查线缆连接
- 清洁传感器表面
- 检查CAN总线终端电阻
- 记录异常情况和参数

---

## 技术支持

- **达妙电机文档**：查看 `dm_README.md`
- **问题反馈**：提交 Issue
- **项目维护**：wech1ng

---

## 更新日志

### 2026-01-30
- 添加 requirements.txt 依赖管理
- 重新组织 README 结构
- 将环境安装说明移至最前
- 添加硬件清单章节
- 详细说明传感器规格（深圳力感科技 6x6阵列压力传感器）
- 更新传感器配置说明（校准参数、偏移校准）
- 更新文件结构说明
- 添加更详细的故障排除指南

### 2026-01-29
- 创建整合UI程序
- 修复可视化卡顿问题
- 优化界面布局
- 添加详细文档

### 2026-01-28
- 初始版本
- 实现基本控制功能

---

## 许可证

本项目仅供学习和研究使用。

---

## 致谢

感谢达妙科技提供的电机控制库和技术支持。
