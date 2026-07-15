# -*- coding: utf-8 -*-
"""追加样品功能模块（v2） — 微机全自动水分测定仪
独立 QThread 封装，仅负责阶段1（单坩埚称量），阶段2 复用现有 WeighController。

流程:
  阶段1 单坩埚称量: 发校正值 → 移样位 → 清零 → 样盘下降 → 读数（全程开盖，不抬样盘）
  阶段2 单样品称量: 由 main_app 创建 WeighController.start_individual_sample_weigh() 负责

依赖: protocol_layer.py, serial_comm.py, db.py（仅 import 调用，不修改）
"""

import time
from PySide2.QtCore import QThread, Signal

from protocol_layer import CommandBuilder, CMD, UplinkBuffer, send_cmd_with_uplink_check
from logging_util import logger

# ======== 可配置常量 ========
CMD_INTERVAL_S = 0.15

TARE_TARGET_COL = 2          # 坩埚重列


def _log(msg):
    logger.info("[APPEND-V2] " + msg)


class AppendSampleWorker(QThread):
    """追加样品 — 阶段1 坩埚称量工作线程

    仅负责: 发送校正值 → 移动到目标工位 → 天平清零 →
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

    def __init__(self, serial_mgr, table_ref, row, name, mode, parent=None):
        super().__init__(parent)
        self._serial = serial_mgr
        self._table = table_ref
        self._row = row                  # 0-based table row
        self._name = name
        self._mode = mode
        self._running = False
        self._uplink_buf = UplinkBuffer()

    # ================================================================
    # 入口
    # ================================================================

    def run(self):
        self._running = True
        self._serial.set_bypass_poll(True)
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
            self._running = False
            self._serial.set_bypass_poll(False)

    def stop(self):
        _log("手动终止")
        self._running = False

    # ================================================================
    # 阶段1: 单坩埚称量
    # ================================================================

    def _do_tare(self):
        """单坩埚称量: 校正值→移位→清零→下降→读数（全程开盖，不抬样盘）"""
        _log("坩埚称量: row=%d name=%s" % (self._row, self._name))
        position = self._row + 1

        # 1. 发送坩埚校正值
        corr_w = self._get_crucible_correction_weight()
        if corr_w > 0:
            _log("发送坩埚校正值: %.4fg" % corr_w)
            corr_cmd = CommandBuilder.build_send_weight(corr_w)
            send_cmd_with_uplink_check(self._serial, corr_cmd, "坩埚校正值")
            self._sleep(CMD_INTERVAL_S)

        # 2. 通知 UI 进入坩埚称量显示
        self.sig_progress.emit({"phase": "tare", "row": self._row,
                                "name": self._name, "weight": 0.0})
        self._send_move_to(position)
        self._sleep(CMD_INTERVAL_S)
        self._sleep(1.0)

        # 3. 天平清零
        self._send_cmd(CMD.TARE, "天平清零")
        _log("天平清零已发送")

        # 4. 样盘下降 + 等待稳定读数
        weight = self._wait_descend_and_read()
        _log("坩埚重量: %.4fg" % weight)

        # 5. 回填坩埚重到表格 + 数据库
        self._backfill_tare(weight)
        _log("坩埚称量完成: %.4fg（样盘未抬）" % weight)

        # 通知完成（不带消息，main_app 直接转阶段2）
        self.sig_done.emit(True, "")

    # ================================================================
    # 串口工具
    # ================================================================

    def _send_cmd(self, func_code, desc=""):
        cmd = CommandBuilder.build_command(func_code)
        _log("发送: %s code=0x%02X %s" % (desc, func_code, cmd.hex()))
        ok = send_cmd_with_uplink_check(self._serial, cmd, desc)
        if not ok:
            self.sig_error.emit("指令发送失败: " + desc)

    def _send_move_to(self, position):
        cmd = CommandBuilder.build_move_to(position)
        _log("样盘移动: pos=%d %s" % (position, cmd.hex()))
        ok = send_cmd_with_uplink_check(self._serial, cmd, "移动到%d号位" % position)
        if not ok:
            self.sig_error.emit("样盘移动指令发送失败 pos=%d" % position)

    # ================================================================
    # 上行帧读取
    # ================================================================

    def _read_uplink_weight(self):
        try:
            raw = self._serial.read_all()
        except Exception:
            return 0.0, False
        if not raw:
            return 0.0, False
        frames = self._uplink_buf.feed(raw)
        if frames:
            self._serial.update_uplink_time()
        if not frames:
            return 0.0, False
        f = frames[-1]
        if f is not None:
            raw_str = f.get("raw_str", "?")
            if not hasattr(self, "_last_uplink_raw") or self._last_uplink_raw != raw_str:
                _log("上行帧: raw=%s 重量=%.4fg 温度=%.1fC 联机=%s" %
                     (raw_str, f["weight"], f["temperature"], f["online"]))
                self._last_uplink_raw = raw_str
        return f["weight"], True

    # ================================================================
    # 等待稳定 + 读数
    # ================================================================

    def _wait_descend_and_read(self):
        """发送样盘下降 → 等上行帧确认 → 5s 持续读数 → 返回最终重量"""
        self._send_cmd(CMD.SAMPLE_PLATE_DOWN, "样盘下降")
        _t0 = time.time()
        while self._running and (time.time() - _t0) < 15.0:
            _, ok = self._read_uplink_weight()
            if ok:
                break
            self._sleep(0.1)
        _log("样盘下降完成, 等待5s稳定...")
        start = time.time()
        weight = 0.0
        while time.time() - start < 5.0:
            if not self._running:
                break
            w, ok = self._read_uplink_weight()
            if ok:
                weight = w
                display = round(weight, 4)
                self.sig_progress.emit({
                    "phase": "tare", "row": self._row,
                    "name": self._name, "weight": display
                })
            self._sleep(0.5)
        return round(weight, 4)

    # ================================================================
    # 数据回填
    # ================================================================

    def _backfill_tare(self, weight):
        """回填坩埚重到表格 + 数据库"""
        from PySide2.QtWidgets import QTableWidgetItem
        from PySide2.QtCore import Qt
        item = self._table.item(self._row, TARE_TARGET_COL)
        if item is None:
            item = QTableWidgetItem("%.4f" % weight)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(self._row, TARE_TARGET_COL, item)
        else:
            item.setText("%.4f" % weight)

        from db import upsert_experiment_sample, ensure_experiment, save_sample
        eid = ensure_experiment()
        upsert_experiment_sample(eid, self._row, tare_weight=weight)
        save_sample(self._row + 1, tare_weight=weight, name=self._name, mode=self._mode)
        _log("坩埚重回填完成: row=%d weight=%.4f" % (self._row, weight))

    # ================================================================
    # 辅助方法
    # ================================================================

    def _get_crucible_correction_weight(self):
        """从 DB 读取坩埚校正值"""
        try:
            from db import load_params
            p = load_params()
            aw = float(p.get("aw_corr", 0.0))
            tw = float(p.get("tw_corr", 0.0))
            return aw if aw > 0 else tw
        except Exception:
            return 0.0

    def _sleep(self, secs):
        if secs <= 0:
            return
        time.sleep(secs)
