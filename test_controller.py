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

        # 恒温保持定时器 (1s)
        self._tick_interval_ms = 200
        self._hold_timer = QTimer(self)
        self._hold_timer.timeout.connect(self._on_hold_tick)

        # 0.5s 上行帧补读定时器 (保底机制, data_received 信号的补充)
        self._uplink_poll_timer = QTimer(self)
        self._uplink_poll_timer.timeout.connect(self._on_uplink_poll)

    def set_table(self, table_widget):
        """设置主表格引用(用于获取校正坩埚名等)"""
        self._table_ref = table_widget

    @staticmethod
    def _process_sleep(seconds):
        """带事件处理的睡眠: Mock 模式 QTimer 需要事件循环"""
        deadline = time.time() + seconds
        while time.time() < deadline:
            QApplication.processEvents()
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(0.01, remaining))

    # ========= 公共接口 =========

    def start_test(self):
        """启动测试 - 进入状态机"""
        _log("测试开始")
        self._running = True
        self._paused = False
        self._phase = ""
        self._initial_weights = {}
        # 连接 readyRead/data_received 信号驱动上行帧处理
        self._serial.data_received.connect(self._on_uplink_data)
        # 启动 0.5s 补读定时器 (保底, 防止 data_received 延迟/丢失)
        self._uplink_poll_timer.start(500)
        # retest=1: 复检样品重量 → 初始称重; retest=0: 跳过 → 直接进分析水分支
        if self.cfg.retest:
            self._transition(_Phase.INITIAL_WEIGH)
        else:
            self._transition(_Phase.BRANCH_AW)

    def stop_test(self):
        """停止测试 - 复位仪器(硬件自动关闭加热/气路)"""
        _log("测试停止")
        self._running = False
        self._paused = False
        self._hold_timer.stop()
        self._patrol_timer.stop()
        self._uplink_poll_timer.stop()
        try:
            self._serial.data_received.disconnect(self._on_uplink_data)
        except Exception:
            pass
        # 停止复检worker（如果正在运行）
        self._stop_retest_worker()
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
    # 步骤1: 初始称重(retest=1) — WeighWorker(QThread) 执行
    # ================================================================

    def _step_initial_weigh(self):
        """复检称重: 关盖→逐位称样品→不开盖不抬盘
        使用 WeighWorker(QThread) 执行，协议时序与批量称重完全一致"""
        self.sig_step_progress.emit("复检称重...")
        self.sig_status_msg.emit("正在复检称重...")
        _log("步骤1: 复检称重, 样品数=%d" % len(self.cfg.samples))

        if not self.cfg.samples:
            _log("复检称重: 无样品, 跳过")
            self._transition(_Phase.BRANCH_AW)
            return

        # 线程安全: 先停止旧的复检 Worker（防止孤儿线程）
        self._stop_retest_worker()

        # 构建有效行列表: 只取有数据的样品行（row=0 校正坩埚由 _retest_weigh 单独处理）
        valid_rows = []
        for r, n, m, s in self.cfg.samples:
            if r == 0:
                continue
            if not n or not n.strip():
                continue
            valid_rows.append((r, n, m if m else ""))

        from weigh_controller import WeighWorker
        self._retest_worker = WeighWorker(self._serial, self)
        self._retest_worker.set_table(self._table_ref)

        # 跨线程安全: sig_backfill 通过 QueuedConnection 在主线程写表格 + DB
        self._retest_worker.sig_backfill.connect(self._on_retest_backfill)

        # 信号连接: 状态消息 → 底部信息栏
        self._retest_worker.sig_status_msg.connect(self.sig_status_msg)
        self._retest_worker.sig_weigh_progress.connect(self._on_retest_progress)
        self._retest_worker.sig_weigh_done.connect(self._on_retest_weigh_done)
        self._retest_worker.sig_error.connect(self._on_retest_error)

        self._retest_worker.run_retest(valid_rows)

    def _on_retest_backfill(self, row, col, weight, phase, extra):
        """复检回填 — 通过 sig_backfill 信号在主线程执行"""
        self.sig_initial_weight.emit(row, col, weight)
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            if col == 2:
                upsert_experiment_sample(eid, row, tare_weight=weight)
            elif col == 3:
                upsert_experiment_sample(eid, row, sample_weight=weight)
        except Exception as e:
            _log("复检DB写入失败: %s" % str(e))

    def _on_retest_progress(self, info):
        """称量进度 → 底部状态栏（与批量称重弹窗文案一致，仅显示位置不同）"""
        # 防护: 忽略已清理 Worker 的过期信号
        if not hasattr(self, '_retest_worker') or self._retest_worker is None:
            return
        row = info.get("row", 0)
        weight = info.get("weight", 0.0)
        phase = info.get("phase", "")
        name = info.get("name", "")
        if phase == "sample":
            self.sig_status_msg.emit("正在复检%d号样品重量：%.4fg" % (row + 1, weight))
        elif phase == "tare":
            self.sig_status_msg.emit("正在复检%s重量：%.4fg" % (name, weight))

    def _on_retest_weigh_done(self, phase):
        """复检称重完成 → 清理线程 → 进入分析水分支"""
        if phase == "retest":
            _log("复检称重完成, 进入分析水分支")
            self._stop_retest_worker()
            self.sig_initial_weigh_done.emit()
            self._transition(_Phase.BRANCH_AW)

    def _on_retest_error(self, msg):
        """复检称重异常 → 清理线程 → 停止测试"""
        _log("复检称重错误: %s" % msg)
        self._stop_retest_worker()
        self.sig_error.emit(msg)
        self.stop_test()

    def _stop_retest_worker(self):
        """安全停止复检 Worker — 等线程自然退出，不强制 terminate"""
        if not hasattr(self, '_retest_worker') or self._retest_worker is None:
            return
        w = self._retest_worker
        # 断开信号连接（防止信号泄漏）
        for sig_name in ['sig_status_msg', 'sig_weigh_progress',
                          'sig_weigh_done', 'sig_error', 'sig_backfill']:
            try:
                getattr(w, sig_name).disconnect()
            except Exception:
                pass
        # 停止线程: stop() 设 _running=False，等自然退出
        if w.isRunning():
            w.stop()
            # 串口指令最长 60s 超时，给 65s 兜底，不 terminate
            if not w.wait(65000):
                _log("复检 Worker 65s 未退出（仪器可能无响应）")
        self._retest_worker = None

    # ================================================================
    # 步骤3: 分析水分支判断
    # ================================================================

    def _step_branch_aw(self):
        """分析水分支判断"""
        _log("步骤3: 分析水分支判断")

        self._samples = [
            s for s in self.cfg.samples
            if s[0] > 0  # 排除 row 0 校正坩埚
            and s[1].strip()  # 样品名非空
            and (s[2] == "分析水" or not s[2])  # 模式匹配
            and s[3] is not None and s[3] > 0  # 有有效样重
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
            if s[0] > 0  # 排除 row 0 校正坩埚
            and s[1].strip()  # 样品名非空
            and s[2] == "全水"  # 模式匹配
            and s[3] is not None and s[3] > 0  # 有有效样重
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
        self._hold_gas_off_sent = False
        self._hold_patrol_stopped = False
        self._hold_timer.stop()
        self._patrol_timer.stop()

        fan = self._dry_cfg_fan
        temp = self._dry_cfg_temp

        _log("烘干启动: mode=%s cycle=%d fan=%s temp=%d℃" %
             (mode, self._dry_cycle + 1, fan, temp))

        self.sig_status_msg.emit("%s 第%d轮烘干, 目标%d℃" %
                                  (mode, self._dry_cycle + 1, temp))

        # 先发开始测试指令 (鼓风/氮气), 再发控温指令
        test_cmd = CMD.MOISTURE_TEST_1 if fan else CMD.MOISTURE_TEST_2
        self._safe_send_cmd(test_cmd,
                            "开始测试(%s)" % ("鼓风" if fan else "氮气"))

        self._cmd_is_temp = False
        cmd = CommandBuilder.build_temp_control(temp)
        self._serial.send(cmd)
        _log("烘干启动: 发送控温 %d℃ %s" % (temp, cmd.hex()))
        self._start_temp_patrol()

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

        # 先排空上行帧, 确保 _current_temp 为最新值
        self._drain_uplink_for_ui()

        self._cmd_is_temp = not self._cmd_is_temp
        if self._cmd_is_temp:
            cmd = CommandBuilder.build_temp_control(self._temp_target)
            self._serial.send(cmd)
            _log("正在控温: 发送控温 %d℃ %s" % (self._temp_target, cmd.hex()))
        else:
            test_cmd = CMD.MOISTURE_TEST_1 if self._dry_cfg_fan else CMD.MOISTURE_TEST_2
            self._safe_send_cmd(test_cmd,
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
        self._hold_gas_off_sent = False  # 关鼓风/氮气仅发送一次标记
        self._hold_patrol_stopped = False  # 停止交替发送仅记录一次日志

        hold_secs = int(self._hold_target)
        if SPEED_MODE:
            self.sig_hold_started.emit(hold_secs)
            self.sig_status_msg.emit("恒温保持 %ds" % hold_secs)
            _log("恒温开始: %d 秒 (目标=%d℃)" % (hold_secs, self._temp_target))
        else:
            hold_min = int(self._hold_target / 60)
            self.sig_hold_started.emit(hold_min)
            self.sig_status_msg.emit("恒温保持 %d:00" % hold_min)
            _log("恒温开始: %d 分钟 (目标=%d℃ 剩余>60s交替发指令, ≤30s关气)" % (hold_min, self._temp_target))
        self._hold_timer.start(1000)

    def _start_hold_end_weigh(self):
        """恒温结束, 进入称重阶段"""
        if not self._running:
            return
        self._dry_sub_state = _DrySubState.WEIGH
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
        self._hold_timer.stop()
        self._patrol_timer.stop()
        self._running = False
        try:
            self._serial.data_received.disconnect(self._on_uplink_data)
        except Exception:
            pass

        self._safe_send_cmd(CMD.HEAT_OFF, "关闭加热")
        self._safe_send_cmd(CMD.FAN_OFF, "关鼓风")
        self._safe_send_cmd(CMD.N2_OFF, "关氮气")
        self._safe_send_cmd(CMD.GAS_ALL_OFF, "关闭全部气体")
        self._safe_send_cmd(CMD.RESET, "仪器复位")

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

        # 倒计时≤30s时: 提前关鼓风/关氮气(仅发送一次)
        if remaining <= 30 and not self._hold_gas_off_sent:
            self._hold_gas_off_sent = True
            self._safe_send_cmd(CMD.FAN_OFF, "关鼓风(恒温倒计时%d秒)" % remaining)
            self._safe_send_cmd(CMD.N2_OFF, "关氮气(恒温倒计时%d秒)" % remaining)
            _log("恒温倒计时 %ds, 提前关鼓风/关氮气" % remaining)

        # 每10s交替发控温/开始测试指令（剩余>60s时，提前60s停止交替发送）
        if remaining <= 60 and not self._hold_patrol_stopped:
            self._hold_patrol_stopped = True
            _log("恒温倒计时 %ds, 停止交替发控温/开始测试（剩余≤60s）" % remaining)
        now = time.time()
        if remaining > 60 and now - self._last_patrol_time >= TEMP_PATROL_INTERVAL_S:
            self._last_patrol_time = now
            self._cmd_is_temp = not self._cmd_is_temp
            if self._cmd_is_temp:
                cmd = CommandBuilder.build_temp_control(self._temp_target)
                self._serial.send(cmd)
                _log("恒温: 发送控温 %d℃ %s" % (self._temp_target, cmd.hex()))
            else:
                test_cmd = CMD.MOISTURE_TEST_1 if self._dry_cfg_fan else CMD.MOISTURE_TEST_2
                self._safe_send_cmd(test_cmd,
                                    "恒温: 开始测试(%s)" % ("鼓风" if self._dry_cfg_fan else "氮气"))


    # ========= 上行帧处理(readyRead 驱动) =========

    def _on_uplink_data(self, data):
        """readyRead 驱动: 每次串口有数据时自动触发, 解析上行帧并更新温度/重量"""
        if not self._running or self._paused:
            return
        if not data:
            return
        self._last_uplink_time = time.time()
        frames = self._uplink_buf.feed(data)
        for f in frames:
            self._current_temp = f["temperature"]
            self._current_weight = f["weight"]
            self.sig_temp_update.emit(f["temperature"])
            self._log_uplink_throttled(f)

        # TEMP_PATROL状态下每次收到数据也检查温度(快速响应)
        if self._dry_sub_state == _DrySubState.TEMP_PATROL:
            if self._current_temp >= (self._temp_target - 5):
                _log("温度达标 %.1fC(readyRead检测)" % self._current_temp)
                self._patrol_timer.stop()
                self._start_hold()

    def _on_uplink_poll(self):
        """0.5s 定时补读: 非阻塞读取串口缓冲区 → 解析上行帧 → 更新温度/重量

        作为 data_received 信号的保底补充:
        - data_received 在 bypass 模式期间被抑制
        - 事件循环繁忙时 readyRead 可能延迟
        - 本方法确保每 0.5s 至少有一次上行数据读取机会
        """
        if not self._running or self._paused:
            return
        self._drain_uplink_for_ui()
        # TEMP_PATROL 状态下每次补读也检查温度 (快速响应, 加速升温达标检测)
        if self._dry_sub_state == _DrySubState.TEMP_PATROL:
            if self._current_temp >= (self._temp_target - 5):
                _log("温度达标 %.1fC(补读检测), 转入恒温保持" % self._current_temp)
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
        self._process_sleep(1.0)

        # 2. 天平清零(去皮)
        self._send_cmd_code_with_uplink_check(CMD.TARE, "天平清零")
        self._process_sleep(0.3)

        # 3. 样盘下降
        self._send_cmd_code_with_uplink_check(CMD.SAMPLE_PLATE_DOWN, "样盘下降")
        self._process_sleep(0.5)

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
        """批量称量: 从2号样位开始称所有样品

        第1轮: 称样品 → 写入 check_dry_weight
        第2轮起: 称样品 → 写入 dry_weight
        """
        mode = "分析水" if self._is_aw else "全水"

        self._dry_cycle += 1
        is_first = (self._dry_cycle == 1)
        self._tare_offset = 0.0

        # ---- 称量所有样品 ----
        col_name = "检查性干燥重量" if is_first else "干燥重量"
        results = []
        mode_name = "分析水" if self._is_aw else "全水"
        total_samples = len(self._samples)
        for idx, (row_idx, name, mode_str, sample_weight) in enumerate(self._samples):
            if not self._running:
                return
            # 逐样品更新进度(UI实时刷新)
            self.sig_status_msg.emit("称量中(%s 第%d轮 %d/%d): %s" % (
                mode_name, self._dry_cycle, idx + 1, total_samples, name))
            QApplication.processEvents()
            tare = self._get_tare_from_db(row_idx)
            dry_weight = self._weigh_single(row_idx, name, tare, desc=col_name)
            if dry_weight is None:
                continue
            mid_val = int(round(dry_weight * 10000)) + 1000000
            self.sig_weigh_result.emit(row_idx, dry_weight, self._phase)
            self._save_weigh_result(row_idx, name, mode_str, 0.0, mid_val,
                                    dry_weight, tare, self._tare_offset, is_first=is_first)
            results.append((row_idx, dry_weight))
            QApplication.processEvents()

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
            # 重新加热时恒温时间使用称量间隔(而非首次烘干时间)
            r = self.cfg.aw_interval if self._is_aw else self.cfg.tw_interval
            self._hold_target = r if SPEED_MODE else r * 60
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
            # 重新加热时恒温时间使用称量间隔
            r = self.cfg.aw_interval if self._is_aw else self.cfg.tw_interval
            self._hold_target = r if SPEED_MODE else r * 60
            self._step_dry_start()

    # ========= 串口工具方法 =========

    def _send_cmd_with_uplink_check(self, cmd_bytes, desc, callback=None):
        """检测上行活跃后发指令(统一入口, 去握手)
        传入 temp_callback, 确保指令发送过程中消费的上行帧温度实时更新到UI
        """
        if not self._running:
            return
        from protocol_layer import send_cmd_with_uplink_check
        ok = send_cmd_with_uplink_check(
            self._serial, cmd_bytes, desc,
            temp_callback=lambda t: (setattr(self, '_current_temp', t), self.sig_temp_update.emit(t)),
        )
        if not ok:
            _log("指令发送超时(60s无响应): %s" % desc)
            self.sig_error.emit("指令发送超时: %s\n请检查串口连接或仪器状态" % desc)
            self.stop_test()
            return
        _log("指令已发送: %s" % desc)
        if callback:
            QTimer.singleShot(int(CMD_INTERVAL_S * 1000), callback)

    def _send_cmd_code_with_uplink_check(self, func_code, desc, callback=None):
        """发送固定4字节指令(统一入口, 去握手)"""
        cmd = CommandBuilder.build_command(func_code)
        self._send_cmd_with_uplink_check(cmd, desc, callback)

    def _drain_uplink_for_ui(self):
        """补读串口上行帧, 更新温度/重量到UI(非阻塞)"""
        try:
            avail = self._serial.bytesAvailable
        except Exception:
            avail = 0
        if avail == 0:
            return
        try:
            raw = self._serial.readAll()
        except Exception:
            return
        if not raw:
            return
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        for f in frames:
            self._current_temp = f["temperature"]
            self._current_weight = f["weight"]
            self.sig_temp_update.emit(f["temperature"])
            self._log_uplink_throttled(f)

    def _log_uplink_throttled(self, f):
        """节流: 每秒最多打印一条上行帧日志"""
        import time as _time
        _now = _time.time()
        if _now - getattr(self, '_last_uplink_log_ts', 0) >= 1.0:
            self._last_uplink_log_ts = _now
            _log("上行帧: %s  temp=%.1f weight=%.4f online=%d btn=%d" % (
                f["raw_str"], f["temperature"], f["weight"], f["online"], f["btn_pressed"]))

    def _safe_send_cmd(self, func_code, desc):
        """安全发送指令(不阻塞，允许失败)"""
        if not self._serial or not self._serial.is_connected:
            return
        try:
            # 非阻塞消费缓冲区已有数据, 转发温度+重量到UI
            try:
                avail = self._serial.bytesAvailable
            except Exception:
                avail = 0
            if avail > 0:
                raw = self._serial.readAll()
                if raw:
                    buf = UplinkBuffer()
                    for f in buf.feed(raw):
                        self._current_temp = f["temperature"]
                        self._current_weight = f["weight"]
                        self.sig_temp_update.emit(f["temperature"])
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
            QApplication.processEvents()
            self._process_sleep(0.2)
        if samples:
            return sum(samples[-5:]) / min(5, len(samples))
        return None

    def _read_current_weight(self):
        """读取当前天平重量(非阻塞)

        优先从串口缓冲区直接读取; 若无可读数据则回退到
        _on_uplink_data 已更新的 _current_weight (来自 data_received 信号),
        确保在 readyRead 已消费数据后仍能获取最新重量。
        """
        try:
            avail = self._serial.bytesAvailable
        except Exception:
            avail = 0
        if avail > 0:
            try:
                raw = self._serial.readAll()
            except Exception:
                raw = b""
            if raw:
                buf = UplinkBuffer()
                frames = buf.feed(raw)
                if frames:
                    self._last_uplink_time = time.time()
                    w = frames[-1]["weight"]
                    # 同步更新 _current_weight, 保持一致性
                    self._current_weight = w
                    # 节流: 1s 最多一条天平读数日志
                    now_ts = time.time()
                    if now_ts - getattr(self, "_last_weight_log_time", 0) >= 1.0:
                        _log("天平读数: %.4fg" % w)
                        self._last_weight_log_time = now_ts
                    return w
        # 回退: 使用 data_received → _on_uplink_data 已更新的当前重量
        if self._current_weight != 0.0:
            return self._current_weight
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