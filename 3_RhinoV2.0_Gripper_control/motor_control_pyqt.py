#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电机控制UI界面 - PyQt5版本
提供打开和闭合两个按钮，可设定力矩值
"""

import sys
import time
import signal
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox,
                             QGroupBox, QMessageBox, QFrame)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QFont, QPalette, QColor
from damiao import *

# 全局应用实例
app_instance = None


class MotorControlThread(QThread):
    """电机控制线程"""
    error_signal = pyqtSignal(str)

    def __init__(self, control, canid):
        super().__init__()
        self.control = control
        self.canid = canid
        self.torque = 0.0
        self.running = True

    def set_torque(self, torque):
        """设置力矩值（实时生效）"""
        self.torque = torque

    def run(self):
        """运行电机控制循环"""
        try:
            while self.running:
                if self.control is not None:
                    self.control.control_mit(self.control.getMotor(self.canid),
                                           0.0, 0.0, 0.0, 0.0, self.torque)
                time.sleep(0.01)  # 10ms控制周期
        except Exception as e:
            self.error_signal.emit(f"电机控制错误: {e}")
        finally:
            # 停止电机
            if self.control is not None:
                try:
                    self.control.control_mit(self.control.getMotor(self.canid),
                                           0.0, 0.0, 0.0, 0.0, 0.0)
                except:
                    pass

    def stop(self):
        """停止线程"""
        self.running = False


class MotorControlUI(QMainWindow):
    def __init__(self):
        super().__init__()

        # 电机控制相关
        self.control = None
        self.canid = 0x01
        self.mstid = 0x11
        self.motor_thread = None
        self.current_mode = None
        self.motor_enabled = False  # 电机使能状态

        # 默认力矩值
        self.open_torque_value = -0.25
        self.close_torque_value = 0.15

        # 初始化UI
        self.init_ui()

        # 延迟初始化电机（让UI先显示）
        QTimer.singleShot(100, self.init_motor)

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("电机控制系统")
        self.setGeometry(100, 100, 600, 500)

        # 设置样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                border-radius: 8px;
                padding: 15px;
                min-height: 60px;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QLabel {
                font-size: 13px;
            }
            QDoubleSpinBox {
                font-size: 14px;
                padding: 5px;
                border: 2px solid #cccccc;
                border-radius: 4px;
                min-height: 30px;
            }
        """)

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(30, 30, 30, 30)

        # 标题
        title_label = QLabel("电机控制系统")
        title_font = QFont("Arial", 24, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #333333; margin-bottom: 10px;")
        main_layout.addWidget(title_label)

        # 状态信息组
        status_group = QGroupBox("状态信息")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(10)

        self.status_label = QLabel("电机状态: 初始化中...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; color: #666666;")
        status_layout.addWidget(self.status_label)

        self.mode_label = QLabel("当前模式: 无")
        self.mode_label.setAlignment(Qt.AlignCenter)
        self.mode_label.setStyleSheet("font-size: 14px; color: #666666;")
        status_layout.addWidget(self.mode_label)

        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # 电机使能/失能区域
        enable_layout = QHBoxLayout()
        enable_layout.setSpacing(10)

        self.enable_button = QPushButton("使能电机")
        self.enable_button.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                min-height: 40px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.enable_button.clicked.connect(self.enable_motor)
        self.enable_button.setEnabled(False)
        enable_layout.addWidget(self.enable_button)

        self.disable_button = QPushButton("失能电机")
        self.disable_button.setStyleSheet("""
            QPushButton {
                background-color: #9E9E9E;
                color: white;
                min-height: 40px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        self.disable_button.clicked.connect(self.disable_motor)
        self.disable_button.setEnabled(False)
        enable_layout.addWidget(self.disable_button)

        main_layout.addLayout(enable_layout)

        # 控制按钮区域
        control_layout = QHBoxLayout()
        control_layout.setSpacing(20)

        # 打开控制组
        open_group = QGroupBox("打开")
        open_layout = QVBoxLayout()
        open_layout.setSpacing(10)

        open_torque_label = QLabel("力矩值:")
        open_torque_label.setAlignment(Qt.AlignCenter)
        open_layout.addWidget(open_torque_label)

        self.open_torque_spin = QDoubleSpinBox()
        self.open_torque_spin.setRange(-10.0, 0.0)
        self.open_torque_spin.setSingleStep(0.1)
        self.open_torque_spin.setValue(self.open_torque_value)
        self.open_torque_spin.setDecimals(2)
        self.open_torque_spin.setSuffix(" N·m")
        self.open_torque_spin.setAlignment(Qt.AlignCenter)
        self.open_torque_spin.valueChanged.connect(self.on_open_torque_changed)
        open_layout.addWidget(self.open_torque_spin)

        self.open_button = QPushButton("打开")
        self.open_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.open_button.clicked.connect(self.start_open)
        self.open_button.setEnabled(False)
        open_layout.addWidget(self.open_button)

        open_group.setLayout(open_layout)
        control_layout.addWidget(open_group)

        # 闭合控制组
        close_group = QGroupBox("闭合")
        close_layout = QVBoxLayout()
        close_layout.setSpacing(10)

        close_torque_label = QLabel("力矩值:")
        close_torque_label.setAlignment(Qt.AlignCenter)
        close_layout.addWidget(close_torque_label)

        self.close_torque_spin = QDoubleSpinBox()
        self.close_torque_spin.setRange(0.0, 10.0)
        self.close_torque_spin.setSingleStep(0.1)
        self.close_torque_spin.setValue(self.close_torque_value)
        self.close_torque_spin.setDecimals(2)
        self.close_torque_spin.setSuffix(" N·m")
        self.close_torque_spin.setAlignment(Qt.AlignCenter)
        self.close_torque_spin.valueChanged.connect(self.on_close_torque_changed)
        close_layout.addWidget(self.close_torque_spin)

        self.close_button = QPushButton("闭合")
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
        """)
        self.close_button.clicked.connect(self.start_close)
        self.close_button.setEnabled(False)
        close_layout.addWidget(self.close_button)

        close_group.setLayout(close_layout)
        control_layout.addWidget(close_group)

        main_layout.addLayout(control_layout)

        # 添加弹性空间
        main_layout.addStretch()

    def init_motor(self):
        """初始化电机"""
        try:
            init_data = []
            init_data.append(DmActData(
                motorType=DM_Motor_Type.DM4310,
                mode=Control_Mode.MIT_MODE,
                can_id=self.canid,
                mst_id=self.mstid))

            # 直接创建 Motor_Control，不使用 with 语句
            # 注意：Motor_Control.__init__ 会自动调用 enable_all()
            self.control = Motor_Control(1000000, 5000000,
                                        "818F9E6ACF42F4147B2EE0FE9382AF11",
                                        init_data)

            # 切换到 MIT 模式
            self.control.switchControlMode(self.control.getMotor(self.canid),
                                          Control_Mode_Code.MIT)

            # Motor_Control.__init__ 已经调用了 enable_all()
            # 所以我们需要立即失能，让用户手动使能
            self.control.disable_all()
            time.sleep(0.1)

            self.status_label.setText("电机状态: 已初始化 (未使能)")
            self.status_label.setStyleSheet("font-size: 14px; color: #FF9800; font-weight: bold;")
            self.enable_button.setEnabled(True)

        except Exception as e:
            self.status_label.setText(f"电机状态: 初始化失败")
            self.status_label.setStyleSheet("font-size: 14px; color: #f44336; font-weight: bold;")
            QMessageBox.critical(self, "错误", f"电机初始化失败:\n{e}")

    def enable_motor(self):
        """使能电机"""
        if self.control is None:
            QMessageBox.warning(self, "警告", "电机未初始化")
            return

        try:
            self.control.enable_all()
            self.motor_enabled = True
            self.status_label.setText("电机状态: 已使能")
            self.status_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")

            self.enable_button.setEnabled(False)
            self.disable_button.setEnabled(True)
            self.open_button.setEnabled(True)
            self.close_button.setEnabled(True)

            print("电机已使能")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"使能电机失败:\n{e}")

    def disable_motor(self):
        """失能电机"""
        if self.control is None:
            QMessageBox.warning(self, "警告", "电机未初始化")
            return

        # 先停止电机运动
        self.stop_motor()

        try:
            self.control.disable_all()
            self.motor_enabled = False
            self.status_label.setText("电机状态: 已失能")
            self.status_label.setStyleSheet("font-size: 14px; color: #9E9E9E; font-weight: bold;")

            self.enable_button.setEnabled(True)
            self.disable_button.setEnabled(False)
            self.open_button.setEnabled(False)
            self.close_button.setEnabled(False)

            # 恢复按钮样式
            self.open_button.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
            self.close_button.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #0b7dda;
                }
            """)

            print("电机已失能")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"失能电机失败:\n{e}")

    def on_open_torque_changed(self, value):
        """打开力矩值改变时的回调"""
        if self.current_mode == 'open' and self.motor_thread is not None and self.motor_thread.isRunning():
            # 实时更新力矩
            self.motor_thread.set_torque(value)
            self.mode_label.setText(f"当前模式: 打开 (力矩: {value:.2f} N·m)")

    def on_close_torque_changed(self, value):
        """闭合力矩值改变时的回调"""
        if self.current_mode == 'close' and self.motor_thread is not None and self.motor_thread.isRunning():
            # 实时更新力矩
            self.motor_thread.set_torque(value)
            self.mode_label.setText(f"当前模式: 闭合 (力矩: {value:.2f} N·m)")

    def start_open(self):
        """开始打开动作"""
        if not self.motor_enabled:
            QMessageBox.warning(self, "警告", "请先使能电机")
            return

        torque = self.open_torque_spin.value()
        if torque > 0:
            QMessageBox.warning(self, "警告", "打开力矩应为负值")
            return

        self.current_mode = 'open'
        self.mode_label.setText(f"当前模式: 打开 (力矩: {torque:.2f} N·m)")
        self.mode_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")

        # 如果线程已存在，直接更新力矩
        if self.motor_thread is not None and self.motor_thread.isRunning():
            self.motor_thread.set_torque(torque)
        else:
            # 启动电机控制线程
            self.motor_thread = MotorControlThread(self.control, self.canid)
            self.motor_thread.set_torque(torque)
            self.motor_thread.error_signal.connect(self.on_motor_error)
            self.motor_thread.start()

        # 更新按钮状态
        self.open_button.setStyleSheet("""
            QPushButton {
                background-color: #2E7D32;
                color: white;
                border: 3px solid #1B5E20;
            }
        """)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
        """)

    def start_close(self):
        """开始闭合动作"""
        if not self.motor_enabled:
            QMessageBox.warning(self, "警告", "请先使能电机")
            return

        torque = self.close_torque_spin.value()
        if torque < 0:
            QMessageBox.warning(self, "警告", "闭合力矩应为正值")
            return

        self.current_mode = 'close'
        self.mode_label.setText(f"当前模式: 闭合 (力矩: {torque:.2f} N·m)")
        self.mode_label.setStyleSheet("font-size: 14px; color: #2196F3; font-weight: bold;")

        # 如果线程已存在，直接更新力矩
        if self.motor_thread is not None and self.motor_thread.isRunning():
            self.motor_thread.set_torque(torque)
        else:
            # 启动电机控制线程
            self.motor_thread = MotorControlThread(self.control, self.canid)
            self.motor_thread.set_torque(torque)
            self.motor_thread.error_signal.connect(self.on_motor_error)
            self.motor_thread.start()

        # 更新按钮状态
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #1565C0;
                color: white;
                border: 3px solid #0D47A1;
            }
        """)
        self.open_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

    def stop_motor(self):
        """停止电机"""
        if self.motor_thread is not None:
            self.motor_thread.stop()
            self.motor_thread.wait(1000)  # 等待最多1秒

        # 确保电机停止
        if self.control is not None:
            try:
                self.control.control_mit(self.control.getMotor(self.canid),
                                       0.0, 0.0, 0.0, 0.0, 0.0)
            except:
                pass

        # 更新UI
        self.mode_label.setText("当前模式: 已停止")
        self.mode_label.setStyleSheet("font-size: 14px; color: #666666;")

        # 恢复按钮原始样式
        self.open_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
        """)

    def on_motor_error(self, error_msg):
        """处理电机错误"""
        QMessageBox.critical(self, "错误", error_msg)
        self.stop_motor()

    def cleanup(self):
        """清理资源"""
        print("开始清理资源...")

        # 停止电机线程
        if self.motor_thread is not None:
            print("停止电机线程...")
            self.motor_thread.stop()
            self.motor_thread.wait(1000)

        # 停止电机并清理控制器
        if self.control is not None:
            try:
                print("停止电机...")
                self.control.control_mit(self.control.getMotor(self.canid),
                                       0.0, 0.0, 0.0, 0.0, 0.0)
                time.sleep(0.1)

                if self.motor_enabled:
                    print("失能电机...")
                    self.control.disable_all()
                    time.sleep(0.1)

                print("关闭控制器...")
                # 手动调用 __exit__ 来清理资源
                self.control.__exit__(None, None, None)
            except Exception as e:
                print(f"清理时出错: {e}")

        print("资源清理完成")

    def closeEvent(self, event):
        """窗口关闭事件"""
        reply = QMessageBox.question(self, '确认退出',
                                    "确定要退出吗？",
                                    QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.cleanup()
            event.accept()
            # 强制退出应用
            QTimer.singleShot(100, lambda: QApplication.quit())
        else:
            event.ignore()


def signal_handler(signum, frame):
    """信号处理函数"""
    print(f"\n接收到信号 {signum}，正在退出...")
    if app_instance:
        # 在主线程中关闭窗口
        QTimer.singleShot(0, lambda: app_instance.closeAllWindows())


def main():
    global app_instance

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app_instance = QApplication(sys.argv)

    # 设置定时器来处理Ctrl+C
    timer = QTimer()
    timer.start(500)  # 每500ms检查一次
    timer.timeout.connect(lambda: None)  # 允许处理信号

    # 设置应用样式
    app_instance.setStyle('Fusion')

    window = MotorControlUI()
    window.show()

    return app_instance.exec_()


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n程序被中断")
    except Exception as e:
        print(f"程序错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("程序退出")
        sys.exit(exit_code)
