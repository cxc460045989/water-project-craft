# -*- coding: utf-8 -*-
"""协议解析与指令封装层 — 水分测定仪串口通讯协议
依赖: serial_comm.py（SerialManager）
框架: PySide2 (Qt5) — 兼容 Windows 7 / 麒麟Linux x86/ARM64

设计原则:
  - 只负责协议解析与指令组包，不参与业务逻辑
  - 上行解析独立无状态，下行指令纯函数构造
  - 粘包/半包由 UplinkBuffer 状态机处理
  - 异步 CmdSender: readyRead 驱动，QTimer 超时检测，消除 time.sleep() 阻塞
  - 兼容层: 旧 send_cmd_with_uplink_check() 同步函数保留用于逐步迁移

用法:
    from protocol_layer import (CommandBuilder, FrameParser, UplinkBuffer,
                                 send_cmd_with_uplink_check, CmdSender)
    cmd = CommandBuilder.build_command(CommandBuilder.CMD_TARE)
    parsed = FrameParser.parse_uplink(b"S0850301001701END")

注意: 握手指令(HANDSHAKE)已废弃，不得在新代码中使用。
"""

import time
from PySide2.QtCore import QObject, Signal, QTimer
from logging_util import logger


# ============================================================
# 功能码常量（对应协议文档 4.2 固定4字节指令全集）
# ============================================================
class CMD:
    """指令功能码常量 — 5A 4D <func_code> 44"""
    HANDSHAKE = 0x01          # 握手 [已废弃]
    BEEPER_1S = 0x07          # 蜂鸣器响1秒
    SAMPLE_PLATE_ROTATE = 0x13
    SAMPLE_PLATE_UP = 0x14
    SAMPLE_PLATE_DOWN = 0x15
    TARE = 0x16
    CALIBRATE = 0x17
    CLOSE_LID = 0x18
    OPEN_LID = 0x19
    ENTER_WEIGH_MODE = 0x12
    EXIT_WEIGH_MODE = 0x11
    ALL_OFF = 0x10
    HEAT_OFF = 0x1B
    FAN_ON = 0x1C
    FAN_OFF = 0x1D
    N2_ON = 0x1E
    N2_OFF = 0x1F
    RESET = 0x20
    BEEPER_ON = 0x21
    BEEPER_OFF = 0x22
    SAMPLE_PLATE_STEP = 0x29
    SAMPLE_PLATE_HOME = 0x30
    GAS_ALL_OFF = 0x32
    MOISTURE_TEST_1 = 0x33
    MOISTURE_TEST_2 = 0x34
    O2_ON = 0x0E
    O2_OFF = 0x0F


# ============================================================
# CommandBuilder — 下行指令组包（纯函数）
# ============================================================
class CommandBuilder:
    FRAME_HEAD = 0x5A
    FRAME_TAIL = 0x44

    @staticmethod
    def build_command(func_code: int) -> bytes:
        return bytes([CommandBuilder.FRAME_HEAD, 0x4D, func_code, CommandBuilder.FRAME_TAIL])

    @staticmethod
    def build_move_to(position: int) -> bytes:
        if not (1 <= position <= 99):
            raise ValueError("样位号范围 1~99")
        param = 0x34 + position
        return bytes([CommandBuilder.FRAME_HEAD, 0x4D, param, CommandBuilder.FRAME_TAIL])

    @staticmethod
    def build_temp_control(temp_c: int) -> bytes:
        if not (0 <= temp_c <= 9999):
            raise ValueError("温度范围 0~9999C")
        s = f"{temp_c:04d}"
        params = bytes(int(ch) for ch in s)
        return bytes([CommandBuilder.FRAME_HEAD, 0x57]) + params + bytes([CommandBuilder.FRAME_TAIL])

    @staticmethod
    def build_send_weight(weight_g: float) -> bytes:
        mid = int(round(weight_g * 10000)) + 1000000
        if not (0 <= mid <= 99999999):
            raise ValueError("计算结果超出8位十进制范围")
        s = f"{mid:08d}"
        params = bytes(int(ch) for ch in s)
        return bytes([CommandBuilder.FRAME_HEAD, 0x58]) + params + bytes([CommandBuilder.FRAME_TAIL])


# ============================================================
# FrameParser — 上行帧解析
# ============================================================
class FrameParser:
    FRAME_LEN = 17
    END_MARKER = b"END"

    @staticmethod
    def parse_uplink(raw: bytes):
        if not raw or len(raw) != FrameParser.FRAME_LEN:
            return None
        try:
            s = raw.decode("ascii", errors="strict")
        except (UnicodeDecodeError, ValueError):
            return None
        if len(s) != FrameParser.FRAME_LEN or s[0] != "S":
            return None
        if s[-3:] != "END":
            return None
        temp_str = s[1:5]
        weight_str = s[5:12]
        online_str = s[12:13]
        btn_str = s[13:14]
        if not (temp_str.isdigit() and weight_str.isdigit()
                and online_str.isdigit() and btn_str.isdigit()):
            return None
        temperature = int(temp_str) / 10.0
        weight_raw = int(weight_str)
        weight = (weight_raw - 3000000) / 10000.0
        online = int(online_str)
        btn_pressed = int(btn_str)
        return {
            "temperature": temperature,
            "weight": weight,
            "online": online,
            "btn_pressed": btn_pressed,
            "raw_str": s,
        }


# ============================================================
# UplinkBuffer — 粘包/半包处理器
# ============================================================
class UplinkBuffer:
    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes):
        if not data:
            return []
        self._buffer.extend(data)
        frames = []
        while True:
            end_idx = self._buffer.find(b"END")
            if end_idx < 0:
                if len(self._buffer) > 64:
                    self._buffer.clear()
                break
            potential_end = end_idx + 3
            if potential_end < FrameParser.FRAME_LEN:
                # "END" 标记出现在非上行帧数据中 (如 ACK 响应 "OK3END")
                # 跳过这段假标记, 继续搜索真正的上行帧
                self._buffer = self._buffer[potential_end:]
                continue
            candidate = bytes(self._buffer[:FrameParser.FRAME_LEN])
            parsed = FrameParser.parse_uplink(candidate)
            if parsed is not None:
                frames.append(parsed)
                self._buffer = self._buffer[FrameParser.FRAME_LEN:]
            else:
                self._buffer.pop(0)
        return frames

    def clear(self):
        self._buffer.clear()

    @property
    def pending_bytes(self):
        return len(self._buffer)


# ============================================================
# CmdSender — 异步指令发送器（QTimer 超时 + readyRead 驱动）
# ============================================================
class CmdSender(QObject):
    """异步指令发送器 — 替代 send_cmd_with_uplink_check 的阻塞行为

    用法:
        sender = CmdSender(serial_mgr, cmd_bytes, "控温 105C")
        sender.sig_temp.connect(lambda t: ui.update_temp(t))
        sender.sig_done.connect(lambda ok: handle_result(ok))
        sender.start()
    """
    sig_done = Signal(bool)
    sig_temp = Signal(float)

    RESP_TIMEOUT_MS = 200
    TOTAL_TIMEOUT_MS = 60000  # 总超时: 1分钟

    def __init__(self, serial_mgr, cmd_bytes, desc="", parent=None):
        super().__init__(parent)
        self._serial = serial_mgr
        self._cmd_bytes = cmd_bytes
        self._desc = desc
        self._start_time = 0.0
        self._started = False
        self._first_send = True
        self._uplink_buf = UplinkBuffer()

    def start(self):
        import time as _time
        if self._started:
            return
        self._started = True
        self._start_time = _time.time()
        self._first_send = True
        self._drain_and_send()

    def _drain_and_send(self):
        """非阻塞排空旧数据后发送指令"""
        # 排空: readAll 非阻塞读取已有的上行帧
        try:
            stale = self._serial.readAll()
        except Exception:
            stale = b""
        if stale:
            # 转发温度（如果有消费方连接了 sig_temp）
            frames = self._uplink_buf.feed(stale)
            for f in frames:
                try:
                    self.sig_temp.emit(f["temperature"])
                except Exception:
                    pass
        self._do_send()

    def _do_send(self):
        """发送指令 + 启动 200ms 超时定时器"""
        n = 0
        try:
            n = self._serial.send(self._cmd_bytes)
        except Exception:
            pass
        if n == 0 and self._first_send:
            logger.warning("[CmdSender] 发送失败: %s" % self._desc)
        if self._first_send:
            logger.info("[CmdSender] 已发送: %s | %s" % (self._desc, self._cmd_bytes.hex()))
            self._first_send = False

        # 连接 readyRead 等待响应
        if hasattr(self._serial, 'data_received'):
            try:
                self._serial.data_received.connect(self._on_data)
            except Exception:
                pass

        # 200ms 超时
        QTimer.singleShot(self.RESP_TIMEOUT_MS, self._on_timeout)

    def _on_data(self, data):
        """收到串口数据 → 解析 → 转发温度 → 判定完成"""
        if not data:
            return
        frames = self._uplink_buf.feed(data)
        if not frames:
            return
        self._serial.update_uplink_time()
        for f in frames:
            try:
                self.sig_temp.emit(f["temperature"])
            except Exception:
                pass
        # 收到至少一帧有效数据 → 成功
        self._cleanup()
        logger.info("[CmdSender] 发送成功: %s" % self._desc)
        self.sig_done.emit(True)

    def _on_timeout(self):
        """200ms 超时: 检查 bytesAvailable → 重试或60s总超时"""
        try:
            avail = self._serial.bytesAvailable
        except Exception:
            avail = 0
        if avail > 0:
            raw = self._serial.readAll()
            if raw:
                self._on_data(raw)
                return

        import time as _time
        if _time.time() - self._start_time > self.TOTAL_TIMEOUT_MS / 1000.0:
            self._cleanup()
            logger.warning("[CmdSender] 发送超时(60s无响应): %s" % self._desc)
            self.sig_done.emit(False)
        else:
            self._do_send()

    def _cleanup(self):
        if hasattr(self._serial, 'data_received'):
            try:
                self._serial.data_received.disconnect(self._on_data)
            except Exception:
                pass


# ============================================================
# send_cmd_with_uplink_check — 兼容层（同步函数，逐步过渡期使用）
# ============================================================
def _build_expected_response(cmd_bytes):
    """根据下行指令构建预期应答
    4字节指令: 5A 4D <fc> 44  →  4F 4B <fc> 45 4E 44
    固定4字节: 5A 4D <fc> 44  →  4F 4B <fc> 45 4E 44
    控温指令:  5A 57 <d1> <d2> <d3> <d4> 44  →  4F 4B <d1> <d2> <d3> 4E 44
    发送重量:  5A 58 <d1>...<d8> 44  →  4F 4B <d1> <d2> <d3> 4E 44
    无法识别:  返回 None，不做校验
    """
    if len(cmd_bytes) < 4 or cmd_bytes[0] != 0x5A or cmd_bytes[-1] != 0x44:
        return None
    if cmd_bytes[1] == 0x4D and len(cmd_bytes) == 4:
        return bytes([0x4F, 0x4B, cmd_bytes[2], 0x45, 0x4E, 0x44])
    if cmd_bytes[1] in (0x57, 0x58) and len(cmd_bytes) >= 6:
        return bytes([0x4F, 0x4B, cmd_bytes[2], cmd_bytes[3], cmd_bytes[4], 0x45, 0x4E, 0x44])
    return None


def send_cmd_with_uplink_check(serial_mgr, cmd_bytes, desc="", temp_callback=None):
    """发指令 → 等仪器上行帧响应，持续重试直至成功或60秒超时

    核心前提: 发送指令前必须先收到新的上行帧，确认仪器处于空闲态。
    仪器在执行机械动作（移动样盘、开关炉盖等）期间不发送上行帧，
    此时发指令必然失败。

    流程:
      1. 清空 _sync_buf
      2. 等待仪器发来新的上行帧（确认空闲）
      3. 收到上行帧
      4. TARE 指令额外延时 1s（天平稳定）
      5. 发送指令
      6. 200ms 内等待 ACK 匹配
      7. 超时无 ACK → 回到步骤 1 重试
      8. 总超时 60s

    参数:
        serial_mgr: SerialManager 实例
        cmd_bytes:  要发送的指令字节
        desc:       指令描述（用于日志）
        temp_callback: 可选, callable(temperature_float)
    """
    import time as _time
    import threading as _threading
    from PySide2.QtWidgets import QApplication as _QApp

    # 判断当前是否在主线程（主线程才需要 processEvents 让 Mock 上行帧生成）
    _is_main_thread = (_threading.current_thread() is _threading.main_thread())

    def _poll_sleep(seconds):
        """线程安全的睡眠: 主线程用 processEvents 保持事件循环，
        工作线程用纯 time.sleep（不能跨线程调 processEvents）"""
        if _is_main_thread:
            deadline = _time.time() + seconds
            while _time.time() < deadline:
                _QApp.processEvents()
                remaining = deadline - _time.time()
                if remaining > 0:
                    _time.sleep(min(0.01, remaining))
        else:
            _time.sleep(seconds)

    TOTAL_TIMEOUT_S = 60.0      # 总超时: 1分钟
    RESP_TIMEOUT_S = 0.2        # 发指令后等待 ACK 的超时: 200ms
    POLL_INTERVAL_S = 0.05      # 轮询间隔: 50ms
    overall_start = _time.time()
    attempt = 0

    serial_mgr._enter_bypass()
    try:
        while True:
            # 检查总超时
            if _time.time() - overall_start > TOTAL_TIMEOUT_S:
                logger.warning("[CMD] 发送超时(60s无响应): %s (共%d次尝试)" % (desc, attempt))
                return False

            # ===== 步骤 1: 清空旧缓冲区 =====
            buf_before = len(serial_mgr._sync_buf)
            serial_mgr._sync_buf.clear()
            if buf_before > 0:
                logger.info("[CMD] %s 清除上行帧缓存(%d字节)" % (desc, buf_before))

            # ===== 步骤 2: 等待仪器上行帧，确认空闲 =====
            uplink_wait_start = _time.time()
            uplink_received = False
            while True:
                if _time.time() - overall_start > TOTAL_TIMEOUT_S:
                    logger.warning("[CMD] 发送超时(60s无响应): %s (共%d次尝试)" % (desc, attempt))
                    return False

                if len(serial_mgr._sync_buf) > 0:
                    # 收到数据，确认是否为有效上行帧
                    raw = bytes(serial_mgr._sync_buf)
                    ub = UplinkBuffer()
                    frames = ub.feed(raw)
                    if frames:
                        # 有效上行帧 → 仪器空闲，可以发指令
                        uplink_received = True
                        f = frames[-1]
                        logger.info("[CMD] %s 检测到上行帧 temp=%.1f weight=%.4f (等待%.2fs)" %
                                    (desc, f["temperature"], f["weight"],
                                     _time.time() - uplink_wait_start))
                        break
                    # 有数据但不是有效上行帧（可能是上一次指令残留的 ACK），丢弃
                    logger.info("[CMD] %s 丢弃非上行帧数据(%d字节): %s" %
                                (desc, len(raw), raw.hex()))
                    serial_mgr._sync_buf.clear()

                _poll_sleep(POLL_INTERVAL_S)

            # ===== 步骤 3: 发送前特定指令延时 =====
            _TARE_CMD = b'\x5a\x4d\x16\x44'
            if cmd_bytes == _TARE_CMD:
                logger.info("[CMD] %s 延时1.0s等待天平稳定..." % desc)
                _poll_sleep(1.0)

            # ===== 步骤 4: 发送指令 =====
            n = serial_mgr.send(cmd_bytes)
            if n == 0:
                logger.warning("[CMD] %s 发送失败，将重试" % desc)
                attempt += 1
                continue

            if attempt == 0:
                logger.info("[CMD] >>> %s | %s" % (desc, cmd_bytes.hex()))
            else:
                logger.info("[CMD] >>> %s 重试(%d) | %s" % (desc, attempt, cmd_bytes.hex()))
            attempt += 1
            send_time = _time.time()

            # ===== 步骤 5: 200ms 内等待 ACK =====
            while True:
                if _time.time() - overall_start > TOTAL_TIMEOUT_S:
                    logger.warning("[CMD] 发送超时(60s无响应): %s (共%d次尝试)" % (desc, attempt))
                    return False

                if len(serial_mgr._sync_buf) > 0:
                    raw = bytes(serial_mgr._sync_buf)
                    expected = _build_expected_response(cmd_bytes)
                    if expected is not None:
                        idx = raw.find(expected)
                        if idx >= 0:
                            consumed = idx + len(expected)
                            del serial_mgr._sync_buf[:consumed]
                            serial_mgr.update_uplink_time()
                            logger.info("[CMD] %s -> %s (耗时%.1fs)" %
                                        (desc, expected.hex(), _time.time() - send_time))
                            return True
                        # 有数据但不含 ACK，不清缓冲区，继续等
                    else:
                        serial_mgr._sync_buf.clear()
                        serial_mgr.update_uplink_time()
                        logger.info("[CMD] %s -> %s (耗时%.1fs)" %
                                    (desc, raw.hex(), _time.time() - send_time))
                        return True

                # 200ms 无 ACK → 回到步骤 1 重新等上行帧再发
                if _time.time() - send_time > RESP_TIMEOUT_S:
                    break

                _poll_sleep(POLL_INTERVAL_S)
            # 200ms 无应答 → 回到外层循环
    finally:
        serial_mgr._leave_bypass()


# ============================================================
# handshake — [已废弃]
# ============================================================
def handshake(serial_mgr, retries=3, wait_ms=80, last_uplink_time=None, timeout=3.0):
    cmd = CommandBuilder.build_command(CMD.HANDSHAKE)
    return send_cmd_with_uplink_check(serial_mgr, cmd, desc="握手(兼容)")
