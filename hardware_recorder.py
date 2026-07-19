# -*- coding: utf-8 -*-
"""硬件流量录制器 — 透明记录串口双向通讯
在正式版运行时无侵入记录所有串口流量，保存为结构化 JSON Lines 文件。

用法:
    # 环境变量启用:
    set WATER_RECORD=recording_20260719.hwr
    python main_app.py

    # 或代码中启用:
    from hardware_recorder import HardwareRecorder
    rec = HardwareRecorder("recording.hwr")
    serial_mgr.set_recorder(rec)  # 开始录制
    serial_mgr.set_recorder(None) # 停止录制

录制格式 (JSON Lines):
    {"ts": 0.000, "dir": "DOWN", "hex": "5a4d2044", "desc": "RESET", "len": 4}
    {"ts": 0.152, "dir": "UP",   "hex": "4f4b20454e44", "desc": "ACK RESET", "len": 6}
    {"ts": 0.253, "dir": "UP",   "hex": "53303235...", "desc": "uplink frame 17B", "len": 17}
    {"ts": 3.141, "tag": "EVENT", "desc": "关盖倒计时开始 15s"}

特性:
    - 零侵入: SerialManager._recorder 为 None 时无任何开销
    - 自动 flush: 每 10 条记录 flush 一次，防数据丢失
    - 标签事件: 支持录制自定义事件（如"倒计时开始"）
    - 时间戳: 相对开始时间的秒数，精确到毫秒
"""

import json
import time
import os


class HardwareRecorder:
    """串口流量录制器"""

    def __init__(self, filepath):
        self._filepath = filepath
        self._file = None
        self._start_time = 0.0
        self._record_count = 0
        self._flush_interval = 10

    # ---- 生命周期 ----

    def start(self):
        """开始录制"""
        if self._file is not None:
            return
        self._file = open(self._filepath, "w", encoding="utf-8")
        self._start_time = time.time()
        self._record_count = 0
        self._write_meta()

    def stop(self):
        """停止录制并关闭文件"""
        if self._file is None:
            return
        self._record_count += 1
        self._write_line({
            "ts": round(time.time() - self._start_time, 3),
            "tag": "META",
            "action": "stop",
            "total_records": self._record_count,
        })
        self._file.close()
        self._file = None

    @property
    def is_recording(self):
        return self._file is not None

    @property
    def filepath(self):
        return self._filepath

    # ---- 录制接口 ----

    def record_downlink(self, data: bytes, desc: str = ""):
        """录制下行指令（PC → 仪器）"""
        if self._file is None:
            return
        self._record_count += 1
        self._write_line({
            "ts": round(time.time() - self._start_time, 3),
            "dir": "DOWN",
            "hex": data.hex(),
            "len": len(data),
            "desc": desc,
        })

    def record_uplink(self, data: bytes, desc: str = ""):
        """录制上行数据（仪器 → PC）"""
        if self._file is None:
            return
        self._record_count += 1
        self._write_line({
            "ts": round(time.time() - self._start_time, 3),
            "dir": "UP",
            "hex": data.hex(),
            "len": len(data),
            "desc": desc or self._classify_uplink(data),
        })

    def record_event(self, desc: str):
        """录制自定义事件（如状态变化、倒计时等）"""
        if self._file is None:
            return
        self._record_count += 1
        self._write_line({
            "ts": round(time.time() - self._start_time, 3),
            "tag": "EVENT",
            "desc": desc,
        })

    # ---- 内部方法 ----

    def _write_meta(self):
        """写入录制文件元信息"""
        self._write_line({
            "ts": 0.0,
            "tag": "META",
            "action": "start",
            "version": "1.0",
            "start_time_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    def _write_line(self, obj: dict):
        """写入一行 JSON"""
        self._file.write(json.dumps(obj, ensure_ascii=False) + "\n")
        if self._record_count % self._flush_interval == 0:
            self._file.flush()

    @staticmethod
    def _classify_uplink(data: bytes) -> str:
        """自动分类上行数据"""
        if not data:
            return "empty"
        # 上行帧: SxxxxyyyyyyyabEND (17字节 ASCII)
        if len(data) == 17 and data[0:1] == b"S":
            return "uplink frame 17B"
        # ACK 响应: OK<fc>END 或 OK<d1><d2><d3>END
        if data[:2] == b"OK":
            return "ACK " + data.hex()
        return "unknown"


# ===== 工厂函数 =====

def create_recorder_from_env():
    """从环境变量 WATER_RECORD 创建录制器

    Returns:
        HardwareRecorder 或 None（未设置环境变量时）
    """
    filepath = os.environ.get("WATER_RECORD", "").strip()
    if not filepath:
        return None
    rec = HardwareRecorder(filepath)
    rec.start()
    print("[RECORDER] 录制已启动 → %s" % os.path.abspath(filepath))
    return rec


# ===== 独立测试 =====
if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mktemp(suffix=".hwr")
    rec = HardwareRecorder(tmp)
    rec.start()
    print("录制中: %s" % tmp)

    rec.record_uplink(b"S02500000000011END", "上行帧")
    rec.record_downlink(b"\x5a\x4d\x20\x44", "RESET")
    rec.record_uplink(b"OK\x20\x45\x4e\x44", "ACK RESET")
    rec.record_event("关盖倒计时开始 15s")
    rec.record_downlink(b"\x5a\x4d\x18\x44", "CLOSE_LID")

    rec.stop()
    print("录制完成，共 %d 条记录" % rec._record_count)

    # 打印录制内容
    with open(tmp, "r", encoding="utf-8") as f:
        for line in f:
            print("  " + line.strip())
    os.unlink(tmp)
