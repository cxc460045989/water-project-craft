# -*- coding: utf-8 -*-
"""调试版入口 - 带控制台窗口 + 串口详细日志
用法: 直接双击运行, 会显示控制台窗口输出串口通讯日志
"""
import sys, os

_import_orig = __builtins__.__import__ if isinstance(__builtins__, dict) else __builtins__.__import__

def _debug_import(name, *args, **kwargs):
    mod = _import_orig(name, *args, **kwargs)
    if name == "serial_comm":
        _patch_serial_manager(mod)
    return mod

def _patch_serial_manager(mod):
    import datetime
    _ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

    _SerialManager_open = mod.SerialManager.open
    _SerialManager_send = mod.SerialManager.send
    _SerialManager_read = mod.SerialManager.read
    _SerialManager_read_all = mod.SerialManager.read_all
    _SerialManager_readline = mod.SerialManager.readline
    _SerialManager_flush_input = mod.SerialManager.flush_input
    _MockSerial_write = mod.MockSerial.write
    _MockSerial_read = mod.MockSerial.read
    _MockSerial_read_all = mod.MockSerial.read_all
    _MockSerial_readline = mod.MockSerial.readline
    _MockSerial_read_until = mod.MockSerial.read_until

    TAG = "[调试-串口] "

    def _debug_open(self, port=None, baudrate=None, config=None):
        result = _SerialManager_open(self, port, baudrate, config)
        print(TAG + _ts() + " 打开串口(端口=" + str(port) + " 波特率=" + str(baudrate) + ") -> " + str(result) + " 已连接=" + str(self.is_connected))
        if self._serial and hasattr(self._serial, "port"):
            print(TAG + _ts() + "  实际端口: " + str(self._serial.port))
        return result

    def _debug_send(self, data):
        hex_str = " ".join(f"{b:02X}" for b in data)
        ascii_repr = repr(data) if all(32 <= b < 127 for b in data) else ""
        print(TAG + _ts() + " 发送(len=" + str(len(data)) + ")  HEX: " + hex_str + ("  ASCII: " + ascii_repr if ascii_repr else ""))
        n = _SerialManager_send(self, data)
        print(TAG + _ts() + " 发送完成 -> " + str(n) + " 字节")
        return n

    def _debug_read(self, size=1):
        data = _SerialManager_read(self, size)
        if data:
            hex_str = " ".join(f"{b:02X}" for b in data)
            ascii_str = repr(data) if all(32 <= b < 127 for b in data) else ""
            print(TAG + _ts() + " 读取(" + str(size) + ") -> " + str(len(data)) + " 字节  HEX: " + hex_str + ("  ASCII: " + ascii_str if ascii_str else ""))
        return data

    def _debug_read_all(self):
        data = _SerialManager_read_all(self)
        if data:
            hex_str = " ".join(f"{b:02X}" for b in data)
            ascii_str = repr(data) if all(32 <= b < 127 for b in data) else ""
            print(TAG + _ts() + " 读取全部() -> " + str(len(data)) + " 字节  HEX: " + hex_str + ("  ASCII: " + ascii_str if ascii_str else ""))
        return data

    def _debug_readline(self):
        data = _SerialManager_readline(self)
        if data:
            hex_str = " ".join(f"{b:02X}" for b in data)
            ascii_str = repr(data) if all(32 <= b < 127 for b in data) else ""
            print(TAG + _ts() + " 读一行() -> " + str(len(data)) + " 字节  HEX: " + hex_str + ("  ASCII: " + ascii_str if ascii_str else ""))
        return data

    def _debug_flush_input(self):
        print(TAG + _ts() + " 清空接收缓冲区")
        _SerialManager_flush_input(self)

    def _debug_mock_write(self, data):
        hex_str = " ".join(f"{b:02X}" for b in data)
        print(TAG + _ts() + " 模拟写入(len=" + str(len(data)) + ")  HEX: " + hex_str)
        return _MockSerial_write(self, data)

    def _debug_mock_read(self, size=1):
        data = _MockSerial_read(self, size)
        if data:
            print(TAG + _ts() + " 模拟读取(" + str(size) + ") -> " + str(len(data)) + " 字节")
        return data

    def _debug_mock_read_all(self):
        data = _MockSerial_read_all(self)
        if data:
            print(TAG + _ts() + " 模拟读取全部() -> " + str(len(data)) + " 字节")
        return data

    def _debug_mock_readline(self):
        data = _MockSerial_readline(self)
        if data:
            print(TAG + _ts() + " 模拟读一行() -> " + str(len(data)) + " 字节")
        return data

    def _debug_mock_read_until(self, expected=b"\\n", size=256):
        data = _MockSerial_read_until(self, expected, size)
        if data:
            print(TAG + _ts() + " 模拟读直到() -> " + str(len(data)) + " 字节")
        return data

    mod.SerialManager.open = _debug_open
    mod.SerialManager.send = _debug_send
    mod.SerialManager.read = _debug_read
    mod.SerialManager.read_all = _debug_read_all
    mod.SerialManager.readline = _debug_readline
    mod.SerialManager.flush_input = _debug_flush_input
    mod.MockSerial.write = _debug_mock_write
    mod.MockSerial.read = _debug_mock_read
    mod.MockSerial.read_all = _debug_mock_read_all
    mod.MockSerial.readline = _debug_mock_readline
    mod.MockSerial.read_until = _debug_mock_read_until

    print(TAG + "串口通讯调试补丁已注入")

if isinstance(__builtins__, dict):
    __builtins__["__import__"] = _debug_import
else:
    __builtins__.__import__ = _debug_import

from main_app import main
main()