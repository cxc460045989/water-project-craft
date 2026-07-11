# -*- coding: utf-8 -*-
"""协议解析与指令封装层 — 水分测定仪串口通讯协议
依赖: serial_comm.py（SerialManager）
框架: PySide2 (Qt5) — 兼容 Windows 7 / 麒麟Linux x86/ARM64

设计原则:
  - 只负责协议解析与指令组包，不参与业务逻辑
  - 上行解析独立无状态，下行指令纯函数构造
  - 粘包/半包由 UplinkBuffer 状态机处理
  - 握手流程封装为单独函数

用法:
    from protocol_layer import CommandBuilder, FrameParser, UplinkBuffer, handshake
    cmd = CommandBuilder.build_command(CommandBuilder.CMD_HANDSHAKE)
    parsed = FrameParser.parse_uplink(b"S0850301001701END")
"""

import time


# ============================================================
# 功能码常量（对应协议文档 4.2 固定4字节指令全集）
# ============================================================
class CMD:
    """指令功能码常量 — 5A 4D <func_code> 44"""
    HANDSHAKE = 0x01          # 握手
    BEEPER_1S = 0x07          # 蜂鸣器响1秒
    SAMPLE_PLATE_ROTATE = 0x13   # 样盘不停转动
    SAMPLE_PLATE_UP = 0x14    # 样盘上升到高位
    SAMPLE_PLATE_DOWN = 0x15  # 样盘降到低位
    TARE = 0x16               # 天平清零（去皮）
    CALIBRATE = 0x17          # 天平校正
    CLOSE_LID = 0x18          # 关闭炉盖
    OPEN_LID = 0x19           # 打开炉盖
    ENTER_WEIGH_MODE = 0x11   # 进入仪器称量样重状态
    EXIT_WEIGH_MODE = 0x12    # 解除称重状态
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
# Handshaker — 握手流程封装
# ============================================================
def handshake(serial_mgr, retries=3, wait_ms=80, last_uplink_time=None, timeout=3.0):
    """执行握手指令流程，含上行链路预检和设备忙容错

    步骤:
        1. 若 last_uplink_time 不为 None，检查是否超过 timeout 秒无上行帧
        2. 清空串口接收缓冲区
        3. 发送 5A 4D 01 44
        4. 等待 wait_ms 毫秒
        5. 读取回复，判断是否为 4F 4B 01 45 4E 44 握手响应帧
        6. 失败重试，最多 retries 次
        7. 若 last_uplink_time 正常（上行帧持续到来）但握手始终无响应，
           判定为设备忙而非链路断开

    参数:
        serial_mgr: SerialManager 实例
        retries: 最大重试次数
        wait_ms: 每次握手等待时间(ms)
        last_uplink_time: 最近一次收到上行帧的时间戳(time.time())，None 表示跳过预检
        timeout: 上行帧超时阈值(秒)，超过此时间无帧则判链路断开

    返回:
        True  — 握手成功
        False — 握手失败(链路断开或设备忙)
    侧效应:
        通过 serial_mgr.error_occurred.emit() 发出详细错误信息
    """
    import time as _time

    # 上行链路预检
    if last_uplink_time is not None:
        elapsed = _time.time() - last_uplink_time
        if elapsed > timeout:
            msg = "上行帧已 %.1f 秒无数据，判定通信链路断开" % elapsed
            serial_mgr.error_occurred.emit(msg)
            return False

    for attempt in range(1, retries + 1):
        # 清接收缓冲区
        serial_mgr.flush_input()

        # 发送握手
        cmd = CommandBuilder.build_command(CMD.HANDSHAKE)
        n = serial_mgr.send(cmd)
        if n == 0:
            _time.sleep(wait_ms / 1000.0)
            continue

        # 等待仪器响应
        _time.sleep(wait_ms / 1000.0)

        # 读取回复
        try:
            resp = serial_mgr.read_all()
        except Exception:
            resp = b""

        # 新协议：握手成功响应帧为 4F 4B 01 45 4E 44
        if resp and b'\x4F\x4B\x01\x45\x4E\x44' in resp:
            return True

        # 若 last_uplink_time 有效且上行帧仍在到来，判定为设备忙，不递减重试次数
        if last_uplink_time is not None:
            elapsed = _time.time() - last_uplink_time
            if elapsed <= timeout:
                # 设备忙：继续重试，不计入上限
                continue

    