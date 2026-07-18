# -*- coding: utf-8 -*-
"""调试版入口 - Mock仪器模拟器 + 控制台串口日志
无需硬件，双击运行即可用完整UI测试全部功能，同时控制台输出所有串口通讯日志。

用法:
    python main_app_debug.py
"""
import sys, os, datetime

os.environ['WATER_SPEED_MODE'] = '1'

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

# ===== 2. 注入 Mock + 调试日志到 serial_comm =====
import serial_comm

_ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
TAG = "[调试-串口] "

# Mock: 替换 open 注入 SimSerialAdapter
def _mock_open(self, port=None, baudrate=None, config=None):
    self._mock = False
    if self._serial is None:
        self._serial = SimSerialAdapter(_mock_sim, serial_mgr=self)
        self._serial.readyRead.connect(self._on_ready_read)
    self._config.port = "MOCK"
    if getattr(self, "_connected_emitted", False):
        print(TAG + _ts() + " 打开串口(端口=MOCK) -> 已连接(复用)")
        return True
    self._connected_emitted = True
    self.connected.emit()
    print(TAG + _ts() + " 打开串口(端口=MOCK) -> True 已连接=True")
    return True

serial_comm.SerialManager.open = _mock_open

# 调试日志：包装 send
_send_orig = serial_comm.SerialManager.send

def _debug_send(self, data):
    hex_str = " ".join(f"{b:02X}" for b in data)
    print(TAG + _ts() + " 发送(len=%d) HEX: %s" % (len(data), hex_str))
    return _send_orig(self, data)

serial_comm.SerialManager.send = _debug_send

print(TAG + "Mock模拟器 + 调试补丁已注入")


# ===== 3. 启动主界面 =====
from main_app import main

main()
