# -*- coding: utf-8 -*-
"""串口通讯统一封装层 — QSerialPort + readyRead 信号驱动
框架: PySide2 (Qt5) + QSerialPort — 兼容 Windows 7 / 麒麟Linux x86/ARM64

设计原则:
  - 不预设具体通讯协议，只负责收发原始字节
  - 解析层留给后续 protocol_layer.py
  - 通过 Qt Signal 与 UI 层解耦
  - readyRead 信号驱动，彻底消除 time.sleep()/read_all() 阻塞

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
from PySide2.QtSerialPort import QSerialPort


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
    """串口管理器 — QSerialPort + readyRead 信号驱动
    信号:
        connected()           串口成功打开
        disconnected()        串口关闭
        data_received(data)   收到原始字节
        error_occurred(msg)   错误信息
        heartbeat_timeout()   心跳超时
    """
    connected = Signal()
    disconnected = Signal()
    data_received = Signal(bytes)
    error_occurred = Signal(str)
    heartbeat_timeout = Signal()

    # ---- 配置映射 ----
    _PARITY_MAP = {"N": QSerialPort.NoParity, "E": QSerialPort.EvenParity,
                   "O": QSerialPort.OddParity, "M": QSerialPort.MarkParity,
                   "S": QSerialPort.SpaceParity}
    _STOP_MAP = {1: QSerialPort.OneStop, 1.5: QSerialPort.OneAndHalfStop,
                 2: QSerialPort.TwoStop}
    _DATA_MAP = {5: QSerialPort.Data5, 6: QSerialPort.Data6,
                 7: QSerialPort.Data7, 8: QSerialPort.Data8}

    def __init__(self, parent=None, use_mock=False):
        super().__init__(parent)
        self._serial = None
        self._config = SerialConfig()
        self._mock = use_mock
        self._heartbeat = HeartbeatController(self)
        self._heartbeat.timeout.connect(self.heartbeat_timeout)
        self._last_uplink_time = 0.0
        self._uplink_watchdog = None
        self._uplink_watchdog_interval = 3.0
        self._bypass_refcount = 0      # 引用计数 >0 时 readyRead 数据存入 _sync_buf
        self._sync_buf = bytearray()    # 同步指令期间的响应数据缓冲区

    @property
    def _bypass_readyread(self):
        return self._bypass_refcount > 0

    def _enter_bypass(self):
        """进入旁路模式（引用计数+1）"""
        self._bypass_refcount += 1

    def _leave_bypass(self):
        """退出旁路模式（引用计数-1）"""
        if self._bypass_refcount > 0:
            self._bypass_refcount -= 1

    @staticmethod
    def scan_ports():
        return SerialScanner.list_ports()

    @staticmethod
    def scan_ports_short():
        return SerialScanner.list_ports_short()

    @property
    def is_connected(self):
        if self._serial is None:
            return False
        try:
            if hasattr(self._serial, 'is_open'):
                return self._serial.is_open
            return self._serial.isOpen()
        except Exception:
            return False

    @property
    def bytesAvailable(self):
        """非阻塞返回可读字节数（QSerialPort 兼容接口）"""
        try:
            if self._serial:
                if hasattr(self._serial, 'bytesAvailable'):
                    return self._serial.bytesAvailable()
                if hasattr(self._serial, 'in_waiting'):
                    return self._serial.in_waiting
        except Exception:
            pass
        return 0

    @property
    def port_name(self):
        if self._serial:
            try:
                if hasattr(self._serial, 'portName'):
                    return self._serial.portName()
                return getattr(self._serial, 'port', '')
            except Exception:
                pass
        return ""

    # ---- 打开/关闭 ----

    def open(self, port=None, baudrate=None, config=None):
        if self.is_connected:
            self.close()
        if config is not None:
            self._config = config
        if port is not None:
            self._config.port = port
        if baudrate is not None:
            self._config.baudrate = baudrate

        if self._mock:
            self._serial = MockSerial(self._config)
            self._serial.readyRead.connect(self._on_ready_read)
            self._serial.add_response(b"START_TEST", b"TEST_RUNNING\n")
            self._serial.add_response(b"STOP_TEST", b"TEST_STOPPED\n")
            self._serial.add_response(b"HEARTBEAT\n", b"HB_OK\n")
            self.connected.emit()
            return True

        if not self._config.port:
            self.error_occurred.emit("未指定串口号")
            return False

        try:
            sp = QSerialPort()
            sp.setPortName(self._config.port)
            sp.setBaudRate(self._config.baudrate)
            sp.setParity(self._PARITY_MAP.get(self._config.parity, QSerialPort.NoParity))
            sp.setStopBits(self._STOP_MAP.get(self._config.stopbits, QSerialPort.OneStop))
            sp.setDataBits(self._DATA_MAP.get(self._config.bytesize, QSerialPort.Data8))
            sp.readyRead.connect(self._on_ready_read)
            if not sp.open(QSerialPort.ReadWrite):
                self.error_occurred.emit("打开串口失败: " + (sp.errorString() or "未知错误"))
                return False
            self._serial = sp
            self.connected.emit()
            return True
        except Exception as e:
            self._serial = None
            self.error_occurred.emit("打开串口失败: " + str(e))
            return False

    def close(self):
        self.disconnect()

    def disconnect(self):
        self._heartbeat.stop()
        if self._serial:
            try:
                if hasattr(self._serial, 'readyRead'):
                    try:
                        self._serial.readyRead.disconnect(self._on_ready_read)
                    except Exception:
                        pass
                if hasattr(self._serial, 'close'):
                    self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.disconnected.emit()

    # ---- 收发 ----

    def send(self, data):
        if not self.is_connected:
            self.error_occurred.emit("串口未连接，无法发送")
            return 0
        try:
            n = self._serial.write(data)
            if hasattr(self._serial, 'waitForBytesWritten'):
                self._serial.waitForBytesWritten(100)
            # Mock + 旁路模式: write() 内已同步生成响应到 _out_buf，
            # 但 readyRead 跨线程时 Qt 走 QueuedConnection 会延迟。
            # 直接同步读取，确保 _sync_buf 在 send() 返回时已有数据。
            if self._mock and self._bypass_readyread:
                self._on_ready_read()
            return n
        except Exception as e:
            self.error_occurred.emit("发送失败: " + str(e))
            return 0

    def readAll(self):
        """非阻塞读取所有可用字节（QSerialPort 兼容接口）"""
        if not self.is_connected:
            return b""
        try:
            if hasattr(self._serial, 'readAll'):
                return bytes(self._serial.readAll())
            if hasattr(self._serial, 'read_all'):
                return self._serial.read_all()
        except Exception as e:
            self.error_occurred.emit("读取失败: " + str(e))
        return b""

    # ---- readyRead 信号处理 ----

    def _on_ready_read(self):
        """串口硬件中断 → 读取数据
        正常模式: emit data_received 信号通知 UI
        旁路模式: 数据存入 _sync_buf，供同步指令等待读取
        """
        data = self.readAll()
        if not data:
            return
        self._last_uplink_time = time.time()
        if self._bypass_readyread:
            self._sync_buf.extend(data)
        else:
            self.data_received.emit(data)

    # ---- 上行时间戳 ----

    def update_uplink_time(self):
        self._last_uplink_time = time.time()

    @property
    def last_uplink_time(self):
        return self._last_uplink_time

    # ---- 上行超时监视器 ----

    def enable_uplink_watchdog(self, timeout_sec=3.0):
        if self._uplink_watchdog is None:
            self._uplink_watchdog = QTimer(self)
            self._uplink_watchdog.timeout.connect(self._check_uplink_timeout)
        self._uplink_watchdog_interval = timeout_sec
        self._uplink_watchdog.start(int(timeout_sec * 1000))

    def disable_uplink_watchdog(self):
        if self._uplink_watchdog:
            self._uplink_watchdog.stop()

    def _check_uplink_timeout(self):
        if self._last_uplink_time > 0 and time.time() - self._last_uplink_time > self._uplink_watchdog_interval:
            self.heartbeat_timeout.emit()

    # ---- 心跳 ----

    @property
    def heartbeat_active(self):
        return self._heartbeat.is_active

    def set_heartbeat_max_miss(self, count):
        self._heartbeat.max_miss = count

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

    def _on_heartbeat_tick(self):
        if not self.is_connected:
            self._heartbeat.notify_miss()
            return
        cmd = self._config.heartbeat_cmd
        if not cmd:
            return
        try:
            self._serial.write(cmd)
            if hasattr(self._serial, 'flush'):
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
# MockSerial — QSerialPort 兼容的纯软件模拟串口
# ============================================================
class MockSerial(QObject):
    readyRead = Signal()

    def __init__(self, config):
        super().__init__()
        self.is_open = True
        self.port = config.port if config and config.port else "MOCK"
        self._in_buf = bytearray()
        self._out_buf = bytearray()
        self._responses = {}
        self._uplink_callback = None
        self._uplink_frame = None

    def bytesAvailable(self):
        return len(self._out_buf)

    def isOpen(self):
        return self.is_open

    def portName(self):
        return self.port

    def write(self, data):
        self._in_buf.extend(data)
        n = len(data)
        self._process_write()
        return n

    def flush(self):
        pass

    def _process_write(self):
        """写入后立即处理，模拟硬件响应"""
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
        if len(self._out_buf) > 0:
            self.readyRead.emit()

    def readAll(self):
        data = bytes(self._out_buf)
        self._out_buf.clear()
        return data

    def read(self, size=1):
        if len(self._out_buf) == 0:
            return b""
        n = min(size, len(self._out_buf))
        data = bytes(self._out_buf[:n])
        self._out_buf = self._out_buf[n:]
        return data

    def readline(self):
        idx = self._out_buf.find(b"\n")
        if idx < 0:
            return b""
        line = bytes(self._out_buf[:idx + 1])
        self._out_buf = self._out_buf[idx + 1:]
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

    def close(self):
        self.is_open = False
        self._in_buf.clear()
        self._out_buf.clear()

    def waitForBytesWritten(self, msecs):
        """Mock: 无传输延迟，始终返回 True"""
        return True

    def waitForReadyRead(self, msecs):
        """Mock: write() 内已同步处理响应并存入 _sync_buf，
        此处直接返回 True 表示'数据已就绪'"""
        return True

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
    print("  模块加载正常 — QSerialPort + readyRead 信号驱动")
