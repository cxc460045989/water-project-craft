# -*- coding: utf-8 -*-
# ============================================================
# @CRAFT-MARKER: 追加样品
# 快速定位标记 - 请勿删除
# ============================================================
"""追加样品功能模块 - 微机全自动水分测定仪
完整串口控制流程：移动样位 -> 称坩埚 -> 称样品 -> 存储
依赖: protocol_layer.py, serial_comm.py, db.py
架构: QObject + moveToThread + 信号槽
"""

import time
from PySide2.QtCore import QObject, Signal, QTimer
from protocol_layer import CommandBuilder, CMD, UplinkBuffer
from logging_util import logger

CMD_INTERVAL_S = 0.15
STABLE_WAIT_S = 5.0
UPLINK_TIMEOUT_S = 3.0
WEIGHT_REPORT_INTERVAL_S = 1.0

def _log(msg):
    logger.info("[APPEND] " + msg)

def _format_weight(w):
    return round(float(w), 4)

class SampleAppendWorker(QObject):
    sig_status_update = Signal(str)
    sig_weight_update = Signal(float)
    sig_sample_weight_update = Signal(float)
    sig_finished = Signal(bool, str)
    sig_error = Signal(str)

    def __init__(self, serial_mgr, parent=None):
        super().__init__(parent)
        self._serial = serial_mgr
        self._running = False
        self._uplink_buf = UplinkBuffer()
        self._last_uplink_time = time.time()
        self._current_weight = 0.0
        self._confirm_flag = False
        self._tare_weight = 0.0
        self._position = 1
        self._weight_lo = 0.9
        self._weight_hi = 1.1
        self._sample_name = ""
        self._step_timer = QTimer(self)
        self._step_timer.timeout.connect(self._on_step_timer)
        self._weigh_timer = QTimer(self)
        self._weigh_timer.timeout.connect(self._on_weigh_tick)
        self._signal_connected = False
        self._btn_pressed = False

    def start_append(self, position, weight_lo, weight_hi, sample_name=""):
        _log("追加样品启动 position=%d range=[%.4f,%.4f] name=%s" %
             (position, weight_lo, weight_hi, sample_name))
        self._running = True
        self._confirm_flag = False
        self._tare_weight = 0.0
        self._position = position
        self._weight_lo = weight_lo
        self._weight_hi = weight_hi
        self._sample_name = sample_name
        if not self._signal_connected:
            self._serial.data_received.connect(self._on_serial_data)
            self._signal_connected = True
        self._step1_move_to_position()

    def stop(self):
        _log("追加样品手动终止")
        self._running = False
        self._step_timer.stop()
        self._weigh_timer.stop()
        self._safe_send_cmd(CMD.SAMPLE_PLATE_UP, "样盘上升")
        self._safe_send_cmd(CMD.EXIT_WEIGH_MODE, "解除称重")
        self.sig_finished.emit(False, "已手动终止")

    def confirm_weigh(self):
        _log("用户点击确认")
        self._confirm_flag = True

    # ===== 串口数据接收 =====

    def _on_serial_data(self, data):
        """解析上行帧, 更新重量和按键状态"""
        if not data:
            return
        self._last_uplink_time = time.time()
        frames = self._uplink_buf.feed(data)
        for f in frames:
            self._current_weight = f["weight"]
            self.sig_weight_update.emit(f["weight"])
            if f["btn_pressed"]:
                self._btn_pressed = True
            _log("[上行帧] temp=%.1f weight=%.4f btn=%d" %
                 (f["temperature"], f["weight"], f["btn_pressed"]))

    # ===== 步骤1: 样盘移动到目标工位 =====

    def _step1_move_to_position(self):
        self.sig_status_update.emit("步骤1: 样盘移动到%d号位" % self._position)
        _log("[步骤1] 样盘移动到%d号位" % self._position)
        cmd = CommandBuilder.build_move_to(self._position)
        self._log_send("样盘移动", cmd)
        self._send_cmd_with_uplink_check(cmd, "样盘移动", callback=self._step2_after_ready)

    def _start_wait_handshake_1(self):
        # [已废弃] 新协议不需要握手等待，直接进入下一步
        self._step2_after_ready()

    def _step2_after_ready(self):
        self.sig_status_update.emit("步骤2: 就绪等待2s...")
        _log("[步骤2] 样盘就位, 等待2秒")
        self._step_timer_type = "delay"
        self._step_timer_target = self._step3_tare_prepare
        self._step_timer_count = 0
        self._step_timer_max = 10  # 10 ticks at 200ms = 2s
        self._step_timer.start(200)

    # ===== 步骤3: 坩埚称量准备 =====

    def _step3_tare_prepare(self):
        self.sig_status_update.emit("步骤3: 天平清零...")
        _log("[步骤3] 天平清零")
        cmd = CommandBuilder.build_command(CMD.TARE)
        self._send_cmd_with_uplink_check(cmd, "天平清零", callback=self._step3_tare_down)

    def _step3_tare_down(self):
        self.sig_status_update.emit("步骤3: 样盘下降...")
        _log("[步骤3] 样盘下降")
        cmd = CommandBuilder.build_command(CMD.SAMPLE_PLATE_DOWN)
        self._send_cmd_with_uplink_check(cmd, "样盘下降", callback=self._start_wait_handshake_3)

    def _start_wait_handshake_3(self):
        # [已废弃] 新协议不需要握手等待，直接进入下一步
        self._step3_tare_stable()

    def _step3_tare_stable(self):
        self.sig_status_update.emit("步骤3: 等待坩埚重量稳定5s...")
        _log("[步骤3] 下降到位, 等待5秒稳定")
        self._step_timer_type = "delay"
        self._step_timer_target = self._step4_tare_read
        self._step_timer_count = 0
        self._step_timer_max = 25  # 25 ticks at 200ms = 5s
        self._step_timer.start(200)

    # ===== 步骤4: 坩埚重量采集入库 =====

    def _step4_tare_read(self):
        weight = self._read_stable_weight()
        self._tare_weight = _format_weight(weight)
        _log("[步骤4] 坩埚重: %.4fg" % self._tare_weight)
        self.sig_status_update.emit("步骤4: 坩埚重%.4fg" % self._tare_weight)
        self._save_tare_to_db(self._tare_weight)
        self._step5_sample_prompt()

    # ===== 步骤5: 进入样品称量 =====

    def _step5_sample_prompt(self):
        """坩埚称量完成 → 不抬样盘 → 延迟5s → 清零 → 进入称重 → 蜂鸣 → 单独称量"""
        self.sig_status_update.emit("步骤5: 坩埚称量完成, 等待5秒...")
        _log("[步骤5] 坩埚称量完成, 延迟5秒")
        self._start_timer(5000, self._step5_tare_first)

    def _step5_tare_first(self):
        self.sig_status_update.emit("步骤5: 天平清零...")
        _log("[步骤5] 天平清零")
        cmd = CommandBuilder.build_command(CMD.TARE)
        self._send_cmd_with_uplink_check(cmd, "天平清零", callback=self._step5_enter_weigh_mode)

    def _step5_enter_weigh_mode(self):
        self.sig_status_update.emit("步骤5: 进入称重状态...")
        _log("[步骤5] 进入称重状态")
        cmd = CommandBuilder.build_command(CMD.ENTER_WEIGH_MODE)
        self._send_cmd_with_uplink_check(cmd, "进入称量样重状态", callback=self._step5_beeper)

    def _step5_beeper(self):
        cmd = CommandBuilder.build_command(CMD.BEEPER_1S)
        self._send_cmd_with_uplink_check(cmd, "蜂鸣提示", callback=self._step5_start_weighing)

    def _step5_start_weighing(self):
        self.sig_status_update.emit("步骤5: 实时称量中...")
        _log("[步骤5] 实时称量开始")
        self._confirm_flag = False
        self._btn_pressed = False
        self._weigh_timer.start(1000)
        # 同时启动200ms轮询检测结束条件
        self._step_timer_type = "weigh_check"
        self._step_timer.start(200)

    # ===== 实时称量 =====

    def _on_weigh_tick(self):
        """每秒: 计算样品重量并发送到仪器"""
        sample_weight = _format_weight(self._current_weight - self._tare_weight)
        self.sig_sample_weight_update.emit(sample_weight)
        cmd = CommandBuilder.build_send_weight(sample_weight)
        self._log_send("发送天平数据(%.4fg)" % sample_weight, cmd)
        self._send_cmd_with_uplink_check(cmd, "发送天平数据(%.4fg)" % sample_weight)

    def _step_timer_weigh_check(self):
        """检测称量结束条件"""
        if self._confirm_flag:
            _log("[称量] 用户确认结束")
            self._weigh_timer.stop()
            self._step_timer.stop()
            self._finish_weighing()
            return
        if self._btn_pressed:
            self._btn_pressed = False
            _log("[称量] 物理按键结束")
            self._weigh_timer.stop()
            self._step_timer.stop()
            self._finish_weighing()
            return

    # ===== 称量结束判定 =====

    def _finish_weighing(self):
        """读取最终重量, 校验, 存储或重试"""
        final_weight = self._read_stable_weight()
        sample_weight = _format_weight(final_weight - self._tare_weight)
        _log("[称量结束] 天平=%.4f 坩埚=%.4f 样品=%.4f range=[%.4f,%.4f]" %
             (final_weight, self._tare_weight, sample_weight, self._weight_lo, self._weight_hi))

        if sample_weight < self._weight_lo or sample_weight > self._weight_hi:
            _log("[称量] 样品重量%.4f超出范围[%.4f,%.4f], 重新称量" %
                 (sample_weight, self._weight_lo, self._weight_hi))
            self.sig_error.emit("样品重量%.4fg超出范围(%.4f-%.4f)" %
                               (sample_weight, self._weight_lo, self._weight_hi))
            self._step5_sample_prompt()
            return

        _log("[称量] 样品重量合格: %.4fg" % sample_weight)
        self._save_sample_to_db(self._position, self._sample_name, self._tare_weight, sample_weight)
        self._step6_finish()

    # ===== 收尾 =====

    def _step6_finish(self):
        self.sig_status_update.emit("步骤6: 样盘上升...")
        _log("[步骤6] 样盘上升")
        cmd = CommandBuilder.build_command(CMD.SAMPLE_PLATE_UP)
        self._send_cmd_with_uplink_check(cmd, "样盘上升", callback=self._step6_exit_weigh)

    def _step6_exit_weigh(self):
        self.sig_status_update.emit("步骤6: 解除称重状态...")
        _log("[步骤6] 解除称重")
        cmd = CommandBuilder.build_command(CMD.EXIT_WEIGH_MODE)
        self._send_cmd_with_uplink_check(cmd, "解除称重状态", callback=self._step6_done)

    def _step6_done(self):
        self._running = False
        self._step_timer.stop()
        self._weigh_timer.stop()
        self.sig_status_update.emit("追加样品完成")
        _log("[完成] 追加样品流程结束")
        self.sig_finished.emit(True, "追加样品完成 position=%d" % self._position)

    # ===== 定时器调度 =====

    def _on_step_timer(self):
        """统一定时器调度: 根据类型执行不同逻辑"""
        if not self._running:
            self._step_timer.stop()
            return
        ttype = getattr(self, "_step_timer_type", "")
        if ttype == "delay":
            self._timer_delay_tick()
        elif ttype == "weigh_check":
            self._step_timer_weigh_check()

    def _start_timer(self, ms, target_cb):
        """启动延迟定时器"""
        self._step_timer_type = "delay"
        self._step_timer_target = target_cb
        self._step_timer_count = 0
        self._step_timer_max = max(1, ms // 200)
        self._step_timer.start(200)

    def _timer_delay_tick(self):
        """延迟定时器tick"""
        self._step_timer_count += 1
        if self._step_timer_count >= self._step_timer_max:
            self._step_timer.stop()
            target = getattr(self, "_step_timer_target", None)
            if target:
                target()

    # ===== 串口工具 =====

    def _send_cmd_with_uplink_check(self, cmd_bytes, desc="", callback=None):
        """检测上行活跃后发送指令(统一入口, 去握手)"""
        if not self._running:
            return
        from protocol_layer import send_cmd_with_uplink_check
        ok = send_cmd_with_uplink_check(
            self._serial, cmd_bytes, desc,
        )
        if ok:
            self._log_send(desc, cmd_bytes)
        if callback:
            callback()

    def _safe_send_cmd(self, func_code, desc=""):
        """不经握手直接发送(紧急复位)"""
        if not self._serial or not self._serial.is_connected:
            return
        try:
            self._serial.flush_input()
            cmd = CommandBuilder.build_command(func_code)
            self._serial.send(cmd)
            _log("[安全] %s %s" % (desc, cmd.hex()))
        except Exception as e:
            _log("[安全] 发送失败: %s" % str(e))

    def _read_stable_weight(self):
        """读取当前稳定天平重量(最近5次均值)"""
        samples = []
        for _ in range(15):
            if not self._running:
                return self._current_weight
            samples.append(self._current_weight)
            time.sleep(0.1)
        if samples:
            return sum(samples[-5:]) / 5.0
        return self._current_weight

    def _log_send(self, desc, cmd):
        _log("[发送] %s - %s" % (desc, cmd.hex()))

    # ===== 数据库操作 =====

    def _save_tare_to_db(self, tare_weight):
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            upsert_experiment_sample(eid, self._position,
                                     name=self._sample_name,
                                     tare_weight=tare_weight)
            _log("[DB] 坩埚重%.4f写入 row=%d" % (tare_weight, self._position))
            from db import save_sample
            save_sample(self._position, tare_weight=tare_weight, name=self._sample_name)
        except Exception as e:
            _log("[DB] 写入失败: %s" % str(e))

    def _save_sample_to_db(self, row_idx, name, tare, sample):
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            upsert_experiment_sample(eid, row_idx,
                                     name=name,
                                     tare_weight=tare,
                                     sample_weight=sample)
            _log("[DB] 样品重%.4f写入 row=%d" % (sample, row_idx))
            from db import save_sample
            save_sample(row_idx, tare_weight=tare, sample_weight=sample, name=name)
        except Exception as e:
            _log("[DB] 写入失败: %s" % str(e))