# -*- coding: utf-8 -*-
"""持续上行模拟 — 模拟仪器每秒主动上报，数据动态变化"""

import sys, os, math, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide2.QtCore import QCoreApplication, QTimer
from serial_comm import SerialManager
from protocol_layer import UplinkBuffer, FrameParser, CommandBuilder, CMD


def main():
    app = QCoreApplication(sys.argv)
    mgr = SerialManager(use_mock=True)
    buf = UplinkBuffer()

    # 场景参数 (随时间演变)
    sim = {
        "temp": 25.0,       # 起始温度
        "weight": 0.0,      # 天平重量
        "online": 0,        # 联机标志
        "btn": 0,           # 按键
        "step": 0,          # 帧计数器
    }

    def on_connected():
        print("[MOCK] 已连接")
        mgr._serial.add_response(CommandBuilder.build_command(CMD.HANDSHAKE), b'\x4F\x4B\x01\x45\x4E\x44')
        mgr._serial.set_uplink_frame(**uplink_kw())
        # 每秒1帧
        QTimer.singleShot(1000, tick)

    def uplink_kw():
        return {
            "temperature": sim["temp"],
            "weight": sim["weight"],
            "online": sim["online"],
            "btn": sim["btn"],
        }

    def tick():
        sim["step"] += 1
        s = sim["step"]

        # 模拟加热过程: 前 20 秒升温到 105 度
        if s <= 20:
            sim["temp"] = 25.0 + (105.0 - 25.0) * s / 20.0
            sim["online"] = 1 if s >= 3 else 0  # 第3秒联机
        elif s <= 40:
            sim["temp"] = 105.0  # 恒温
            # 模拟天平读数波动
            sim["weight"] = 1.0000 + math.sin(s * 0.5) * 0.01
        elif s <= 50:
            sim["temp"] = 105.0
            sim["weight"] = max(0.0, sim["weight"] - 0.002)  # 失重
        else:
            sim["temp"] = max(25.0, sim["temp"] - 5.0)  # 降温
            sim["weight"] = 0.0

        # 按键: 第 15 秒模拟按下
        sim["btn"] = 1 if s == 15 else 0

        # 生成并注入上行帧
        mgr._serial.set_uplink_frame(**uplink_kw())
        f = mgr._serial._uplink_frame
        if f:
            mgr._serial._out_buf.extend(f)
        raw = mgr.read_all()
        if raw:
            frames = buf.feed(raw)
            for f in frames:
                btn_s = " [按键!]" if f["btn_pressed"] else ""
                print("[%4ds] temp=%6.1fC  weight=%8.4fg  %s%s" % (
                    s, f["temperature"], f["weight"],
                    "联机" if f["online"] else "脱机", btn_s))

        if s >= 60:
            print("\n=== 60 秒模拟结束 ===")
            mgr.disconnect()
            app.quit()
            return
        QTimer.singleShot(1000, tick)

    mgr.connected.connect(on_connected)
    mgr.disconnected.connect(lambda: print("[MOCK] 断开"))

    print("=" * 60)
    print("  持续上行模拟 — 每秒 1 帧, 共 60 秒")
    print("  第 1-20s: 升温  第 21-40s: 恒温+天平波动  第 41-50s: 失重  第 51-60s: 降温")
    print("=" * 60)
    print()
    mgr.open()
    app.exec_()


if __name__ == "__main__":
    main()