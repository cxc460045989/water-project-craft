# -*- coding: utf-8 -*-
"""上行数据 GUI 测试 — 模拟仪器每秒上报，炉膛温度实时变化
直接运行：python test_uplink_gui.py

温度曲线（60秒循环）:
  第  1-10s: 常温 25℃ 待机
  第 11-30s: 升温 25→105℃
  第 31-50s: 恒温 105℃（±0.3℃ 波动）
  第 51-60s: 降温 105→30℃

=== 切换到真实串口 ===
将下面 serial_mgr 的 use_mock=True 改为 use_mock=False，
并取消注释 open() 中的 port="COM3" 参数即可连真实硬件。
"""

import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide2.QtWidgets import QApplication
from PySide2.QtCore import QTimer
from serial_comm import SerialManager
from protocol_layer import UplinkBuffer, FrameParser
from main_app import MoistureAnalyzer


def patch_window(w):
    """给主窗口注入上行模拟器和真实串口双模式支持"""

    class UplinkSimulator:
        def __init__(self, mgr):
            self._mgr = mgr
            self._step = 0
            self._timer = QTimer()
            self._timer.timeout.connect(self._tick)

        def start(self):
            self._step = 0
            self._timer.start(1000)

        def stop(self):
            self._timer.stop()

        def _tick(self):
            self._step += 1
            s = self._step
            cycle = (s - 1) % 60 + 1

            if cycle <= 10:
                temp = 25.0
                desc = "待机"
            elif cycle <= 30:
                t = (cycle - 10) / 20.0
                temp = 25.0 + 80.0 * t
                desc = "升温"
            elif cycle <= 50:
                temp = 105.0 + math.sin(cycle * 0.7) * 0.3
                desc = "恒温"
            else:
                t = (cycle - 50) / 10.0
                temp = 105.0 - 75.0 * t
                desc = "降温"

            weight = 0.0 if cycle <= 30 else round(1.0 + math.sin(cycle * 0.3) * 0.005, 4)
            online = 1 if cycle >= 3 else 0
            btn = 1 if cycle == 35 else 0

            mgr = self._mgr
            mgr._serial.set_uplink_frame(temperature=round(temp, 1), weight=weight,
                                          online=online, btn=btn)
            frame = mgr._serial._uplink_frame
            if frame:
                mgr._serial._out_buf.extend(frame)
            raw = mgr.read_all()
            if raw:
                mgr.data_received.emit(raw)

            w.progress_data.setText(
                "模拟: %s %ds/60  炉温: %.1f\u2103  重量: %.4fg  %s" % (
                    desc, cycle, temp, weight, "联机" if online else "脱机")
            )

    # ─── 打补丁 ───
    sim = UplinkSimulator(w.serial_mgr)
    w._sim = sim

    orig_connected = w._on_serial_connected
    def on_connected():
        orig_connected()
        # 如果是 Mock 模式才启动模拟器
        if w.serial_mgr._mock:
            sim.start()
            print("[SIM] 上行模拟已启动")
    w._on_serial_connected = on_connected


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # ─── 切换点 ───
    # Mock 模式：纯软件模拟，无需硬件
    # 真实模式：use_mock=False，连接真实串口仪器
    USE_MOCK = True

    if USE_MOCK:
        w = MoistureAnalyzer()
        patch_window(w)
    else:
        # 真实硬件模式：走完整 protocol_layer 流程
        w = MoistureAnalyzer()
        # 将 MainWindow 中的 SerialManager 切到真实模式
        w.serial_mgr = SerialManager(parent=w, use_mock=False)
        w._uplink_buf = UplinkBuffer()
        w.serial_mgr.connected.connect(w._on_serial_connected)
        w.serial_mgr.disconnected.connect(w._on_serial_disconnected)
        w.serial_mgr.data_received.connect(w._on_serial_data)
        w.serial_mgr.error_occurred.connect(w._on_serial_error)
        # 打开真实串口（按实际端口修改）
        # w.serial_mgr.open(port="COM3")

    w.setWindowTitle("微机全自动水分测定仪" + (" [MOCK 模拟]" if USE_MOCK else " [真实串口]"))
    w.show()

    # Mock 模式下自动连接
    if USE_MOCK and not w.serial_mgr.is_connected:
        w.serial_mgr.open()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()