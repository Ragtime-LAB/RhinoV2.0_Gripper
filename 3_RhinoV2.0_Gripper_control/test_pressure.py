import serial
import csv
import time
import numpy as np
import matplotlib.pyplot as plt
import struct
from typing import List, Dict, Tuple

# 配置matplotlib支持中文显示
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'Noto Sans Mono CJK SC', 'AR PL UMing CN', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


class PressureSensorCalibration:
    def __init__(self, csv_file_path: str = None):
        """
        初始化压力传感器校准类

        Args:
            csv_file_path: 校准数据CSV文件路径
        """
        self.calibration_data = {}  # 存储每个传感器的校准参数
        self.sensor_count = 36
        self.grid_size = 6  # 6x6网格

        # 每个点位的尺寸为2.5mm × 2.5mm，转换为平方米
        self.sensor_area_mm2 = 2.5 * 2.5  # 面积(mm²)
        self.sensor_area_m2 = self.sensor_area_mm2 * 1e-6  # 转换为平方米(m²)

        # 如果提供了CSV文件路径，则加载校准数据
        if csv_file_path:
            self.load_calibration_data(csv_file_path)
        else:
            # 使用您提供的校准数据
            self._load_default_calibration_data()

    def _load_default_calibration_data(self):
        """加载默认的校准数据（从您提供的表格）"""
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

        for sensor_id, k, b in calibration_params:
            self.calibration_data[sensor_id] = {'k': k, 'b': b}

    def load_calibration_data(self, csv_file_path: str):
        """
        从CSV文件加载校准数据

        Args:
            csv_file_path: CSV文件路径
        """
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    sensor_id = int(row['传感器点位'])
                    k = float(row['斜率(k)'])
                    b = float(row['截距(b)'])
                    self.calibration_data[sensor_id] = {'k': k, 'b': b}
            print(f"成功加载 {len(self.calibration_data)} 个传感器的校准数据")
        except Exception as e:
            print(f"加载校准数据失败: {e}")
            # 如果加载失败，使用默认数据
            self._load_default_calibration_data()

    def ad_to_pressure(self, sensor_id: int, ad_value: float) -> Tuple[float, float]:
        """
        将AD值转换为压强(kPa)和压力(N)

        Args:
            sensor_id: 传感器ID (1-36)
            ad_value: AD值

        Returns:
            (压强_kPa, 压力_N)
        """
        if sensor_id not in self.calibration_data:
            raise ValueError(f"传感器ID {sensor_id} 不存在")

        k = self.calibration_data[sensor_id]['k']
        b = self.calibration_data[sensor_id]['b']

        # 使用一次函数转换: pressure_kPa = k * ad_value + b
        # 加上截距之后压强值偏差更大 因此只用斜率
        # pressure_kPa = k * ad_value + b
        pressure_kPa = k * ad_value

        # 计算压力(N): 压力 = 压强 × 面积
        # 注意: 1 kPa = 1000 Pa, 1 Pa = 1 N/m²
        # 传感器面积: 2.5mm × 2.5mm = 6.25 mm² = 6.25e-6 m²
        pressure_N = pressure_kPa * 1000 * self.sensor_area_m2  # kPa -> Pa -> N

        return (pressure_kPa, pressure_N)

    def get_grid_position(self, sensor_id: int) -> tuple:
        """
        根据传感器ID获取网格位置

        Args:
            sensor_id: 传感器ID (1-36)

        Returns:
            (x, y) 坐标
        """
        if sensor_id < 1 or sensor_id > self.sensor_count:
            raise ValueError(f"传感器ID必须在1-{self.sensor_count}之间")

        # 计算网格位置（反转Y轴以匹配物理布局）
        x = (sensor_id - 1) % self.grid_size
        y = self.grid_size - 1 - ((sensor_id - 1) // self.grid_size)  # 反转Y轴
        return (x, y)

    def get_sensor_id_from_grid(self, x: int, y: int) -> int:
        """
        根据网格位置获取传感器ID

        Args:
            x: x坐标 (0-5)
            y: y坐标 (0-5)

        Returns:
            传感器ID
        """
        if x < 0 or x >= self.grid_size or y < 0 or y >= self.grid_size:
            raise ValueError(f"坐标必须在0-{self.grid_size - 1}之间")

        # 反转Y轴以匹配物理布局
        actual_y = self.grid_size - 1 - y
        return actual_y * self.grid_size + x + 1


class PressureVisualizer:
    def __init__(self, calibration: PressureSensorCalibration):
        """
        压力可视化类

        Args:
            calibration: 校准对象
        """
        self.calibration = calibration
        self.fig = None
        self.ax = None
        self.pressure_matrix = None
        self.text_matrix = None
        self.im = None
        self.cbar = None

        # 初始化可视化
        self.setup_visualization()

    def setup_visualization(self):
        """设置可视化界面"""
        self.fig, self.ax = plt.subplots(figsize=(10, 8))

        # 初始化6x6的压力矩阵
        self.pressure_matrix = np.zeros((6, 6))

        # 创建热力图
        self.im = self.ax.imshow(self.pressure_matrix, cmap='hot', interpolation='nearest', vmin=0, vmax=100)

        # 添加颜色条
        self.cbar = self.fig.colorbar(self.im, ax=self.ax)
        self.cbar.set_label('压强 (kPa)', rotation=270, labelpad=15, fontsize=12)

        # 设置坐标轴
        self.ax.set_xticks(np.arange(6))
        self.ax.set_yticks(np.arange(6))
        self.ax.set_xticklabels(np.arange(6))
        self.ax.set_yticklabels(np.arange(6))
        self.ax.set_xlabel('X 坐标', fontsize=12)
        self.ax.set_ylabel('Y 坐标', fontsize=12)
        self.ax.set_title('6x6 压力传感器分布图 (每个点位面积: 2.5mm × 2.5mm)', fontsize=14, pad=10)

        # 初始化文本矩阵，用于显示压强和压力值
        self.text_matrix = [[None for _ in range(6)] for _ in range(6)]
        for i in range(6):
            for j in range(6):
                self.text_matrix[i][j] = self.ax.text(j, i, '',
                                                      ha="center", va="center",
                                                      color="white", fontsize=8)

        plt.tight_layout()
        plt.show(block=False)  # 非阻塞显示

    def update_visualization(self, sensor_data: Dict[int, Dict]):
        """
        更新可视化

        Args:
            sensor_data: 传感器数据
        """
        # 更新压力矩阵
        for sensor_id, data in sensor_data.items():
            x, y = data['x'], data['y']
            pressure_kPa = data['pressure_kPa']
            pressure_N = data['pressure_N']

            # 更新矩阵值
            self.pressure_matrix[y, x] = max(0, pressure_kPa)  # 确保不为负

            # 更新文本显示
            if pressure_kPa > 0:
                text = f"{pressure_kPa:.1f} kPa\n{pressure_N:.3f} N"
                color = "white" if pressure_kPa > 50 else "black"  # 根据背景色调整文字颜色
            else:
                text = "0.0 kPa\n0.000 N"
                color = "black"

            self.text_matrix[y][x].set_text(text)
            self.text_matrix[y][x].set_color(color)

        # 更新热力图
        self.im.set_data(self.pressure_matrix)

        # 自动调整颜色范围
        if np.max(self.pressure_matrix) > 0:
            self.im.set_clim(0, max(100, np.max(self.pressure_matrix) * 1.1))

        # 刷新图像
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()


class SerialPressureReader:
    # 配置参数
    HEADER = b'\xFF\x66'
    FRAME_SIZE = 78  # 帧大小

    def __init__(self, port: str, baudrate: int = 460800, calibration: PressureSensorCalibration = None):
        """
        串口压力读取器

        Args:
            port: 串口名称 (如 'COM1' 或 '/dev/ttyUSB0')
            baudrate: 波特率
            calibration: 校准对象
        """
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.calibration = calibration or PressureSensorCalibration()
        self.visualizer = PressureVisualizer(self.calibration)
        self.buffer = bytearray()  # 数据缓冲区

    def connect(self):
        """连接串口"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1  # 读取超时时间
            )
            print(f"成功连接到串口 {self.port}")
            print(
                f"每个传感器点位面积: {self.calibration.sensor_area_mm2:.2f} mm² ({self.calibration.sensor_area_m2:.2e} m²)")
            return True
        except Exception as e:
            print(f"连接串口失败: {e}")
            return False

    def disconnect(self):
        """断开串口连接"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print("已断开串口连接")

    def parse_frame(self, data: bytes) -> Dict[int, Dict]:
        """解析数据帧"""
        if len(data) != self.FRAME_SIZE:
            print(f"帧大小错误: 期望{self.FRAME_SIZE}, 实际{len(data)}")
            return None

        # 验证包头
        if data[0:2] != self.HEADER:
            print(f"包头错误: 期望{self.HEADER}, 实际{data[0:2]}")
            return None

        # 计算校验和
        checksum = sum(data[2:-2]) & 0xFFFF
        received_checksum = struct.unpack('>H', data[-2:])[0]

        if checksum != received_checksum:
            print(f"校验和错误: 计算值 {checksum}, 接收值 {received_checksum}")
            return None

        # 解析AD值 (36个点 x 2字节)
        ad_values = []
        for i in range(4, 76, 2):
            ad = struct.unpack('>H', data[i:i + 2])[0]  # 大端序
            ad_values.append(ad)

        # 转换为压力值并组织数据
        sensor_data = {}
        for i, ad_value in enumerate(ad_values):
            sensor_id = i + 1
            pressure_kPa, pressure_N = self.calibration.ad_to_pressure(sensor_id, ad_value)
            x, y = self.calibration.get_grid_position(sensor_id)

            sensor_data[sensor_id] = {
                'ad_value': ad_value,
                'pressure_kPa': pressure_kPa,
                'pressure_N': pressure_N,
                'x': x,
                'y': y
            }

        return sensor_data

    def read_sensor_data(self) -> Dict[int, Dict]:
        """
        读取所有传感器数据并转换为压力值

        Returns:
            字典格式的传感器数据 {传感器ID: {'ad_value': AD值, 'pressure_kPa': 压强, 'pressure_N': 压力, 'x': x坐标, 'y': y坐标}}
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            raise Exception("串口未连接")

        try:
            # 读取串口数据
            data = self.serial_conn.read(self.serial_conn.in_waiting or self.FRAME_SIZE * 2)
            if data:
                self.buffer += data

                # 处理缓冲区中的所有完整帧
                sensor_data = {}
                while len(self.buffer) >= self.FRAME_SIZE:
                    # 查找包头
                    header_pos = self.buffer.find(self.HEADER)
                    if header_pos == -1:
                        # 没有找到包头，清空缓冲区
                        self.buffer.clear()
                        break

                    # 丢弃包头之前的数据
                    if header_pos > 0:
                        self.buffer = self.buffer[header_pos:]

                    # 检查是否有完整帧
                    if len(self.buffer) >= self.FRAME_SIZE:
                        frame = self.buffer[:self.FRAME_SIZE]
                        self.buffer = self.buffer[self.FRAME_SIZE:]

                        # 解析帧
                        frame_data = self.parse_frame(frame)
                        if frame_data:
                            sensor_data = frame_data

                return sensor_data
            else:
                return {}

        except Exception as e:
            print(f"读取传感器数据失败: {e}")
            return {}

    def format_grid_output(self, sensor_data: Dict[int, Dict]) -> str:
        """
        格式化网格输出

        Args:
            sensor_data: 传感器数据

        Returns:
            格式化的网格字符串
        """
        grid_kPa = [['' for _ in range(6)] for _ in range(6)]
        grid_N = [['' for _ in range(6)] for _ in range(6)]

        for sensor_id, data in sensor_data.items():
            x, y = data['x'], data['y']
            pressure_kPa = data['pressure_kPa']
            pressure_N = data['pressure_N']
            grid_kPa[y][x] = f"{pressure_kPa:.2f}kPa"
            grid_N[y][x] = f"{pressure_N:.3f}N"

        # 构建输出字符串
        output = "压力分布网格 (6x6):\n"
        output += "压强 (kPa):\n"
        output += "Y\\X " + " ".join([f"{i:>10}" for i in range(6)]) + "\n"

        for y in range(6):
            output += f"{y}   "
            for x in range(6):
                output += f"{grid_kPa[y][x]:>10} "
            output += "\n"

        output += "\n压力 (N):\n"
        output += "Y\\X " + " ".join([f"{i:>10}" for i in range(6)]) + "\n"

        for y in range(6):
            output += f"{y}   "
            for x in range(6):
                output += f"{grid_N[y][x]:>10} "
            output += "\n"

        return output


# 使用示例
def main():
    # 创建校准对象
    calibration = PressureSensorCalibration()

    # 创建串口读取器 (请根据实际情况修改串口参数)
    serial_reader = SerialPressureReader(
        port='/dev/ttyUSB0',  # Linux串口
        baudrate=460800,  # 使用原始程序中的波特率
        calibration=calibration
    )

    # 连接串口
    if serial_reader.connect():
        try:
            # 持续读取数据
            while True:
                # 读取传感器数据
                sensor_data = serial_reader.read_sensor_data()

                if sensor_data:
                    # 更新可视化
                    serial_reader.visualizer.update_visualization(sensor_data)

                    # 显示控制台输出
                    print("\n" * 50)  # 清屏效果
                    grid_output = serial_reader.format_grid_output(sensor_data)
                    print(grid_output)

                    # 计算并显示统计信息
                    total_pressure_kPa = sum(data['pressure_kPa'] for data in sensor_data.values())
                    total_pressure_N = sum(data['pressure_N'] for data in sensor_data.values())
                    max_pressure_kPa = max(data['pressure_kPa'] for data in sensor_data.values())
                    max_pressure_N = max(data['pressure_N'] for data in sensor_data.values())

                    print(f"统计信息:")
                    print(f"总压强: {total_pressure_kPa:.2f} kPa")
                    print(f"总压力: {total_pressure_N:.5f} N")
                    print(
                        f"最大压强: {max_pressure_kPa:.2f} kPa (传感器 {max((k for k in sensor_data.keys()), key=lambda k: sensor_data[k]['pressure_kPa'])})")
                    print(f"最大压力: {max_pressure_N:.5f} N")
                    print(
                        f"每个传感器面积: {calibration.sensor_area_mm2:.2f} mm² ({calibration.sensor_area_m2:.2e} m²)")

                # 等待一段时间
                time.sleep(0.01)

        except KeyboardInterrupt:
            print("程序被用户中断")
        finally:
            serial_reader.disconnect()
            plt.close('all')

    # 测试单个转换示例
    print("\n--- 单个传感器转换测试 ---")
    test_ad_value = 100.0  # 测试AD值
    for sensor_id in [1, 7, 13, 19, 25, 31, 36]:  # 测试几个传感器
        try:
            pressure_kPa, pressure_N = calibration.ad_to_pressure(sensor_id, test_ad_value)
            x, y = calibration.get_grid_position(sensor_id)
            print(
                f"传感器{sensor_id} (X:{x}, Y:{y}): AD值={test_ad_value} -> 压强={pressure_kPa:.2f}kPa, 压力={pressure_N:.5f}N")
        except Exception as e:
            print(f"传感器{sensor_id}转换失败: {e}")


if __name__ == "__main__":
    main()