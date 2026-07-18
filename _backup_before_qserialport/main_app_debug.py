# -*- coding: utf-8 -*-
"""调试版入口 - Mock仪器模拟器 + 控制台串口日志
无需硬件，双击运行即可用完整UI测试全部功能，同时控制台输出所有串口通讯日志。

用法:
    python main_app_debug.py
"""
import sys, os, datetime

# ===== 1. 启动 Mock 仪器模拟器 =====
from mock_instrument import MockInstrumentSimulator, SimSerialAdapter

_mock_sim = MockInstrumentSimulator()
_mock_sim.set_online(True)
_mock_sim.start()

print("=" * 60)
print("  微机全自动水分测定仪 — Mock 调试版")
print("  仪器模拟器已启动 + 串口日志全开")
print("=" * 60)
print()

# ===== 2. 导入钩子：拦截 serial_comm，注入 Mock + 日志 =====
_import_orig = __builtins__.__import__ if isinstance(__builtins__, dict) else __builtins__.__import__


def _debug_import(name, *args, **kwargs):
    mod = _import_orig(name, *args, **kwargs)
    if name == "serial_comm":
        _patch_for_mock_and_debug(mod)
    return mod


def _patch_for_mock_and_debug(mod):
    _ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    TAG = "[调试-串口] "

    # ---- Mock: 替换 __init__ 和 open，注入 SimSerialAdapter ----
    _orig_init = mod.SerialManager.__init__

    def _mock_init(self, parent=None, use_mock=False):
        _orig_init(self, parent, use_mock=False)
        self._serial = None  # 由 _mock_open 创建

    def _mock_open(self, port=None, baudrate=None, config=None):
        self._mock = False
        if self._serial is None:
            self._serial = SimSerialAdapter(_mock_sim, serial_mgr=self)
        self._config.port = "MOCK"
        if getattr(self, "_connected_emitted", False):
            print(TAG + _ts() + " 打开串口(端口=MOCK) -> 已连接(复用)")
            return True
        self._connected_emitted = True
        self.connected.emit()
        print(TAG + _ts() + " 打开串口(端口=MOCK) -> True 已连接=True")
        # 启动上行帧轮询定时器: 每200ms读取模拟器上行帧并触发 data_received 信号
        from PySide2.QtCore import QTimer
        def _poll():
            try:
                raw = self._serial.read_all()
            except Exception:
                return
            if raw:
                self.update_uplink_time()
                self.data_received.emit(raw)
        self._mock_poll_timer = QTimer(self)
        self._mock_poll_timer.timeout.connect(_poll)
        self._mock_poll_timer.start(200)
        return True

    mod.SerialManager.__init__ = _mock_init
    mod.SerialManager.open = _mock_open

    # ---- 调试日志：包装 send/read/read_all ----
    _send = mod.SerialManager.send
    _read_all = mod.SerialManager.read_all
    _flush = mod.SerialManager.flush_input

    def _debug_send(self, data):
        hex_str = " ".join(f"{b:02X}" for b in data)
        ascii_repr = repr(data) if all(32 <= b < 127 for b in data) else ""
        print(TAG + _ts() + " 发送(len=%d) HEX: %s %s" % (len(data), hex_str, ascii_repr))
        n = _send(self, data)
        if n == 0:
            print(TAG + _ts() + " 发送失败!")
        return n

    def _debug_read_all(self):
        data = _read_all(self)
        if data:
            hex_str = " ".join(f"{b:02X}" for b in data[:80])
            if len(data) > 80:
                hex_str += "..."
            has_ok = b'\x4F\x4B\x01\x45\x4E\x44' in data
            print(TAG + _ts() + " 读取全部 -> %d字节 %s %s" % (
                len(data), "含OK" if has_ok else "", hex_str))
        return data

    def _debug_flush_input(self):
        print(TAG + _ts() + " 清空接收缓冲区")
        _flush(self)

    mod.SerialManager.send = _debug_send
    mod.SerialManager.read_all = _debug_read_all
    mod.SerialManager.flush_input = _debug_flush_input

    print(TAG + "Mock模拟器 + 调试补丁已注入")


if isinstance(__builtins__, dict):
    __builtins__["__import__"] = _debug_import
else:
    __builtins__.__import__ = _debug_import

# ===== 3. 启动主界面 =====
from main_app import main

main()
