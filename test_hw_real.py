# -*- coding: utf-8 -*-
"""真机硬件检测测试入口 — 连接真实仪器串口进行通讯控制测试

用法:
    python test_hw_real.py COM3        # 连接 COM3 口
    python test_hw_real.py COM5 9600   # 自定义波特率
    python test_hw_real.py /dev/ttyUSB0  # Linux

流程:
    1. 打开指定串口 (9600-N-8-1)
    2. 等待仪器上报 (最多5秒，收到2帧确认链路)
    3. 执行握手指令
    4. 弹出硬件检测对话框
    5. 实时显示温度+重量, 按钮控制仪器
    6. 关闭对话框即断开串口退出
"""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide2.QtWidgets import QApplication, QMessageBox
from PySide2.QtCore import QTimer

from serial_comm import SerialManager, SerialConfig
from protocol_layer import handshake


def main():
    if len(sys.argv) < 2:
        print("用法: python test_hw_real.py <串口号> [波特率]")
        print("示例: python test_hw_real.py COM3")
        print("      python test_hw_real.py COM5 9600")
        print("      python test_hw_real.py /dev/ttyUSB0")
        sys.exit(1)

    port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 9600

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    config = SerialConfig()
    config.port = port
    config.baudrate = baud
    config.bytesize = 8
    config.parity = "N"
    config.stopbits = 1
    config.timeout = 1.0
    config.write_timeout = 1.0

    mgr = SerialManager(use_mock=False)

    def on_connected():
        print("[MAIN] 串口已连接: %s @ %d bps" % (port, baud))
        print("[MAIN] 等待仪器上报数据...")
        wait_start = time.time()
        frames_received = [0]

        def wait_uplink():
            raw = mgr.read_all()
            if raw:
                from protocol_layer import UplinkBuffer, FrameParser
                buf = UplinkBuffer()
                frames = buf.feed(raw)
                frames_received[0] += len(frames)
                for f in frames:
                    print("[UPLINK] temp=%.1fC  weight=%.4fg  online=%d" % (
                        f["temperature"], f["weight"], f["online"]))

            if frames_received[0] >= 2:
                print("[MAIN] 通讯链路正常，执行握手...")
                if handshake(mgr):
                    print("[MAIN] 握手成功！")
                    _open_dialog(mgr)
                else:
                    _show_error("握手失败，检查仪器连接")
                return

            if time.time() - wait_start > 5.0:
                print("[MAIN] 未收到足够上行帧，尝试直接握手...")
                if handshake(mgr):
                    print("[MAIN] 握手成功！")
                    _open_dialog(mgr)
                else:
                    _show_error("握手失败，检查仪器连接")
                return

            QTimer.singleShot(500, wait_uplink)

        QTimer.singleShot(500, wait_uplink)

    def on_disconnected():
        print("[MAIN] 串口已断开")

    def on_error(msg):
        print("[MAIN] 错误: %s" % msg)

    def _show_error(msg):
        print("[MAIN] %s" % msg)
        QMessageBox.critical(None, "连接失败", msg)
        mgr.disconnect()
        QTimer.singleShot(100, app.quit)

    def _open_dialog(mgr):
        from hardware_check_dialog import HardwareCheckDialog
        dlg = HardwareCheckDialog(serial_mgr=mgr)
        def cb(f):
            sys.stdout.write("\r[UPLINK] temp=%.1fC  weight=%.4fg  online=%d          " % (
                f["temperature"], f["weight"], f["online"]))
            sys.stdout.flush()
        dlg.set_status_callback(cb)
        dlg.finished.connect(lambda: _on_dialog_closed(mgr))
        dlg.show()

    def _on_dialog_closed(mgr):
        print("\n[MAIN] 对话框关闭，断开串口...")
        mgr.disconnect()
        QTimer.singleShot(100, app.quit)

    mgr.connected.connect(on_connected)
    mgr.disconnected.connect(on_disconnected)
    mgr.error_occurred.connect(on_error)

    print("=" * 50)
    print("  硬件检测真机测试")
    print("  串口: %s  波特率: %d" % (port, baud))
    print("=" * 50)
    print()
    print("[MAIN] 正在打开串口 %s ..." % port)
    ok = mgr.open(config=config)
    if not ok:
        print("[MAIN] 串口打开失败")
        sys.exit(1)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()