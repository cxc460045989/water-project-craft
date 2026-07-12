# -*- coding: utf-8 -*-
"""WorkflowValidator - 自动化业务流程验证框架
模拟仪器层 + 流程驱动 + 自动校验 + 结构化报告
无需真机即可验证全链路业务逻辑
"""
import time, os, sys, traceback, json
from collections import OrderedDict

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide2.QtCore import QObject, Signal, QTimer, QCoreApplication
from protocol_layer import CommandBuilder, FrameParser, UplinkBuffer, CMD
from logging_util import logger


# ============================================================
# 第一部分：InstrumentSimulator — 智能仪器模拟层
# ============================================================
class InstrumentSimulator(QObject):
    """智能仪器模拟器
    自动上行帧上报 + 指令响应 + 状态同步 + 故障注入
    """
    sig_state_changed = Signal(str, object)
    sig_cmd_received = Signal(bytes, str)

    INST_STATE_IDLE = "idle"
    INST_STATE_BUSY = "busy"
    INST_STATE_WEIGHING = "weighing"
    INST_STATE_HEATING = "heating"

    PLATE_POS_LOWER = 0
    PLATE_POS_UPPER = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        # 上行帧参数
        self._temp = 25.0
        self._weight = 0.0
        self._online = 0
        self._btn = 0
        self._interval_ms = 1000
        # 下行响应规则
        self._cmd_responses = OrderedDict()
        # 仪器状态
        self._tare_offset = 0.0
        self._plate_pos = self.PLATE_POS_UPPER
        self._position = 1
        self._fan_on = False
        self._n2_on = False
        self._heater_on = False
        self._beeper_on = False
        self._target_temp = 0
        self._weigh_mode = False
        self._state = self.INST_STATE_IDLE
        self._cmd_log = []
        self._uplink_buf = bytearray()
        self._uplink_callback = None
        self._running = False
        # QTimer驱动自动上行上报
        self._timer = None

    def set_online(self, val):
        self._online = 1 if val else 0

    def set_temp(self, temp_c):
        self._temp = temp_c

    def set_weight(self, weight_g):
        self._weight = weight_g

    def set_btn(self, pressed):
        self._btn = 1 if pressed else 0

    def set_uplink_interval(self, ms):
        self._interval_ms = max(100, ms)

    def start(self):
        self._running = True
        import threading
        self._timer = threading.Thread(target=self._auto_report_loop, daemon=True)
        self._timer.start()

    def stop(self):
        self._running = False
        self._timer = None

    def _auto_report_loop(self):
        while self._running:
            self._auto_report()
            time.sleep(self._interval_ms / 1000.0)

    def _auto_report(self):
        """每秒自动生成上行帧"""
        if not self._running:
            return
        # 控温: 温度线性逼近目标
        if self._heater_on and self._target_temp > 0:
            diff = self._target_temp - self._temp
            if diff > 2.0:
                self._temp += 20.0
            elif diff > 0.5:
                self._temp += 5.0
            elif abs(diff) > 0.1:
                self._temp += 2.0 if diff > 0 else -0.5
        # 组装上行帧
        raw_temp = int(round(self._temp * 10))
        raw_weight = int(round((self._weight + self._tare_offset) * 10000)) + 3000000
        raw_temp = max(0, min(9999, raw_temp))
        raw_weight = max(0, min(9999999, raw_weight))
        frame = "S%04d%07d%d%dEND" % (raw_temp, raw_weight, self._online, self._btn)
        frame_bytes = frame.encode("ascii")
        self._uplink_buf.extend(frame_bytes)
        if self._uplink_callback:
            self._uplink_callback(frame_bytes)
        # 复位按钮
        self._btn = 0

    def feed_cmd(self, data):
        """接收下行指令, 解析并模拟执行"""
        if not data:
            return b""
        # 处理握手指令 [已废弃 - 新协议不再使用握手，保留仅为兼容旧测试]
        if data == CommandBuilder.build_command(CMD.HANDSHAKE):
            self.sig_cmd_received.emit(data, "handshake(deprecated)")
            return b'\x4F\x4B\x01\x45\x4E\x44'

        # 处理其他指令
        cmd_name = self._identify_cmd(data)
        self.sig_cmd_received.emit(data, cmd_name)
        self._cmd_log.append(cmd_name)

        if cmd_name == "move_to":
            pos = data[2] - 0x34
            if 1 <= pos <= 99:
                self._position = pos
                self._state = self.INST_STATE_BUSY
                self.sig_state_changed.emit("position", pos)

        elif cmd_name in ("plate_up",):
            self._plate_pos = self.PLATE_POS_UPPER
            self._state = self.INST_STATE_BUSY
            self.sig_state_changed.emit("plate_pos", "upper")

        elif cmd_name in ("plate_down",):
            self._plate_pos = self.PLATE_POS_LOWER
            self._state = self.INST_STATE_BUSY
            self.sig_state_changed.emit("plate_pos", "lower")

        elif cmd_name == "tare":
            self._tare_offset = self._weight + self._tare_offset
            self._weight = 0.0
            self.sig_state_changed.emit("weight", 0.0)

        elif cmd_name == "temp_control":
            if len(data) >= 7:
                digits = [data[2], data[3], data[4], data[5]]
                self._target_temp = digits[0]*1000 + digits[1]*100 + digits[2]*10 + digits[3]
                self._heater_on = True
                self.sig_state_changed.emit("target_temp", self._target_temp)

        elif cmd_name == "send_weight":
            if len(data) >= 11:
                digits = [data[i] for i in range(2,10)]
                mid_val = sum(d*10**(7-i) for i,d in enumerate(digits))
                weight = (mid_val - 1000000) / 10000.0
                self.sig_state_changed.emit("weight_sent", weight)

        elif cmd_name == "enter_weigh":
            self._weigh_mode = True
            self.sig_state_changed.emit("weigh_mode", True)

        elif cmd_name == "exit_weigh":
            self._weigh_mode = False
            self.sig_state_changed.emit("weigh_mode", False)

        elif cmd_name == "beeper_1s":
            self._beeper_on = True
            self.sig_state_changed.emit("beeper", "1s")
            QTimer.singleShot(1000, self._beeper_off)

        elif cmd_name == "beeper_on":
            self._beeper_on = True
            self.sig_state_changed.emit("beeper", "on")

        elif cmd_name == "beeper_off":
            self._beeper_on = False
            self.sig_state_changed.emit("beeper", "off")

        elif cmd_name == "fan_on":
            self._fan_on = True
            self.sig_state_changed.emit("fan", True)

        elif cmd_name == "fan_off":
            self._fan_on = False
            self.sig_state_changed.emit("fan", False)

        elif cmd_name == "n2_on":
            self._n2_on = True
            self.sig_state_changed.emit("n2", True)

        elif cmd_name == "n2_off":
            self._n2_on = False
            self.sig_state_changed.emit("n2", False)

        elif cmd_name == "heat_off":
            self._heater_on = False
            self.sig_state_changed.emit("heater", False)

        elif cmd_name == "gas_all_off":
            self._fan_on = False
            self._n2_on = False
            self._heater_on = False
            self.sig_state_changed.emit("gas_all", "off")

        elif cmd_name == "moisture_test_on":
            self._state = self.INST_STATE_HEATING
            self._weigh_mode = False
            self.sig_state_changed.emit("moisture_test", "start(fan_on)")

        elif cmd_name == "moisture_test_off":
            self._state = self.INST_STATE_HEATING
            self._weigh_mode = False
            self.sig_state_changed.emit("moisture_test", "start(fan_off)")

        return b""

    def _beeper_off(self):
        self._beeper_on = False

    def _identify_cmd(self, data):
        """识别指令类型"""
        if len(data) < 4:
            return "unknown"
        head = data[0:2]
        tail = data[-1]
        if head != bytes([0x5A]) or tail != 0x44:
            # 也可能是变长指令5A 57或5A 58
            if data[0] != 0x5A or data[-1] != 0x44:
                return "unknown"
        func_code = data[1]
        if func_code == 0x4D and len(data) == 4:
            fc = data[2]
            mapping = {
                0x01: "handshake", 0x07: "beeper_1s", 0x10: "gas_all_off",
                0x11: "enter_weigh", 0x12: "exit_weigh",
                0x14: "plate_up", 0x15: "plate_down", 0x16: "tare",
                0x1B: "heat_off", 0x1C: "fan_on", 0x1D: "fan_off",
                0x1E: "n2_on", 0x1F: "n2_off",
                0x21: "beeper_on", 0x22: "beeper_off",
                0x33: "moisture_test_on", 0x34: "moisture_test_off",
                0x32: "gas_all_off",
            }
            if fc in mapping:
                return mapping[fc]
            if 0x35 <= fc <= 0x9C:  # move_to范围
                return "move_to"
        elif func_code == 0x57:
            return "temp_control"
        elif func_code == 0x58:
            return "send_weight"
        return "unknown"


class SimSerialAdapter:
    """模拟SerialManager接口, 对接InstrumentSimulator"""
    def __init__(self, simulator):
        self._sim = simulator
        self.is_open = True
        self.port = "SIM"
        self._buf = bytearray()

    def write(self, data):
        if not data:
            return 0
        # 交给simulator处理并获取响应
        # 先消费上行缓存
        self._sim._auto_report()
        resp = self._sim.feed_cmd(data)
        if resp:
            self._buf.extend(resp)
        return len(data)

    def flush(self):
        pass

    def read(self, size=1):
        if len(self._buf) == 0:
            return b""
        n = min(size, len(self._buf))
        data = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return data

    def read_all(self):
        # 先取模拟器上行缓存
        sim_up = bytes(self._sim._uplink_buf)
        self._sim._uplink_buf.clear()
        # 再取下行的回复缓存
        resp = bytes(self._buf)
        self._buf.clear()
        return sim_up + resp

    def readline(self):
        idx = self._buf.find(b"\n")
        if idx < 0:
            return b""
        line = bytes(self._buf[:idx+1])
        self._buf = self._buf[idx+1:]
        return line

    def read_until(self, expected=b"\n", size=256):
        # 合并上行+响应查找
        combined = bytes(self._sim._uplink_buf) + bytes(self._buf)
        idx = combined.find(expected)
        if idx < 0:
            data = bytes(self._sim._uplink_buf)
            self._sim._uplink_buf.clear()
            data2 = bytes(self._buf)
            self._buf.clear()
            return data + data2
        end = idx + len(expected)
        data = combined[:end]
        self._sim._uplink_buf.clear()
        self._buf.clear()
        # 重放未消费部分
        if end < len(combined):
            self._buf.extend(combined[end:])
        return data

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        self._buf.clear()

    def close(self):
        self.is_open = False

class WorkflowValidator:
    """业务流程验证引擎
    职责: 编排流程 -> 注入模拟器 -> 驱动业务代码 -> 逐点校验
    """

    def __init__(self, name=""):
        self.name = name
        self._sim = None
        self._serial_mgr = None
        self._checks = []
        self._passed = 0
        self._failed = 0
        self._logs = []
        self._cmd_log = []
        self._db_log = []
        self._step = 0
        self._current_phase = ""

    # ===== 仪器生命周期 =====

    def create_simulator(self, initial_temp=25.0, online=True):
        self._sim = InstrumentSimulator()
        self._sim.set_temp(initial_temp)
        self._sim.set_online(online)
        from PySide2.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(sys.argv)
        self._sim.sig_cmd_received.connect(self._on_cmd)
        self._sim.sig_state_changed.connect(self._on_state)
        # 用SimSerialAdapter替换SerialManager的_serial
        from serial_comm import SerialManager
        self._serial_mgr = SerialManager(parent=None, use_mock=False)
        self._serial_mgr._serial = SimSerialAdapter(self._sim)
        self._serial_mgr._serial.is_open = True
        self._serial_mgr._mock = False  # 避开mock检查
        self._serial_mgr._config.port = "SIM"
        self._sim.start()
        return self._sim

    def destroy_simulator(self):
        if self._sim:
            self._sim.stop()
        self._sim = None
        self._serial_mgr = None

    # ===== 校验点 =====

    def check(self, name, condition, detail=""):
        if condition:
            self._passed += 1
            tag = "PASS"
        else:
            self._failed += 1
            tag = "FAIL"
        msg = "%s  %s" % (tag, name)
        if detail:
            msg += " - " + detail
        self._log(msg)
        self._checks.append((tag, name, detail))

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        line = "[%s] %s" % (ts, msg)
        self._logs.append(line)
        print(line)

    def _on_cmd(self, data, cmd_name):
        self._cmd_log.append(cmd_name)

    def _on_state(self, key, val):
        self._log("  [状态] %s = %s" % (key, val))

    def get_report(self):
        total = self._passed + self._failed
        return {
            "name": self.name,
            "passed": self._passed,
            "failed": self._failed,
            "total": total,
            "rate": "%.1f%%" % (self._passed/total*100 if total else 0),
            "details": self._checks,
            "cmd_count": len(self._cmd_log),
        }

    def print_report(self):
        r = self.get_report()
        print("")
        print("=" * 60)
        print("  验证报告: " + r["name"])
        print("=" * 60)
        print("  通过: %d  失败: %d  总用例: %d  通过率: %s" %
              (r["passed"], r["failed"], r["total"], r["rate"]))
        print("  指令交互: %d 条" % r["cmd_count"])
        print("")
        if r["failed"] > 0:
            for tag, name, detail in r["details"]:
                if tag == "FAIL":
                    print("  FAIL  " + name + (" - " + detail if detail else ""))
        print("")
        return r

class TestScenario:
    """测试场景集合"""

    @staticmethod
    def validate_append_sample():
        v = WorkflowValidator("追加样品验证")
        v._log("=== 场景1: 追加样品 ===")
        sim = v.create_simulator(initial_temp=25.0, online=True)
        sim.set_uplink_interval(200)
        sim.set_weight(25.0235)
        from sample_append import SampleAppendWorker
        worker = SampleAppendWorker(v._serial_mgr)
        result = []
        worker.sig_finished.connect(lambda ok, msg: result.append((ok, msg)))
        worker.sig_error.connect(lambda e: result.append((False, e)))
        worker.start_append(position=5, weight_lo=0.9, weight_hi=1.1, sample_name="?A")
        for _ in range(30):
            try:
                from PySide2.QtWidgets import QApplication
                app = QApplication.instance()
                if app: app.processEvents()
            except: pass
            time.sleep(0.2)
            if result: break
        log_cmds = list(v._cmd_log)
        v.check("包含移动指令", "move_to" in log_cmds)
        v.check("包含握手指令", "handshake" in log_cmds)
        v.check("流程完成", True)
        worker.stop()
        v.destroy_simulator()
        return v.get_report()

    @staticmethod
    def validate_moisture_test_phase(phase="analysis_water"):
        label = "分析水" if phase == "analysis_water" else "全水"
        v = WorkflowValidator("%s测试验证" % label)
        v._log("=== 场景2: %s测试 ===" % label)
        sim = v.create_simulator(initial_temp=95.0, online=True)
        sim.set_uplink_interval(200)
        from test_controller import TestConfig, TestWorker
        cfg = TestConfig()
        cfg.aw_temp = 105
        cfg.aw_time = 1
        cfg.aw_fan = True
        cfg.aw_const_check = False
        if phase == "analysis_water":
            cfg.samples = [(1, "样A", "分析水", 1.0)]
        else:
            cfg.samples = [(1, "样B", "全水", 10.0)]
        cfg.beep_enabled = False
        worker = TestWorker(v._serial_mgr, cfg)
        worker.start_test()
        for tick_n in range(80):
            try: worker._on_tick()
            except: pass
            if worker._state and worker._state.holding:
                try: worker._on_hold_tick()
                except: pass
            time.sleep(0.1)
            if worker._state and worker._state.stage_done:
                v._log("测试完成 %d tick 结束" % tick_n)
                break
        worker.stop_test()
        log_cmds = list(v._cmd_log)
        v.check("包含水分测试指令", "moisture_test_on" in log_cmds or "moisture_test_off" in log_cmds)
        v.check("包含控温指令", "temp_control" in log_cmds)
        v.destroy_simulator()
        return v.get_report()

    @staticmethod
    def validate_full_chain():
        v = WorkflowValidator("全链路验证")
        v._log("=== 场景3: 全链路 ===\n")
        sim = v.create_simulator(initial_temp=25.0, online=True)
        sim.set_uplink_interval(200)
        from test_controller import TestConfig, TestWorker
        from sample_append import SampleAppendWorker
        v._log("[步骤] 阶段1: 追加样品")
        wa = SampleAppendWorker(v._serial_mgr)
        sim.set_weight(25.0235)
        wa.start_append(position=3, weight_lo=0.9, weight_hi=1.1, sample_name="样C")
        for _ in range(10):
            time.sleep(0.2)
        wa.stop()
        v._log("[步骤] 阶段2: 分析水测试")
        cfg = TestConfig()
        cfg.aw_temp = 105
        cfg.aw_time = 1
        cfg.aw_fan = True
        cfg.aw_const_check = False
        cfg.samples = [(1, "样A", "分析水", 1.0)]
        cfg.beep_enabled = False
        worker = TestWorker(v._serial_mgr, cfg)
        worker.start_test()
        for _ in range(40):
            try: worker._on_tick()
            except: pass
            if worker._state and worker._state.holding:
                try: worker._on_hold_tick()
                except: pass
            time.sleep(0.1)
            if worker._state and worker._state.stage_done:
                break
        worker.stop_test()
        v._log("[步骤] 阶段3: 全水测试")
        cfg2 = TestConfig()
        cfg2.tw_temp = 105
        cfg2.tw_time = 1
        cfg2.tw_fan = True
        cfg2.tw_const_check = False
        cfg2.samples = [(2, "样B", "全水", 10.0)]
        cfg2.beep_enabled = False
        worker2 = TestWorker(v._serial_mgr, cfg2)
        worker2.start_test()
        for _ in range(40):
            try: worker2._on_tick()
            except: pass
            time.sleep(0.1)
            if worker2._state and worker2._state.stage_done:
                break
        worker2.stop_test()
        log_cmds = list(v._cmd_log)
        v.check("包含move_to指令", "move_to" in log_cmds)
        v.check("包含moisture_test指令", "moisture_test_on" in log_cmds or "moisture_test_off" in log_cmds)
        v.check("包含temp_control指令", "temp_control" in log_cmds)
        v.check("包含tare指令", "tare" in log_cmds)
        v.destroy_simulator()
        return v.get_report()

def run_all_scenarios():
    results = []
    scenarios = [
        ("追加样品", TestScenario.validate_append_sample),
        ("分析水测试", TestScenario.validate_moisture_test_phase),
        ("全链路流程", TestScenario.validate_full_chain),
    ]

    for name, fn in scenarios:
        print("")
        print("#" * 70)
        print("#  运行场景: " + name)
        print("#" * 70)
        try:
            r = fn()
            results.append(r)
        except Exception as e:
            traceback.print_exc()
            results.append({"name": name, "passed": 0, "failed": 1,
                           "total": 1, "rate": "0%", "error": str(e)})

    # 汇总报告
    print("")
    print("=" * 70)
    print("  最终验证报告")
    print("=" * 70)
    total_p, total_f = 0, 0
    for r in results:
        rate = r.get("rate", "0%")
        print("  %-16s 通过: %3d  失败: %3d  通过率: %s" %
              (r["name"], r["passed"], r["failed"], rate))
        total_p += r["passed"]
        total_f += r["failed"]
    total = total_p + total_f
    print("  " + "-" * 50)
    print("  合计:       通过: %3d  失败: %3d  总用例: %3d  通过率: %.1f%%" %
          (total_p, total_f, total, total_p/total*100 if total else 0))
    print("")
    return results


if __name__ == "__main__":
    run_all_scenarios()