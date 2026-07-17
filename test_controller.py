# -*- coding: utf-8 -*-
# ============================================================
# @CRAFT-MARKER: 开始测试 | 分析水 | 全水
# 快速定位标记 - 请勿删除
# ============================================================
"""测试流程控制器 - 微机全自动水分测定仪
分析水/全水测试主流程
自动完成升温-恒温-降温-称量-恒重检查全流程
支持分析水和全水两种测试模式(串行执行)
依赖: protocol_layer.py, serial_comm.py, db.py
驱动: QTimer定时 + 状态机
"""

import time
from PySide2.QtCore import QObject, Signal, QTimer
from PySide2.QtWidgets import QApplication
from protocol_layer import CommandBuilder, CMD, UplinkBuffer
from logging_util import logger

# ===== 加速模式(Mock调试用) =====
import os as _os
SPEED_MODE = _os.environ.get('WATER_SPEED_MODE', '0') == '1'


def _ts(val_normal, val_fast):
    """时间缩放: WATER_SPEED_MODE=1 时使用快速值"""
    return val_fast if SPEED_MODE else val_normal


CMD_INTERVAL_S = _ts(0.15, 0.05)
STABLE_WEIGHT_SAMPLES = _ts(15, 3)
STABLE_TOLERANCE = _ts(0.0005, 0.01)
UPLINK_TIMEOUT_S = _ts(3.0, 1.0)
CMD_REPEAT_INTERVAL_S = _ts(30, 3)
BEEPER_DURATION_S = _ts(10, 2)


def _log(msg):
    logger.info("[TEST] " + msg)


class TestConfig:
    """测试参数配置容器"""

    def __init__(self):
        # 分析水参数
        self.aw_temp = 105
        self.aw_time = 60
        self.aw_precision = 0.0010
        self.aw_fan = False
        self.aw_const_check = True
        self.aw_interval = 5
        self.aw_corr_crucible = 0.0
        self.aw_corr_dry = 0.0
        self.aw_tare_weight = 0.0
        # 全水参数
        self.tw_temp = 105
        self.tw_time = 60
        self.tw_precision = 0.0030
        self.tw_fan = True
        self.tw_const_check = True
        self.tw_interval = 5
        self.tw_corr_crucible = 0.0
        self.tw_corr_dry = 0.0
        # 新增: 氮气/鼓风
        self.tw_tare_weight = 0.0
        self.samples = []  # [(row_idx, name, mode, sample_weight), ...]
        self.beep_enabled = True
        self.retest = False  # 开始测试时复检样品重量

    @classmethod
    def from_db_params(cls, db_params, sample_list):
        """从 db.load_params() + 样品列表构建配置"""
        cfg = cls()
        cfg.aw_temp = int(float(db_params.get("aw_temp", 105)))
        cfg.aw_time = int(db_params.get("aw_time", 60))
        cfg.aw_precision = float(db_params.get("aw_prec", 0.0010))
        cfg.aw_fan = bool(db_params.get("aw_fan", 0))
        cfg.aw_const_check = bool(db_params.get("aw_const_check", 1))
        cfg.aw_interval = int(db_params.get("aw_interval", 5))
        cfg.aw_corr_crucible = float(db_params.get("aw_corr", 0.0))
        cfg.aw_corr_dry = 0.0
        cfg.tw_temp = int(float(db_params.get("tw_temp", 105)))
        cfg.tw_time = int(db_params.get("tw_time", 60))
        cfg.tw_precision = float(db_params.get("tw_prec", 0.0030))
        cfg.tw_fan = bool(db_params.get("tw_fan", 1))
        cfg.tw_const_check = bool(db_params.get("tw_const_check", 1))
        cfg.tw_interval = int(db_params.get("tw_interval", 5))
        cfg.tw_corr_crucible = float(db_params.get("tw_corr", 0.0))
        cfg.tw_corr_dry = 0.0
        cfg.beep_enabled = bool(db_params.get("beep", 1))
        cfg.retest = bool(int(db_params.get("retest", 0)))
        cfg.samples = list(sample_list) if sample_list else []
        return cfg


class TestPhaseState:
    """测试阶段运行时状态"""
    def __init__(self, cfg):
        self.cfg = cfg
        self.samples = []  # [(row_idx, name, mode, sample_weight), ...]
        self.holding = False
        self.hold_elapsed = 0.0
        self.hold_target = 0.0
        self.last_cmd_time = 0.0
        self.stage_done = False
        self.cycle_count = 0


# ============================================================
# 状态机阶段常量
# ============================================================
class _Phase:
    """状态机阶段常量"""
    INITIAL_WEIGH = "initial_weigh"
    BRANCH_AW = "branch_aw"
    DRY_AW = "dry_aw"
    WRAP_AW = "wrap_aw"
    BRANCH_TW = "branch_tw"
    DRY_TW = "dry_tw"
    CALC_SAVE = "calc_save"
    DONE = "done"

    # 中文显示映射
    CN = {
        INITIAL_WEIGH: "初始称重",
        BRANCH_AW: "分析水分支",
        DRY_AW: "分析水烘干",
        WRAP_AW: "分析水收尾",
        BRANCH_TW: "全水分支",
        DRY_TW: "全水烘干",
        CALC_SAVE: "结果计算",
        DONE: "测试完成",
    }


class _DrySubState:
    """烘干恒重子流程状态"""
    START = 0
    TEMP_PATROL = 1
    HOLD = 2
    WEIGH = 3
    CONST_CHECK = 4


TEMP_PATROL_INTERVAL_S = _ts(10, 3)

class TestWorker(QObject):
    """测试执行器 - QTimer驱动状态机"""

    sig_phase_changed = Signal(str)
    sig_temp_update = Signal(float)
    sig_weight_update = Signal(float)
    sig_hold_countdown = Signal(int)
    sig_hold_started = Signal(int)
    sig_status_msg = Signal(str)
    sig_error = Signal(str)
    sig_step_progress = Signal(str)
    sig_weigh_result = Signal(int, float, str)  # (row_idx, dry_weight, phase)
    sig_weigh_batch_done = Signal(str)
    sig_const_check_result = Signal(int, bool, float, float)
    sig_phase_done = Signal(str)
    sig_test_done = Signal()
    sig_beeper_start = Signal()
    sig_beeper_stop = Signal()
    # 新增: 初始称重信号
    sig_initial_weight = Signal(int, int, float)  # row_idx, col, value
    sig_initial_weigh_done = Signal()

    def __init__(self, serial_mgr, config, parent=None):
        super().__init__(parent)
        self._serial = serial_mgr
        self.cfg = config
        self._running = False
        self._paused = False
        self._phase = ""
        self._state = None
        self._uplink_buf = UplinkBuffer()
        self._last_uplink_time = time.time()
        self._current_temp = 0.0
        self._current_weight = 0.0
        # 状态机
        self._phase = ""
        self._dry_sub_state = _DrySubState.START
        self._dry_cycle = 0
        self._samples = []
        self._temp_target = 0
        self._initial_weights = {}
        self._tare_offset = 0.0       # 坩埚校正差值
        self._table_ref = None         # 主表格引用

        # 10s交替指令: 控温/开始测试
        self._cmd_is_temp = False
        # 温度巡检
        self._last_patrol_time = 0.0
        self._patrol_timer = QTimer(self)
        self._patrol_timer.timeout.connect(self._on_patrol_tick)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._tick_interval_ms = 200
        self._hold_timer = QTimer(self)
        self._hold_timer.timeout.connect(self._on_hold_tick)

    def set_table(self, table_widget):
        """设置主表格引用(用于获取校正坩埚名等)"""
        self._table_ref = table_widget

    # ========= 公共接口 =========

    def start_test(self):
        """启动测试 - 进入状态机"""
        _log("测试开始")
        self._running = True
        self._paused = False
        self._phase = ""
        self._initial_weights = {}
        # 测试期间禁用主轮询, 避免与 _on_tick 竞争串口数据(mock模式关键)
        self._serial.set_bypass_poll(True)
        self._timer.start(self._tick_interval_ms)
        # retest=1: 复检样品重量 → 初始称重; retest=0: 跳过 → 直接进分析水分支
        if self.cfg.retest:
            self._transition(_Phase.INITIAL_WEIGH)
        else:
            self._transition(_Phase.BRANCH_AW)

    def stop_test(self):
        """停止测试 - 关闭加热/气体/蜂鸣"""
        _log("测试停止")
        self._running = False
        self._paused = False
        self._timer.stop()
        self._hold_timer.stop()
        self._patrol_timer.stop()
        self._serial.set_bypass_poll(False)
        self._safe_send_cmd(CMD.HEAT_OFF, "关闭加热")
        self._safe_send_cmd(CMD.FAN_OFF, "关鼓风")
        self._safe_send_cmd(CMD.N2_OFF, "关氮气")
        self._safe_send_cmd(CMD.GAS_ALL_OFF, "关闭全部气体")
        self._safe_send_cmd(CMD.BEEPER_OFF, "关蜂鸣")
        self._safe_send_cmd(CMD.RESET, "仪器复位")

    def pause_test(self):
        self._paused = True
        _log("测试暂停")

    def resume_test(self):
        self._paused = False
        _log("测试恢复")

    @property
    def is_running(self):
        return self._running

    # ================================================================
    # 状态机转换
    # ================================================================

    def _transition(self, phase):
        """状态转换入口"""
        if not self._running:
            return
        self._phase = phase
        self.sig_phase_changed.emit(_Phase.CN.get(phase, phase))
        _log("状态切换: " + phase)

        dispatch = {
            _Phase.INITIAL_WEIGH: self._step_initial_weigh,
            _Phase.BRANCH_AW: self._step_branch_aw,
            _Phase.DRY_AW: self._step_dry_start,
            _Phase.WRAP_AW: self._step_wrap_aw,
            _Phase.BRANCH_TW: self._step_branch_tw,
            _Phase.DRY_TW: self._step_dry_start,
            _Phase.CALC_SAVE: self._step_calc_save,
            _Phase.DONE: self._step_done,
        }
        fn = dispatch.get(phase)
        if fn:
            QTimer.singleShot(_ts(50, 10), fn)
        else:
            _log("未知阶段: " + phase)

    # ================================================================
    # 步骤1: 初始称重(retest=1, 完整批量称重流程)
    # ================================================================

    def _step_initial_weigh(self):
        """复检样品重量: 关盖→倒计时→跳过坩埚称重→直接称样品→不开盖不抬盘→写入表格"""
        self.sig_step_progress.emit("复检称重...")
        self.sig_status_msg.emit("正在复检称重...")
        _log("步骤1: 复检称重, 样品数=%d" % len(self.cfg.samples))

        if not self.cfg.samples:
            _log("复检称重: 无样品, 跳过")
            self._transition(_Phase.BRANCH_AW)
            return

        sample_rows = [(r, n, m, s) for r, n, m, s in self.cfg.samples]

        # 关炉盖 + 逐秒倒计时(真机15s, mock 3s)
        self._send_cmd_code_with_uplink_check(CMD.CLOSE_LID, "关炉盖(复检准备)")
        lid_wait = int(_ts(15, 3))
        for remaining in range(lid_wait, 0, -1):
            if not self._running:
                return
            self.sig_status_msg.emit("正在关闭炉盖倒计时 %ds" % remaining)
            QApplication.processEvents()  # 强制刷新UI, 避免sleep阻塞事件循环
            time.sleep(1)

        # 跳过坩埚称重和开盖放样, 直接称样品(坩埚重从DB读取)
        self._send_cmd_code_with_uplink_check(CMD.ENTER_WEIGH_MODE, "进入称重模式(复检)")
        self.sig_status_msg.emit("正在称样品重...")
        QApplication.processEvents()
        for row_idx, name, mode, sample_weight in sample_rows:
            if not self._running:
                return
            # 行0校正坩埚: 样重=天平读数, 不减坩埚重
            tare = 0.0 if row_idx == 0 else self._get_tare_from_db(row_idx)

            self.sig_status_msg.emit("正在复检%d号样品重量：" % (row_idx + 1))
            QApplication.processEvents()
            # 实时回调: 等待稳定期间每秒推送当前净重到UI
            t = tare  # 闭包捕获
            ridx = row_idx
            def _on_weight_sample(w):
                net = round(w - t, 4) if t else round(w, 4)
                self.sig_status_msg.emit("正在复检%d号样品重量：%.4fg" % (ridx + 1, net))
                QApplication.processEvents()  # 强制刷新UI
            total = self._weigh_single(row_idx, name, tare, desc="复检样品", progress_cb=_on_weight_sample, timeout=_ts(15.0, 5.0), min_duration=_ts(5.0, 5.0))
            if total is not None:
                sample_net = round(total, 4)
                self._backfill_table(row_idx, 3, sample_net)  # col3=样重
                # 最终值再确认一次显示
                self.sig_status_msg.emit("正在复检%d号样品重量：%.4fg" % (ridx + 1, sample_net))
                QApplication.processEvents()
                _log("复检样品 row=%d name=%s sample=%.4f" % (row_idx, name, sample_net))

        # 不开盖、不抬样盘, 直接进入控温流程(最终测试完成复位时才开盖抬盘)
        _log("复检称重完成, 共 %d 个样品" % len(sample_rows))
        self.sig_initial_weigh_done.emit()
        self._transition(_Phase.BRANCH_AW)

    def _backfill_table(self, row_idx, col, value):
        """实时回填表格指定列 + 同步写 DB"""
        self.sig_initial_weight.emit(row_idx, col, value)
        # 同步写入 experiment_samples, 保证后续流程读到最新值
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            if col == 2:
                upsert_experiment_sample(eid, row_idx, tare_weight=value)
            elif col == 3:
                upsert_experiment_sample(eid, row_idx, sample_weight=value)
        except Exception as e:
            _log("复检DB写入失败: %s" % str(e))

    # ================================================================
    # 步骤3: 分析水分支判断
    # ================================================================

    def _step_branch_aw(self):
        """分析水分支判断"""
        _log("步骤3: 分析水分支判断")

        self._samples = [
            s for s in self.cfg.samples
            if s[1].strip() and (s[2] == "分析水" or not s[2]) and s[3] is not None
        ]
        _log("分析水样品数: %d" % len(self._samples))

        if not self._samples:
            _log("分析水无有效样品, 跳过")
            self._transition(_Phase.WRAP_AW)
            return

        self._dry_cycle = 0
        self._temp_target = self.cfg.aw_temp
        r = self.cfg.aw_time
        self._hold_target = r if SPEED_MODE else r * 60
        self.sig_status_msg.emit("开始分析水测试")
        self._transition(_Phase.DRY_AW)

    # ================================================================
    # 步骤6: 全水分支判断
    # ================================================================

    def _step_branch_tw(self):
        """全水分支判断"""
        _log("步骤6: 全水分支判断")

        self._samples = [
            s for s in self.cfg.samples
            if s[1].strip() and s[2] == "全水" and s[3] is not None
        ]
        _log("全水样品数: %d" % len(self._samples))

        if not self._samples:
            _log("全水无有效样品, 跳过")
            self._transition(_Phase.CALC_SAVE)
            return

        self._dry_cycle = 0
        self._temp_target = self.cfg.tw_temp
        r = self.cfg.tw_time
        self._hold_target = r if SPEED_MODE else r * 60
        self.sig_status_msg.emit("开始全水分测试")
        self._transition(_Phase.DRY_TW)

    # ================================================================
    # 步骤4: 烘干恒重通用子流程(分析水/全水复用)
    # ================================================================

    @property
    def _is_aw(self):
        return self._phase == _Phase.DRY_AW

    @property
    def _dry_cfg_fan(self):
        return self.cfg.aw_fan if self._is_aw else self.cfg.tw_fan

    @property
    def _dry_cfg_temp(self):
        return self.cfg.aw_temp if self._is_aw else self.cfg.tw_temp

    @property
    def _dry_cfg_time(self):
        return self.cfg.aw_time if self._is_aw else self.cfg.tw_time

    @property
    def _dry_cfg_precision(self):
        return self.cfg.aw_precision if self._is_aw else self.cfg.tw_precision

    @property
    def _dry_cfg_const_check(self):
        return self.cfg.aw_const_check if self._is_aw else self.cfg.tw_const_check

    def _step_dry_start(self):
        """烘干启动: 开鼓风/氮气 -> 发控温指令"""
        mode = "分析水" if self._is_aw else "全水"
        self._dry_sub_state = _DrySubState.START
        self._holding = False
        self._hold_elapsed = 0.0
        self._hold_timer.stop()
        self._patrol_timer.stop()

        fan = self._dry_cfg_fan
        temp = self._dry_cfg_temp

        _log("烘干启动: mode=%s cycle=%d fan=%s temp=%d℃" %
             (mode, self._dry_cycle + 1, fan, temp))

        if fan:
            self._safe_send_cmd(CMD.FAN_ON, "开鼓风")

        self.sig_status_msg.emit("%s 第%d轮烘干, 目标%d℃" %
                                  (mode, self._dry_cycle + 1, temp))

        self._cmd_is_temp = False
        cmd = CommandBuilder.build_temp_control(temp)
        self._send_cmd_with_uplink_check(cmd, "控温 %d℃" % temp,
                                          callback=self._send_start_test_and_patrol)

    def _start_temp_patrol(self):
        """开始控温: 10s间隔, 交替发控温/开始测试指令"""
        if not self._running:
            return
        self._dry_sub_state = _DrySubState.TEMP_PATROL
        self._last_patrol_time = time.time()
        self.sig_status_msg.emit("正在控温... 目标%d℃" % self._temp_target)
        _log("正在控温, 目标=%d℃, 间隔=%ds" % (self._temp_target, TEMP_PATROL_INTERVAL_S))
        self._patrol_timer.start(TEMP_PATROL_INTERVAL_S * 1000)

    def _on_patrol_tick(self):
        """升温阶段定时器(每10s): 交替发控温/开始测试+检查温度"""
        if not self._running or self._paused:
            return
        if self._dry_sub_state != _DrySubState.TEMP_PATROL:
            return

        self._cmd_is_temp = not self._cmd_is_temp
        if self._cmd_is_temp:
            cmd = CommandBuilder.build_temp_control(self._temp_target)
            self._send_cmd_with_uplink_check(cmd,
                                              "正在控温: 控温 %d℃" % self._temp_target,
                                              callback=None)
        else:
            test_cmd = CMD.MOISTURE_TEST_1 if self._dry_cfg_fan else CMD.MOISTURE_TEST_2
            self._send_cmd_code_with_uplink_check(test_cmd,
                                                   "正在控温: 开始测试(%s)" % ("鼓风" if self._dry_cfg_fan else "氮气"))
        _log("正在控温: 当前=%.1f℃ 目标=%d℃" % (self._current_temp, self._temp_target))

        if self._current_temp >= (self._temp_target - 5):
            _log("温度达标 %.1f℃ >= %d℃, 转入恒温保持" %
                 (self._current_temp, self._temp_target - 5))
            self._patrol_timer.stop()
            self._start_hold()

    def _start_hold(self):
        """开始恒温保持倒计时"""
        if not self._running:
            return
        self._dry_sub_state = _DrySubState.HOLD
        self._holding = True
        self._hold_elapsed = 0.0

        hold_secs = int(self._hold_target)
        if SPEED_MODE:
            self.sig_hold_started.emit(hold_secs)
            self.sig_status_msg.emit("恒温保持 %ds" % hold_secs)
            _log("恒温开始: %d 秒" % hold_secs)
        else:
            hold_min = int(self._hold_target / 60)
            self.sig_hold_started.emit(hold_min)
            self.sig_status_msg.emit("恒温保持 %d:00" % hold_min)
            _log("恒温开始: %d 分钟" % hold_min)
        self._hold_timer.start(1000)

    def _send_start_test_and_patrol(self):
        """控温指令发送成功后的回调: 发开始测试指令, 然后开始温度巡检"""
        if not self._running:
            return
        test_cmd = CMD.MOISTURE_TEST_1 if self._dry_cfg_fan else CMD.MOISTURE_TEST_2
        self._send_cmd_code_with_uplink_check(test_cmd,
                                               "开始测试(%s)" % ("鼓风" if self._dry_cfg_fan else "氮气"))
        self._start_temp_patrol()

    def _start_hold_end_weigh(self):
        """恒温结束, 进入称重阶段"""
        if not self._running:
            return
        self._dry_sub_state = _DrySubState.WEIGH
        self._safe_send_cmd(CMD.FAN_OFF, "关鼓风")
        self._safe_send_cmd(CMD.N2_OFF, "关氮气")
        self.sig_step_progress.emit("开始称量")
        self.sig_status_msg.emit("正在称量...")
        _log("恒温结束, 开始称量 %d 个样品" % len(self._samples))
        self._do_weighing()

    def _on_dry_done(self):
        """烘干恒重子流程完成"""
        mode = "分析水" if self._is_aw else "全水"
        _log("%s 烘干恒重完成" % mode)
        self._safe_send_cmd(CMD.HEAT_OFF, "关闭加热")

        if self._is_aw:
            self._transition(_Phase.WRAP_AW)
        else:
            self._transition(_Phase.CALC_SAVE)

    # ================================================================
    # 步骤5: 分析水收尾
    # ================================================================

    def _step_wrap_aw(self):
        """分析水测试收尾"""
        _log("步骤5: 分析水测试收尾")
        self.sig_status_msg.emit("分析水测试完成")
        self.sig_phase_done.emit("analysis_water")
        self._transition(_Phase.BRANCH_TW)

    # ================================================================
    # 步骤8: 结果计算与存储
    # ================================================================

    def _step_calc_save(self):
        """结果计算与数据存储"""
        _log("步骤8: 结果计算与数据存储")
        self.sig_status_msg.emit("测试完成, 计算水分...")
        self.sig_phase_done.emit("total_water")
        self._finalize_experiment()
        self._transition(_Phase.DONE)

    # ================================================================
    # 步骤9: 测试结束
    # ================================================================

    def _step_done(self):
        """测试结束: 关闭所有输出"""
        _log("步骤9: 测试结束")
        self._timer.stop()
        self._hold_timer.stop()
        self._patrol_timer.stop()
        self._running = False
        self._serial.set_bypass_poll(False)

        self._safe_send_cmd(CMD.HEAT_OFF, "关闭加热")
        self._safe_send_cmd(CMD.FAN_OFF, "关鼓风")
        self._safe_send_cmd(CMD.N2_OFF, "关氮气")
        self._safe_send_cmd(CMD.GAS_ALL_OFF, "关闭全部气体")

        self.sig_status_msg.emit("测试完成")
        self.sig_test_done.emit()

        if self.cfg.beep_enabled:
            self._safe_send_cmd(CMD.BEEPER_ON, "开蜂鸣")
            self.sig_beeper_start.emit()
            QTimer.singleShot(BEEPER_DURATION_S * 1000, self._auto_stop_beeper)

    # ================================================================
    # 主循环(200ms) + 恒温保持tick(修改版)
    # ================================================================

    def _auto_stop_beeper(self):
        """自动关闭蜂鸣器"""
        if self._serial and self._serial.is_connected:
            self._safe_send_cmd(CMD.BEEPER_OFF, "关蜂鸣")
        self.sig_beeper_stop.emit()

    # ========= 步骤7: 最终结果计算与存储 =========

    @staticmethod
    def _bankers_round(value, decimals):
        """银行舍入法(四舍六入五成双) — 使用 Decimal 避免浮点精度问题"""
        from decimal import Decimal, ROUND_HALF_EVEN
        d = Decimal(str(value))
        quantize = Decimal('0.' + '0' * decimals)
        return float(d.quantize(quantize, rounding=ROUND_HALF_EVEN))

    def _calc_moisture(self, sample_weight, dry_weight, check_dry_weight):
        """水分计算: 取检查性干燥重与干燥后重中较小值作为 m1
        公式: 水分% = (m - m1) / m * 100
        参数全部来自原始数据(experiment_samples)
        """
        from decimal import Decimal
        m = Decimal(str(sample_weight))
        # 取较小的作为 m1; 无检查性干燥重时用干燥后重
        cd = Decimal(str(check_dry_weight)) if check_dry_weight is not None else None
        dd = Decimal(str(dry_weight)) if dry_weight is not None else Decimal('0')
        if cd is not None:
            m1 = cd if cd < dd else dd
        else:
            m1 = dd
        if m == 0:
            return 0.0, float(m1)
        moisture = float((m - m1) / m * Decimal('100'))
        return moisture, float(m1)

    def _finalize_experiment(self):
        """测试完成收尾: 计算水分(银行舍入+校正+反算)→写 experiment_results→开炉盖

        水分公式:
          样品重量记作 m
          取 min(检查性干燥重, 干燥后重) 记作 m1
          水分 = (m - m1) / m * 100
          全水保留1位小数, 分析水保留2位小数
          结果校正: 水分 - 校正值(%), 反算干燥重填入结果表
          原始数据(experiment_samples)不改变
        """
        try:
            from db import (ensure_experiment, load_experiment_samples,
                           update_experiment_status, save_experiment_results_batch,
                           load_params, load_experiment)
            import datetime as _dt

            eid = ensure_experiment()
            samples = load_experiment_samples(eid)
            params = load_params()
            exp_record, _ = load_experiment(eid)
            batch_no = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            test_date = _dt.datetime.now().strftime("%Y-%m-%d")

            if not samples:
                _log("finalize: 无样品数据，跳过")
                update_experiment_status(eid, "done")
                return

            results = []
            单位 = (exp_record or {}).get("unit", "") or params.get("unit", "")
            化验员 = (exp_record or {}).get("tech", "") or params.get("hy_current", "")

            for mode in ("分析水", "全水"):
                mode_samples = [
                    s for s in samples
                    if s.get("mode") == mode
                    and s.get("sample_weight") is not None
                    and s.get("dry_weight") is not None
                    and s.get("sample_weight", 0) != 0
                ]
                if not mode_samples:
                    continue

                # 确定该模式的小数位和校正值
                decimals = 2 if mode == "分析水" else 1  # 全水1位, 分析水2位
                corr = float(params.get("aw_corr", 0) if mode == "分析水" else params.get("tw_corr", 0))
                temp_val = params.get("aw_temp", 105) if mode == "分析水" else params.get("tw_temp", 105)
                time_val = params.get("aw_time", 60) if mode == "分析水" else params.get("tw_time", 60)

                moistures = []
                for s in mode_samples:
                    sample_w = s["sample_weight"]
                    dry_w = s["dry_weight"]
                    check_w = s.get("check_dry_weight")

                    # 1. 用原始数据计算水分
                    moisture_raw, m1 = self._calc_moisture(sample_w, dry_w, check_w)

                    # 2. 银行舍入
                    moisture = self._bankers_round(moisture_raw, decimals)

                    # 3. 应用校正值
                    moisture_corrected = self._bankers_round(moisture - corr, decimals)

                    # 4. 反算干燥重(用于结果显示, 原始数据不改变)
                    from decimal import Decimal
                    m = Decimal(str(sample_w))
                    display_dry = float(m * (Decimal('1') - Decimal(str(moisture_corrected)) / Decimal('100')))
                    display_dry = self._bankers_round(display_dry, 4)

                    moistures.append(moisture_corrected)
                    s["_moisture"] = moisture_corrected
                    s["_m1"] = m1
                    s["_display_dry"] = display_dry

                    _log("水分计算 row=%s mode=%s m=%.4f m1=%.4f moisture=%.4f→校正%.*f%%"
                         % (s.get("row_idx", "?"), mode, sample_w, m1,
                            moisture_raw, decimals, moisture_corrected))

                # 平均水分和精密度(均用校正后值银行舍入)
                avg_m = self._bankers_round(sum(moistures) / len(moistures), decimals)
                if len(moistures) >= 2:
                    prec = self._bankers_round(max(moistures) - min(moistures), decimals)
                else:
                    prec = 0.0

                for s in mode_samples:
                    results.append({
                        "实验ID": eid,
                        "批次号": batch_no,
                        "试验日期": test_date,
                        "坩埚位号": str(s.get("row_idx", "")),
                        "样品名": s.get("name", ""),
                        "模式": mode,
                        "坩埚重": s.get("tare_weight"),
                        "样重": s.get("sample_weight"),
                        "检查性干燥重": self._bankers_round(s["_display_dry"], 4),
                        "干燥后重": self._bankers_round(s["_display_dry"], 4),
                        "水分": s["_moisture"],
                        "平均水分": avg_m,
                        "精密度": prec,
                        "分析水温度": temp_val if mode == "分析水" else None,
                        "分析水时间": time_val if mode == "分析水" else None,
                        "全水温度": temp_val if mode == "全水" else None,
                        "全水时间": time_val if mode == "全水" else None,
                        "测试单位": 单位,
                        "化验员": 化验员,
                    })

            if results:
                save_experiment_results_batch(results)
                _log("finalize: 已写入 %d 条结果到 experiment_results" % len(results))

                # 同步更新 experiment_samples 的水分/平均/精密度字段（供表格刷新显示）
                from db import upsert_experiment_sample
                for mode in ("分析水", "全水"):
                    mode_samples = [
                        s for s in samples
                        if s.get("mode") == mode
                        and s.get("_moisture") is not None
                    ]
                    if not mode_samples:
                        continue
                    moistures = [s["_moisture"] for s in mode_samples]
                    avg_m = self._bankers_round(sum(moistures) / len(moistures),
                                                2 if mode == "分析水" else 1)
                    prec = self._bankers_round(max(moistures) - min(moistures),
                                               2 if mode == "分析水" else 1) if len(moistures) >= 2 else 0.0
                    for s in mode_samples:
                        upsert_experiment_sample(eid, s["row_idx"],
                                                  moisture=s["_moisture"],
                                                  avg_moisture=avg_m,
                                                  precision_val=prec)
                _log("finalize: 已同步 %d 条水分数据到 experiment_samples" % len(results))

            update_experiment_status(eid, "done")
            _log("finalize: 实验状态更新为 done")

            # 自动开炉盖
            self._send_cmd_code_with_uplink_check(CMD.OPEN_LID, desc="实验完成开炉盖")
            self.sig_status_msg.emit("实验完成, 炉盖已打开")

        except Exception as e:
            _log("finalize 失败: %s" % str(e))
            import traceback
            traceback.print_exc()
            self.sig_error.emit("结果保存失败: " + str(e))



    def _on_hold_tick(self):
        """恒温保持每秒tick"""
        if not self._running or self._paused:
            return
        if self._dry_sub_state != _DrySubState.HOLD:
            return

        self._hold_elapsed += 1
        remaining = int(self._hold_target - self._hold_elapsed)
        if remaining <= 0:
            self._hold_timer.stop()
            self.sig_hold_countdown.emit(0)
            _log("恒温结束")
            self._start_hold_end_weigh()
            return

        self.sig_hold_countdown.emit(remaining)

        # 每10s交替发控温/开始测试指令（剩余>30s时）
        now = time.time()
        if remaining > 30 and now - self._last_patrol_time >= TEMP_PATROL_INTERVAL_S:
            self._last_patrol_time = now
            self._cmd_is_temp = not self._cmd_is_temp
            if self._cmd_is_temp:
                cmd = CommandBuilder.build_temp_control(self._temp_target)
                self._send_cmd_with_uplink_check(cmd,
                                                  "恒温: 控温 %d℃" % self._temp_target,
                                                  callback=None)
            else:
                test_cmd = CMD.MOISTURE_TEST_1 if self._dry_cfg_fan else CMD.MOISTURE_TEST_2
                self._send_cmd_code_with_uplink_check(test_cmd,
                                                       "恒温: 开始测试(%s)" % ("鼓风" if self._dry_cfg_fan else "氮气"))


    # ========= 主循环(200ms) =========

    def _on_tick(self):
        """200ms主循环: 读取上行帧检测升温转恒温"""
        if not self._running or self._paused:
            return
        # 读取上行帧
        try:
            raw = self._serial.read_all()
        except Exception:
            raw = b""
        if raw:
            self._last_uplink_time = time.time()
            frames = self._uplink_buf.feed(raw)
            for f in frames:
                self._current_temp = f["temperature"]
                self._current_weight = f["weight"]
                self.sig_temp_update.emit(f["temperature"])
                # 温度日志节流: 每3s最多一条
                now = time.time()
                last_log = getattr(self, "_last_temp_log_time", 0)
                temp_val = f["temperature"]
                if now - last_log >= 3.0 or \
                   getattr(self, "_last_logged_temp", -999) != round(temp_val, 1):
                    _log("温度更新: %.1f℃" % temp_val)
                    self._last_temp_log_time = now
                    self._last_logged_temp = round(temp_val, 1)

        # TEMP_PATROL状态下200ms tick也检查温度(快速响应)
        if self._dry_sub_state == _DrySubState.TEMP_PATROL:
            if self._current_temp >= (self._temp_target - 5):
                _log("温度达标 %.1f℃(200ms tick检测)" % self._current_temp)
                self._patrol_timer.stop()
                self._start_hold()

    # ========= 称量流程 =========

    def _weigh_single(self, row_idx, name, tare_weight, desc="", progress_cb=None, timeout=None, min_duration=0):
        """单样位称重: 移动→去皮→样盘下降→稳定→读数, 与批量称重流程一致

        progress_cb(weight): 每次采样时回调, 用于实时更新UI重量显示
        timeout: 稳定等待超时(秒), None则使用默认 _ts(15, 3)
        min_duration: 最短等待秒数
        返回: dry_weight (g) 或 None
        """
        pos = row_idx + 1
        _log("称重[%s] row=%d pos=%d name=%s" % (desc, row_idx, pos, name))

        # 1. 移动到指定样位
        cmd_move = CommandBuilder.build_move_to(pos)
        self._send_cmd_with_uplink_check(cmd_move, "移动到%d号位" % pos)
        time.sleep(1.0)

        # 2. 天平清零(去皮)
        self._send_cmd_code_with_uplink_check(CMD.TARE, "天平清零")
        time.sleep(0.3)

        # 3. 样盘下降
        self._send_cmd_code_with_uplink_check(CMD.SAMPLE_PLATE_DOWN, "样盘下降")
        time.sleep(0.5)

        # 4. 等待稳定读数(5s)
        _log("等待稳定读数 5s...")
        stable_weight = self._wait_stable_weight(timeout=timeout if timeout is not None else _ts(15.0, 3.0), progress_cb=progress_cb, min_duration=min_duration)
        if stable_weight is None:
            self.sig_error.emit("称量失败 row=%d %s" % (row_idx, name))
            return None

        dry = round(stable_weight - tare_weight + self._tare_offset, 4)
        _log("称重[%s] row=%d 读数=%.4f 坩埚重=%.4f 偏移=%.4f 干燥重=%.4f" %
             (desc, row_idx, stable_weight, tare_weight, self._tare_offset, dry))
        return dry

    def _do_weighing(self):
        """批量称量: 首轮称校正坩埚→计算校正值→称所有样品

        第1轮: 称校正坩埚(计算tare_offset) + 称样品 → 写入 check_dry_weight
        第2轮起: 只称样品(用已算好的tare_offset) → 写入 dry_weight
        """
        mode = "分析水" if self._is_aw else "全水"
        corr_w = self.cfg.aw_corr_crucible if self._is_aw else self.cfg.tw_corr_crucible

        self._dry_cycle += 1
        is_first = (self._dry_cycle == 1)

        # ---- 首轮: 称校正坩埚, 计算校正值 ----
        if is_first and corr_w > 0:
            self.sig_status_msg.emit("正在称校正坩埚...")
            corr_name = "校正坩埚"
            if self._table_ref:
                item = self._table_ref.item(0, 0)
                if item and item.text().strip():
                    corr_name = item.text().strip()
            corr_tare = self._get_tare_from_db(0)
            self.sig_weigh_result.emit(0, 0.0, self._phase)  # 通知UI开始称校正坩埚
            corr_dry = self._weigh_single(0, corr_name, corr_tare, desc="校正坩埚")
            if corr_dry is not None:
                self._tare_offset = corr_w - corr_dry
                _log("校正坩埚: corr_w=%.4f corr_dry=%.4f tare_offset=%.4f" %
                     (corr_w, corr_dry, self._tare_offset))
                self.sig_weigh_result.emit(0, corr_dry, self._phase)
            else:
                self._tare_offset = corr_w  # 降级: 直接用坩埚校正值
            self._safe_send_cmd(CMD.SAMPLE_PLATE_UP, "样盘上升(校正坩埚完成)")
        else:
            self._tare_offset = corr_w  # 非首轮直接使用坩埚校正值

        # ---- 称量所有样品 ----
        col_name = "检查性干燥重量" if is_first else "干燥重量"
        results = []
        for row_idx, name, mode_str, sample_weight in self._samples:
            if not self._running:
                return
            tare = self._get_tare_from_db(row_idx)
            dry_weight = self._weigh_single(row_idx, name, tare, desc=col_name)
            if dry_weight is None:
                continue
            mid_val = int(round(dry_weight * 10000)) + 1000000
            self.sig_weigh_result.emit(row_idx, dry_weight, self._phase)
            self._save_weigh_result(row_idx, name, mode_str, 0.0, mid_val,
                                    dry_weight, tare, self._tare_offset, is_first=is_first)
            results.append((row_idx, dry_weight))

        # ---- 称量完成, 样盘上升 ----
        self._safe_send_cmd(CMD.SAMPLE_PLATE_UP, "样盘上升(称量完成)")
        self.sig_status_msg.emit("%s完成, %d 个样品" % (col_name, len(results)))
        self.sig_weigh_batch_done.emit(mode)
        _log("%s完成 %d 个" % (col_name, len(results)))
        self._step_const_check(results)

    # ========= 步骤6: 恒重检查 =========

    def _step_const_check(self, weigh_results):
        """恒重检查: diff<=阈值 通过; 不通过则干燥重前移→重新加热→称重

        第1轮: 已写入检查性干燥重量, 无对比基准 → 直接重新加热
        第2轮起: 检查性干燥重量 vs 干燥重量 → diff<=精度则通过
                 不通过: 干燥重量覆盖检查性干燥重量 → 重新加热称重
                 无次数上限, 直到全部样品通过
        """
        if not self._dry_cfg_const_check:
            _log("跳过恒重检查")
            self._dry_sub_state = _DrySubState.CONST_CHECK
            self._on_dry_done()
            return

        precision = self._dry_cfg_precision

        # 第1轮: 刚写完检查性干燥重量, 无对比基准 → 直接重新加热
        if self._dry_cycle == 1:
            _log("第1轮称重完成(检查性干燥重量), 重新加热进行第2轮")
            self.sig_status_msg.emit("检查性干燥重量已记录, 重新加热...")
            self._dry_sub_state = _DrySubState.START
            self._step_dry_start()
            return

        # 第2轮起: 比较检查性干燥重量 vs 干燥重量
        all_passed = True
        for row_idx, dry_weight in weigh_results:
            check_dry = self._load_check_dry_weight(row_idx)
            if check_dry is None:
                _log("缺少检查性干燥重量 row=%d, 跳过" % row_idx)
                all_passed = False
                continue
            diff = abs(check_dry - dry_weight)
            passed = diff <= precision
            self.sig_const_check_result.emit(row_idx, passed, dry_weight, check_dry)
            _log("恒重检查 row=%d 检查性=%.4f 干燥=%.4f diff=%.4f prec=%.4f %s" %
                 (row_idx, check_dry, dry_weight, diff, precision,
                  "通过" if passed else "不通过"))
            if not passed:
                all_passed = False
                # 干燥重前移: 用本次干燥重量覆盖检查性干燥重量
                self._save_check_dry_weight(row_idx, dry_weight)
                _log("干燥重前移 row=%d check_dry←%.4f" % (row_idx, dry_weight))

        if all_passed:
            _log("全部样品恒重检查通过")
            self._dry_sub_state = _DrySubState.CONST_CHECK
            self._on_dry_done()
        else:
            _log("恒重检查未通过, 重新加热(第 %d 轮)" % (self._dry_cycle + 1))
            self.sig_status_msg.emit("恒重检查未通过, 重新加热(第%d轮)" %
                                      (self._dry_cycle + 1))
            self._dry_sub_state = _DrySubState.START
            self._step_dry_start()
            self._dry_sub_state = _DrySubState.START
            self._step_dry_start()

    # ========= 串口工具方法 =========

    def _send_cmd_with_uplink_check(self, cmd_bytes, desc, callback=None):
        """检测上行活跃后发指令(统一入口, 去握手)"""
        if not self._running:
            return
        from protocol_layer import send_cmd_with_uplink_check
        ok = send_cmd_with_uplink_check(
            self._serial, cmd_bytes, desc,
        )
        if not ok:
            self.sig_error.emit("指令发送失败: " + desc)
            return
        _log("指令已发送: %s" % desc)
        # 指令发送过程中 send_cmd_with_uplink_check 内部会消耗上行帧,
        # 补读一帧确保温度/重量实时更新到UI
        self._drain_uplink_for_ui()
        if callback:
            QTimer.singleShot(int(CMD_INTERVAL_S * 1000), callback)

    def _send_cmd_code_with_uplink_check(self, func_code, desc, callback=None):
        """发送固定4字节指令(统一入口, 去握手)"""
        cmd = CommandBuilder.build_command(func_code)
        self._send_cmd_with_uplink_check(cmd, desc, callback)

    def _drain_uplink_for_ui(self):
        """补读串口上行帧, 更新温度/重量到UI
        send_cmd_with_uplink_check 内部会消耗上行帧, 补读一帧确保UI不丢数据
        """
        try:
            raw = self._serial.read_all()
        except Exception:
            return
        if not raw:
            return
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        for f in frames:
            self.sig_temp_update.emit(f["temperature"])

    def _safe_send_cmd(self, func_code, desc):
        """安全发送指令(不阻塞，允许失败)"""
        if not self._serial or not self._serial.is_connected:
            return
        try:
            self._serial.flush_input()
            cmd = CommandBuilder.build_command(func_code)
            self._serial.send(cmd)
            _log("安全发送: %s %s" % (desc, cmd.hex()))
        except Exception as e:
            _log("安全发送失败: " + str(e))

    def _wait_stable_weight(self, timeout=None, progress_cb=None, min_duration=0):
        if timeout is None:
            timeout = _ts(15.0, 3.0)
        """等待天平读数稳定, 返回均值
        连续N次波动<=容差判定稳定
        progress_cb(weight): 每次采样时回调
        min_duration: 最短等待秒数, 即使提前稳定也继续采样
        """
        samples = []
        start = time.time()
        while time.time() - start < timeout:
            if not self._running:
                return None
            weight = self._read_current_weight()
            if weight is not None:
                samples.append(weight)
                self.sig_weight_update.emit(weight)
                if progress_cb:
                    progress_cb(weight)
                # 仅在 min_duration 过后才检查稳定性
                if (time.time() - start) >= min_duration and len(samples) >= STABLE_WEIGHT_SAMPLES:
                    recent = samples[-STABLE_WEIGHT_SAMPLES:]
                    if max(recent) - min(recent) <= STABLE_TOLERANCE:
                        return sum(recent) / len(recent)
            time.sleep(0.2)
        if samples:
            return sum(samples[-5:]) / min(5, len(samples))
        return None

    def _read_current_weight(self):
        """读取当前天平重量"""
        try:
            raw = self._serial.read_all()
        except Exception:
            return None
        if not raw:
            return None
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        if frames:
            self._last_uplink_time = time.time()
            w = frames[-1]["weight"]
            # 节流: 1s 最多一条天平读数日志
            now = time.time()
            if now - getattr(self, "_last_weight_log_time", 0) >= 1.0:
                _log("天平读数: %.4fg" % w)
                self._last_weight_log_time = now
            return w
        return None

    # ========= 数据持久化 =========

    def _get_tare_from_db(self, row_idx):
        """从 experiment_samples 读取指定行的坩埚重"""
        try:
            from db import load_experiment_samples, ensure_experiment
            eid = ensure_experiment()
            samples = load_experiment_samples(eid)
            for s in samples:
                if s.get("row_idx") == row_idx:
                    tw = s.get("tare_weight")
                    if tw is not None:
                        return tw
        except Exception:
            pass
        return 0.0

    def _save_weigh_result(self, row_idx, name, mode, raw_weight, mid_val, dry_weight,
                            tare_weight, tare_offset, is_first=False):
        """保存称量结果: 首轮写入检查性干燥重量, 后续写入干燥重量"""
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            if is_first:
                upsert_experiment_sample(eid, row_idx,
                                         name=name, mode=mode,
                                         tare_weight=tare_weight,
                                         check_dry_weight=dry_weight)
            else:
                upsert_experiment_sample(eid, row_idx,
                                         name=name, mode=mode,
                                         tare_weight=tare_weight,
                                         dry_weight=dry_weight)
            self._save_raw_data_backup(eid, row_idx, name, mode,
                                       raw_weight, mid_val, dry_weight,
                                       tare_weight, tare_offset, self._phase)
            col = "check_dry" if is_first else "dry"
            _log("DB保存 row=%d %s=%.4f" % (row_idx, col, dry_weight))
        except Exception as e:
            _log("DB保存失败: %s" % str(e))

    def _save_raw_data_backup(self, experiment_id, row_idx, name, mode,
                               raw_weight, mid_val, dry_weight,
                               tare_weight, tare_offset, phase):
        """保存原始称量数据到 raw_data_backup 表"""
        try:
            import sqlite3
            from db import DB_PATH
            conn = sqlite3.connect(DB_PATH)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_data_backup (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id INTEGER,
                    row_idx INTEGER,
                    name TEXT,
                    mode TEXT,
                    phase TEXT,
                    raw_weight REAL,
                    mid_val INTEGER,
                    dry_weight REAL,
                    tare_weight REAL,
                    tare_offset REAL,
                    created_at TEXT DEFAULT (datetime("now","localtime"))
                )
            """)
            conn.execute("""
                INSERT INTO raw_data_backup
                    (experiment_id, row_idx, name, mode, phase,
                     raw_weight, mid_val, dry_weight, tare_weight, tare_offset)
                VALUES (?,?,?,?,?, ?,?,?,?,?)
            """, (experiment_id, row_idx, name, mode, phase,
                  raw_weight, mid_val, dry_weight, tare_weight, tare_offset))
            conn.commit()
            conn.close()
        except Exception as e:
            _log("原始数据备份失败: %s" % str(e))

    def _load_check_dry_weight(self, row_idx):
        """读取上次检查性干燥重量"""
        try:
            from db import load_experiment_samples, ensure_experiment
            eid = ensure_experiment()
            samples = load_experiment_samples(eid)
            for s in samples:
                if s.get("row_idx") == row_idx:
                    cdw = s.get("check_dry_weight")
                    if cdw is not None:
                        return cdw
            return None
        except Exception:
            return None

    def _save_check_dry_weight(self, row_idx, weight):
        """保存本次检查性干燥重量"""
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            upsert_experiment_sample(eid, row_idx, check_dry_weight=weight)
            _log("保存检查性干燥重量 row=%d weight=%.4f" % (row_idx, weight))
        except Exception as e:
            _log("保存检查性干燥重量失败: %s" % str(e))


class TestController(QObject):
    """测试控制器-外观模式, 封装Worker管理"""

    sig_phase_changed = Signal(str)
    sig_temp_update = Signal(float)
    sig_weight_update = Signal(float)
    sig_hold_countdown = Signal(int)
    sig_hold_started = Signal(int)
    sig_status_msg = Signal(str)
    sig_error = Signal(str)
    sig_step_progress = Signal(str)
    sig_weigh_result = Signal(int, float, str)
    sig_weigh_batch_done = Signal(str)
    sig_const_check_result = Signal(int, bool, float, float)
    sig_phase_done = Signal(str)
    sig_test_done = Signal()
    sig_beeper_start = Signal()
    sig_beeper_stop = Signal()
    sig_initial_weight = Signal(int, int, float)  # row_idx, col, value
    sig_initial_weigh_done = Signal()

    def __init__(self, serial_mgr, parent=None):
        super().__init__(parent)
        self._serial = serial_mgr
        self._worker = None

    def start_test(self, config):
        """启动测试
        参数: config - TestConfig 实例
        """
        if self._worker and self._worker.is_running:
            _log("已有测试在运行")
            return
        _log("创建 TestWorker")
        self._worker = TestWorker(self._serial, config, self)
        # 转发全部信号
        signals = [
            "sig_phase_changed", "sig_temp_update", "sig_weight_update",
            "sig_hold_countdown", "sig_hold_started", "sig_status_msg",
            "sig_error", "sig_step_progress", "sig_weigh_result",
            "sig_weigh_batch_done", "sig_const_check_result",
            "sig_phase_done", "sig_test_done", "sig_beeper_start", "sig_beeper_stop",
            "sig_initial_weight", "sig_initial_weigh_done",
        ]
        for sname in signals:
            getattr(self._worker, sname).connect(getattr(self, sname))
        self._worker.start_test()

    def stop_test(self):
        """停止测试"""
        if self._worker:
            self._worker.stop_test()

    def pause_test(self):
        if self._worker:
            self._worker.pause_test()

    def resume_test(self):
        if self._worker:
            self._worker.resume_test()

    @property
    def is_running(self):
        return self._worker is not None and self._worker.is_running