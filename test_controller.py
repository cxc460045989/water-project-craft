# -*- coding: utf-8 -*-
"""测试流程控制器 - 微机全自动水分测定仪
分析水/全水测试主流程
自动完成升温-恒温-降温-称量-恒重检查全流程
支持分析水和全水两种测试模式(串行执行)
依赖: protocol_layer.py, serial_comm.py, db.py
驱动: QTimer定时 + 状态机
"""

import time
from PySide2.QtCore import QObject, Signal, QTimer
from protocol_layer import CommandBuilder, CMD, UplinkBuffer
from logging_util import logger

CMD_INTERVAL_S = 0.15
STABLE_WEIGHT_SAMPLES = 15
STABLE_TOLERANCE = 0.0005
UPLINK_TIMEOUT_S = 3.0
CMD_REPEAT_INTERVAL_S = 30
BEEPER_DURATION_S = 10


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
        self.tw_tare_weight = 0.0
        self.samples = []  # [(row_idx, name, mode, sample_weight), ...]
        self.beep_enabled = True

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
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._tick_interval_ms = 200
        self._hold_timer = QTimer(self)
        self._hold_timer.timeout.connect(self._on_hold_tick)

    # ========= 公共接口 =========

    def start_test(self):
        """启动测试 - 从分析水阶段开始"""
        _log("测试开始")
        self._running = True
        self._paused = False
        self._phase = ""
        self._start_phase("analysis_water", self.cfg)
        self._timer.start(self._tick_interval_ms)

    def stop_test(self):
        """停止测试 - 关闭加热/气体/蜂鸣"""
        _log("测试停止")
        self._running = False
        self._paused = False
        self._timer.stop()
        self._hold_timer.stop()
        self._safe_send_cmd(CMD.HEAT_OFF, "关闭加热")
        self._safe_send_cmd(CMD.GAS_ALL_OFF, "关闭全部气体")
        self._safe_send_cmd(CMD.BEEPER_OFF, "关蜂鸣")

    def pause_test(self):
        self._paused = True
        _log("测试暂停")

    def resume_test(self):
        self._paused = False
        _log("测试恢复")

    @property
    def is_running(self):
        return self._running

    # ========= 阶段管理 =========

    def _start_phase(self, phase_name, cfg):
        """启动测试阶段, 过滤对应模式的样品"""
        self._phase = phase_name
        self._state = TestPhaseState(cfg)
        # 过滤对应模式样品
        mode_filter = "分析水" if phase_name == "analysis_water" else "全水"
        self._state.samples = [
            s for s in cfg.samples
            if s[1].strip() and (s[2] == mode_filter or not s[2]) and s[3] is not None
        ]
        _log("启动阶段 %s, 有效样品 %d 个" % (phase_name, len(self._state.samples)))
        self.sig_phase_changed.emit(phase_name)
        label = "分析水" if phase_name == "analysis_water" else "全水"
        self.sig_status_msg.emit("阶段: " + label)

        if not self._state.samples:
            _log("阶段 %s 无有效样品, 跳过" % phase_name)
            self._on_phase_done()
            return

        self._state.stage_done = False
        self._state.cycle_count = 0
        self._step_start_moisture_test()

    def _on_phase_done(self):
        """阶段完成后调度: 分析水->全水->结束"""
        if self._phase == "analysis_water":
            _log("分析水阶段完成, 开始全水测试")
            self.sig_phase_done.emit("analysis_water")
            self._start_phase("total_water", self.cfg)
        else:
            _log("跳过恒重检查, 阶段完成")
            self.sig_phase_done.emit("total_water")
            self._on_test_complete()

    def _on_test_complete(self):
        """测试完成 - 计算水分→存结果→开炉门→蜂鸣"""
        self._timer.stop()
        self._hold_timer.stop()
        self._running = False
        self.sig_status_msg.emit("测试完成, 计算水分...")
        self.sig_test_done.emit()
        # 计算水分 + 存入 experiment_results + 开炉门
        self._finalize_experiment()
        # 完成蜂鸣
        if self.cfg.beep_enabled:
            self._safe_send_cmd(CMD.BEEPER_ON, "开蜂鸣")
            self.sig_beeper_start.emit()
            QTimer.singleShot(BEEPER_DURATION_S * 1000, self._auto_stop_beeper)

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
        """测试完成收尾: 计算水分(银行舍入+校正+反算)→写 experiment_results→开炉门

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
                        "器皿位号": str(s.get("row_idx", "")),
                        "样品名": s.get("name", ""),
                        "模式": mode,
                        "器皿重": s.get("tare_weight"),
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

            update_experiment_status(eid, "done")
            _log("finalize: 实验状态更新为 done")

            # 自动开炉门
            self._send_long_duration_cmd(CMD.OPEN_LID, desc="实验完成开炉门")
            self.sig_status_msg.emit("实验完成, 炉门已打开")

        except Exception as e:
            _log("finalize 失败: %s" % str(e))
            import traceback
            traceback.print_exc()
            self.sig_error.emit("结果保存失败: " + str(e))

    # ========= 步骤2: 发送水分测试指令 =========

    def _step_start_moisture_test(self):
        """发送水分测试指令(开鼓风/关鼓风)"""
        fan_on = self._state.cfg.aw_fan if self._phase == "analysis_water" else self._state.cfg.tw_fan
        func = CMD.MOISTURE_TEST_1 if fan_on else CMD.MOISTURE_TEST_2
        label = "开鼓风" if fan_on else "关鼓风"
        desc = "发送水分测试指令(" + label + ")"
        self.sig_step_progress.emit(desc)
        _log(desc)
        self._send_cmd_code_with_uplink_check(func, desc, callback=self._step_send_temp_control)

    # ========= 步骤3: 发送控温指令 =========

    def _step_send_temp_control(self):
        """发送控温指令(变长 5A 57 x1-x4 44)"""
        temp_c = self._state.cfg.aw_temp if self._phase == "analysis_water" else self._state.cfg.tw_temp
        cmd = CommandBuilder.build_temp_control(temp_c)
        desc = "发送控温 %dC" % temp_c
        self.sig_step_progress.emit(desc)
        _log(desc)
        self._send_cmd_with_uplink_check(cmd, desc, callback=self._step_wait_heating)

    # ========= 步骤4: 等待升温进入恒温保持 =========

    def _step_wait_heating(self):
        """等待升温(由_on_tick检测)"""
        if not self._running:
            return
        temp = self._state.cfg.aw_temp if self._phase == "analysis_water" else self._state.cfg.tw_temp
        hold_minutes = self._state.cfg.aw_time if self._phase == "analysis_water" else self._state.cfg.tw_time
        self._state.hold_target = hold_minutes * 60
        self._state.holding = False
        self._state.hold_elapsed = 0.0
        self._state.last_cmd_time = time.time()
        self.sig_status_msg.emit("等待升温 >=" + str(temp - 5) + "C...")
        _log("等待加热 温度>=" + str(temp - 5) + "C 保持" + str(hold_minutes) + "分钟")

    def _on_hold_tick(self):
        """恒温保持每秒tick"""
        if not self._running or self._paused:
            return
        self._state.hold_elapsed += 1
        remaining = int(self._state.hold_target - self._state.hold_elapsed)
        if remaining <= 0:
            self._hold_timer.stop()
            self.sig_hold_countdown.emit(0)
            _log("恒温结束")
            self._step_hold_end()
        else:
            self.sig_hold_countdown.emit(remaining)
            # 恒温>1分钟: 每30秒重发水分测试指令
            if remaining > 60:
                now = time.time()
                if now - self._state.last_cmd_time >= CMD_REPEAT_INTERVAL_S:
                    self._state.last_cmd_time = now
                    fan_on = self._state.cfg.aw_fan if self._phase == "analysis_water" else self._state.cfg.tw_fan
                    func = CMD.MOISTURE_TEST_1 if fan_on else CMD.MOISTURE_TEST_2
                    self._send_cmd_code_with_uplink_check(func, "重发水分测试", callback=None)
            # 剩余30秒: 提前关闭氮气鼓风
            if remaining == 30:
                _log("恒温剩余30秒, 关闭气体")
                self._send_cmd_code_with_uplink_check(CMD.N2_OFF, "关氮气", callback=None)
                self._send_cmd_code_with_uplink_check(CMD.FAN_OFF, "关鼓风", callback=None)

    # ========= 步骤5: 恒温结束-称量 =========

    def _step_hold_end(self):
        """恒温结束进入称量阶段"""
        self.sig_step_progress.emit("恒温结束, 开始称量")
        self.sig_status_msg.emit("称量中...")
        _log("恒温结束, 开始称量 %d 个样品" % len(self._state.samples))
        self._do_weighing()

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

        # 升温检测: 温度达标后转恒温保持
        if self._state and not self._state.holding and not self._state.stage_done:
            temp = self._state.cfg.aw_temp if self._phase == "analysis_water" else self._state.cfg.tw_temp
            if self._current_temp >= (temp - 5):
                self._state.holding = True
                self._state.hold_elapsed = 0
                self._state.last_cmd_time = time.time()
                hold_min = int(self._state.hold_target / 60)
                self.sig_hold_started.emit(hold_min)
                self.sig_status_msg.emit("恒温保持 %d:00" % hold_min)
                _log("温度 %.1fC 达标, 开始恒温 %d 分钟" % (self._current_temp, hold_min))
                self._hold_timer.start(1000)

    # ========= 称量流程 =========

    def _do_weighing(self):
        """批量称量: 读取稳定重量->计算干燥重->存储"""
        corr_w = self._state.cfg.aw_corr_crucible if self._phase == "analysis_water" else self._state.cfg.tw_corr_crucible
        if corr_w > 0:
            cmd = CommandBuilder.build_send_weight(corr_w)
            self._send_cmd_with_uplink_check(cmd, "发送坩埚校正值 %.4fg" % corr_w)
            time.sleep(0.2)

        tare = self._state.cfg.aw_tare_weight if self._phase == "analysis_water" else self._state.cfg.tw_tare_weight
        corr_dry = self._state.cfg.aw_corr_dry if self._phase == "analysis_water" else self._state.cfg.tw_corr_dry
        tare_offset = corr_w - corr_dry

        results = []
        for row_idx, name, mode, sample_weight in self._state.samples:
            if not self._running:
                return
            stable_weight = self._wait_stable_weight(timeout=15.0)
            if stable_weight is None:
                self.sig_error.emit("称量失败 row=%d %s" % (row_idx, name))
                continue
            # 干燥重公式: 干燥重 = 读数 - 器皿重 + (坩埚校正 - 干燥校正)
            dry_weight = round(stable_weight - tare + tare_offset, 4)
            mid_val = int(round(dry_weight * 10000)) + 1000000
            _log("称量 row=%d name=%s 读数=%.4f 器皿重=%.4f 干燥重=%.4f" %
                 (row_idx, name, stable_weight, tare, dry_weight))
            self.sig_weigh_result.emit(row_idx, dry_weight, self._phase)
            self._save_weigh_result(row_idx, name, mode, stable_weight, mid_val, dry_weight, tare, tare_offset)
            results.append((row_idx, dry_weight))

        self.sig_status_msg.emit("称量完成, %d 个样品" % len(results))
        self.sig_weigh_batch_done.emit(self._phase)
        _log("称量完成 %d 个" % len(results))
        self._step_const_check(results)

    # ========= 步骤6: 恒重检查 =========

    def _step_const_check(self, weigh_results):
        """恒重检查 + 不合格重做"""
        const_check = self._state.cfg.aw_const_check if self._phase == "analysis_water" else self._state.cfg.tw_const_check
        if not const_check:
            _log("跳过恒重检查, 阶段完成")
            self._state.stage_done = True
            self._on_phase_done()
            return

        precision = self._state.cfg.aw_precision if self._phase == "analysis_water" else self._state.cfg.tw_precision
        all_passed = True
        for row_idx, dry_weight in weigh_results:
            check_dry = self._load_check_dry_weight(row_idx)
            if check_dry is None:
                self._save_check_dry_weight(row_idx, dry_weight)
                _log("首次恒重检查, 保存基准值 row=%d weight=%.4f" % (row_idx, dry_weight))
                all_passed = False
                continue
            # 判定: abs(上次干燥重 - 本次干燥重) <= 精度
            diff = abs(check_dry - dry_weight)
            passed = diff <= precision
            self.sig_const_check_result.emit(row_idx, passed, dry_weight, check_dry)
            _log("恒重检查 row=%d 上次=%.4f 本次=%.4f diff=%.4f prec=%.4f %s" %
                 (row_idx, check_dry, dry_weight, diff, precision, "通过" if passed else "不通过"))
            if not passed:
                all_passed = False
                self._save_check_dry_weight(row_idx, dry_weight)
                _log("未通过, 更新检查值 row=%d weight=%.4f" % (row_idx, dry_weight))

        if all_passed:
            _log("全部样品恒重检查通过")
            self._state.stage_done = True
            self._on_phase_done()
        else:
            self._state.cycle_count += 1
            _log("恒重检查未通过, 重新加热(第 %d 次)" % self._state.cycle_count)
            self.sig_status_msg.emit("恒重检查未通过, 重新加热(第 %d 次)" % self._state.cycle_count)
            self._state.holding = False
            self._state.hold_elapsed = 0.0
            self._step_send_temp_control()

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
        if callback:
            QTimer.singleShot(int(CMD_INTERVAL_S * 1000), callback)

    def _send_cmd_code_with_uplink_check(self, func_code, desc, callback=None):
        """发送固定4字节指令(统一入口, 去握手)"""
        cmd = CommandBuilder.build_command(func_code)
        self._send_cmd_with_uplink_check(cmd, desc, callback)

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

    def _wait_stable_weight(self, timeout=15.0):
        """等待天平读数稳定, 返回均值
        连续N次波动<=容差判定稳定
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
                if len(samples) >= STABLE_WEIGHT_SAMPLES:
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
            return frames[-1]["weight"]
        return None

    # ========= 数据持久化 =========

    def _save_weigh_result(self, row_idx, name, mode, raw_weight, mid_val, dry_weight, tare_weight, tare_offset):
        """保存称量结果(实验样品表+原始数据备份)"""
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            upsert_experiment_sample(eid, row_idx,
                                     name=name,
                                     mode=mode,
                                     tare_weight=tare_weight,
                                     dry_weight=dry_weight)
            self._save_raw_data_backup(eid, row_idx, name, mode,
                                       raw_weight, mid_val, dry_weight,
                                       tare_weight, tare_offset, self._phase)
            _log("DB保存 row=%d dry=%.4f" % (row_idx, dry_weight))
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