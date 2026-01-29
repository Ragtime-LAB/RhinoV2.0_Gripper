#!/usr/bin/env python3
"""
夹持力控制程序 - 带可视化
完全参考 simple_grip_control.py 的退出机制
"""

import time
import serial
import signal
import sys
import struct
import numpy as np
import threading
from threading import Event
from typing import List, Dict, Tuple
from dataclasses import dataclass
from enum import IntEnum

# ==================== 串口和传感器配置 ====================
SERIAL_PORT = '/dev/ttyUSB0'
BAUDRATE = 460800
HEADER = b'\xFF\x66'
FRAME_SIZE = 78

# ==================== 全局运行开关 ====================
running_ev = Event()
running_ev.set()

def sigint_handler(signum, frame):
    """信号处理器 - 完全参考 simple_grip_control.py"""
    global running_ev
    if running_ev is not None:
        running_ev.clear()
    sys.stderr.write(f"\nInterrupt signal({signum}) received.\n")
    sys.stderr.flush()

# 注册信号处理器
signal.signal(signal.SIGINT, sigint_handler)

# ==================== 达妙电机相关定义 ====================
class DM_Motor_Type(IntEnum):
    DM3507 = 0
    DM4310 = 1
    DM4310_48V = 2
    DM4340 = 3
    DM4340_48V = 4
    DM6006 = 5
    DM6248 = 6
    DM8006 = 7
    DM8009 = 8
    DM10010L = 9
    DM10010 = 10
    DMH3510 = 11
    DMH6215 = 12
    DMS3519 = 13
    DMG6220 = 14
    Num_Of_Motor = 15

class Control_Mode(IntEnum):
    MIT_MODE = 0x000
    POS_VEL_MODE = 0x100
    VEL_MODE = 0x200
    POS_FORCE_MODE = 0x300

class Control_Mode_Code(IntEnum):
    MIT = 1
    POS_VEL = 2
    VEL = 3
    POS_FORCE = 4

@dataclass
class DmActData:
    motorType: DM_Motor_Type
    mode: Control_Mode
    can_id: int
    mst_id: int

# ==================== 压力传感器校准类 ====================
class PressureSensorCalibration:
    def __init__(self):
        self.sensor_area_mm2 = 2.5 * 2.5
        self.sensor_area_m2 = self.sensor_area_mm2 * 1e-6
        self.sensor_count = 36
        self.grid_size = 6

        calibration_params = [
            (1, 0.562714, -14.79), (2, 0.395393, 10.1), (3, 0.418163, -23.95),
            (4, 0.446264, -2.56), (5, 0.320379, -5.81), (6, 0.339545, -0.79),
            (7, 0.880961, -79.67), (8, 0.511704, -2.75), (9, 0.532828, -48.19),
            (10, 0.579626, -38.1), (11, 0.459192, -66.58), (12, 0.457822, -28.08),
            (13, 0.554179, -49.81), (14, 0.408191, -1.81), (15, 0.517851, -48.86),
            (16, 0.613271, -21.8), (17, 0.451063, -67.59), (18, 0.390688, -62.41),
            (19, 0.647005, -82.75), (20, 0.414492, -20.47), (21, 0.49972, -78.84),
            (22, 0.510365, -32.84), (23, 0.454021, -60.85), (24, 0.565351, -38.52),
            (25, 0.773406, -53.7), (26, 0.418644, -3.49), (27, 0.437578, -42.11),
            (28, 0.528323, -15.28), (29, 0.356723, -34.61), (30, 0.502185, -32.73),
            (31, 0.710866, -77.16), (32, 0.616831, -22.65), (33, 0.672263, -60.23),
            (34, 0.673123, 3.31), (35, 0.45524, -11.36), (36, 0.471449, 5.94)
        ]

        self.calibration_data = {}
        for sensor_id, k, b in calibration_params:
            self.calibration_data[sensor_id] = {'k': k, 'b': b}

        self.offset_values = {}
        self.offset_calibrated = False

    def set_offset_values(self, offset_data):
        self.offset_values = offset_data.copy()
        self.offset_calibrated = True
        print(f"已设置静态偏移值，共{len(self.offset_values)}个传感器")

    def ad_to_pressure(self, sensor_id: int, ad_value: float) -> Tuple[float, float]:
        if sensor_id not in self.calibration_data:
            return 0.0, 0.0

        k = self.calibration_data[sensor_id]['k']
        compensated_ad_value = ad_value
        if self.offset_calibrated and sensor_id in self.offset_values:
            compensated_ad_value = ad_value - self.offset_values[sensor_id]

        pressure_kPa = k * compensated_ad_value
        pressure_N = pressure_kPa * 1000 * self.sensor_area_m2

        return max(0.0, pressure_kPa), max(0.0, pressure_N)

    def get_grid_position(self, sensor_id: int) -> Tuple[int, int]:
        if sensor_id < 1 or sensor_id > self.sensor_count:
            raise ValueError(f"传感器ID必须在1-{self.sensor_count}之间")

        x = (sensor_id - 1) % self.grid_size
        y = self.grid_size - 1 - ((sensor_id - 1) // self.grid_size)
        return (x, y)

# ==================== 压力数据解析器 ====================
class PressureParser:
    def __init__(self):
        self.buffer = bytearray()
        self.calibration = PressureSensorCalibration()
        self.sync_errors = 0
        self.total_frames = 0

    def find_frame_start(self):
        while len(self.buffer) >= 2:
            header_pos = self.buffer.find(HEADER)
            if header_pos == -1:
                self.buffer = bytearray()
                return None
            elif header_pos > 0:
                self.buffer = self.buffer[header_pos:]
                self.sync_errors += 1

            if len(self.buffer) >= FRAME_SIZE:
                return 0
            else:
                return None
        return None

    def parse_frame(self, data):
        if len(data) != FRAME_SIZE:
            return None

        if data[0:2] != HEADER:
            return None

        checksum = sum(data[2:-2]) & 0xFFFF
        received_checksum = struct.unpack('>H', data[-2:])[0]

        self.total_frames += 1
        if checksum != received_checksum:
            self.sync_errors += 1
            return None

        pressure_data = []
        for i in range(4, 76, 2):
            ad = struct.unpack('>H', data[i:i+2])[0]
            sensor_id = (i - 4) // 2 + 1
            pressure_kPa, pressure_N = self.calibration.ad_to_pressure(sensor_id, ad)
            pressure_data.append({
                'sensor_id': sensor_id,
                'ad_value': ad,
                'pressure_kPa': pressure_kPa,
                'pressure_N': pressure_N
            })

        return pressure_data

    def get_sync_stats(self):
        if self.total_frames > 0:
            error_rate = self.sync_errors / self.total_frames * 100
            return f"同步错误率: {error_rate:.1f}% ({self.sync_errors}/{self.total_frames})"
        return "无统计数据"

# ==================== 压力可视化类（使用线程） ====================
class PressureVisualizer:
    def __init__(self, calibration: PressureSensorCalibration):
        self.calibration = calibration
        self.enabled = False
        self.pressure_data_lock = threading.Lock()
        self.latest_pressure_data = None
        self.viz_thread = None
        self.running = False

    def start(self):
        """启动可视化线程"""
        if self.enabled:
            return

        self.running = True
        self.viz_thread = threading.Thread(target=self._visualization_loop, daemon=True)
        self.viz_thread.start()
        self.enabled = True
        print("可视化线程已启动")

    def _visualization_loop(self):
        """可视化线程主循环"""
        try:
            import matplotlib
            matplotlib.use('TkAgg')
            import matplotlib.pyplot as plt

            plt.ion()
            fig, ax = plt.subplots(figsize=(10, 8))

            pressure_matrix = np.zeros((6, 6))
            im = ax.imshow(pressure_matrix, cmap='hot', interpolation='nearest', vmin=0, vmax=100)

            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label('压强 (kPa)', rotation=270, labelpad=15, fontsize=12)

            ax.set_xticks(np.arange(6))
            ax.set_yticks(np.arange(6))
            ax.set_xticklabels(np.arange(6))
            ax.set_yticklabels(np.arange(6))
            ax.set_xlabel('X 坐标', fontsize=12)
            ax.set_ylabel('Y 坐标', fontsize=12)
            ax.set_title('6x6 压力传感器分布图 (按 q 键或关闭窗口退出)', fontsize=14, pad=10)

            text_matrix = [[None for _ in range(6)] for _ in range(6)]
            for i in range(6):
                for j in range(6):
                    text_matrix[i][j] = ax.text(j, i, '', ha="center", va="center",
                                                color="white", fontsize=8)

            # 添加键盘事件处理
            def on_key(event):
                if event.key == 'q':
                    print("\n检测到 'q' 键，正在退出程序...", file=sys.stderr)
                    sys.stderr.flush()
                    running_ev.clear()
                    self.running = False
                    plt.close(fig)

            # 添加窗口关闭事件处理
            def on_close(event):
                print("\n检测到窗口关闭，正在退出程序...", file=sys.stderr)
                sys.stderr.flush()
                running_ev.clear()
                self.running = False

            fig.canvas.mpl_connect('key_press_event', on_key)
            fig.canvas.mpl_connect('close_event', on_close)

            plt.tight_layout()
            plt.show(block=False)

            while self.running and running_ev.is_set():
                with self.pressure_data_lock:
                    pressure_data = self.latest_pressure_data

                if pressure_data:
                    for data in pressure_data:
                        sensor_id = data['sensor_id']
                        x, y = self.calibration.get_grid_position(sensor_id)
                        pressure_kPa = data['pressure_kPa']
                        pressure_N = data['pressure_N']

                        pressure_matrix[y, x] = max(0, pressure_kPa)

                        if pressure_kPa > 0:
                            text = f"{pressure_kPa:.1f} kPa\n{pressure_N:.3f} N"
                            color = "white" if pressure_kPa > 50 else "black"
                        else:
                            text = "0.0 kPa\n0.000 N"
                            color = "black"

                        text_matrix[y][x].set_text(text)
                        text_matrix[y][x].set_color(color)

                    im.set_data(pressure_matrix)
                    if np.max(pressure_matrix) > 0:
                        im.set_clim(0, max(100, np.max(pressure_matrix) * 1.1))

                    fig.canvas.draw()
                    fig.canvas.flush_events()

                time.sleep(0.05)

            plt.close(fig)

        except Exception as e:
            print(f"可视化线程错误: {e}")

    def update_visualization(self, pressure_data: List[Dict]):
        """更新压力数据（线程安全）"""
        if not self.enabled:
            return

        with self.pressure_data_lock:
            self.latest_pressure_data = pressure_data

    def close(self):
        """关闭可视化"""
        if self.enabled:
            self.running = False
            if self.viz_thread:
                self.viz_thread.join(timeout=1.0)
            self.enabled = False

# ==================== PID控制器 ====================
class SimplePID:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.prev_error = 0.0
        self.integral = 0.0
        self.prev_time = time.time()

    def compute(self, target, current):
        now = time.time()
        dt = now - self.prev_time
        error = target - current

        self.integral += error * dt
        derivative = (error - self.prev_error) / dt if dt > 0 else 0

        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        output = max(-0.5, min(output, 0.5))

        self.prev_error = error
        self.prev_time = now
        return output

# ==================== 辅助函数 ====================
def calibrate_offset(ser, parser, num_frames=10, running_event=None, timeout_seconds=30):
    """采集静态偏移值校准数据 - 参考 test_pressure.py"""
    print(f"正在采集{num_frames}帧静态偏移数据，请确保传感器无外力...")

    offset_accumulator = {}
    valid_frames = 0
    start_time = time.time()
    last_progress_time = start_time

    while valid_frames < num_frames and (running_event is None or running_event.is_set()):
        current_time = time.time()
        if current_time - start_time > timeout_seconds:
            print(f"校准超时({timeout_seconds}秒)，已采集{valid_frames}帧")
            break

        if current_time - last_progress_time > 5.0:
            print(f"警告: 5秒内没有收到有效数据帧，当前进度: {valid_frames}/{num_frames}")
            last_progress_time = current_time

        data = ser.read(FRAME_SIZE * 2)
        if data:
            parser.buffer += data

            while valid_frames < num_frames and (running_event is None or running_event.is_set()):
                frame_start = parser.find_frame_start()
                if frame_start is None:
                    break

                if len(parser.buffer) < FRAME_SIZE:
                    break

                frame = parser.buffer[:FRAME_SIZE]
                parser.buffer = parser.buffer[FRAME_SIZE:]

                if len(frame) != FRAME_SIZE or frame[0:2] != HEADER:
                    continue

                checksum = sum(frame[2:-2]) & 0xFFFF
                received_checksum = struct.unpack('>H', frame[-2:])[0]
                if checksum != received_checksum:
                    parser.sync_errors += 1
                    continue

                for i in range(4, 76, 2):
                    ad = struct.unpack('>H', frame[i:i+2])[0]
                    sensor_id = (i - 4) // 2 + 1

                    if sensor_id not in offset_accumulator:
                        offset_accumulator[sensor_id] = []
                    offset_accumulator[sensor_id].append(ad)

                valid_frames += 1
                last_progress_time = current_time
                print(f"采集进度: {valid_frames}/{num_frames}")
        else:
            time.sleep(0.01)

        time.sleep(0.02)

    if running_event is not None and not running_event.is_set():
        print("校准被中断")
        return {}

    if valid_frames < num_frames:
        print(f"警告: 只采集到{valid_frames}帧数据")
        if valid_frames == 0:
            print("没有采集到任何有效数据，请检查设备连接")
            return {}

    offset_values = {}
    for sensor_id, ad_values in offset_accumulator.items():
        offset_values[sensor_id] = sum(ad_values) / len(ad_values)

    print("静态偏移值校准完成!")
    print(f"传感器偏移值示例: 传感器1={offset_values.get(1, 0):.1f}, 传感器2={offset_values.get(2, 0):.1f}")

    return offset_values

def get_total_pressure(pressure_data):
    """获取总压力值"""
    return sum(data['pressure_N'] for data in pressure_data)

# ==================== 主控制函数 ====================
def main():
    """主控制循环 - 完全参考 simple_grip_control.py"""
    global running_ev
    target_force = 0.15

    # 连接串口
    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.1)
    except Exception as e:
        print(f"串口连接失败: {e}")
        return

    # 初始化解析器和PID控制器
    parser = PressureParser()
    pid = SimplePID(kp=2.0, ki=0.1, kd=0.0)

    # 初始化可视化
    visualizer = PressureVisualizer(parser.calibration)
    try:
        visualizer.start()
    except Exception as e:
        print(f"可视化启动失败: {e}")
        visualizer = None

    # 清空串口缓冲区
    ser.flushInput()
    parser.buffer = bytearray()

    # 静态偏移校准
    print("开始静态偏移校准...")
    offset_values = calibrate_offset(ser, parser, num_frames=10, running_event=running_ev)
    if not running_ev.is_set():
        print("校准被中断")
        ser.close()
        if visualizer:
            visualizer.close()
        return

    parser.calibration.set_offset_values(offset_values)

    print("开始PID控制...")
    print("=" * 60)
    print("退出方式:")
    print("  1. 在可视化窗口中按 'q' 键")
    print("  2. 关闭可视化窗口")
    print("  3. 在终端按 Ctrl+C")
    print("=" * 60)
    sys.stdout.flush()

    try:
        next_time = time.monotonic()
        cycle_time = 0.01  # 10ms控制周期

        frame_count = 0
        while running_ev.is_set():  # 每次循环都检查停止标志
            data = ser.read(FRAME_SIZE * 2)
            if data:
                parser.buffer += data

                # 使用帧同步机制 - 完全参考 simple_grip_control.py
                while running_ev.is_set():
                    frame_start = parser.find_frame_start()
                    if frame_start is None:
                        break  # 没有找到有效帧，需要更多数据

                    if len(parser.buffer) < FRAME_SIZE:
                        break  # 数据不足

                    frame = parser.buffer[:FRAME_SIZE]
                    parser.buffer = parser.buffer[FRAME_SIZE:]

                    pressure_data = parser.parse_frame(frame)
                    if pressure_data:
                        current_force = get_total_pressure(pressure_data)
                        motor_output = pid.compute(target_force, current_force)
                        frame_count += 1

                        # 更新可视化
                        if visualizer:
                            visualizer.update_visualization(pressure_data)

                        # 每100帧显示一次同步统计
                        if frame_count % 100 == 0:
                            print(f"当前力: {current_force:.3f}N, 目标: {target_force:.3f}N, 电机输出: {motor_output:.3f}N·m | {parser.get_sync_stats()}")
                        else:
                            print(f"当前力: {current_force:.3f}N, 目标: {target_force:.3f}N, 电机输出: {motor_output:.3f}N·m")

                        control.control_mit(control.getMotor(canid1), 0.0, 0.0, 0.0, 0.0, motor_output)

            # 精确定时但可中断 - 完全参考 simple_grip_control.py
            next_time += cycle_time
            sleep_time = next_time - time.monotonic()
            if sleep_time > 0:
                if sleep_time > 0.0005:
                    time.sleep(sleep_time - 0.0005)
                # 忙等待，但外层循环会检查running_ev
                while time.monotonic() < next_time and running_ev.is_set():
                    pass

    except KeyboardInterrupt:
        print("程序被中断")
    finally:
        # 停止电机
        print("正在停止电机...")
        try:
            control.control_mit(control.getMotor(canid1), 0.0, 0.0, 0.0, 0.0, 0.0)
        except:
            pass
        ser.close()
        if visualizer:
            visualizer.close()
        print("资源清理完成")


# ==================== 程序入口 ====================
if __name__ == "__main__":
    try:
        from damiao import Motor_Control

        control = None

        try:
            init_data1 = []
            canid1 = 0x01
            mstid1 = 0x11
            init_data1.append(DmActData(
                motorType=DM_Motor_Type.DM4310,
                mode=Control_Mode.MIT_MODE,
                can_id=canid1,
                mst_id=mstid1))

            with Motor_Control(1000000, 5000000, "818F9E6ACF42F4147B2EE0FE9382AF11", init_data1) as control:
                control.switchControlMode(control.getMotor(canid1), Control_Mode_Code.MIT)
                control.enable_all()

                # 运行主程序
                main()

        except KeyboardInterrupt:
            print("收到键盘中断信号", file=sys.stderr)
        except Exception as e:
            print(f"Error: hardware interface exception: {e}", file=sys.stderr)
        finally:
            # 确保所有资源被正确清理
            running_ev.clear()  # 确保所有循环停止

            # 停止电机
            if control is not None:
                try:
                    print("最终停止电机...", file=sys.stderr)
                    control.control_mit(control.getMotor(canid1), 0.0, 0.0, 0.0, 0.0, 0.0)
                    time.sleep(0.1)  # 给电机一点时间响应
                except:
                    pass

            print("The program exited safely.", file=sys.stderr)

    except ImportError as e:
        print(f"无法导入达妙电机控制库: {e}")
        print("请确保 damiao.py 和相关依赖已正确安装")
        sys.exit(1)
