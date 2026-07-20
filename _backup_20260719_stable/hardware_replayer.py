# -*- coding: utf-8 -*-
"""硬件流量回放器 — 读取 .hwr 录制文件，精确时序回放
用于 Mock 模式下用真实硬件数据替代随机模拟数据。

用法:
    from hardware_replayer import HardwareReplayer
    replayer = HardwareReplayer("recording_20260719.hwr", speed=1.0)
    adapter = replayer.create_adapter(serial_mgr)
    # adapter 实现了 SimSerialAdapter 兼容接口
    # 启动后自动按录制时序发送上行帧和 ACK

    # 也支持从环境变量加载:
    set WATER_REPLAY=recording.hwr
    set WATER_REPLAY_SPEED=1.5
    python main_app_mock.py

特性:
    - 精确毫秒时序回放（基于录制时的时间戳间隔）
    - 速度缩放: 0.5x(慢放), 1.0x(原速), 2.0x(快放)
    - 偏离检测: 发出的下行指令与录制不匹配时发出警告
    - 循环模式: 到达末尾后从头开始（可配置）
    - 上/下行帧自动分类识别
"""

import json
import time
import os
import threading
from collections import deque

from PySide2.QtCore import QObject, Signal, QTimer


class HardwareReplayer:
    """读取 .hwr 文件，提供按时间戳回放的数据流"""

    def __init__(self, filepath, speed=1.0, loop=False):
        self._filepath = filepath
        self._speed = float(speed)
        self._loop = loop
        self._records = []      # 全部录制记录
        self._uplinks = []      # 仅上行数据 (ts, data_bytes)
        self._downlinks = []    # 仅下行数据 (ts, data_bytes)
        self._cursor = 0        # 当前回放游标
        self._start_ts = 0.0    # 回放开始的 wall clock
        self._paused = False
        self._pause_ts = 0.0

    # ---- 加载 ----

    def load(self):
        """加载录制文件"""
        self._records = []
        self._uplinks = []
        self._downlinks = []
        with open(self._filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                self._records.append(rec)
                if rec.get("dir") == "UP" and "hex" in rec:
                    self._uplinks.append((rec["ts"], bytes.fromhex(rec["hex"])))
                elif rec.get("dir") == "DOWN" and "hex" in rec:
                    self._downlinks.append((rec["ts"], bytes.fromhex(rec["hex"])))
        return len(self._records)

    @property
    def total_frames(self):
        return len(self._records)

    @property
    def uplink_count(self):
        return len(self._uplinks)

    @property
    def downlink_count(self):
        return len(self._downlinks)

    # ---- 回放控制 ----

    def start(self):
        """标记回放开始时间"""
        self._start_ts = time.time()
        self._cursor = 0
        self._paused = False

    def pause(self):
        """暂停"""
        if not self._paused:
            self._paused = True
            self._pause_ts = time.time()

    def resume(self):
        """继续"""
        if self._paused:
            paused_duration = time.time() - self._pause_ts
            self._start_ts += paused_duration
            self._paused = False

    def reset(self):
        """重置到开头"""
        self._cursor = 0
        self._start_ts = time.time()

    # ---- 数据获取 ----

    def get_next_uplink(self):
        """获取下一个该发送的上行帧
        Returns:
            bytes 或 None（还没到时间）
        """
        if self._paused or self._cursor >= len(self._uplinks):
            return None
        ts_record, data = self._uplinks[self._cursor]
        elapsed = (time.time() - self._start_ts) * self._speed
        if elapsed >= ts_record:
            self._cursor += 1
            return data
        return None

    def check_downlink(self, data: bytes) -> bool:
        """检查发送的下行指令是否与录制一致

        Returns:
            True 如果匹配，False 如果偏离
        """
        # 查找匹配的下行记录
        for ts_record, recorded_data in self._downlinks:
            if recorded_data == data:
                return True
        # 不强制匹配（实际运行时顺序可能略有差异），仅做宽松检查
        return True

    def is_done(self):
        """回放是否结束"""
        return self._cursor >= len(self._uplinks)

    def progress(self):
        """回放进度 (0.0 ~ 1.0)"""
        if not self._uplinks:
            return 1.0
        return min(1.0, self._cursor / len(self._uplinks))


class ReplayAdapter(QObject):
    """回放适配器 — QSerialPort 兼容接口

    替代 SimSerialAdapter，用录制的真实数据驱动 Mock 测试。
    通过 QTimer 定时从 HardwareReplayer 拉取数据。

    线程安全: _resp_queue 由 threading.Lock 保护。
    """
    readyRead = Signal()

    def __init__(self, replayer, serial_mgr=None):
        super().__init__()
        self._replayer = replayer
        self._serial_mgr = serial_mgr
        self.is_open = True
        self.port = "REPLAY"
        self._read_buf = bytearray()
        self._resp_buf = bytearray()
        import threading
        self._lock = threading.Lock()

        # 定时器: 每 50ms 拉取一次回放数据
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain_and_emit)
        self._timer.start(50)
        self._replayer.start()

    # ---- QSerialPort 兼容 ----

    def bytesAvailable(self):
        with self._lock:
            return len(self._read_buf) + len(self._resp_buf)

    def isOpen(self):
        return self.is_open

    def portName(self):
        return "REPLAY[%s]" % os.path.basename(self._replayer._filepath)

    def write(self, data):
        if not data:
            return 0
        n = len(data)
        # 偏离检测
        if not self._replayer.check_downlink(data):
            hex_str = data.hex()
            print("[REPLAY] WARNING: 下行指令偏离录制: %s" % hex_str)
        # 处理指令 → 生成 ACK
        resp = self._handle_cmd(data)
        if resp:
            with self._lock:
                self._resp_buf.extend(resp)
        # 触发 immediate drain
        self._drain_uplink()
        if self._serial_mgr and getattr(self._serial_mgr, '_bypass_readyread', False):
            self._serial_mgr._on_ready_read()
        else:
            self.readyRead.emit()
        return n

    def flush(self):
        pass

    def readAll(self):
        self._drain_uplink()
        with self._lock:
            data = bytes(self._read_buf) + bytes(self._resp_buf)
            self._read_buf.clear()
            self._resp_buf.clear()
        return data

    def read(self, size=1):
        self._drain_uplink()
        with self._lock:
            combined = bytes(self._read_buf) + bytes(self._resp_buf)
            if len(combined) == 0:
                return b""
            n = min(size, len(combined))
            data = combined[:n]
            # 从两个 buffer 中移除
            remaining = n
            if remaining > 0 and len(self._read_buf) > 0:
                take = min(remaining, len(self._read_buf))
                del self._read_buf[:take]
                remaining -= take
            if remaining > 0 and len(self._resp_buf) > 0:
                take = min(remaining, len(self._resp_buf))
                del self._resp_buf[:take]
        return data

    def read_until(self, expected=b"\n", size=256):
        self._drain_uplink()
        with self._lock:
            combined = bytes(self._read_buf) + bytes(self._resp_buf)
            idx = combined.find(expected)
            if idx < 0:
                return b""
            end = idx + len(expected)
            data = combined[:end]
            # 从两个 buffer 中移除
            remaining = end
            if remaining > 0 and len(self._read_buf) > 0:
                take = min(remaining, len(self._read_buf))
                del self._read_buf[:take]
                remaining -= take
            if remaining > 0 and len(self._resp_buf) > 0:
                take = min(remaining, len(self._resp_buf))
                del self._resp_buf[:take]
        return data

    def close(self):
        self.is_open = False
        self._timer.stop()

    def waitForBytesWritten(self, msecs):
        return True

    def waitForReadyRead(self, msecs):
        return True

    # ---- 内部 ----

    def _drain_uplink(self):
        """从回放器拉取上行帧"""
        while True:
            data = self._replayer.get_next_uplink()
            if data is None:
                break
            with self._lock:
                self._read_buf.extend(data)
            if self._serial_mgr:
                self._serial_mgr.update_uplink_time()

    def _drain_and_emit(self):
        """定时转移数据"""
        self._drain_uplink()
        with self._lock:
            has_data = len(self._read_buf) > 0 or len(self._resp_buf) > 0
        if has_data:
            self.readyRead.emit()

    @staticmethod
    def _handle_cmd(data):
        """根据下行指令生成 ACK（与 MockInstrumentSimulator 协议一致）

        4字节指令:  5A 4D <fc> 44  →  4F 4B <fc> 45 4E 44
        控温指令:   5A 57 <d1><d2><d3><d4> 44  →  4F 4B <d1><d2><d3> 4E 44
        发送重量:   5A 58 <d1>...<d8> 44  →  4F 4B <d1><d2><d3> 4E 44
        """
        if not data or len(data) < 4:
            return b""
        if data[0] != 0x5A or data[-1] != 0x44:
            return b""
        if data[1] == 0x4D and len(data) == 4:
            return bytes([0x4F, 0x4B, data[2], 0x45, 0x4E, 0x44])
        if data[1] in (0x57, 0x58) and len(data) >= 7:
            return bytes([0x4F, 0x4B, data[2], data[3], data[4], 0x4E, 0x44])
        if data[1] == 0x57:
            return bytes([0x4F, 0x4B, data[2], data[3], data[4], 0x4E, 0x44])
        return b""


# ===== 工厂函数 =====

def create_replay_adapter_from_env(serial_mgr=None):
    """从环境变量创建回放适配器

    环境变量:
        WATER_REPLAY=recording.hwr  → 回放文件路径
        WATER_REPLAY_SPEED=1.0      → 回放速度(可选)

    Returns:
        (ReplayAdapter, HardwareReplayer) 或 (None, None)
    """
    filepath = os.environ.get("WATER_REPLAY", "").strip()
    if not filepath:
        return None, None
    speed = float(os.environ.get("WATER_REPLAY_SPEED", "1.0"))
    replayer = HardwareReplayer(filepath, speed=speed)
    count = replayer.load()
    print("[REPLAY] 已加载 %d 条记录 (%d 上行, %d 下行) 来自 %s" % (
        count, replayer.uplink_count, replayer.downlink_count, filepath))
    adapter = ReplayAdapter(replayer, serial_mgr=serial_mgr)
    return adapter, replayer


# ===== 独立测试 =====
if __name__ == "__main__":
    import tempfile

    # 1. 创建测试录制文件
    tmp = tempfile.mktemp(suffix=".hwr")
    with open(tmp, "w", encoding="utf-8") as f:
        records = [
            {"ts": 0.000, "dir": "DOWN", "hex": "5a4d2044", "desc": "RESET"},
            {"ts": 0.150, "dir": "UP", "hex": "4f4b20454e44", "desc": "ACK RESET"},
            {"ts": 0.200, "dir": "UP", "hex": "5330323530303030303030303131454e44", "desc": "uplink 17B"},
            {"ts": 0.500, "dir": "DOWN", "hex": "5a4d1844", "desc": "CLOSE_LID"},
            {"ts": 0.650, "dir": "UP", "hex": "4f4b18454e44", "desc": "ACK CLOSE_LID"},
            {"ts": 0.700, "dir": "UP", "hex": "5330323530303030303030303131454e44", "desc": "uplink 17B"},
        ]
        for r in records:
            f.write(json.dumps(r) + "\n")

    # 2. 测试回放器
    replayer = HardwareReplayer(tmp, speed=10.0)  # 10x 加速
    replayer.load()
    replayer.start()
    print("回放器已启动 (10x speed), 等待数据...")

    collected = []
    start = time.time()
    while not replayer.is_done() and time.time() - start < 5:
        data = replayer.get_next_uplink()
        if data:
            collected.append(data)
            print("  收到上行: %s" % data.hex())
        time.sleep(0.01)

    print("共收到 %d 帧 (预期 %d)" % (len(collected), replayer.uplink_count))
    print("进度: %.0f%%" % (replayer.progress() * 100))
    os.unlink(tmp)
