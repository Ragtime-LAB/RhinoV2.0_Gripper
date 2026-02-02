#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夹爪控制UI - 整合版 V2
修复可视化卡顿问题，PID控制和可视化在同一界面
"""

import sys
import time
import signal
import struct
import serial
import numpy as np
import threading
from threading import Event, Thread, Lock
from typing import List, Dict, Tuple

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox,
                             QGroupBox, QMessageBox, QTabWidget, QGridLayout,
                             QSplitter)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QFont

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib
matplotlib.use('Qt5Agg')

# 配置matplotlib - 使用英文避免字体问题
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

from damiao import *

# ==================== 串口和传感器配置 ====================
SERIAL_PORT = '/dev/ttyUSB0'
BAUDRATE = 460800
HEADER = b'\xFF\x66'
FRAME_SIZE = 78

# ==================== 全局运行开关 ====================
running_ev = Event()
running_ev.set()

app_instance = None

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

    def reset(self):
        self.prev_error = 0.0
        self.integral = 0.0
        self.prev_time = time.time()

# ==================== 线程类 ====================
class MotorControlThread(QThread):
    """手动控制线程"""
    def __init__(self, control, canid, torque):
        super().__init__()
        self.control = control
        self.canid = canid
        self.torque = torque
        self.running = True
    
    def set_torque(self, torque):
        self.torque = torque
    
    def run(self):
        try:
            while self.running:
                if self.control:
                    self.control.control_mit(self.control.getMotor(self.canid),
                                           0.0, 0.0, 0.0, 0.0, self.torque)
                time.sleep(0.01)
        except:
            pass
        finally:
            if self.control:
                try:
                    self.control.control_mit(self.control.getMotor(self.canid),
                                           0.0, 0.0, 0.0, 0.0, 0.0)
                except:
                    pass
    
    def stop(self):
        self.running = False


class SensorReadThread(QThread):
    """传感器读取线程 - 不直接更新UI"""
    data_update = pyqtSignal(list)
    
    def __init__(self, serial_port, parser):
        super().__init__()
        self.serial_port = serial_port
        self.parser = parser
        self.running = True
        self.latest_data = None
        self.data_lock = Lock()
    
    def run(self):
        try:
            while self.running:
                data = self.serial_port.read(FRAME_SIZE * 2)
                if data:
                    self.parser.buffer += data
                    
                    while len(self.parser.buffer) >= FRAME_SIZE and self.running:
                        frame_start = self.parser.find_frame_start()
                        if frame_start is None:
                            break
                        
                        if len(self.parser.buffer) < FRAME_SIZE:
                            break
                        
                        frame = self.parser.buffer[:FRAME_SIZE]
                        self.parser.buffer = self.parser.buffer[FRAME_SIZE:]
                        
                        pressure_data = self.parser.parse_frame(frame)
                        if pressure_data:
                            with self.data_lock:
                                self.latest_data = pressure_data
                            self.data_update.emit(pressure_data)
                
                time.sleep(0.02)
        except:
            pass
    
    def get_latest_data(self):
        with self.data_lock:
            return self.latest_data
    
    def stop(self):
        self.running = False


class PIDControlThread(QThread):
    """PID控制线程"""
    force_update = pyqtSignal(float, float)
    
    def __init__(self, control, canid, sensor_thread, target_force, kp, ki, kd):
        super().__init__()
        self.control = control
        self.canid = canid
        self.sensor_thread = sensor_thread
        self.target_force = target_force
        self.pid = SimplePID(kp, ki, kd)
        self.running = True
    
    def run(self):
        try:
            # 校准偏移
            offset_values = self.calibrate_offset()
            if not offset_values:
                return
            
            self.sensor_thread.parser.calibration.set_offset_values(offset_values)
            
            # PID控制循环
            while self.running:
                pressure_data = self.sensor_thread.get_latest_data()
                
                if pressure_data:
                    current_force = sum(d['pressure_N'] for d in pressure_data)
                    motor_output = self.pid.compute(self.target_force, current_force)
                    
                    self.force_update.emit(current_force, motor_output)
                    
                    if self.control:
                        self.control.control_mit(self.control.getMotor(self.canid),
                                               0.0, 0.0, 0.0, 0.0, motor_output)
                
                time.sleep(0.01)
        except:
            pass
        finally:
            if self.control:
                try:
                    self.control.control_mit(self.control.getMotor(self.canid),
                                           0.0, 0.0, 0.0, 0.0, 0.0)
                except:
                    pass
    
    def calibrate_offset(self):
        """校准偏移"""
        offset_accumulator = {}
        valid_frames = 0
        num_frames = 10
        start_time = time.time()
        
        while valid_frames < num_frames and self.running and (time.time() - start_time) < 5:
            pressure_data = self.sensor_thread.get_latest_data()
            if pressure_data:
                for data in pressure_data:
                    sensor_id = data['sensor_id']
                    ad_value = data['ad_value']
                    
                    if sensor_id not in offset_accumulator:
                        offset_accumulator[sensor_id] = []
                    offset_accumulator[sensor_id].append(ad_value)
                
                valid_frames += 1
            
            time.sleep(0.1)
        
        if valid_frames == 0:
            return {}
        
        offset_values = {}
        for sensor_id, ad_values in offset_accumulator.items():
            offset_values[sensor_id] = sum(ad_values) / len(ad_values)
        
        return offset_values
    
    def stop(self):
        self.running = False

# ==================== 主窗口类 ====================
class GripperUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 电机控制相关
        self.control = None
        self.canid = 0x01
        self.mstid = 0x11
        self.motor_enabled = False
        
        # 串口和传感器
        self.serial_port = None
        self.parser = PressureParser()
        
        # 控制线程
        self.manual_thread = None
        self.pid_thread = None
        self.sensor_thread = None
        
        # 默认值
        self.open_torque = -0.25
        self.close_torque = 0.15
        self.target_force = 0.15
        
        # 可视化数据
        self.pressure_matrix = np.zeros((6, 6))
        self.latest_pressure_data = None
        
        # 初始化UI
        self.init_ui()
        
        # 可视化更新定时器
        self.viz_timer = QTimer()
        self.viz_timer.timeout.connect(self.update_visualization)
        self.viz_timer.start(100)  # 100ms更新一次，避免卡顿
        
        # 延迟初始化
        QTimer.singleShot(100, self.init_hardware)
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("RhinoV2.0夹爪控制系统")
        self.setGeometry(100, 100, 1400, 900)
        
        # 设置样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                font-size: 13px;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px;
                min-height: 35px;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        
        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 标题
        title = QLabel("RhinoV2.0+阵列压力")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # 状态栏
        status_group = QGroupBox("系统状态")
        status_layout = QHBoxLayout()
        self.motor_status_label = QLabel("电机: 初始化中...")
        self.sensor_status_label = QLabel("传感器: 未连接")
        self.mode_status_label = QLabel("模式: 无")
        status_layout.addWidget(self.motor_status_label)
        status_layout.addWidget(self.sensor_status_label)
        status_layout.addWidget(self.mode_status_label)
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        # 使能/失能按钮
        enable_layout = QHBoxLayout()
        self.enable_btn = QPushButton("使能电机")
        self.enable_btn.setStyleSheet("background-color: #FF9800; color: white;")
        self.enable_btn.clicked.connect(self.enable_motor)
        self.enable_btn.setEnabled(False)
        
        self.disable_btn = QPushButton("失能电机")
        self.disable_btn.setStyleSheet("background-color: #9E9E9E; color: white;")
        self.disable_btn.clicked.connect(self.disable_motor)
        self.disable_btn.setEnabled(False)
        
        enable_layout.addWidget(self.enable_btn)
        enable_layout.addWidget(self.disable_btn)
        main_layout.addLayout(enable_layout)
        
        # Tab控件
        self.tabs = QTabWidget()
        
        # 手动控制标签
        self.manual_tab = self.create_manual_tab()
        self.tabs.addTab(self.manual_tab, "手动控制")
        
        # PID控制标签（包含可视化）
        self.pid_tab = self.create_pid_with_viz_tab()
        self.tabs.addTab(self.pid_tab, "PID控制 + 可视化")
        
        main_layout.addWidget(self.tabs)

    def create_manual_tab(self):
        """创建手动控制标签"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 控制按钮区
        control_layout = QHBoxLayout()
        
        # 打开组
        open_group = QGroupBox("打开")
        open_layout = QVBoxLayout()
        self.open_torque_spin = QDoubleSpinBox()
        self.open_torque_spin.setRange(-10.0, 0.0)
        self.open_torque_spin.setValue(self.open_torque)
        self.open_torque_spin.setSingleStep(0.05)
        self.open_torque_spin.setDecimals(2)
        self.open_torque_spin.setSuffix(" N·m")
        open_layout.addWidget(QLabel("力矩值:"))
        open_layout.addWidget(self.open_torque_spin)
        
        self.open_btn = QPushButton("打开")
        self.open_btn.setStyleSheet("background-color: #4CAF50; color: white; min-height: 60px;")
        self.open_btn.clicked.connect(self.start_open)
        self.open_btn.setEnabled(False)
        open_layout.addWidget(self.open_btn)
        open_group.setLayout(open_layout)
        
        # 闭合组
        close_group = QGroupBox("闭合")
        close_layout = QVBoxLayout()
        self.close_torque_spin = QDoubleSpinBox()
        self.close_torque_spin.setRange(0.0, 10.0)
        self.close_torque_spin.setValue(self.close_torque)
        self.close_torque_spin.setSingleStep(0.05)
        self.close_torque_spin.setDecimals(2)
        self.close_torque_spin.setSuffix(" N·m")
        close_layout.addWidget(QLabel("力矩值:"))
        close_layout.addWidget(self.close_torque_spin)
        
        self.close_btn = QPushButton("闭合")
        self.close_btn.setStyleSheet("background-color: #2196F3; color: white; min-height: 60px;")
        self.close_btn.clicked.connect(self.start_close)
        self.close_btn.setEnabled(False)
        close_layout.addWidget(self.close_btn)
        close_group.setLayout(close_layout)
        
        control_layout.addWidget(open_group)
        control_layout.addWidget(close_group)
        layout.addLayout(control_layout)
        
        layout.addStretch()
        return widget
    
    def create_pid_with_viz_tab(self):
        """创建PID控制+可视化标签"""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # 左侧：PID控制面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(400)
        
        # PID参数组
        pid_group = QGroupBox("PID参数")
        pid_layout = QGridLayout()
        
        self.target_force_spin = QDoubleSpinBox()
        self.target_force_spin.setRange(0.0, 2.0)
        self.target_force_spin.setValue(self.target_force)
        self.target_force_spin.setSingleStep(0.01)
        self.target_force_spin.setDecimals(3)
        self.target_force_spin.setSuffix(" N")
        
        self.kp_spin = QDoubleSpinBox()
        self.kp_spin.setRange(0.0, 10.0)
        self.kp_spin.setValue(2.0)
        self.kp_spin.setSingleStep(0.1)
        self.kp_spin.setDecimals(2)
        
        self.ki_spin = QDoubleSpinBox()
        self.ki_spin.setRange(0.0, 5.0)
        self.ki_spin.setValue(0.1)
        self.ki_spin.setSingleStep(0.01)
        self.ki_spin.setDecimals(3)
        
        self.kd_spin = QDoubleSpinBox()
        self.kd_spin.setRange(0.0, 5.0)
        self.kd_spin.setValue(0.0)
        self.kd_spin.setSingleStep(0.01)
        self.kd_spin.setDecimals(3)
        
        pid_layout.addWidget(QLabel("目标力:"), 0, 0)
        pid_layout.addWidget(self.target_force_spin, 0, 1)
        pid_layout.addWidget(QLabel("Kp:"), 1, 0)
        pid_layout.addWidget(self.kp_spin, 1, 1)
        pid_layout.addWidget(QLabel("Ki:"), 2, 0)
        pid_layout.addWidget(self.ki_spin, 2, 1)
        pid_layout.addWidget(QLabel("Kd:"), 3, 0)
        pid_layout.addWidget(self.kd_spin, 3, 1)
        
        pid_group.setLayout(pid_layout)
        left_layout.addWidget(pid_group)
        
        # 当前力显示
        force_group = QGroupBox("当前状态")
        force_layout = QVBoxLayout()
        self.current_force_label = QLabel("当前力: 0.000 N")
        self.current_force_label.setFont(QFont("Arial", 14, QFont.Bold))
        self.current_force_label.setAlignment(Qt.AlignCenter)
        self.motor_output_label = QLabel("电机输出: 0.000 N·m")
        self.motor_output_label.setAlignment(Qt.AlignCenter)
        force_layout.addWidget(self.current_force_label)
        force_layout.addWidget(self.motor_output_label)
        force_group.setLayout(force_layout)
        left_layout.addWidget(force_group)
        
        # 统计信息
        stats_group = QGroupBox("传感器统计")
        stats_layout = QVBoxLayout()
        self.total_force_label = QLabel("总压力: 0.000 N")
        self.max_pressure_label = QLabel("最大压强: 0.0 kPa")
        stats_layout.addWidget(self.total_force_label)
        stats_layout.addWidget(self.max_pressure_label)
        stats_group.setLayout(stats_layout)
        left_layout.addWidget(stats_group)
        
        # PID控制按钮
        self.start_pid_btn = QPushButton("开始PID控制")
        self.start_pid_btn.setStyleSheet("background-color: #4CAF50; color: white; min-height: 45px;")
        self.start_pid_btn.clicked.connect(self.start_pid_control)
        self.start_pid_btn.setEnabled(False)
        left_layout.addWidget(self.start_pid_btn)
        
        self.stop_pid_btn = QPushButton("停止PID控制")
        self.stop_pid_btn.setStyleSheet("background-color: #f44336; color: white; min-height: 45px;")
        self.stop_pid_btn.clicked.connect(self.stop_pid_control)
        self.stop_pid_btn.setEnabled(False)
        left_layout.addWidget(self.stop_pid_btn)
        
        left_layout.addStretch()
        
        # 右侧：可视化
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # 嵌入matplotlib图表
        self.viz_figure = Figure(figsize=(7, 6))
        self.viz_canvas = FigureCanvas(self.viz_figure)
        self.viz_ax = self.viz_figure.add_subplot(111)

        # 初始化热力图
        self.viz_im = self.viz_ax.imshow(self.pressure_matrix, cmap='hot',
                                         interpolation='nearest', vmin=0, vmax=100)
        self.viz_cbar = self.viz_figure.colorbar(self.viz_im, ax=self.viz_ax)

        # 设置标签 - 使用英文避免乱码
        self.viz_cbar.set_label('Pressure (kPa)', rotation=270, labelpad=15)
        self.viz_ax.set_xlabel('X Coordinate')
        self.viz_ax.set_ylabel('Y Coordinate')
        self.viz_ax.set_title('6x6 Pressure Sensor Array')

        self.viz_ax.set_xticks(np.arange(6))
        self.viz_ax.set_yticks(np.arange(6))
        
        # 添加文本标签
        self.text_matrix = [[None for _ in range(6)] for _ in range(6)]
        for i in range(6):
            for j in range(6):
                self.text_matrix[i][j] = self.viz_ax.text(j, i, '', 
                                                         ha="center", va="center",
                                                         color="white", fontsize=7)
        
        self.viz_figure.tight_layout()
        right_layout.addWidget(self.viz_canvas)
        
        # 添加到主布局
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        
        return widget

    def init_hardware(self):
        """初始化硬件"""
        # 初始化电机
        try:
            init_data = [DmActData(
                motorType=DM_Motor_Type.DM4310,
                mode=Control_Mode.MIT_MODE,
                can_id=self.canid,
                mst_id=self.mstid)]
            
            self.control = Motor_Control(1000000, 5000000,
                                        "818F9E6ACF42F4147B2EE0FE9382AF11",
                                        init_data)
            self.control.switchControlMode(self.control.getMotor(self.canid),
                                          Control_Mode_Code.MIT)
            
            # 立即失能
            self.control.disable_all()
            time.sleep(0.1)
            
            self.motor_status_label.setText("电机: 已初始化 (未使能)")
            self.motor_status_label.setStyleSheet("color: #FF9800;")
            self.enable_btn.setEnabled(True)
            
        except Exception as e:
            self.motor_status_label.setText("电机: 初始化失败")
            self.motor_status_label.setStyleSheet("color: #f44336;")
            QMessageBox.critical(self, "错误", f"电机初始化失败:\n{e}")
        
        # 初始化串口
        try:
            self.serial_port = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.1)
            self.sensor_status_label.setText("传感器: 已连接")
            self.sensor_status_label.setStyleSheet("color: #4CAF50;")
            
            # 启动传感器读取线程
            self.start_sensor_thread()
            
        except Exception as e:
            self.sensor_status_label.setText("传感器: 连接失败")
            self.sensor_status_label.setStyleSheet("color: #f44336;")
            print(f"传感器连接失败: {e}")
    
    def enable_motor(self):
        """使能电机"""
        try:
            self.control.enable_all()
            self.motor_enabled = True
            self.motor_status_label.setText("电机: 已使能")
            self.motor_status_label.setStyleSheet("color: #4CAF50;")
            
            self.enable_btn.setEnabled(False)
            self.disable_btn.setEnabled(True)
            self.open_btn.setEnabled(True)
            self.close_btn.setEnabled(True)
            self.start_pid_btn.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"使能失败:\n{e}")
    
    def disable_motor(self):
        """失能电机"""
        # 先停止所有控制
        self.stop_manual_control()
        self.stop_pid_control()
        
        try:
            self.control.disable_all()
            self.motor_enabled = False
            self.motor_status_label.setText("电机: 已失能")
            self.motor_status_label.setStyleSheet("color: #9E9E9E;")
            
            self.enable_btn.setEnabled(True)
            self.disable_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            self.close_btn.setEnabled(False)
            self.start_pid_btn.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"失能失败:\n{e}")
    
    def start_open(self):
        """开始打开"""
        if not self.motor_enabled:
            QMessageBox.warning(self, "警告", "请先使能电机")
            return
        
        torque = self.open_torque_spin.value()
        self.mode_status_label.setText(f"模式: 手动-打开 ({torque:.2f} N·m)")
        
        if self.manual_thread and self.manual_thread.isRunning():
            self.manual_thread.set_torque(torque)
        else:
            self.manual_thread = MotorControlThread(self.control, self.canid, torque)
            self.manual_thread.start()
    
    def start_close(self):
        """开始闭合"""
        if not self.motor_enabled:
            QMessageBox.warning(self, "警告", "请先使能电机")
            return
        
        torque = self.close_torque_spin.value()
        self.mode_status_label.setText(f"模式: 手动-闭合 ({torque:.2f} N·m)")
        
        if self.manual_thread and self.manual_thread.isRunning():
            self.manual_thread.set_torque(torque)
        else:
            self.manual_thread = MotorControlThread(self.control, self.canid, torque)
            self.manual_thread.start()
    
    def stop_manual_control(self):
        """停止手动控制"""
        if self.manual_thread:
            self.manual_thread.stop()
            self.manual_thread.wait(1000)
        
        if self.control:
            try:
                self.control.control_mit(self.control.getMotor(self.canid),
                                       0.0, 0.0, 0.0, 0.0, 0.0)
            except:
                pass
    
    def start_pid_control(self):
        """开始PID控制"""
        if not self.motor_enabled:
            QMessageBox.warning(self, "警告", "请先使能电机")
            return
        
        if not self.sensor_thread or not self.sensor_thread.isRunning():
            QMessageBox.warning(self, "警告", "传感器未连接")
            return
        
        # 校准确认
        reply = QMessageBox.question(self, "校准确认",
                                    "开始PID控制前需要进行偏移校准(约1秒)\n请确保传感器无外力",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        
        target_force = self.target_force_spin.value()
        kp = self.kp_spin.value()
        ki = self.ki_spin.value()
        kd = self.kd_spin.value()
        
        self.pid_thread = PIDControlThread(
            self.control, self.canid, self.sensor_thread,
            target_force, kp, ki, kd)
        self.pid_thread.force_update.connect(self.update_force_display)
        self.pid_thread.start()
        
        self.start_pid_btn.setEnabled(False)
        self.stop_pid_btn.setEnabled(True)
        self.mode_status_label.setText(f"模式: PID控制 (目标 {target_force:.3f} N)")
    
    def stop_pid_control(self):
        """停止PID控制"""
        if self.pid_thread:
            self.pid_thread.stop()
            self.pid_thread.wait(2000)
        
        if self.control:
            try:
                self.control.control_mit(self.control.getMotor(self.canid),
                                       0.0, 0.0, 0.0, 0.0, 0.0)
            except:
                pass
        
        self.start_pid_btn.setEnabled(True)
        self.stop_pid_btn.setEnabled(False)
        self.mode_status_label.setText("模式: 已停止")
    
    def start_sensor_thread(self):
        """启动传感器读取线程"""
        self.sensor_thread = SensorReadThread(self.serial_port, self.parser)
        self.sensor_thread.data_update.connect(self.on_sensor_data_update)
        self.sensor_thread.start()
    
    def on_sensor_data_update(self, pressure_data):
        """传感器数据更新回调 - 只保存数据，不更新UI"""
        self.latest_pressure_data = pressure_data
    
    def update_force_display(self, current_force, motor_output):
        """更新力显示"""
        self.current_force_label.setText(f"当前力: {current_force:.3f} N")
        self.motor_output_label.setText(f"电机输出: {motor_output:.3f} N·m")
    
    def update_visualization(self):
        """定时更新可视化 - 避免阻塞"""
        if not self.latest_pressure_data:
            return
        
        pressure_data = self.latest_pressure_data
        
        # 更新压力矩阵
        for data in pressure_data:
            sensor_id = data['sensor_id']
            x, y = self.parser.calibration.get_grid_position(sensor_id)
            pressure_kPa = data['pressure_kPa']
            pressure_N = data['pressure_N']
            
            self.pressure_matrix[y, x] = max(0, pressure_kPa)
            
            # 更新文本
            if pressure_kPa > 0.5:  # 只显示有意义的值
                text = f"{pressure_kPa:.1f}\n{pressure_N:.3f}"
                color = "white" if pressure_kPa > 50 else "black"
            else:
                text = ""
                color = "black"
            
            self.text_matrix[y][x].set_text(text)
            self.text_matrix[y][x].set_color(color)
        
        # 更新热力图
        self.viz_im.set_data(self.pressure_matrix)
        if np.max(self.pressure_matrix) > 0:
            self.viz_im.set_clim(0, max(100, np.max(self.pressure_matrix) * 1.1))
        
        # 只在需要时刷新
        try:
            self.viz_canvas.draw_idle()  # 使用 draw_idle 而不是 draw，避免阻塞
        except:
            pass
        
        # 更新统计信息
        total_force = sum(d['pressure_N'] for d in pressure_data)
        max_pressure = max(d['pressure_kPa'] for d in pressure_data)
        self.total_force_label.setText(f"总压力: {total_force:.3f} N")
        self.max_pressure_label.setText(f"最大压强: {max_pressure:.1f} kPa")
    
    def cleanup(self):
        """清理资源"""
        print("清理资源...")
        
        # 停止定时器
        self.viz_timer.stop()
        
        # 停止所有线程
        self.stop_manual_control()
        self.stop_pid_control()
        
        if self.sensor_thread:
            self.sensor_thread.stop()
            self.sensor_thread.wait(1000)
        
        # 清理硬件
        if self.serial_port:
            try:
                self.serial_port.close()
            except:
                pass
        
        if self.control:
            try:
                if self.motor_enabled:
                    self.control.disable_all()
                    time.sleep(0.1)
                self.control.__exit__(None, None, None)
            except:
                pass
        
        print("清理完成")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        reply = QMessageBox.question(self, '确认退出',
                                    "确定要退出吗？",
                                    QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.cleanup()
            event.accept()
            QTimer.singleShot(100, lambda: QApplication.quit())
        else:
            event.ignore()


# ==================== 主函数 ====================
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = GripperUI()
    window.show()
    
    return app.exec_()


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as e:
        print(f"程序错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sys.exit(0)
