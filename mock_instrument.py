# -*- coding: utf-8 -*-
"""MockInstrumentSimulator - 智能仪器模拟器
在无硬件环境下完整模拟微机全自动水分测定仪的串口行为。
后台线程自动生成上行帧，响应全部下行指令，温度/重量动态变化。

用法:
    from mock_instrument import create_mock_serial_manager
    mgr = create_mock_serial_manager()
    # mgr 即为已连接、已启动模拟的 SerialManager
"""

import time, threading
from protocol_layer import CommandBuilder, CMD


class MockInstrumentSimulator:
    """智能仪器模拟器 — 后台线程驱动"""

    def __init__(self):
        # 上行帧参数
        self._temp = 25.0
        self._weight = 0.0
        self._online = 0
        self._btn = 0
        self._interval_ms = 1000

        # 仪器状态
        self._tare_offset = 0.0
        self._plate_pos = 1   # 1=upper, 0=lower
        self._position = 1
        self._fan_on = False
        self._n2_on = False
        self._heater_on = False
        self._beeper_on = False
        self._target_temp = 0
        self._weigh_mode = False
        self._lid_open = False
        self._moisture_testing = False

        # 上行帧缓存（供 SimSerialAdapter 读取）
        self._uplink_buf = bytearray()
        self._resp_buf = bytearray()

        # 后台线程
        self._running = False
        self._thread = None

        # 模拟升温速率 (℃/s)
        self._heat_rate = 20.0
        self._cool_rate = 2.0

    # ===== 生命周期 =====

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._auto_report_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # ===== 后台上行帧生成 =====

    def _auto_report_loop(self):
        while self._running:
            self._auto_report()
            time.sleep(self._interval_ms / 1000.0)

    def _auto_report(self):
        if not self._running:
            return
        # 控温逻辑
        if self._heater_on and self._target_temp > 0:
            diff = self._target_temp - self._temp
            if diff > 2.0:
                self._temp += self._heat_rate * (self._interval_ms / 1000.0)
            elif diff > 0.5:
                self._temp += 5.0 * (self._interval_ms / 1000.0)
            elif abs(diff) > 0.1:
                self._temp += 2.0 * (self._interval_ms / 1000.0) if diff > 0 else -0.5 * (self._interval_ms / 1000.0)
            self._temp = min(self._temp, self._target_temp + 0.5)
        elif not self._heater_on and self._temp > 25.0:
            self._temp -= self._cool_rate * (self._interval_ms / 1000.0)
            self._temp = max(self._temp, 25.0)

        # 组装上行帧
        raw_temp = int(round(self._temp * 10))
        raw_weight = int(round((self._weight + self._tare_offset) * 10000)) + 3000000
        raw_temp = max(0, min(9999, raw_temp))
        raw_weight = max(0, min(9999999, raw_weight))
        frame = "S%04d%07d%d%dEND" % (raw_temp, raw_weight, self._online, self._btn)
        self._uplink_buf.extend(frame.encode("ascii"))
        # 复位按键
        self._btn = 0

    # ===== 下行指令处理 =====

    def feed_cmd(self, data):
        """接收下行指令，解析并模拟执行，返回响应字节"""
        if not data:
            return b""

        # 握手 — 新协议返回完整响应帧 4F 4B 01 45 4E 44
        if self._is_handshake(data):
            self._resp_buf.extend(b'\x4F\x4B\x01\x45\x4E\x44')
            return b'\x4F\x4B\x01\x45\x4E\x44'

        # 固定4字节指令
        if len(data) >= 4 and data[0] == 0x5A and data[-1] == 0x44:
            return self._handle_4byte_cmd(data)

        return b""

    def _is_handshake(self, data):
        return data == CommandBuilder.build_command(CMD.HANDSHAKE)

    def _handle_4byte_cmd(self, data):
        if len(data) < 4:
            return b""
        if data[1] != 0x4D:
            # 变长指令
            if data[1] == 0x57:  # 控温
                self._handle_temp_control(data)
            elif data[1] == 0x58:  # 发送天平数据
                pass  # 无需响应
            return b""

        fc = data[2]
        if fc == CMD.HANDSHAKE:
            return b'\x4F\x4B\x01\x45\x4E\x44'
        elif fc == CMD.BEEPER_1S:
            self._beeper_on = True
            threading.Timer(1.0, lambda: setattr(self, '_beeper_on', False)).start()
        elif fc == CMD.BEEPER_ON:
            self._beeper_on = True
        elif fc == CMD.BEEPER_OFF:
            self._beeper_on = False
        elif fc == CMD.SAMPLE_PLATE_UP:
            self._plate_pos = 1
        elif fc == CMD.SAMPLE_PLATE_DOWN:
            self._plate_pos = 0
        elif fc == CMD.TARE:
            self._tare_offset = 0.0
            self._weight = 0.0
        elif fc == CMD.CALIBRATE:
            pass  # 模拟校准
        elif fc == CMD.CLOSE_LID:
            self._lid_open = False
        elif fc == CMD.OPEN_LID:
            self._lid_open = True
        elif fc == CMD.ENTER_WEIGH_MODE:
            self._weigh_mode = True
        elif fc == CMD.EXIT_WEIGH_MODE:
            self._weigh_mode = False
        elif fc == CMD.HEAT_OFF:
            self._heater_on = False
        elif fc == CMD.FAN_ON:
            self._fan_on = True
        elif fc == CMD.FAN_OFF:
            self._fan_on = False
        elif fc == CMD.N2_ON:
            self._n2_on = True
        elif fc == CMD.N2_OFF:
            self._n2_on = False
        elif fc == CMD.GAS_ALL_OFF:
            self._fan_on = False
            self._n2_on = False
            self._heater_on = False
        elif fc == CMD.SAMPLE_PLATE_STEP:
            self._position = (self._position % 24) + 1
        elif fc == CMD.SAMPLE_PLATE_HOME:
            self._position = 1
        elif fc == CMD.RESET:
            self._heater_on = False
            self._target_temp = 0
            self._fan_on = False
            self._n2_on = False
        elif fc in (CMD.MOISTURE_TEST_1, CMD.MOISTURE_TEST_2):
            self._moisture_testing = True
            self._weigh_mode = False
        elif 0x35 <= fc <= 0x9C:  # move_to
            pos = fc - 0x34
            if 1 <= pos <= 99:
                self._position = pos
        return b""

    def _handle_temp_control(self, data):
        if len(data) >= 7:
            digits = [data[2], data[3], data[4], data[5]]
            self._target_temp = digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]
            self._heater_on = True

    # ===== 手动控制接口（测试用） =====

    def set_temperature(self, temp_c):
        self._temp = float(temp_c)

    def set_weight(self, weight_g):
        self._weight = float(weight_g)

    def set_online(self, online):
        self._online = 1 if online else 0

    def press_button(self):
        """模拟仪器按键按下（上行帧中 btn=1）"""
        self._btn = 1

    def get_temperature(self):
        return self._temp

    def get_weight(self):
        return self._weight

    def get_target_temp(self):
        return self._target_temp

    def is_heating(self):
        return self._heater_on

    def get_position(self):
        return self._position

    @property
    def state_summary(self):
        return {
            "temperature": round(self._temp, 1),
            "weight": round(self._weight, 4),
            "target_temp": self._target_temp,
            "heating": self._heater_on,
            "online": bool(self._online),
            "fan": self._fan_on,
            "n2": self._n2_on,
            "position": self._position,
            "plate_up": bool(self._plate_pos),
            "weigh_mode": self._weigh_mode,
            "moisture_testing": self._moisture_testing,
        }


class SimSerialAdapter:
    """模拟串口适配器 — 对接 MockInstrumentSimulator 与 SerialManager

    实现与 MockSerial 兼容的接口，使 SerialManager(mock=True) 可以透明使用。
    """

    def __init__(self, simulator, serial_mgr=None):
        self._sim = simulator
        self._serial_mgr = serial_mgr  # 用于更新上行时间戳
        self.is_open = True
        self.port = "MOCK"
        self._read_buf = bytearray()
        self._handshake_resp = bytearray()  # 握手指令专用响应通道
        import threading
        self._lock = threading.Lock()

    def write(self, data):
        if not data:
            return 0
        n = len(data)
        # 握手指令走专用通道, 确保 read_all 一定能读到 OK
        if self._sim._is_handshake(data):
            resp = self._sim.feed_cmd(data)
            self._handshake_resp.extend(b'\x4F\x4B\x01\x45\x4E\x44')
            return n
        # 其他指令交给模拟器处理
        resp = self._sim.feed_cmd(data)
        if resp:
            self._read_buf.extend(resp)
        return n

    def flush(self):
        pass

    def read(self, size=1):
        # 握手指令响应优先
        if len(self._handshake_resp) > 0:
            hk = bytes(self._handshake_resp)
            self._handshake_resp.clear()
            self._read_buf = hk + self._read_buf
        self._drain_uplink()
        if len(self._read_buf) == 0:
            return b""
        n = min(size, len(self._read_buf))
        data = bytes(self._read_buf[:n])
        self._read_buf = self._read_buf[n:]
        return data

    def read_all(self):
        # 握手指令响应优先返回
        hk = bytes(self._handshake_resp)
        self._handshake_resp.clear()
        self._drain_uplink()
        data = hk + bytes(self._read_buf)
        self._read_buf.clear()
        return data

    def readline(self):
        self._drain_uplink()
        idx = self._read_buf.find(b"\n")
        if idx < 0:
            return b""
        line = bytes(self._read_buf[:idx + 1])
        self._read_buf = self._read_buf[idx + 1:]
        return line

    def read_until(self, expected=b"\n", size=256):
        self._drain_uplink()
        idx = self._read_buf.find(expected)
        if idx < 0:
            data = bytes(self._read_buf[:min(size, len(self._read_buf))])
            self._read_buf = self._read_buf[len(data):]
            return data
        end = idx + len(expected)
        data = bytes(self._read_buf[:end])
        self._read_buf = self._read_buf[end:]
        return data

    def _drain_uplink(self):
        """将模拟器上行缓存转移到读缓存(线程安全)"""
        with self._lock:
            up = bytes(self._sim._uplink_buf)
            self._sim._uplink_buf.clear()
            if up:
                self._read_buf.extend(up)
                if self._serial_mgr:
                    self._serial_mgr.update_uplink_time()
            rp = bytes(self._sim._resp_buf)
            self._sim._resp_buf.clear()
            if rp:
                self._read_buf.extend(rp)

    def reset_input_buffer(self):
        with self._lock:
            self._read_buf.clear()
            self._handshake_resp.clear()
            # 不清空 _uplink_buf / _resp_buf：模拟器数据是有效上行帧，
            # 不是真实串口的残留垃圾。清空会导致 send_cmd_with_uplink_check
            # 永远等不到响应，陷入无限重试死循环。

    def reset_output_buffer(self):
        self._read_buf.clear()

    def close(self):
        self.is_open = False
        self._sim.stop()

    # MockSerial 兼容接口
    def add_response(self, cmd_prefix, resp_bytes):
        pass  # 模拟器已内部处理

    def set_uplink_frame(self, **kwargs):
        pass  # 模拟器已自动生成

    def set_uplink_callback(self, callback):
        pass

    def process_incoming(self):
        self._drain_uplink()


# ===== 工厂函数 =====

def create_mock_serial_manager():
    """创建已连接模拟仪器的 SerialManager 实例

    返回:
        SerialManager: is_connected=True, 已启动后台模拟
        MockInstrumentSimulator: 模拟器实例（可手动控制温度/重量等）
    """
    from serial_comm import SerialManager

    sim = MockInstrumentSimulator()
    sim.set_online(True)
    sim.start()

    mgr = SerialManager(parent=None, use_mock=False)
    mgr._serial = SimSerialAdapter(sim, serial_mgr=mgr)
    mgr._mock = False  # 避开 mock 检查
    mgr._config.port = "MOCK"

    return mgr, sim


# ===== 独立测试入口 =====
if __name__ == "__main__":
    sim = MockInstrumentSimulator()
    sim.set_online(True)
    sim.start()

    print("=== MockInstrumentSimulator 独立测试 ===")
    print("初始:  temp=%.1fC  weight=%.4fg  online=%d" % (
        sim.get_temperature(), sim.get_weight(), 1))

    # 模拟控温
    from protocol_layer import CommandBuilder
    cmd = CommandBuilder.build_temp_control(105)
    sim.feed_cmd(cmd)
    print("发送控温 105°C")

    for i in range(10):
        time.sleep(0.5)
        print("  t=%.1fs  temp=%.1fC  heating=%s  target=%d" % (
            i * 0.5, sim.get_temperature(), sim.is_heating(), sim.get_target_temp()))

    # 模拟发送天平数据
    sim.set_weight(25.0235)
    cmd2 = CommandBuilder.build_send_weight(1.0019)
    sim.feed_cmd(cmd2)
    print("设置天平 weight=25.0235g")
    time.sleep(1)
    print("最终:  temp=%.1fC  weight=%.4fg  state=%s" % (
        sim.get_temperature(), sim.get_weight(), sim.state_summary))

    sim.stop()
    print("测试完成")
