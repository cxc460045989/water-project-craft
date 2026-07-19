# -*- coding: utf-8 -*-
"""MockInstrumentSimulator - 智能仪器模拟器
在无硬件环境下完整模拟微机全自动水分测定仪的串口行为。
QTimer 驱动自动生成上行帧，响应全部下行指令，温度/重量动态变化。
SimSerialAdapter 通过 readyRead 信号与 SerialManager 的 _on_ready_read 对接。

用法:
    from mock_instrument import create_mock_serial_manager
    mgr, sim = create_mock_serial_manager()
    # mgr 即为已连接、已启动模拟的 SerialManager
"""

import time
from protocol_layer import CommandBuilder, CMD
from PySide2.QtCore import QObject, Signal, QTimer


class MockInstrumentSimulator(QObject):
    """智能仪器模拟器 — 后台线程驱动

    用独立线程生成上行帧，确保在 send_cmd_with_uplink_check 的
    time.sleep() 期间也能持续产生数据（QTimer 会被 sleep 阻塞）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 上行帧参数
        self._temp = 25.0
        self._weight = 0.0
        self._online = 0
        self._btn = 0
        self._interval_ms = 200

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

        # 模拟称重数据
        self._crucible_weights = {}
        self._sample_weights = {}
        self._in_sample_phase = False
        self._dry_read_count = 0  # 烘干后称重次数，用于恒重模拟(每轮递减)

        # 上行帧缓存（供 SimSerialAdapter 读取，跨线程需锁保护）
        self._uplink_buf = bytearray()
        self._resp_buf = bytearray()
        import threading
        self._buf_lock = threading.Lock()

        # 后台线程驱动（QTimer 在 time.sleep() 期间不触发，必须用线程）
        import os as _os
        import threading
        _speed = _os.environ.get('WATER_SPEED_MODE', '0') == '1'
        self._heat_rate = 10.0
        self._cool_rate = 3.0
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        import threading
        self._thread = threading.Thread(target=self._auto_report_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _auto_report_loop(self):
        import time as _time
        while self._running:
            self._auto_report()
            _time.sleep(self._interval_ms / 1000.0)

    def _auto_report(self):
        if not self._running:
            return
        prev_temp = self._temp
        if self._heater_on and self._target_temp > 0:
            diff = self._target_temp - self._temp
            if diff > 2.0:
                self._temp += self._heat_rate * (self._interval_ms / 1000.0)
            elif diff > 0.5:
                self._temp += 5.0 * (self._interval_ms / 1000.0)
            elif abs(diff) > 0.1:
                self._temp += 2.0 * (self._interval_ms / 1000.0) if diff > 0 else -0.5 * (self._interval_ms / 1000.0)
            self._temp = min(self._temp, self._target_temp + 0.5)
            threshold = self._target_temp - 5
            if prev_temp < threshold <= self._temp:
                print("[MOCK] 温度达标! %.1fC >= %dC (目标%dC-5), 可进入恒温" % (
                    self._temp, threshold, self._target_temp))
            elif int(prev_temp / 10) != int(self._temp / 10) and self._temp < self._target_temp:
                print("[MOCK] 加热中: %.1fC -> 目标 %dC" % (self._temp, self._target_temp))
        elif not self._heater_on and self._temp > 25.0:
            self._temp -= self._cool_rate * (self._interval_ms / 1000.0)
            self._temp = max(self._temp, 25.0)

        self._weight = self._compute_weight()

        # 故障注入: 温度噪声/传感器故障
        self._temp = self._apply_faults_to_temp(self._temp)

        # 故障注入: 上行帧丢帧
        if self._apply_faults_to_uplink():
            return  # 丢弃本帧

        raw_temp = int(round(self._temp * 10))
        raw_weight = int(round(self._weight * 10000)) + 3000000
        raw_temp = max(0, min(9999, raw_temp))
        raw_weight = max(0, min(9999999, raw_weight))
        frame = "S%04d%07d%d%dEND" % (raw_temp, raw_weight, self._online, self._btn)
        with self._buf_lock:
            self._uplink_buf.extend(frame.encode("ascii"))
        self._btn = 0

    def _get_physical_weight(self):
        if self._plate_pos == 1:
            return 0.0
        pos = self._position
        if pos not in self._crucible_weights:
            self._crucible_weights[pos] = round(18.5 + pos * 0.25, 4)
        physical = self._crucible_weights[pos]
        if self._in_sample_phase:
            if pos not in self._sample_weights:
                if self._moisture_testing:
                    # 烘干后重量 (水分测试模式, 称量/恒重阶段)
                    if pos == 1:
                        self._sample_weights[pos] = 0.0  # pos 1 是校正坩埚位, 无样品
                    elif pos <= 7:
                        # 分析水: 干燥后 0.5~0.9g (pos 2~7), 每轮递减模拟恒重
                        base = 0.5 + (pos - 2) * 0.08
                        self._sample_weights[pos] = round(base - self._dry_read_count * 0.0003, 4)
                    else:
                        # 全水: 干燥后 0~0.9g (pos 8+)
                        base = (pos - 7) * 0.05
                        self._sample_weights[pos] = round(base - self._dry_read_count * 0.0002, 4)
                else:
                    if pos <= 6:
                        self._sample_weights[pos] = round(0.95 + pos * 0.01, 4)
                    else:
                        self._sample_weights[pos] = round(9.50 + (pos - 6) * 0.12, 4)
            physical += self._sample_weights[pos]
        return physical

    def _compute_weight(self):
        physical = self._get_physical_weight()
        # 故障注入: 天平噪声/漂移
        physical = self._apply_faults_to_weight(physical)
        return physical + self._tare_offset

    # ===== 下行指令处理 =====

    def feed_cmd(self, data):
        if not data:
            return b""
        if self._is_handshake(data):
            resp = b'\x4F\x4B\x01\x45\x4E\x44'
            resp = self._apply_faults_to_ack(resp)
            self._resp_buf.extend(resp)
            return resp
        if len(data) >= 4 and data[0] == 0x5A and data[-1] == 0x44:
            resp = self._handle_4byte_cmd(data)
            if resp:
                resp = self._apply_faults_to_ack(resp)
            return resp
        return b""

    def _is_handshake(self, data):
        return data == CommandBuilder.build_command(CMD.HANDSHAKE)

    def _handle_4byte_cmd(self, data):
        if len(data) < 4:
            return b""
        if data[1] != 0x4D:
            if data[1] == 0x57:
                self._handle_temp_control(data)
                return bytes([0x4F, 0x4B, data[2], data[3], data[4], 0x4E, 0x44])
            elif data[1] == 0x58:
                return bytes([0x4F, 0x4B, data[2], data[3], data[4], 0x4E, 0x44])
            return b""

        fc = data[2]
        if fc == CMD.HANDSHAKE:
            return b'\x4F\x4B\x01\x45\x4E\x44'
        elif fc == CMD.BEEPER_1S:
            self._beeper_on = True
            import threading
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
            self._tare_offset = -self._get_physical_weight()
            if self._moisture_testing:
                self._dry_read_count += 1  # 烘干后每次去皮计数，模拟恒重递减
        elif fc == CMD.CALIBRATE:
            pass
        elif fc == CMD.CLOSE_LID:
            if not self._lid_open:
                self._in_sample_phase = False
            self._lid_open = False
        elif fc == CMD.OPEN_LID:
            self._lid_open = True
            self._in_sample_phase = True
        elif fc == CMD.ENTER_WEIGH_MODE:
            self._weigh_mode = True
            self._in_sample_phase = True
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
            self._plate_pos = 1
        elif fc == CMD.SAMPLE_PLATE_HOME:
            self._position = 1
            self._plate_pos = 1
        elif fc == CMD.RESET:
            self._in_sample_phase = False
            self._weigh_mode = False
            self._moisture_testing = False
            self._sample_weights.clear()  # 退出水分测试模式, 下次称重按原始范围生成
            self._dry_read_count = 0
            print("[MOCK] 收到复位指令 (RESET 0x20), _in_sample_phase=False, 样品重已重置为原始范围")
        elif fc in (CMD.MOISTURE_TEST_1, CMD.MOISTURE_TEST_2):
            self._moisture_testing = True
            self._weigh_mode = False
            self._in_sample_phase = True
            self._sample_weights.clear()  # 清空旧称重数据, 强制按干燥后范围重新生成
            self._dry_read_count = 0
            mode_name = "鼓风" if fc == CMD.MOISTURE_TEST_1 else "氮气"
            print("[MOCK] 收到开始测试指令(%s), 进入水分测试模式, 样品重已重置为干燥后范围" % mode_name)
        elif 0x35 <= fc <= 0x9C:
            pos = fc - 0x34
            if 1 <= pos <= 99:
                self._position = pos
                self._plate_pos = 1
        return bytes([0x4F, 0x4B, fc, 0x45, 0x4E, 0x44])

    def _handle_temp_control(self, data):
        if len(data) >= 7:
            digits = [data[2], data[3], data[4], data[5]]
            self._target_temp = digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]
            self._heater_on = True
            print("[MOCK] 收到控温指令: 目标=%dC, 当前=%.1fC, 开始加热" % (
                self._target_temp, self._temp))

    # ===== 手动控制接口 =====

    def set_temperature(self, temp_c):
        self._temp = float(temp_c)

    def set_weight(self, weight_g):
        self._weight = float(weight_g)

    def set_online(self, online):
        self._online = 1 if online else 0

    def press_button(self):
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

    # ===== 协议自检 =====

    def validate_protocol(self):
        """协议一致性自检 — 验证所有指令的 ACK 响应与协议文档一致

        Returns:
            dict: {"passed": [...], "failed": [...], "warnings": [...]}
        """
        results = {"passed": [], "failed": [], "warnings": []}
        import copy
        saved_state = {
            "_in_sample_phase": self._in_sample_phase,
            "_lid_open": self._lid_open,
            "_plate_pos": self._plate_pos,
            "_position": self._position,
            "_heater_on": self._heater_on,
            "_target_temp": self._target_temp,
            "_moisture_testing": self._moisture_testing,
        }

        # 所有 4 字节指令 (5A 4D <fc> 44)
        test_cases = [
            (0x01, "HANDSHAKE(已废弃)", True),    # 握手始终返回 OK
            (0x07, "BEEPER_1S", True),
            (0x13, "SAMPLE_PLATE_ROTATE", True),
            (0x14, "SAMPLE_PLATE_UP", True),
            (0x15, "SAMPLE_PLATE_DOWN", True),
            (0x16, "TARE", True),
            (0x17, "CALIBRATE", True),
            (0x18, "CLOSE_LID", True),
            (0x19, "OPEN_LID", True),
            (0x12, "ENTER_WEIGH_MODE", True),
            (0x11, "EXIT_WEIGH_MODE", True),
            (0x10, "ALL_OFF", True),
            (0x1B, "HEAT_OFF", True),
            (0x1C, "FAN_ON", True),
            (0x1D, "FAN_OFF", True),
            (0x1E, "N2_ON", True),
            (0x1F, "N2_OFF", True),
            (0x20, "RESET", True),
            (0x21, "BEEPER_ON", True),
            (0x22, "BEEPER_OFF", True),
            (0x29, "SAMPLE_PLATE_STEP", True),
            (0x30, "SAMPLE_PLATE_HOME", True),
            (0x32, "GAS_ALL_OFF", True),
            (0x33, "MOISTURE_TEST_1", True),
            (0x34, "MOISTURE_TEST_2", True),
            (0x0E, "O2_ON", True),
            (0x0F, "O2_OFF", True),
        ]

        for fc, name, _ in test_cases:
            cmd = bytes([0x5A, 0x4D, fc, 0x44])
            resp = self.feed_cmd(cmd)
            expected = bytes([0x4F, 0x4B, fc, 0x45, 0x4E, 0x44])
            if resp == expected:
                results["passed"].append(name)
            else:
                results["failed"].append({
                    "name": name,
                    "fc": "0x%02X" % fc,
                    "expected": expected.hex(),
                    "got": resp.hex() if resp else "None",
                })
            # 恢复状态
            self._in_sample_phase = False
            self._lid_open = False

        # 控温指令
        temp_cmd = bytes([0x5A, 0x57, 1, 0, 5, 0x44])
        resp = self.feed_cmd(temp_cmd)
        expected_temp = bytes([0x4F, 0x4B, 1, 0, 5, 0x4E, 0x44])
        if resp == expected_temp:
            results["passed"].append("TEMP_CONTROL(105C)")
        else:
            results["failed"].append({
                "name": "TEMP_CONTROL(105C)",
                "expected": expected_temp.hex(),
                "got": resp.hex() if resp else "None",
            })

        # 发送重量
        weight_cmd = bytes([0x5A, 0x58, 0, 0, 1, 0, 0, 0, 0, 0x44])
        resp = self.feed_cmd(weight_cmd)
        expected_weight = bytes([0x4F, 0x4B, 0, 0, 1, 0x4E, 0x44])
        if resp == expected_weight:
            results["passed"].append("SEND_WEIGHT")
        else:
            results["failed"].append({
                "name": "SEND_WEIGHT",
                "expected": expected_weight.hex(),
                "got": resp.hex() if resp else "None",
            })

        # 移动样位
        move_cmd = bytes([0x5A, 0x4D, 0x35, 0x44])  # 0x35 - 0x34 = 1, pos 1
        resp = self.feed_cmd(move_cmd)
        expected_move = bytes([0x4F, 0x4B, 0x35, 0x45, 0x4E, 0x44])
        if resp == expected_move:
            results["passed"].append("MOVE_TO(1)")
        else:
            results["failed"].append({
                "name": "MOVE_TO(1)",
                "expected": expected_move.hex(),
                "got": resp.hex() if resp else "None",
            })

        # 检查状态恢复
        for k, v in saved_state.items():
            setattr(self, k, v)

        total = len(results["passed"]) + len(results["failed"])
        results["summary"] = "%d/%d passed" % (len(results["passed"]), total)
        return results

    @staticmethod
    def print_protocol_report(results):
        """打印协议自检报告"""
        print("\n" + "=" * 60)
        print("  协议一致性自检报告: %s" % results["summary"])
        print("=" * 60)
        if results["failed"]:
            print("\n  [FAILED] %d 项:" % len(results["failed"]))
            for f in results["failed"]:
                print("    - %s: expected=%s got=%s" % (
                    f["name"], f["expected"], f["got"]))
        print("  [PASSED] %d 项" % len(results["passed"]))
        if results.get("warnings"):
            for w in results["warnings"]:
                print("  [WARN] %s" % w)
        print()

    # ===== 故障注入 =====

    def enable_fault_injection(self, config=None):
        """启用故障注入模式

        config 支持的故障类型:
            drop_uplink_rate: 0.0~1.0  上行帧丢帧概率 (默认 0.0)
            ack_delay_ms: 0~5000       ACK 应答延迟 (默认 0)
            uplink_delay_ms: 0~5000    上行帧延迟 (默认 0)
            temp_noise: 0~10.0         温度读数噪声幅度 (默认 0)
            weight_drift: 0~1.0        天平读数漂移 (默认 0)
            temp_sensor_fault: bool    温度传感器故障 (默认 False, 读数锁定为 999.9)
            motor_stall: bool          电机卡死 (默认 False, 样位不移动)
        """
        self._fault_config = {
            "drop_uplink_rate": 0.0,
            "ack_delay_ms": 0,
            "uplink_delay_ms": 0,
            "temp_noise": 0.0,
            "weight_drift": 0.0,
            "temp_sensor_fault": False,
            "motor_stall": False,
        }
        if config:
            self._fault_config.update(config)
        if not hasattr(self, '_fault_stats'):
            self._fault_stats = {"dropped_frames": 0, "delayed_acks": 0}
        print("[MOCK] 故障注入已启用: %s" % self._fault_config)

    def disable_fault_injection(self):
        """禁用故障注入"""
        self._fault_config = None
        print("[MOCK] 故障注入已禁用")

    @property
    def fault_stats(self):
        return getattr(self, '_fault_stats', {"dropped_frames": 0, "delayed_acks": 0})

    def _apply_faults_to_uplink(self):
        """对上行帧应用故障（丢帧/延迟）"""
        cfg = getattr(self, '_fault_config', None)
        if cfg is None:
            return False  # 不丢帧
        import random
        if random.random() < cfg["drop_uplink_rate"]:
            self._fault_stats["dropped_frames"] += 1
            return True  # 丢帧
        return False

    def _apply_faults_to_ack(self, resp):
        """对 ACK 响应应用故障（延迟）"""
        cfg = getattr(self, '_fault_config', None)
        if cfg is None:
            return resp
        if cfg["ack_delay_ms"] > 0:
            self._fault_stats["delayed_acks"] += 1
            import time as _time
            _time.sleep(cfg["ack_delay_ms"] / 1000.0)
        return resp

    def _apply_faults_to_weight(self, physical):
        """对天平读数应用故障（噪声/漂移）"""
        cfg = getattr(self, '_fault_config', None)
        if cfg is None:
            return physical
        import random
        result = physical
        if cfg["weight_drift"] > 0:
            result += cfg["weight_drift"] * (self._dry_read_count or 0)
        if cfg["temp_noise"] > 0:
            result += random.uniform(-cfg["temp_noise"] / 1000.0, cfg["temp_noise"] / 1000.0)
        return result

    def _apply_faults_to_temp(self, temp):
        """对温度读数应用故障"""
        cfg = getattr(self, '_fault_config', None)
        if cfg is None:
            return temp
        if cfg["temp_sensor_fault"]:
            return 999.9
        import random
        if cfg["temp_noise"] > 0:
            return temp + random.uniform(-cfg["temp_noise"], cfg["temp_noise"])
        return temp


class SimSerialAdapter(QObject):
    """模拟串口适配器 — QSerialPort 兼容接口 + readyRead 信号

    实现与 QSerialPort/MockSerial 兼容的接口，通过 readyRead 信号
    与 SerialManager._on_ready_read 对接。

    线程安全: _read_buf 由 threading.Lock 保护，
    因为 QThread worker 和主线程 QTimer 会并发访问。
    """
    readyRead = Signal()

    def __init__(self, simulator, serial_mgr=None):
        super().__init__()
        self._sim = simulator
        self._serial_mgr = serial_mgr
        self.is_open = True
        self.port = "MOCK"
        self._read_buf = bytearray()
        import threading
        self._lock = threading.Lock()
        self._drain_timer = QTimer(self)
        self._drain_timer.timeout.connect(self._drain_and_emit)
        self._drain_timer.start(200)

    def bytesAvailable(self):
        """非阻塞返回可读字节数 — 必须先 drain 再返回"""
        self._drain_uplink()
        with self._lock:
            return len(self._read_buf)

    def isOpen(self):
        return self.is_open

    def portName(self):
        return self.port

    def write(self, data):
        if not data:
            return 0
        n = len(data)
        resp = self._sim.feed_cmd(data)
        if resp:
            with self._lock:
                self._read_buf.extend(resp)
        # 同步排空模拟器上行帧到 _read_buf
        self._drain_uplink()
        # bypass 模式: 直调 _on_ready_read 同步填入 _sync_buf，
        # 避免 readyRead QueuedConnection 跨线程排队延迟。
        if self._serial_mgr and self._serial_mgr._bypass_readyread:
            self._serial_mgr._on_ready_read()
        else:
            self.readyRead.emit()
        return n

    def flush(self):
        pass

    def readAll(self):
        self._drain_uplink()
        with self._lock:
            data = bytes(self._read_buf)
            self._read_buf.clear()
        return data

    def read(self, size=1):
        self._drain_uplink()
        with self._lock:
            if len(self._read_buf) == 0:
                return b""
            n = min(size, len(self._read_buf))
            data = bytes(self._read_buf[:n])
            self._read_buf = self._read_buf[n:]
        return data

    def readline(self):
        self._drain_uplink()
        with self._lock:
            idx = self._read_buf.find(b"\n")
            if idx < 0:
                return b""
            line = bytes(self._read_buf[:idx + 1])
            self._read_buf = self._read_buf[idx + 1:]
        return line

    def read_until(self, expected=b"\n", size=256):
        self._drain_uplink()
        with self._lock:
            idx = self._read_buf.find(expected)
            if idx < 0:
                data = bytes(self._read_buf[:min(size, len(self._read_buf))])
                self._read_buf = self._read_buf[len(data):]
                return data
            end = idx + len(expected)
            data = bytes(self._read_buf[:end])
            self._read_buf = self._read_buf[end:]
        return data

    def close(self):
        self.is_open = False
        self._sim.stop()

    def _drain_uplink(self):
        """将模拟器上行缓存转移到读缓存（线程安全）"""
        with self._sim._buf_lock:
            up = bytes(self._sim._uplink_buf)
            self._sim._uplink_buf.clear()
            rp = bytes(self._sim._resp_buf)
            self._sim._resp_buf.clear()
        if up:
            with self._lock:
                self._read_buf.extend(up)
            if self._serial_mgr:
                self._serial_mgr.update_uplink_time()
        if rp:
            with self._lock:
                self._read_buf.extend(rp)

    def _drain_and_emit(self):
        """定时转移数据，有数据时发射 readyRead"""
        self._drain_uplink()
        with self._lock:
            has_data = len(self._read_buf) > 0
        if has_data:
            self.readyRead.emit()


# ===== 工厂函数 =====

def create_mock_serial_manager():
    from serial_comm import SerialManager

    sim = MockInstrumentSimulator()
    sim.set_online(True)
    sim.start()

    mgr = SerialManager(parent=None, use_mock=False)
    mgr._serial = SimSerialAdapter(sim, serial_mgr=mgr)
    mgr._serial.readyRead.connect(mgr._on_ready_read)
    mgr._mock = False
    mgr._config.port = "MOCK"

    return mgr, sim


# ===== 独立测试入口 =====
if __name__ == "__main__":
    from PySide2.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    sim = MockInstrumentSimulator()
    sim.set_online(True)
    sim.start()

    print("=== MockInstrumentSimulator 独立测试 ===")
    print("初始:  temp=%.1fC  weight=%.4fg  online=%d" % (
        sim.get_temperature(), sim.get_weight(), 1))

    from protocol_layer import CommandBuilder
    cmd = CommandBuilder.build_temp_control(105)
    sim.feed_cmd(cmd)
    print("发送控温 105C")

    for i in range(10):
        time.sleep(0.5)
        print("  t=%.1fs  temp=%.1fC  heating=%s  target=%d" % (
            i * 0.5, sim.get_temperature(), sim.is_heating(), sim.get_target_temp()))

    sim.set_weight(25.0235)
    cmd2 = CommandBuilder.build_send_weight(1.0019)
    sim.feed_cmd(cmd2)
    print("设置天平 weight=25.0235g")
    time.sleep(1)
    print("最终:  temp=%.1fC  weight=%.4fg  state=%s" % (
        sim.get_temperature(), sim.get_weight(), sim.state_summary))

    sim.stop()
    print("测试完成")
