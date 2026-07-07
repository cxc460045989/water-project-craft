# -*- coding: utf-8 -*-
"""上行数据测试脚本 — Mock 模式下模拟仪器每秒上报"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide2.QtCore import QCoreApplication, QTimer
from serial_comm import SerialManager
from protocol_layer import UplinkBuffer, FrameParser, CommandBuilder, CMD


def main():
    app = QCoreApplication(sys.argv)
    mgr = SerialManager(use_mock=True)
    buf = UplinkBuffer()

    scenarios = [
        (25.0,  0.0000, 0, 0, "初始待机 — 常温 25C, 天平 0g, 脱机"),
        (25.0,  0.0000, 1, 0, "联机建立 — 联机标志变为 1"),
        (85.0,  0.0000, 1, 0, "开始加热 — 炉温升至 85C"),
        (105.0, 0.0000, 1, 0, "恒温阶段 — 炉温 105C"),
        (105.0, 1.0017, 1, 0, "样品放入 — 天平读数 1.0017g"),
        (105.0, 0.9823, 1, 1, "称量确认 — 按键按下 1"),
    ]
    idx = [0]

    def on_connected():
        print("[MOCK] 串口已连接")
        mgr._serial.add_response(CommandBuilder.build_command(CMD.HANDSHAKE), b"OK")
        mgr._serial.set_uplink_frame(**scenario_to_kw(scenarios[0]))
        QTimer.singleShot(500, tick)

    def scenario_to_kw(s):
        return {"temperature": s[0], "weight": s[1], "online": s[2], "btn": s[3]}

    def tick():
        i = idx[0]
        if i >= len(scenarios):
            print("\n=== 全部场景播放完毕 ===")
            mgr.disconnect()
            app.quit()
            return
        temp, weight, online, btn, desc = scenarios[i]
        mgr._serial.set_uplink_frame(temperature=temp, weight=weight, online=online, btn=btn)
        # 直接模拟仪器主动上报：把上行帧放入输出缓冲
        f = mgr._serial._uplink_frame
        if f:
            mgr._serial._out_buf.extend(f)
        raw = mgr.read_all()
        if raw:
            frames = buf.feed(raw)
            for f in frames:
                btn_s = " [按键按下]" if f["btn_pressed"] else ""
                print("帧 #%d: 炉温 %6.1fC 重量 %8.4fg  %s%s" % (
                    i+1, f["temperature"], f["weight"],
                    "联机" if f["online"] else "脱机", btn_s))
                print("       原始: %s  (%s)" % (f["raw_str"], desc))
        idx[0] += 1
        QTimer.singleShot(1500, tick)

    mgr.connected.connect(on_connected)
    mgr.disconnected.connect(lambda: print("[MOCK] 串口已断开"))

    print("=" * 60)
    print("  上行数据 Mock 测试  (6 种工况, 每 1.5s 切换)")
    print("=" * 60)
    print()
    mgr.open()
    app.exec_()


if __name__ == "__main__":
    main()