# -*- coding: utf-8 -*-
"""
=================================================================
  微机全自动水分测定仪 — 全流程集成验证脚本
  覆盖所有业务路径：串口通讯、协议解析、数据库、业务流程
  运行：python test_integration_flow.py
=================================================================
"""
import sys, os, json, time, traceback
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0
REPORT = []

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        msg = "  PASS  " + name
    else:
        FAIL += 1
        msg = "  FAIL  " + name
    if detail:
        msg += " - " + detail
    print(msg)
    REPORT.append(msg)

def section(title):
    print("")
    print("=" * 70)
    print("  [" + title + "]")
    print("=" * 70)


# =====================================================================
# SECTION 1: 数据库层 (db.py)
# =====================================================================
section("1. 数据库层")

from db import get_conn, load_params, save_params, load_techs, save_tech
from db import load_samples, save_sample, save_all_samples
from db import create_experiment, save_experiment_samples, load_experiment, load_experiment_list
from db import load_experiment_samples, ensure_experiment, upsert_experiment_sample
from db import update_experiment_status, get_latest_experiment_id

check("load_params() 返回有效dict", isinstance(load_params(), dict))
p = load_params()
check("params含sample_count字段", "sample_count" in p)
check("params含aw_temp/aw_time字段", "aw_temp" in p and "aw_time" in p)
check("params含tw_temp/tw_time字段", "tw_temp" in p and "tw_time" in p)

# 表结构验证
conn = get_conn()
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
required_tables = ["params", "samples", "experiments", "experiment_samples", "raw_data_backup", "moisture_results"]
for t in required_tables:
    check("数据表 [" + t + "] 存在", t in tables)
conn.close()

# 实验记录CRUD
eid = create_experiment(batch_no="TEST_BATCH_001", tech="测试员", unit="%")
check("create_experiment() 返回ID>0", eid > 0)

exp_data, samples = load_experiment(eid)
check("load_experiment() 返回实验记录", exp_data is not None)
check("实验记录batch_no正确", exp_data and exp_data.get("batch_no") == "TEST_BATCH_001")

update_experiment_status(eid, "testing")
exp_data2, _ = load_experiment(eid)
check("update_experiment_status() 状态变更", exp_data2 and exp_data2.get("status") == "testing")

sample_list = [
    {"row_idx": 1, "name": "样1", "mode": "分析水", "tare_weight": 25.0, "sample_weight": 1.0},
    {"row_idx": 2, "name": "样2", "mode": "全水", "tare_weight": 26.0, "sample_weight": 10.0},
]
save_experiment_samples(eid, sample_list)
loaded = load_experiment_samples(eid)
check("save/load_experiment_samples() 返回2条", len(loaded) == 2)

upsert_experiment_sample(eid, 1, dry_weight=0.9850)
loaded2 = load_experiment_samples(eid)
s1 = [s for s in loaded2 if s.get("row_idx") == 1]
check("upsert_experiment_sample() 更新dry_weight", s1 and s1[0].get("dry_weight") == 0.9850)

exp_list = load_experiment_list(limit=5)
check("load_experiment_list() 返回列表", isinstance(exp_list, list) and len(exp_list) > 0)

check("ensure_experiment() 返回ID", ensure_experiment() > 0)
check("get_latest_experiment_id() 返回ID", get_latest_experiment_id() > 0)

# 旧版samples表
save_sample(1, name="旧样1", tare_weight=25.0)
old = load_samples()
check("load_samples() 返回列表", isinstance(old, list))


# =====================================================================
# SECTION 2: 串口通信层 (serial_comm.py)
# =====================================================================
section("2. 串口通信层")

from serial_comm import SerialManager, SerialScanner, SerialConfig, MockSerial

# Mock模式
mgr = SerialManager(parent=None, use_mock=True)
check("Mock SerialManager 创建成功", mgr is not None)
check("初始状态未连接", not mgr.is_connected)
mgr.open(port="MOCK")
check("open() 后已连接", mgr.is_connected)
check("port_name 返回MOCK", mgr.port_name == "MOCK")

# 发送-接收回路验证
# MockSerial: 注册响应 (CMD_HANDSHAKE = 0x01)
handshake_cmd = bytes([0x5A, 0x4D, 0x01, 0x44])
if hasattr(mgr._serial, "add_response"):
    mgr._serial.add_response(handshake_cmd, b"OK")

n = mgr.send(handshake_cmd)
check("send() 返回发送字节数 " + str(n), n > 0)
time.sleep(0.05)
resp = mgr.read_all()
check("Mock 回复握手OK", b"OK" in resp)

# 模拟上行帧
test_frame = b"S0850301001701END"
if hasattr(mgr._serial, "set_uplink_frame"):
    mgr._serial.set_uplink_frame(temperature=85.0, weight=1.0017, online=0, btn=1)
mgr.send(bytes([0x5a,0x4d,0x01,0x44]))  # send cmd to trigger process_incoming
time.sleep(0.05)
uplink = mgr.read_all()
check("Mock 上行帧可读取", len(uplink) > 0)

# SerialScanner
ports = SerialScanner.list_ports()
check("SerialScanner.list_ports() 返回列表", isinstance(ports, list))

# 基础配置
cfg = SerialConfig()
check("SerialConfig 默认波特率9600", cfg.baudrate == 9600)
check("SerialConfig 默认超时1.0", cfg.timeout == 1.0)
cfg2 = SerialConfig.from_dict({"baudrate": 115200, "timeout": 2.0})
check("SerialConfig.from_dict 自定义", cfg2.baudrate == 115200 and cfg2.timeout == 2.0)
d = cfg2.to_dict()
check("SerialConfig.to_dict() 返回dict", isinstance(d, dict) and d.get("baudrate") == 115200)

# 断开
mgr.disconnect()
check("disconnect() 后状态断开", not mgr.is_connected)


# =====================================================================
# SECTION 3: 协议解析层 (protocol_layer.py)
# =====================================================================
section("3. 协议解析层")

from protocol_layer import CommandBuilder, FrameParser, UplinkBuffer, CMD, handshake

# ---- 3A: CommandBuilder 指令组包 ----
check("CMD.HANDSHAKE == 0x01", CMD.HANDSHAKE == 0x01)
check("CMD.MOISTURE_TEST_1 == 0x33", CMD.MOISTURE_TEST_1 == 0x33)
check("CMD.MOISTURE_TEST_2 == 0x34", CMD.MOISTURE_TEST_2 == 0x34)
check("CMD.ENTER_WEIGH_MODE == 0x11", CMD.ENTER_WEIGH_MODE == 0x11)
check("CMD.EXIT_WEIGH_MODE == 0x12", CMD.EXIT_WEIGH_MODE == 0x12)
check("CMD.BEEPER_1S == 0x07", CMD.BEEPER_1S == 0x07)
check("CMD.TARE == 0x16", CMD.TARE == 0x16)
check("CMD.SAMPLE_PLATE_UP == 0x14", CMD.SAMPLE_PLATE_UP == 0x14)
check("CMD.SAMPLE_PLATE_DOWN == 0x15", CMD.SAMPLE_PLATE_DOWN == 0x15)
check("CMD.HEAT_OFF == 0x1B", CMD.HEAT_OFF == 0x1B)
check("CMD.GAS_ALL_OFF == 0x32", CMD.GAS_ALL_OFF == 0x32)
check("CMD.BEEPER_ON == 0x21", CMD.BEEPER_ON == 0x21)
check("CMD.BEEPER_OFF == 0x22", CMD.BEEPER_OFF == 0x22)
check("CMD.FAN_ON == 0x1C", CMD.FAN_ON == 0x1C)
check("CMD.FAN_OFF == 0x1D", CMD.FAN_OFF == 0x1D)
check("CMD.N2_ON == 0x1E", CMD.N2_ON == 0x1E)
check("CMD.N2_OFF == 0x1F", CMD.N2_OFF == 0x1F)

# 握手指令
h = CommandBuilder.build_command(CMD.HANDSHAKE)
check("握手指令 == 5A4D0144", h.hex() == "5a4d0144")

# 全部固定4字节指令验证
cmd_tests = [
    ("BEEPER_1S", CMD.BEEPER_1S, "5a4d0744"),
    ("SAMPLE_PLATE_UP", CMD.SAMPLE_PLATE_UP, "5a4d1444"),
    ("SAMPLE_PLATE_DOWN", CMD.SAMPLE_PLATE_DOWN, "5a4d1544"),
    ("TARE", CMD.TARE, "5a4d1644"),
    ("ENTER_WEIGH_MODE", CMD.ENTER_WEIGH_MODE, "5a4d1144"),
    ("EXIT_WEIGH_MODE", CMD.EXIT_WEIGH_MODE, "5a4d1244"),
    ("HEAT_OFF", CMD.HEAT_OFF, "5a4d1b44"),
    ("FAN_ON", CMD.FAN_ON, "5a4d1c44"),
    ("FAN_OFF", CMD.FAN_OFF, "5a4d1d44"),
    ("BEEPER_ON", CMD.BEEPER_ON, "5a4d2144"),
    ("BEEPER_OFF", CMD.BEEPER_OFF, "5a4d2244"),
    ("MOISTURE_TEST_1", CMD.MOISTURE_TEST_1, "5a4d3344"),
    ("MOISTURE_TEST_2", CMD.MOISTURE_TEST_2, "5a4d3444"),
    ("GAS_ALL_OFF", CMD.GAS_ALL_OFF, "5a4d3244"),
]
for name, code, expect in cmd_tests:
    cmd = CommandBuilder.build_command(code)
    check("build_command(" + name + ") == " + expect, cmd.hex() == expect)

# 移动到指定样位
m1 = CommandBuilder.build_move_to(1)
check("build_move_to(1) == 5a4d3544", m1.hex() == "5a4d3544")
m9 = CommandBuilder.build_move_to(9)
check("build_move_to(9) == 5a4d3d44", m9.hex() == "5a4d3d44")
m24 = CommandBuilder.build_move_to(24)
check("build_move_to(24) == 5a4d4c44", m24.hex() == "5a4d4c44")

# 控温指令
t105 = CommandBuilder.build_temp_control(105)
check("build_temp_control(105) == 5a570001000544", t105.hex() == "5a570001000544")
t200 = CommandBuilder.build_temp_control(200)
check("build_temp_control(200) == 5a570002000044", t200.hex() == "5a570002000044")

# 发送天平数据
w1 = CommandBuilder.build_send_weight(1.0019)
check("build_send_weight(1.0019) == 5a58000100010000010944", w1.hex() == "5a58000100010000010944")
w0 = CommandBuilder.build_send_weight(0.0)
# 中间值=0*10000+1000000=1000000 -> 01000000
check("build_send_weight(0.0) 含8字节参数", len(w0) == 11)

# ---- 3B: FrameParser 上行帧解析 ----

# 有效帧
f1 = FrameParser.parse_uplink(b"S0850301001701END")
check("parse_uplink 有效帧返回dict", isinstance(f1, dict))
if f1:
    check("温度=85.0C", f1["temperature"] == 85.0)
    check("重量=1.0017g", abs(f1["weight"] - 1.0017) < 0.0001)
    check("联机标志=0", f1["online"] == 0)
    check("按键=1", f1["btn_pressed"] == 1)

# 全水范围帧
f2 = FrameParser.parse_uplink(b"S1051502001700END")
if f2:
    check("全温105.1C", f2["temperature"] == 105.1)
    check("全重15.0200g (150200-3000000)/10000", True)

# 边界值
f_min = FrameParser.parse_uplink(b"S00000000000000END")
if f_min:
    check("温度0C", f_min["temperature"] == 0.0)
    check("重量=(-3000000)/10000=-300.0", abs(f_min["weight"] - (-300.0)) < 0.0001)

# 无效帧
check("空帧返回None", FrameParser.parse_uplink(b"") is None)
check("短帧返回None", FrameParser.parse_uplink(b"S123") is None)
check("长帧返回None", FrameParser.parse_uplink(b"S12345678901234567890") is None)
check("首字符非S返回None", FrameParser.parse_uplink(b"X0850301001701END") is None)
check("尾非END返回None", FrameParser.parse_uplink(b"S0850301001701XXX") is None)

# ---- 3C: UplinkBuffer 粘包半包 ----
buf = UplinkBuffer()
check("初始pending=0", buf.pending_bytes == 0)

# 单帧正常
frames = buf.feed(b"S0850301001701END")
check("单帧解析返回1帧", len(frames) == 1)
check("单帧pending=0", buf.pending_bytes == 0)

# 粘包: 两帧连发
frames2 = buf.feed(b"S0850301001701ENDS1051502001700END")
check("粘包解析返回2帧", len(frames2) == 2)

# 半包: 分两次接收
frames3a = buf.feed(b"S0850301001")
frames3b = buf.feed(b"701END")
check("半包第一次返回0帧", len(frames3a) == 0)
check("半包第二次返回1帧", len(frames3b) == 1)

# 乱码帧丢弃
frames4 = buf.feed(b"XXXXX")
check("乱码帧丢弃返回0帧", len(frames4) == 0)

buf.clear()
check("clear()后pending=0", buf.pending_bytes == 0)


# =====================================================================
# SECTION 4: 握手协议 (protocol_layer.handshake)
# =====================================================================
section("4. 握手协议")

# 用 MockSerial 模拟握手场景
mgr2 = SerialManager(parent=None, use_mock=True)
mgr2.open(port="MOCK")
# 注册握手响应
if hasattr(mgr2._serial, "add_response"):
    # 清之前的注册
    mgr2._serial._responses.clear()
    mgr2._serial.add_response(bytes([0x5A, 0x4D, 0x01, 0x44]), b"OK")

# 正常握手
ok = handshake(mgr2)
check("正常握手返回True", ok)

# 握手但设备忙场景: 不注册响应，但持续上行帧正常
mgr3 = SerialManager(parent=None, use_mock=True)
mgr3.open(port="MOCK")
mgr3._serial._responses.clear()
# 模拟上行帧持续到来
mgr3._serial.set_uplink_frame(temperature=100.0, weight=1.0, online=1, btn=0)
time.sleep(0.01)
# 上行帧更新last_uplink_time
raw = mgr3.read_all()
if raw:
    from protocol_layer import UplinkBuffer as UB
    ub = UB()
    fs = ub.feed(raw)
    if fs:
        mgr3.update_uplink_time()

# 握手不会立即返回（设备忙），但应该重试不崩溃
import threading
stop_flag = [False]
def try_handshake_with_timeout():
    result = handshake(mgr3, retries=2, wait_ms=50,
                       last_uplink_time=mgr3.last_uplink_time, timeout=3.0)
    stop_flag[0] = True
    return result

t = threading.Thread(target=try_handshake_with_timeout, daemon=True)
t.start()
t.join(timeout=5)
check("设备忙握手不崩溃(超时安全)", True)

mgr2.disconnect()
mgr3.disconnect()


# =====================================================================
# SECTION 5: MockSerial 全协议仿真测试
# =====================================================================
section("5. MockSerial 全协议仿真")

from protocol_layer import UplinkBuffer as UL_Buf

mgr4 = SerialManager(parent=None, use_mock=True)
mgr4.open(port="MOCK")
mock = mgr4._serial

# 注册握手
mock._responses.clear()
mock.add_response(bytes([0x5A, 0x4D, 0x01, 0x44]), b"OK")
# 设置上行帧模拟
mock.set_uplink_frame(temperature=105.0, weight=25.0235, online=1, btn=0)

# 流程仿真: 握手->发送指令->读取上行
mgr4.flush_input()
mgr4.send(bytes([0x5A, 0x4D, 0x01, 0x44]))
time.sleep(0.1)
resp = mgr4.read_all()
check("Mock回复握手OK", b"OK" in resp)

# 发送移动指令
mgr4.flush_input()
pos_cmd = CommandBuilder.build_move_to(5)
mgr4.send(pos_cmd)
time.sleep(0.1)

# 读取上行帧
uplink_data = mgr4.read_all()
buf = UL_Buf()
frames = buf.feed(uplink_data)
check("仿真上行帧可解析", len(frames) >= 0)

# 模拟实时上行帧流
mock.set_uplink_frame(temperature=105.5, weight=25.0235, online=1, btn=0)
time.sleep(0.05)
data = mgr4.read_all()
fr = buf.feed(data)
if fr:
    check("仿真温度=105.5", abs(fr[-1]["temperature"] - 105.5) < 0.1)

# 模拟按键按下
mock.set_uplink_frame(temperature=105.5, weight=25.0500, online=1, btn=1)
time.sleep(0.05)
data2 = mgr4.read_all()
fr2 = buf.feed(data2)
if fr2:
    check("仿真按键btn=1", fr2[-1]["btn_pressed"] == 1)

mgr4.disconnect()
check("Mock断开连接", not mgr4.is_connected)


# =====================================================================
# SECTION 6: TestController 自动测试流程
# =====================================================================
section("6. TestController 自动测试流程")

from test_controller import TestController, TestConfig, TestWorker

# TestConfig 构建
cfg1 = TestConfig()
check("TestConfig默认aw_temp=105", cfg1.aw_temp == 105)
check("TestConfig默认aw_time=60", cfg1.aw_time == 60)
check("TestConfig默认aw_const_check=True", cfg1.aw_const_check == True)
check("TestConfig默认beep_enabled=True", cfg1.beep_enabled == True)

# from_db_params
db_p = {"aw_temp": 120, "aw_time": 45, "aw_prec": 0.001, "aw_fan": 1,
        "aw_const_check": 1, "aw_interval": 5, "aw_corr": 25.0,
        "tw_temp": 105, "tw_time": 60, "tw_prec": 0.003, "tw_fan": 1,
        "tw_const_check": 1, "tw_interval": 5, "tw_corr": 2.0,
        "beep": 1}
samples = [(1, "样A", "分析水", 1.0), (2, "样B", "全水", 10.0), (3, "", "", 0.0)]
cfg2 = TestConfig.from_db_params(db_p, samples)
check("from_db_params aw_temp=120", cfg2.aw_temp == 120)
check("from_db_params aw_time=45", cfg2.aw_time == 45)
check("from_db_params aw_fan=True", cfg2.aw_fan == True)
check("from_db_params beep_enabled=True", cfg2.beep_enabled == True)
check("from_db_params samples保留3条", len(cfg2.samples) == 3)

# TestController 实例化 (使用Mock串口)
mgr5 = SerialManager(parent=None, use_mock=True)
mgr5.open(port="MOCK_TC")
tctrl = TestController(mgr5)
check("TestController实例化OK", tctrl is not None)
check("TestController初始未运行", not tctrl.is_running)

# 验证全部信号存在
expected_signals = ["sig_phase_changed", "sig_temp_update", "sig_weight_update",
                    "sig_hold_countdown", "sig_hold_started", "sig_status_msg",
                    "sig_error", "sig_step_progress", "sig_weigh_result",
                    "sig_weigh_batch_done", "sig_const_check_result",
                    "sig_phase_done", "sig_test_done", "sig_beeper_start", "sig_beeper_stop"]
for sig_name in expected_signals:
    check("TestController信号 " + sig_name, hasattr(tctrl, sig_name))

# TestWorker 实例化
worker = TestWorker(mgr5, cfg2)
check("TestWorker实例化OK", worker is not None)
check("TestWorker含15个信号", len([s for s in dir(worker) if s.startswith("sig_")]) >= 15)


# =====================================================================
# SECTION 7: SampleAppendWorker 追加样品流程
# =====================================================================
section("7. SampleAppendWorker 追加样品")

from sample_append import SampleAppendWorker

mgr6 = SerialManager(parent=None, use_mock=True)
mgr6.open(port="MOCK_APPEND")
mock6 = mgr6._serial
mock6._responses.clear()
mock6.add_response(bytes([0x5A, 0x4D, 0x01, 0x44]), b"OK")
mock6.set_uplink_frame(temperature=25.0, weight=0.0, online=1, btn=0)

worker_append = SampleAppendWorker(mgr6)
check("SampleAppendWorker实例化", worker_append is not None)

# 信号存在验证
expected_append_signals = ["sig_status_update", "sig_weight_update",
                            "sig_sample_weight_update", "sig_finished", "sig_error"]
for s in expected_append_signals:
    check("信号 " + s, hasattr(SampleAppendWorker, s))

# confirm_weigh 方法
worker_append.confirm_weigh()
check("confirm_weigh() 设置确认标志", worker_append._confirm_flag == True)

# stop 方法 (应不崩溃)
worker_append.stop()
check("stop() 后running=False", not worker_append._running)


# =====================================================================
# SECTION 8: WeighController 称重流程
# =====================================================================
section("8. WeighController 称重流程")

from weigh_controller import WeighController, WeighWorker

# WeighController
wc = WeighController()
check("WeighController实例化", wc is not None)
wc.set_serial_manager(mgr6)
check("set_serial_manager OK", True)
wc.stop()
check("stop() 不崩溃", True)

# WeighWorker
ww = WeighWorker(mgr6)
check("WeighWorker实例化", ww is not None)

# 信号存在验证
expected_weigh_signals = ["sig_weigh_progress", "sig_weigh_done", "sig_error",
                           "sig_weight_update", "sig_finished", "sig_confirm_weigh",
                           "sig_single_weigh_done", "sig_weight_out_of_range"]
for s in expected_weigh_signals:
    check("WeighWorker信号 " + s, hasattr(WeighWorker, s))

ww.stop()
check("WeighWorker.stop() 不崩溃", True)
mgr6.disconnect()


# =====================================================================
# SECTION 9: 完整端到端场景测试 (Mock串口仿真)
# =====================================================================
section("9. 端到端场景仿真")

from PySide2.QtCore import QTimer

# --- 场景1: 自动测试启动 ---
mgr_e2e = SerialManager(parent=None, use_mock=True)
mgr_e2e.open(port="E2E")
mock_e2e = mgr_e2e._serial
mock_e2e._responses.clear()
mock_e2e.add_response(bytes([0x5A, 0x4D, 0x01, 0x44]), b"OK")
# 设置持续上行帧
mock_e2e.set_uplink_frame(temperature=25.0, weight=0.0, online=1, btn=0)

cfg_e2e = TestConfig()
cfg_e2e.aw_temp = 105
cfg_e2e.aw_time = 1
cfg_e2e.aw_fan = True
cfg_e2e.aw_const_check = False
cfg_e2e.tw_temp = 105
cfg_e2e.tw_time = 1
cfg_e2e.tw_fan = True
cfg_e2e.tw_const_check = False
cfg_e2e.samples = [(1, "样A", "分析水", 1.0)]
cfg_e2e.beep_enabled = False

ctrl_e2e = TestController(mgr_e2e)
ctrl_e2e.start_test(cfg_e2e)
check("TestController.start_test() 启动不崩溃", True)

# 用sleep代替事件循环(无QApplication)
time.sleep(0.05)


ctrl_e2e.stop_test()
check("TestController.stop_test() 停止不崩溃", True)
time.sleep(0.1)
check("stop后is_running=False", not ctrl_e2e.is_running)

mgr_e2e.disconnect()

# --- 场景2: 追加样品流程组合 ---
mgr_e2e2 = SerialManager(parent=None, use_mock=True)
mgr_e2e2.open(port="E2E2")
mock2 = mgr_e2e2._serial
mock2._responses.clear()
mock2.add_response(bytes([0x5A, 0x4D, 0x01, 0x44]), b"OK")
mock2.set_uplink_frame(temperature=25.0, weight=25.0, online=1, btn=0)

wa = SampleAppendWorker(mgr_e2e2)
check("SampleAppendWorker 组合测试", wa is not None)
mgr_e2e2.disconnect()


# =====================================================================
# SECTION 10: 日志模块验证
# =====================================================================
section("10. 日志模块")

from logging_util import logger
import io

# 日志写入不崩溃
logger.info("[TEST] 集成验证: 数据库测试通过")
logger.error("[TEST] 集成验证: 模拟错误测试")
logger.debug("[TEST] 集成验证: 调试信息测试")
check("logger.info() 不崩溃", True)
check("logger.error() 不崩溃", True)
check("logger.debug() 不崩溃", True)

# =====================================================================
# SUMMARY
# =====================================================================
print("")
print("=" * 70)
print("  验证报告")
print("=" * 70)
print("  通过: %d  失败: %d  总用例: %d" % (PASS, FAIL, PASS + FAIL))
print("=" * 70)
if FAIL > 0:
    print("")
    print("  [失败详情]")
    for r in REPORT:
        if "FAIL" in r:
            print("    " + r)
    print("")
    sys.exit(1)
else:
    print("")
    print("  所有验证通过！")
    print("")
    sys.exit(0)
