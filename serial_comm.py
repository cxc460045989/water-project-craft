# -*- coding: utf-8 -*-
"""串口通讯统一封装层 — 通用框架
框架: PySide2 (Qt5) + pyserial — 兼容 Windows 7 / 麒麟Linux x86/ARM64

设计原则:
  - 不预设具体通讯协议，只负责收发原始字节
  - 解析层留给后续 protocol_layer.py
  - 通过 Qt Signal 与 UI 层解耦
  - 心跳为可选能力，默认关闭

用法:
    mgr = SerialManager()
    mgr.connected.connect(lambda: print("已连接"))
    mgr.data_received.connect(lambda data: print("收到:", data))
    mgr.connect("COM3", 9600)
    mgr.send(b"AT\r\n")
"""

import sys, time
from collections import namedtuple

from PySide2.QtCore import QObject, Signal, QTimer
from PySide2.QtCore import Qt


PortInfo = namedtuple("PortInfo", ["device", "description", "hwid"])


class SerialConfig:
    """串口参数容器，提供默认值"""
    __slots__ = (
        "port", "baudrate", "bytesize", "parity",
        "stopbits", "timeout", "write_timeout",
        "heartbeat_interval_ms", "heartbeat_cmd",
    )

    def __init__(self):
        self.port = ""
        self.baudrate = 9600
        self.bytesize = 8
        self.parity = "N"
        self.stopbits = 1
        self.timeout = 1.0
        self.write_timeout = 1.0
        self.heartbeat_interval_ms = 1000
        self.heartbeat_cmd = b""

    @classmethod
    def from_dict(cls, d):
        c = cls()
        for k in c.__slots__:
            if k in d:
                setattr(c, k, d[k])
        return c

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class SerialScanner:
    """跨平台串口扫描工具"""
    @staticmethod
    def list_ports():
        try:
            import serial.tools.list_ports as lp
        except ImportError:
            return []
        result = []
        for p in lp.comports():
            result.append(PortInfo(
                device=p.device,
                description=p.description or "",
                hwid=p.hwid or "",
            ))
        return result

    @staticmethod
    def list_ports_short():
        return [p.device for p in SerialScanner.list_ports()]


class SerialManager(QObject):
    """串口管理器 — 连接、收发、心跳控制
    信号:
        connected()        串口成功打开
        disconnected()     串口关闭
        data_received(data) 收到原始字节
        error_occurred(msg) 错误信息
        heartbeat_timeout() 心跳超时
    """
    connected = Signal()
    disconnected = Signal()
    data_received = Signal(bytes)
    error_occurred = Signal(str)
    heartbeat_timeout = Signal()

    def __init__(self, parent=None, use_mock=False):
        super().__init__(parent)
        self._serial = None
        self._config = SerialConfig()
        self._mock = use_mock
        self._heartbeat = HeartbeatController(self)
        self._heartbeat.timeout.connect(self.heartbeat_timeout)
        self._last_uplink_time = 0.0  # 最近上行数据时间戳
        self._uplink_watchdog = None  # QTimer 上行超时监视器
        self._bypass_poll = False     # 称重期间为 True，主线程 poll 跳过 read_all() 避免竞争

    @staticmethod
    def scan_ports():
        return SerialScanner.list_ports()

    @staticmethod
    def scan_ports_short():
        return SerialScanner.list_ports_short()

    def set_bypass_poll(self, bypass):
        """称重期间设为 True，主线程 poll 跳过串口读取，避免与 Worker 竞争数据"""
        self._bypass_poll = bypass

    @property
    def is_connected(self):
        return self._serial is not None and self._serial.is_open

    @property
    def port_name(self):
        if self._serial and self._serial.is_open:
            return self._serial.port
        return ""

    def open(self, port=None, baudrate=None, config=None):
        if self.is_connected:
            self.disconnect()
        if config is not None:
            self._config = config
        if port is not None:
            self._config.port = port
        if baudrate is not None:
            self._config.baudrate = baudrate
        if self._mock:
            self._serial = MockSerial(self._config)
            # 注册默认模拟响应
            self._serial.add_response(b"START_TEST", b"TEST_RUNNING\n")
            self._serial.add_response(b"STOP_TEST", b"TEST_STOPPED\n")
            self._serial.add_response(b"HEARTBEAT\n", b"HB_OK\n")
            self.connected.emit()
            return True
        if not self._config.port:
            self.error_occurred.emit("未指定串口号")
            return False
        try:
            import serial
        except ImportError:
            self.error_occurred.emit("pyserial 未安装: pip install pyserial")
            return False
        try:
            self._serial = serial.Serial(
                port=self._config.port,
                baudrate=self._config.baudrate,
                bytesize=self._config.bytesize,
                parity=self._config.parity,
                stopbits=self._config.stopbits,
                timeout=self._config.timeout,
                write_timeout=self._config.write_timeout,
            )
        except Exception as e:
            self._serial = None
            self.error_occurred.emit("打开串口失败: " + str(e))
            return False
    def disconnect(self):
        self._heartbeat.stop()
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.disconnected.emit()

    def send(self, data):
        if not self.is_connected:
            self.error_occurred.emit("串口未连接，无法发送")
            return 0
        try:
            n = self._serial.write(data)
            self._serial.flush()
            if self._mock and hasattr(self._serial, 'process_incoming'):
                self._serial.process_incoming()
            return n
        except Exception as e:
            self.error_occurred.emit("发送失败: " + str(e))
            return 0

    def read(self, size=1):
        if not self.is_connected:
            return b""
        try:
            return self._serial.read(size)
        except Exception as e:
            self.error_occurred.emit("读取失败: " + str(e))
            return b""

    def readline(self):
        if not self.is_connected:
            return b""
        try:
            return self._serial.readline()
        except Exception as e:
            self.error_occurred.emit("读取行失败: " + str(e))
            return b""

    def read_all(self):
        if not self.is_connected:
            return b""
        try:
            return self._serial.read_all()
        except Exception as e:
            self.error_occurred.emit("读取全部失败: " + str(e))
            return b""

    def flush_input(self):
        if self._serial and self._serial.is_open:
            try:
                self._serial.reset_input_buffer()
            except Exception:
                pass

    def flush_output(self):
        if self._serial and self._serial.is_open:
            try:
                self._serial.reset_output_buffer()
            except Exception:
                pass

    def enable_heartbeat(self, cmd=None, interval_ms=None):
        if cmd is not None:
            self._config.heartbeat_cmd = cmd
        if interval_ms is not None:
            self._config.heartbeat_interval_ms = interval_ms
        self._heartbeat.start(
            cmd=self._config.heartbeat_cmd,
            interval_ms=self._config.heartbeat_interval_ms,
        )

    def disable_heartbeat(self):
        self._heartbeat.stop()

    def update_uplink_time(self):
        """更新上行数据时间戳为当前时间"""
        self._last_uplink_time = time.time()

    @property
    def last_uplink_time(self):
        return self._last_uplink_time

    def enable_uplink_watchdog(self, timeout_sec=3.0):
        """启用上行数据超时监视器
        超时后发送 heartbeat_timeout 信号
        """
        from PySide2.QtCore import QTimer
        if self._uplink_watchdog is None:
            self._uplink_watchdog = QTimer(self)
            self._uplink_watchdog.timeout.connect(self._check_uplink_timeout)
        self._uplink_watchdog_interval = timeout_sec
        self._uplink_watchdog.start(int(timeout_sec * 1000))

    def disable_uplink_watchdog(self):
        if self._uplink_watchdog:
            self._uplink_watchdog.stop()

    def _check_uplink_timeout(self):
        import time
        if self._last_uplink_time > 0 and time.time() - self._last_uplink_time > self._uplink_watchdog_interval:
            self.heartbeat_timeout.emit()

    @property
    def heartbeat_active(self):
        return self._heartbeat.is_active

    def set_heartbeat_max_miss(self, count):
        self._heartbeat.max_miss = count

    def _on_heartbeat_tick(self):
        if not self.is_connected:
            self._heartbeat.notify_miss()
            return
        cmd = self._config.heartbeat_cmd
        if not cmd:
            return
        try:
            self._serial.write(cmd)
            self._serial.flush()
        except Exception:
            self._heartbeat.notify_miss()
            return
        try:
            resp = self._serial.read_until(expected=b"\n", size=256)
        except Exception:
            resp = b""
        if resp:
            self._heartbeat.notify_hit()
            self.data_received.emit(resp)
        else:
            self._heartbeat.notify_miss()


class HeartbeatController(QObject):
    """定时心跳控制"""
    timeout = Signal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._miss_count = 0
        self.max_miss = 3

    @property
    def is_active(self):
        return self._timer.isActive()

    def start(self, cmd, interval_ms):
        self._miss_count = 0
        if not cmd:
            self._manager.error_occurred.emit("心跳指令为空，不启用心跳")
            return
        self._timer.start(interval_ms)

    def stop(self):
        self._timer.stop()
        self._miss_count = 0

    def notify_hit(self):
        self._miss_count = 0

    def notify_miss(self):
        self._miss_count += 1
        if self._miss_count >= self.max_miss:
            self._miss_count = 0
            self.timeout.emit()

    def _tick(self):
        self._manager._on_heartbeat_tick()



# ============================================================
# MockSerial — 纯软件模拟串口设备，用于测试
# ============================================================
class MockSerial:
    def __init__(self, config):
        self.is_open = True
        self.port = config.port if config and config.port else "MOCK"
        self._in_buf = bytearray()
        self._out_buf = bytearray()
        self._responses = {}
        self._uplink_callback = None
        self._uplink_frame = None

    def write(self, data):
        self._in_buf.extend(data)
        return len(data)

    def flush(self):
        pass

    def read(self, size=1):
        if len(self._out_buf) == 0:
            return b""
        n = min(size, len(self._out_buf))
        data = bytes(self._out_buf[:n])
        self._out_buf = self._out_buf[n:]
        return data

    def read_all(self):
        data = bytes(self._out_buf)
        self._out_buf.clear()
        return data

    def readline(self):
        idx = self._out_buf.find(b"\n")
        if idx < 0:
            return b""
        line = bytes(self._out_buf[:idx+1])
        self._out_buf = self._out_buf[idx+1:]
        return line

    def read_until(self, expected=b"\n", size=256):
        idx = self._out_buf.find(expected)
        if idx < 0:
            if len(self._out_buf) == 0:
                return b""
            data = bytes(self._out_buf[:min(size, len(self._out_buf))])
            self._out_buf = self._out_buf[len(data):]
            return data
        end = idx + len(expected)
        data = bytes(self._out_buf[:end])
        self._out_buf = self._out_buf[end:]
        return data

    def reset_input_buffer(self):
        self._in_buf.clear()

    def reset_output_buffer(self):
        self._out_buf.clear()

    def close(self):
        self.is_open = False
        self._in_buf.clear()
        self._out_buf.clear()

    def add_response(self, cmd_prefix, resp_bytes):
        self._responses[cmd_prefix] = resp_bytes

    def set_uplink_frame(self, temperature=0.0, weight=0.0, online=0, btn=0):
        temp_int = int(round(temperature * 10))
        if temp_int < 0:
            temp_int = 0
        if temp_int > 9999:
            temp_int = 9999
        weight_raw = int(round(weight * 10000)) + 3000000
        if weight_raw < 0:
            weight_raw = 0
        if weight_raw > 9999999:
            weight_raw = 9999999
        online_val = 1 if online else 0
        btn_val = 1 if btn else 0
        s = "S{temp:04d}{weight:07d}{online:d}{btn:d}END".format(
            temp=temp_int, weight=weight_raw, online=online_val, btn=btn_val)
        self._uplink_frame = s.encode("ascii")
        self.set_uplink_callback(lambda: self._uplink_frame)

    def set_uplink_callback(self, callback):
        self._uplink_callback = callback

    def process_incoming(self):
        if len(self._in_buf) == 0:
            return
        data = bytes(self._in_buf)
        self._in_buf.clear()
        for prefix, resp in self._responses.items():
            if data.startswith(prefix):
                self._out_buf.extend(resp)
                break
        if self._uplink_callback:
            frame = self._uplink_callback()
            if frame:
                self._out_buf.extend(
                    frame if isinstance(frame, bytes) else frame.encode("ascii"))
if __name__ == "__main__":
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    print("=== 端口扫描 ===")
    ports = SerialScanner.list_ports()
    if ports:
        for p in ports:
            print("  " + p.device + ": " + p.description)
    else:
        print("  (未发现串口)")

    print("=== SerialManager 功能展示 ===")
    mgr = SerialManager()
    mgr.connected.connect(lambda: print("  信号: 已连接"))
    mgr.disconnected.connect(lambda: print("  信号: 已断开"))
    mgr.error_occurred.connect(lambda msg: print("  信号错误: " + msg))
    mgr.data_received.connect(lambda d: print("  收到数据: " + str(d)))
    mgr.heartbeat_timeout.connect(lambda: print("  信号: 心跳超时"))

    print("  (实例创建完成，等待实际连接)")
    print("  模块加载正常")
