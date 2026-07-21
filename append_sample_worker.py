# -*- coding: utf-8 -*-
# ============================================================
# @CRAFT-MARKER: 追加样品 | 追加样品后台线程
# 快速定位标记 - 请勿删除
# ============================================================
"""追加样品功能模块（v2） — 微机全自动水分测定仪
独立 QThread 封装，仅负责阶段1（单坩埚称量），阶段2 复用现有 WeighController。

流程:
  阶段1 单坩埚称量: 移样位 → 清零 → 样盘下降 → 稳定读数（全程开盖，不抬样盘）
  阶段2 单样品称量: 由 main_app 创建 WeighController.start_individual_sample_weigh() 负责

依赖: protocol_layer.py, serial_comm.py, db.py（仅 import 调用，不修改）
"""

import time
from PySide2.QtCore import QThread, Signal

from protocol_layer import CommandBuilder, CMD, send_cmd_with_uplink_check
from logging_util import logger

# ======== 可配置常量 ========
CMD_INTERVAL_S = 0.15

TARE_TARGET_COL = 2          # 坩埚重列


def _log(msg):
    logger.info("[APPEND-V2] " + msg)


class AppendSampleWorker(QThread):
    """追加样品 — 阶段1 坩埚称量工作线程

    仅负责: 移动到目标工位 → 天平清零 →
            样盘下降 → 稳定读数 → 坩埚重回填（全程开盖，不抬样盘）

    信号:
      sig_status_msg(str) — 硬件动作状态
      sig_progress(dict)   — {phase, row, name, weight}
      sig_done(bool, str)  — 阶段1完成
      sig_error(str)       — 错误
    """

    sig_status_msg = Signal(str)
    sig_progress = Signal(dict)
    sig_done = Signal(bool, str)
    sig_error = Signal(str)
    # 跨线程安全: 回填信号通过 QueuedConnection 在主线程写表格
    sig_tare_backfill = Signal(int, float)

    def __init__(self, serial_mgr, table_ref, row, name, mode, parent=None):
        super().__init__(parent)
        self._serial = serial_mgr
        self._table = table_ref
        self._row = row                  # 0-based table row
        self._name = name
        self._mode = mode
        self._running = False

    # ================================================================
    # 入口
    # ================================================================

    def run(self):
        self._running = True
        # 整个称重流程保持 bypass: 上行帧走 _sync_buf, 不跨线程读 QSerialPort
        self._serial._enter_bypass()
        try:
            self._do_tare()
        except Exception as e:
            self.sig_error.emit("追加样品异常: " + str(e))
            import traceback
            traceback.print_exc()
            try:
                self.sig_done.emit(False, str(e))
            except Exception:
                pass
        finally:
            self._serial._leave_bypass()
            self._running = False

    def stop(self):
        _log("手动终止")
        self._running = False
        # 结束称量时发送复位指令
        if self._serial and self._serial.is_connected:
            from protocol_layer import CommandBuilder, CMD
            cmd = CommandBuilder.build_command(CMD.RESET)
            self._serial.send(cmd)
            _log("结束称量, 发送仪器复位")

    # ================================================================
    # 阶段1: 单坩埚称量
    # ================================================================

    def _do_tare(self):
        """单坩埚称量: 移位→清零→下降→读数（全程开盖，不抬样盘，不发送校正值）"""
        _log("坩埚称量: row=%d name=%s" % (self._row, self._name))
        position = self._row + 1

        # 1. 通知 UI 进入坩埚称量显示
        self.sig_progress.emit({"phase": "tare", "row": self._row,
                                "name": self._name, "weight": 0.0})
        self._send_move_to(position)
        self._sleep(CMD_INTERVAL_S)
        self._sleep(1.0)

        # 2. 天平清零
        self._send_cmd(CMD.TARE, "天平清零")
        _log("天平清零已发送")

        # 3. 样盘下降 + 等待稳定读数
        weight = self._wait_descend_and_read()
        _log("坩埚重量: %.4fg" % weight)

        # 4. 回填坩埚重到表格 + 数据库
        self._backfill_tare(weight)
        _log("坩埚称量完成: %.4fg（样盘未抬）" % weight)

        # 通知完成（5s延迟已移至 weigh_controller._individual_sample 称重界面内）
        self.sig_done.emit(True, "")

    # ================================================================
    # 串口工具
    # ================================================================

    def _send_cmd(self, func_code, desc=""):
        cmd = CommandBuilder.build_command(func_code)
        _log("发送: %s code=0x%02X %s" % (desc, func_code, cmd.hex()))
        ok = send_cmd_with_uplink_check(self._serial, cmd, desc)
        if not ok:
            _log("指令发送失败(已重试3次): %s" % desc)

    def _send_move_to(self, position):
        cmd = CommandBuilder.build_move_to(position)
        _log("样盘移动: pos=%d %s" % (position, cmd.hex()))
        ok = send_cmd_with_uplink_check(self._serial, cmd, "移动到%d号位" % position)
        if not ok:
            _log("样盘移动指令发送失败(已重试3次): pos=%d" % position)

    # ================================================================
    # 上行帧读取
    # ================================================================

    def _read_uplink_weight(self):
        """从 _sync_buf 读取上行帧（主线程 _on_ready_read 自动填充），
        返回 (weight, True) 或 (0.0, False)"""
        if len(self._serial._sync_buf) == 0:
            return 0.0, False
        raw = bytes(self._serial._sync_buf)
        self._serial._sync_buf.clear()
        from protocol_layer import UplinkBuffer, FrameParser
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        if not frames:
            return 0.0, False
        f = frames[-1]
        if f is not None:
            _log("上行帧: %s  temp=%.1f weight=%.4f online=%d btn=%d" % (
                f["raw_str"], f["temperature"], f["weight"], f["online"], f["btn_pressed"]))
            return f["weight"], True
        return 0.0, False

    # ================================================================
    # 等待稳定 + 读数
    # ================================================================

    def _wait_descend_and_read(self):
        """发送样盘下降 → 等上行帧确认 → 5s 持续读数 → 取最后3个中位数"""
        self._send_cmd(CMD.SAMPLE_PLATE_DOWN, "样盘下降")
        _t0 = time.time()
        while self._running and (time.time() - _t0) < 15.0:
            _, ok = self._read_uplink_weight()
            if ok:
                break
            self._sleep(0.1)
        _log("样盘下降完成, 等待5s稳定...")
        start = time.time()
        recent_weights = []
        while time.time() - start < 5.0:
            if not self._running:
                break
            w, ok = self._read_uplink_weight()
            if ok:
                recent_weights.append(w)
                display = round(w, 4)
                self.sig_progress.emit({
                    "phase": "tare", "row": self._row,
                    "name": self._name, "weight": display
                })
            self._sleep(0.5)
        # 5s 结束后取一次最新读数也纳入收集
        final_w, final_ok = self._read_uplink_weight()
        if final_ok:
            recent_weights.append(final_w)
            _log("最终读数: %.4fg" % final_w)
        # 取最后3个读数的中位数, 不足3个则取最后一个
        if len(recent_weights) >= 3:
            last_three = sorted(recent_weights[-3:])
            weight = last_three[1]
        elif recent_weights:
            weight = recent_weights[-1]
        else:
            weight = 0.0
        return round(weight, 4)

    # ================================================================
    # 数据回填
    # ================================================================

    def _backfill_tare(self, weight):
        """回填坩埚重 — 通过信号在主线程写表格 + DB"""
        # 跨线程安全: sig_tare_backfill 通过 QueuedConnection 在主线程执行 UI 操作
        self.sig_tare_backfill.emit(self._row, weight)
        from db import upsert_experiment_sample, ensure_experiment, save_sample
        eid = ensure_experiment()
        upsert_experiment_sample(eid, self._row, tare_weight=weight)
        save_sample(self._row + 1, tare_weight=weight, name=self._name, mode=self._mode)
        _log("坩埚重回填完成: row=%d weight=%.4f" % (self._row, weight))

    # ================================================================
    # 辅助方法
    # ================================================================

    def _sleep(self, secs):
        if secs <= 0:
            return
        time.sleep(secs)
