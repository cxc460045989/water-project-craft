# -*- coding: utf-8 -*-
"""协议解析与指令封装层 — 水分测定仪串口通讯协议
依赖: serial_comm.py（SerialManager）
框架: PySide2 (Qt5) — 兼容 Windows 7 / 麒麟Linux x86/ARM64

设计原则:
  - 只负责协议解析与指令组包，不参与业务逻辑
  - 上行解析独立无状态，下行指令纯函数构造
  - 粘包/半包由 UplinkBuffer 状态机处理
  - 指令发送统一走 send_cmd_with_uplink_check()，不上行检测通过即发，失败自动重试

用法:
    from protocol_layer import CommandBuilder, FrameParser, UplinkBuffer, send_cmd_with_uplink_check
    cmd = CommandBuilder.build_command(CommandBuilder.CMD_TARE)
    parsed = FrameParser.parse_uplink(b"S0850301001701END")

注意: 握手指令(HANDSHAKE)已废弃，不得在新代码中使用。
"""

import time
from logging_util import logger


# ============================================================
# 功能码常量（对应协议文档 4.2 固定4字节指令全集）
# ============================================================
class CMD:
    """指令功能码常量 — 5A 4D <func_code> 44"""
    HANDSHAKE = 0x01          # 握手 [已废弃 - 不得在新代码中使用]
    BEEPER_1S = 0x07          # 蜂鸣器响1秒
    SAMPLE_PLATE_ROTATE = 0x13   # 样盘不停转动
    SAMPLE_PLATE_UP = 0x14    # 样盘上升到高位
    SAMPLE_PLATE_DOWN = 0x15  # 样盘降到低位
    TARE = 0x16               # 天平清零（去皮）
    CALIBRATE = 0x17          # 天平校正
    CLOSE_LID = 0x18          # 关闭炉盖
    OPEN_LID = 0x19           # 打开炉盖
    ENTER_WEIGH_MODE = 0x12   # 进入仪器称量样重状态
    EXIT_WEIGH_MODE = 0x11    # 解除称重状态
    ALL_OFF = 0x10            # 关闭鼓风、氮气、加热
    HEAT_OFF = 0x1B           # 关闭加热
    FAN_ON = 0x1C             # 开鼓风
    FAN_OFF = 0x1D            # 关鼓风
    N2_ON = 0x1E              # 开氮气
    N2_OFF = 0x1F             # 关氮气
    RESET = 0x20              # 仪器复位
    BEEPER_ON = 0x21          # 开蜂鸣（持续）
    BEEPER_OFF = 0x22         # 关蜂鸣
    SAMPLE_PLATE_STEP = 0x29  # 样盘移动一位
    SAMPLE_PLATE_HOME = 0x30  # 样盘移动到1号位
    GAS_ALL_OFF = 0x32        # 关闭鼓风、氮气、氧气
    MOISTURE_TEST_1 = 0x33    # 水分开始测试（开鼓风）
    MOISTURE_TEST_2 = 0x34    # 水分开始测试（开氮气）
    O2_ON = 0x0E              # 开氧气
    O2_OFF = 0x0F             # 关氧气


# ============================================================
# CommandBuilder — 下行指令组包（纯函数）
# ============================================================
class CommandBuilder:
    """下行指令构造器 — 全部返回 bytes 对象"""

    FRAME_HEAD = 0x5A
    FRAME_TAIL = 0x44

    @staticmethod
    def build_command(func_code: int) -> bytes:
        """固定4字节指令: 5A 4D <func_code> 44"""
        return bytes([CommandBuilder.FRAME_HEAD, 0x4D, func_code, CommandBuilder.FRAME_TAIL])

    @staticmethod
    def build_move_to(position: int) -> bytes:
        """移动到指定样位: 5A 4D <0x34+position> 44"""
        if not (1 <= position <= 99):
            raise ValueError("样位号范围 1~99")
        param = 0x34 + position
        return bytes([CommandBuilder.FRAME_HEAD, 0x4D, param, CommandBuilder.FRAME_TAIL])

    @staticmethod
    def build_temp_control(temp_c: int) -> bytes:
        """控温指令: 5A 57 x1 x2 x3 x4 44
        temp_c: 目标温度（整数℃），转4位十进制逐位数值字节
        """
        if not (0 <= temp_c <= 9999):
            raise ValueError("温度范围 0~9999℃")
        s = f"{temp_c:04d}"
        params = bytes(int(ch) for ch in s)
        return bytes([CommandBuilder.FRAME_HEAD, 0x57]) + params + bytes([CommandBuilder.FRAME_TAIL])

    @staticmethod
    def build_send_weight(weight_g: float) -> bytes:
        """发送天平数据到仪器: 5A 58 x1~x8 44
        公式: 中间值 = weight_g * 10000 + 1000000 → 8位十进制 → 逐位数值字节
        """
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
    """上行数据帧解析（仪器→PC），纯静态方法"""

    FRAME_LEN = 17
    END_MARKER = b"END"

    @staticmethod
    def parse_uplink(raw: bytes):
        """解析单帧上行ASCII数据

        参数:
            raw: 原始字节（ASCII字符串编码）
        返回:
            dict | None — None 表示帧校验失败
            成功返回:
            {
                "temperature": 85.0,   # ℃
                "weight": 1.0017,       # g
                "online": 0,            # 0/1
                "btn_pressed": 1,       # 0/1
                "raw_str": "S0850301001701END"
            }
        """
        if not raw or len(raw) != FrameParser.FRAME_LEN:
            return None

        # decode
        try:
            s = raw.decode("ascii", errors="strict")
        except (UnicodeDecodeError, ValueError):
            return None

        # 起始校验
        if len(s) != FrameParser.FRAME_LEN or s[0] != "S":
            return None

        # 结束校验
        if s[-3:] != "END":
            return None

        # 提取字段
        temp_str = s[1:5]       # 炉膛温度 4位
        weight_str = s[5:12]    # 天平数据 7位
        online_str = s[12:13]   # 联机标志 1位
        btn_str = s[13:14]      # 仪器按键 1位

        # 数值校验
        if not (temp_str.isdigit() and weight_str.isdigit()
                and online_str.isdigit() and btn_str.isdigit()):
            return None

        # 数值换算
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
    """上行数据缓存处理器 — 处理粘包和半包

    用法:
        buf = UplinkBuffer()
        frames = buf.feed(data)  # 每次收到串口数据后调用
        for f in frames:
            # f 为 parse_uplink 返回的 dict
            process_frame(f)
    """

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes):
        """注入原始字节，返回已完成的帧列表"""
        if not data:
            return []
        self._buffer.extend(data)

        frames = []
        while True:
            # 找结束标志 END 的位置
            end_idx = self._buffer.find(b"END")
            if end_idx < 0:
                # 未找到 END，检查是否缓存超长（超过帧长仍无 END -> 丢弃，避免内存泄漏）
                if len(self._buffer) > 64:
                    self._buffer.clear()
                break

            # 可能的完整帧 = 从开头到 END+3
            potential_end = end_idx + 3
            if potential_end < FrameParser.FRAME_LEN:
                # 帧长度不够17，继续缓存等待
                break

            # 从开头取17字符尝试解析
            candidate = bytes(self._buffer[:FrameParser.FRAME_LEN])

            # 如果 candidate 以 END 结尾(第14-16位)
            parsed = FrameParser.parse_uplink(candidate)
            if parsed is not None:
                frames.append(parsed)
                # 移除已解析的17字节
                self._buffer = self._buffer[FrameParser.FRAME_LEN:]
            else:
                # 校验失败，丢弃第1字节，继续下一轮尝试
                self._buffer.pop(0)

        return frames

    def clear(self):
        self._buffer.clear()

    @property
    def pending_bytes(self):
        return len(self._buffer)


# ============================================================
# send_cmd_with_uplink_check — 统一指令发送（上行检测 → 发指令 → 等返回值）
# ============================================================
def send_cmd_with_uplink_check(serial_mgr, cmd_bytes, desc="", temp_callback=None):
    """发指令 → 等仪器即时响应（上行帧），200ms 超时重试，无限重试直到成功

    流程:
        1. 一次性排空串口旧数据（转发温度到回调）
        2. 发送指令 → 等待响应帧（200ms 超时）
        3. 超时则重新发送（不再排空，避免吃掉仪器的周期帧导致永远等不到响应）

    参数:
        serial_mgr: SerialManager 实例
        cmd_bytes: 要发送的指令字节
        desc: 指令描述（用于日志）
        temp_callback: 可选, callable(temperature_float) — 每收到一帧上行数据时回调,
                       用于将消费帧的温度实时转发到 UI, 避免数据丢失
    """
    import time as _time

    RESP_TIMEOUT = 0.2  # 200ms
    first_attempt = True

    # ===== 一次性排空旧数据（仅一次，不在重试循环中重复）=====
    try:
        stale = serial_mgr.read_all()
    except Exception:
        stale = b""
    if stale and temp_callback:
        buf = UplinkBuffer()
        for f in buf.feed(stale):
            try:
                temp_callback(f["temperature"])
            except Exception:
                pass

    while True:
        # ===== 发送指令 =====
        n = serial_mgr.send(cmd_bytes)
        if n == 0:
            if first_attempt:
                logger.warning("[CMD] 发送失败(%s)，准备重试" % desc)
                first_attempt = False
            _time.sleep(0.1)
            continue
        if first_attempt:
            logger.info("[CMD] 已发送: %s | %s" % (desc, cmd_bytes.hex()))
            first_attempt = False

        # ===== 等待仪器响应（上行帧）=====
        resp_start = _time.time()
        resp_received = False
        while (_time.time() - resp_start) < RESP_TIMEOUT:
            try:
                raw = serial_mgr.read_all()
            except Exception:
                raw = b""
            if raw:
                buf = UplinkBuffer()
                frames = buf.feed(raw)
                if frames:
                    serial_mgr.update_uplink_time()
                    # 转发温度数据到回调, 避免消费帧后温度被丢弃
                    if temp_callback:
                        for f in frames:
                            try:
                                temp_callback(f["temperature"])
                            except Exception:
                                pass
                    resp_received = True
                    break
            _time.sleep(0.05)

        if resp_received:
            logger.info("[CMD] 发送成功，收到响应: %s" % desc)
            return True

        # 200ms 内无响应，重新发送（不排空，不打印日志避免刷屏）


# ============================================================
# handshake — [已废弃] 保留仅用于向后兼容老旧测试代码
# ============================================================
def handshake(serial_mgr, retries=3, wait_ms=80, last_uplink_time=None, timeout=3.0):
    """[已废弃] 请使用 send_cmd_with_uplink_check 代替

    保留此函数仅为避免旧测试代码报错。
    内部已重定向到 send_cmd_with_uplink_check。
    """
    cmd = CommandBuilder.build_command(CMD.HANDSHAKE)
    return send_cmd_with_uplink_check(
        serial_mgr, cmd, desc="握手(兼容)",
    )
