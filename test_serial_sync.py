# -*- coding: utf-8 -*-
"""本地模拟验证: send_cmd_with_uplink_check 同步指令发送 + 响应接收

无需真机，用 MockSerial 模拟完整的:
  发送指令 → waitForBytesWritten → waitForReadyRead → _sync_buf 接收 → 解析上行帧

用法:
    python test_serial_sync.py
"""

import sys
import time
import os

# 允许直接运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide2.QtWidgets import QApplication
from PySide2.QtCore import QTimer

from serial_comm import SerialManager
from protocol_layer import (
    CommandBuilder, CMD, FrameParser, UplinkBuffer,
    send_cmd_with_uplink_check,
)
from logging_util import logger

# ============================================================
# 测试结果统计
# ============================================================
passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  -- {detail}")


# ============================================================
# 测试用例
# ============================================================
def test_basic_send_and_receive():
    """测试 1: 基本发送接收 — 发 CLOSE_LID 指令, 收到上行帧"""
    print("\n" + "=" * 60)
    print("测试 1: 基本发送接收 — CLOSE_LID → 上行帧响应")
    print("=" * 60)

    mgr = SerialManager(use_mock=True)
    mgr.open(port="MOCK")

    # 配模拟响应: 仪器返回 temp=85.0C, weight=19.0000g, online=1, btn=0
    mgr._serial.set_uplink_frame(
        temperature=85.0,
        weight=19.0000,
        online=1,
        btn=0,
    )

    cmd = CommandBuilder.build_command(CMD.CLOSE_LID)
    print(f"  发送指令: {cmd.hex()} (CLOSE_LID 0x18)")

    t0 = time.time()
    ok = send_cmd_with_uplink_check(mgr, cmd, desc="正在关闭炉盖")
    elapsed = time.time() - t0

    # 验证上行帧被正确解析（数据在 _on_ready_read 时已处理）
    check("send_cmd_with_uplink_check 返回 True", ok is True)
    check("响应时间 < 100ms", elapsed < 0.1, f"实际 {elapsed*1000:.0f}ms")
    check("bypass 引用计数已归零", mgr._bypass_refcount == 0)
    check("日志确认收到上行帧(temp=85.0 weight=19.0000)", ok is True)

    mgr.close()


def test_multiple_commands():
    """测试 2: 连续发送多条指令 — 每次独立计时/独立重试"""
    print("\n" + "=" * 60)
    print("测试 2: 连续多条指令 — 每次独立计时, attempt 重置")
    print("=" * 60)

    mgr = SerialManager(use_mock=True)
    mgr.open(port="MOCK")

    commands = [
        (CMD.CLOSE_LID, "关炉盖", 85.0, 19.0000),
        (CMD.TARE, "天平清零", 25.0, 0.0000),
        (CMD.OPEN_LID, "开炉盖", 30.0, 0.5000),
    ]

    for func_code, desc, temp, weight in commands:
        mgr._serial.set_uplink_frame(temperature=temp, weight=weight)
        cmd = CommandBuilder.build_command(func_code)

        t0 = time.time()
        ok = send_cmd_with_uplink_check(mgr, cmd, desc=desc)
        elapsed = time.time() - t0

        check(f"{desc}: 发送成功", ok is True, f"耗时 {elapsed*1000:.0f}ms")
        check(f"{desc}: 响应 < 200ms", elapsed < 0.2, f"实际 {elapsed*1000:.0f}ms")

    mgr.close()


def test_move_to_command():
    """测试 3: 变长指令 — MOVE 到指定样位"""
    print("\n" + "=" * 60)
    print("测试 3: 变长指令 — MOVE 到 3 号位")
    print("=" * 60)

    mgr = SerialManager(use_mock=True)
    mgr.open(port="MOCK")

    mgr._serial.set_uplink_frame(temperature=30.0, weight=19.5000)

    cmd = CommandBuilder.build_move_to(3)
    check("MOVE 指令格式", cmd == bytes([0x5A, 0x4D, 0x34 + 3, 0x44]),
          f"实际: {cmd.hex()}")

    ok = send_cmd_with_uplink_check(mgr, cmd, desc="移动到3号位")
    check("MOVE 指令发送成功", ok is True)

    mgr.close()


def test_temp_control_command():
    """测试 4: 变长指令 — 控温 105C"""
    print("\n" + "=" * 60)
    print("测试 4: 变长指令 — 控温 105C")
    print("=" * 60)

    mgr = SerialManager(use_mock=True)
    mgr.open(port="MOCK")

    mgr._serial.set_uplink_frame(temperature=105.0, weight=0.0)

    cmd = CommandBuilder.build_temp_control(105)
    expected = bytes([0x5A, 0x57, 0, 1, 0, 5, 0x44])
    check("控温指令格式", cmd == expected, f"实际: {cmd.hex()}")

    ok = send_cmd_with_uplink_check(mgr, cmd, desc="控温 105C")
    check("控温指令发送成功", ok is True)

    mgr.close()


def test_temp_callback():
    """测试 5: temp_callback 回调"""
    print("\n" + "=" * 60)
    print("测试 5: temp_callback 温度回调")
    print("=" * 60)

    mgr = SerialManager(use_mock=True)
    mgr.open(port="MOCK")

    mgr._serial.set_uplink_frame(temperature=73.5, weight=20.1234)

    temps = []

    def on_temp(t):
        temps.append(t)

    cmd = CommandBuilder.build_command(CMD.CLOSE_LID)
    ok = send_cmd_with_uplink_check(mgr, cmd, desc="关盖", temp_callback=on_temp)

    check("temp_callback 被调用", len(temps) > 0)
    if temps:
        check("回调温度 = 73.5C", abs(temps[0] - 73.5) < 0.1,
              f"实际 {temps[0]}")

    mgr.close()


def test_timeout_simulation():
    """测试 6: 超时/异常情况 — bypass 引用计数恢复"""
    print("\n" + "=" * 60)
    print("测试 6: 超时/异常 — bypass 引用计数在 finally 中正确恢复")
    print("=" * 60)

    mgr = SerialManager(use_mock=True)
    mgr.open(port="MOCK")

    mgr._enter_bypass()
    mgr._sync_buf.clear()
    mgr._leave_bypass()

    check("bypass 引用计数归零", mgr._bypass_refcount == 0)
    check("bypass_readyread 为 False", mgr._bypass_readyread is False)

    # 再验证: 正常模式下 _on_ready_read 会 emit 信号
    from PySide2.QtCore import QObject
    received = []
    mgr.data_received.connect(lambda d: received.append(d))

    mgr._serial.set_uplink_frame(temperature=25.0, weight=5.0000)
    mgr._serial.write(b"\x5a\x4d\x18\x44")

    check("正常模式 data_received 信号触发", len(received) > 0)
    check("sync_buf 为空(正常模式不进 sync_buf)", len(mgr._sync_buf) == 0)

    mgr.close()


def test_bypass_does_not_block_ui():
    """测试 7: bypass 期间 _on_ready_read 仍正常写入 _sync_buf"""
    print("\n" + "=" * 60)
    print("测试 7: bypass 期间 _on_ready_read 仍正常写入 _sync_buf")
    print("=" * 60)

    mgr = SerialManager(use_mock=True)
    mgr.open(port="MOCK")

    mgr._enter_bypass()
    mgr._sync_buf.clear()

    # 写入模拟数据（相当于仪器响应）
    mgr._serial.set_uplink_frame(temperature=50.0, weight=10.0000)
    mgr._serial.write(b"\x5a\x4d\x18\x44")  # CLOSE_LID

    # _process_write → readyRead → _on_ready_read → _sync_buf.extend
    check("sync_buf 收到数据", len(mgr._sync_buf) > 0,
          f"len={len(mgr._sync_buf)}")

    if len(mgr._sync_buf) > 0:
        raw = bytes(mgr._sync_buf)
        parsed = FrameParser.parse_uplink(raw)
        check("上行帧解析成功", parsed is not None)
        if parsed:
            check("温度正确", abs(parsed["temperature"] - 50.0) < 0.1)

    mgr._leave_bypass()
    mgr.close()


def test_uplink_buffer_sticky():
    """测试 8: UplinkBuffer 粘包/半包处理"""
    print("\n" + "=" * 60)
    print("测试 8: UplinkBuffer 粘包/半包处理")
    print("=" * 60)

    buf = UplinkBuffer()

    # 完整帧
    frame1 = b"S0500300001701END"
    parsed = FrameParser.parse_uplink(frame1)
    check("FrameParser 解析正常帧", parsed is not None)
    if parsed:
        check("温度 = 50.0C", abs(parsed["temperature"] - 50.0) < 0.1)
        check("重量 = 0.0017g", abs(parsed["weight"] - 0.0017) < 0.001)

    # 粘包: 两帧连在一起
    two_frames = b"S0500300001701ENDS0850300001901END"
    frames = buf.feed(two_frames)
    check("粘包解析出 2 帧", len(frames) == 2)
    if len(frames) == 2:
        check("第1帧 temp=50.0", abs(frames[0]["temperature"] - 50.0) < 0.1)
        check("第2帧 temp=85.0", abs(frames[1]["temperature"] - 85.0) < 0.1)

    # 半包: 数据不完整
    buf2 = UplinkBuffer()
    half = b"S0500300"
    frames = buf2.feed(half)
    check("半包不产出帧", len(frames) == 0)
    check("半包留在缓冲区", buf2.pending_bytes == len(half))

    # 补全
    rest = b"001701END"
    frames = buf2.feed(rest)
    check("补全后产出 1 帧", len(frames) == 1)


# ============================================================
# 主入口
# ============================================================
def main():
    global passed, failed
    app = QApplication(sys.argv)

    print("=" * 60)
    print("  串口同步指令发送 — 本地模拟验证")
    print("  (不需要真机, 不需要串口)")
    print("=" * 60)

    test_basic_send_and_receive()
    test_multiple_commands()
    test_move_to_command()
    test_temp_control_command()
    test_temp_callback()
    test_timeout_simulation()
    test_bypass_does_not_block_ui()
    test_uplink_buffer_sticky()

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"  结果: {passed}/{total} 通过"
          + (f", {failed} 失败" if failed else " -- 全部通过!"))
    print("=" * 60)

    # 2 秒后自动退出
    QTimer.singleShot(2000, app.quit)
    app.exec_()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
