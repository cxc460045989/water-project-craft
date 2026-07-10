# -*- coding: utf-8 -*-
"""称重流程控制器 - 微机全自动水分测定仪
串口通讯版本：批量称坩埚 + 批量称样品 + 单个称样品完整流程
所有串口操作在 QThread 工作线程执行，信号槽更新 UI，不阻塞主线程
"""

from PySide2.QtCore import QObject, QThread, Signal, QTimer
from PySide2.QtWidgets import QTableWidgetItem
from PySide2.QtCore import Qt
import datetime, time
from protocol_layer import CMD

# ======== 可配置常量 ========
HEARTBEAT_INTERVAL_S = 1.0
HANDSHAKE_RETRIES = 10
WAIT_AFTER_HANDSHAKE_S = 2.0
STABLE_WAIT_S = 5.0
BEEPER_DURATION_S = 10
CMD_INTERVAL_S = 0.15
UPLINK_TIMEOUT_S = 3.0
TARE_TARGET_COL = 2
SAMPLE_TARGET_COL = 3
WEIGHT_REPORT_INTERVAL_S = 1.0


def _log(msg):
    from logging_util import logger
    logger.info("[WEIGH] " + msg)


class WeighWorker(QThread):
    sig_weigh_progress = Signal(dict)
    sig_weigh_done = Signal(str)
    sig_add_sample_prompt = Signal()
    sig_error = Signal(str)
    sig_weight_update = Signal(float)
    sig_finished = Signal()
    sig_confirm_weigh = Signal(int, str, float)
    sig_single_weigh_done = Signal(int, float)
    sig_weight_out_of_range = Signal(str, float, float, float)
    sig_status_msg = Signal(str)
    sig_real_time_sample_weight = Signal(float)

    def __init__(self, serial_mgr, parent=None):
        super().__init__(parent)
        self._serial = serial_mgr
        self._running = False
        self._valid_rows = []
        self._cur_phase = ""
        self._backfill_cb = None
        self._table_ref = None
        self._confirm_event = None
        self._last_uplink_time = time.time()  # 最近上行帧时间戳

    def set_backfill(self, cb):
        self._backfill_cb = cb

    def set_table(self, table_widget):
        self._table_ref = table_widget

    def run_tare(self, valid_rows):
        self._valid_rows = list(valid_rows)
        self._cur_phase = "tare"
        self._running = True
        self.start()

    def run_sample(self, valid_rows):
        self._valid_rows = list(valid_rows)
        self._cur_phase = "sample"
        self._running = True
        self.start()

    def run_single_sample(self, valid_rows):
        self._valid_rows = list(valid_rows)
        self._cur_phase = "single_sample"
        self._running = True
        self.start()

    def stop(self):
        self._running = False
        if self._confirm_event:
            try:
                self._confirm_event.set()
            except Exception:
                pass

    def run(self):
        try:
            if self._cur_phase == "tare":
                self._batch_tare()
            elif self._cur_phase == "sample":
                self._batch_sample()
            elif self._cur_phase == "single_sample":
                self._single_sample()
        except Exception as e:
            self.sig_error.emit("称量异常: " + str(e))
            import traceback
            traceback.print_exc()
        finally:
            self._running = False
            self.sig_finished.emit()

    # ===== 批量称坩埚 =====
    def _batch_tare(self):
        _log("批量坩埚称量开始, 共 " + str(len(self._valid_rows)) + " 个")
        self.sig_status_msg.emit("正在关闭炉盖...")
        self._send_long_duration_cmd(CMD.CLOSE_LID, desc="关炉门")
        for row, name, mode in self._valid_rows:
            if not self._running:
                return
            if not name.strip():
                continue
            self._weigh_one_tare(row, name)
        _log("批量坩埚称量完成")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self.sig_status_msg.emit("正在打开炉盖...")
        self._send_long_duration_cmd(CMD.OPEN_LID, desc="开炉门")
        self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示")
        self.sig_weigh_done.emit("tare")

    # ===== 批量称样品 =====
    def _batch_sample(self):
        _log("批量样品称量开始, 共 " + str(len(self._valid_rows)) + " 个")
        self.sig_status_msg.emit("正在关闭炉盖...")
        self._send_long_duration_cmd(CMD.CLOSE_LID, desc="关炉门")
        for row, name, mode in self._valid_rows:
            if not self._running:
                return
            if not name.strip():
                continue
            self._weigh_one_sample(row, name)
        _log("批量样品称量完成")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self.sig_status_msg.emit("正在打开炉盖...")
        self._send_long_duration_cmd(CMD.OPEN_LID, desc="开炉门")
        self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示")
        self.sig_weigh_done.emit("sample")

    # ===== 单个称样品 =====
    def _single_sample(self):
        _log("单个称量样品开始, 共 " + str(len(self._valid_rows)) + " 个")
        self._send_cmd(CMD.ENTER_WEIGH_MODE, desc="进入称量样重状态")
        self._sleep(CMD_INTERVAL_S)
        self._send_long_duration_cmd(CMD.CLOSE_LID, desc="关炉门")
        for row, name, mode in self._valid_rows:
            if not self._running:
                return
            if not name.strip():
                continue
            position = row
            _log("单个称量 row=" + str(row) + " name=" + name + " pos=" + str(position))
            while self._running:
                self._send_move_to(position)
                self._sleep(CMD_INTERVAL_S)
                if not self._do_handshake_with_retry():
                    self.sig_error.emit("单个称量 row=" + str(row) + " 握手失败，跳过")
                    break
                self._sleep(WAIT_AFTER_HANDSHAKE_S)
                self._send_cmd(CMD.TARE, desc="天平清零")
                self._sleep(CMD_INTERVAL_S)
                self._send_cmd(CMD.SAMPLE_PLATE_DOWN, desc="样盘下降")
                self._sleep(CMD_INTERVAL_S)
                self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示加样")
                self._sleep(CMD_INTERVAL_S)
                tare_weight = self._get_tare_weight(row)
                confirmed = self._wait_confirm_with_display(tare_weight)
                if not self._running:
                    return
                total_weight = self._wait_stable_with_display(1.0)
                total_weight = round(total_weight, 4)
                sample_weight = round(total_weight - tare_weight, 4) if tare_weight else round(total_weight, 4)
                _log("单个称量 row=" + str(row) +
                     " 总重=" + str(total_weight) +
                     " 器皿重=" + str(tare_weight) +
                     " 样重=" + str(sample_weight))
                lo, hi = self._get_weight_range_for_mode(mode)
                if sample_weight < lo or sample_weight > hi:
                    self.sig_weight_out_of_range.emit(name, sample_weight, lo, hi)
                    _log("重量超限 row=" + str(row) + " weight=" + str(sample_weight) +
                         " range=[" + str(lo) + "," + str(hi) + "] 重新称量")
                    continue
                self.sig_single_weigh_done.emit(row, sample_weight)
                _log("单个称量完成 row=" + str(row) + " weight=" + str(sample_weight))
                if self._backfill_cb:
                    self._backfill_cb(row, SAMPLE_TARGET_COL, sample_weight, "sample",
                                      total_weight=total_weight, tare_weight=tare_weight)
                break
        _log("单个称量全部完成")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self._send_long_duration_cmd(CMD.OPEN_LID, desc="开炉门")
        self._send_cmd(CMD.EXIT_WEIGH_MODE, desc="解除称重状态")
        self.sig_weigh_done.emit("sample")

    def _wait_confirm_with_display(self, tare_weight):
        import threading
        self._confirm_event = threading.Event()
        start = time.time()
        timeout = 300.0
        while self._running and not self._confirm_event.is_set():
            if time.time() - start > timeout:
                self.sig_error.emit("等待确认超时(5分钟)")
                return False
            total, ok = self._read_uplink_weight()
            if ok:
                sample = round(total - tare_weight, 4) if tare_weight else round(total, 4)
                self.sig_real_time_sample_weight.emit(sample)
                self._send_send_weight_to_instrument(sample)
                if self._check_instrument_button():
                    return True
            self._sleep(0.3)
        return True

    def confirm_current_weigh(self):
        if self._confirm_event:
            try:
                self._confirm_event.set()
            except Exception:
                pass

    def _get_weight_range_for_mode(self, mode):
        from db import load_params
        p = load_params()
        if mode == "全水":
            return (float(p.get("tw_low", 9.0)), float(p.get("tw_high", 12.0)))
        return (float(p.get("aw_low", 0.9)), float(p.get("aw_high", 1.1)))

    def _send_send_weight_to_instrument(self, weight_g):
        from protocol_layer import CommandBuilder
        cmd = CommandBuilder.build_send_weight(weight_g)
        self._serial.send(cmd)

    def _check_instrument_button(self):
        try:
            raw = self._serial.read_all()
        except Exception:
            return False
        if not raw:
            return False
        from protocol_layer import UplinkBuffer, FrameParser
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        for f in frames:
            if f.get("btn_pressed") == 1 and f.get("online") == 1:
                _log("检测到仪器按键按下")
                return True
        return False

    # ===== 单个坩埚称量 =====
    def _weigh_one_tare(self, row, name):
        position = row
        _log("坩埚称量 row=" + str(row) + " name=" + name + " pos=" + str(position))
        self._send_move_to(position)
        self._sleep(CMD_INTERVAL_S)
        if not self._do_handshake_with_retry():
            self.sig_error.emit("坩埚称量 row=" + str(row) + " 握手失败，跳过")
            return
        self._sleep(WAIT_AFTER_HANDSHAKE_S)
        self._send_cmd(CMD.TARE, desc="天平清零")
        self._sleep(CMD_INTERVAL_S)
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_DOWN, desc="样盘下降")

        if not self._do_handshake_with_retry():
            self.sig_error.emit("坩埚称量 row=" + str(row) + " 稳定握手失败，跳过")
            return
        weight = self._wait_stable_with_display(STABLE_WAIT_S)
        weight = round(weight, 4)
        _log("坩埚重量 row=" + str(row) + " weight=" + str(weight))
        self.sig_weigh_progress.emit({
            "phase": "tare", "row": row, "name": name, "weight": weight
        })
        if self._backfill_cb:
            self._backfill_cb(row, TARE_TARGET_COL, weight, "tare")

    # ===== 单个样品称量(批量中使用) =====
    def _weigh_one_sample(self, row, name):
        position = row
        _log("样品称量 row=" + str(row) + " name=" + name + " pos=" + str(position))
        self._send_move_to(position)
        self._sleep(CMD_INTERVAL_S)
        if not self._do_handshake_with_retry():
            self.sig_error.emit("样品称量 row=" + str(row) + " 握手失败，跳过")
            return
        self._sleep(WAIT_AFTER_HANDSHAKE_S)
        self._send_cmd(CMD.TARE, desc="天平清零")
        self._sleep(CMD_INTERVAL_S)
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_DOWN, desc="样盘下降")

        if not self._do_handshake_with_retry():
            self.sig_error.emit("样品称量 row=" + str(row) + " 稳定握手失败，跳过")
            return
        total_weight = self._wait_stable_with_display(STABLE_WAIT_S)
        total_weight = round(total_weight, 4)
        tare_weight = self._get_tare_weight(row)
        sample_weight = round(total_weight - tare_weight, 4)
        _log("样品称量 row=" + str(row) +
             " 总重=" + str(total_weight) +
             " 器皿重=" + str(tare_weight) +
             " 样重=" + str(sample_weight))
        self.sig_weigh_progress.emit({
            "phase": "sample", "row": row, "name": name,
            "weight": sample_weight,
            "total_weight": total_weight,
            "tare_weight": tare_weight,
        })
        if self._backfill_cb:
            self._backfill_cb(row, SAMPLE_TARGET_COL, sample_weight, "sample",
                              total_weight=total_weight, tare_weight=tare_weight)

    # ===== 串口工具方法 =====
    def _do_handshake_with_retry(self):
        """统一调用 protocol_layer.handshake，带上行链路预检"""
        from protocol_layer import handshake
        ok = handshake(self._serial, retries=HANDSHAKE_RETRIES, wait_ms=100,
                       last_uplink_time=self._serial.last_uplink_time, timeout=UPLINK_TIMEOUT_S)
        if ok:
            _log("握手成功")
        else:
            _log("握手失败，上行帧最近时间: " + str(self._serial.last_uplink_time))
        return ok

    def _send_cmd(self, func_code, desc=""):
        """发送固定4字节指令"""
        from protocol_layer import CommandBuilder
        cmd = CommandBuilder.build_command(func_code)
        _log("发送指令: " + desc + " code=0x" + format(func_code, "02X") +
             " cmd=" + cmd.hex())
        n = self._serial.send(cmd)
        if n == 0:
            self.sig_error.emit("指令发送失败: " + desc)

    # 机械类指令（不改变炉温，无需温度检测）
    _MECHANICAL_CMDS = {CMD.SAMPLE_PLATE_UP, CMD.SAMPLE_PLATE_DOWN,
                        CMD.SAMPLE_PLATE_STEP, CMD.SAMPLE_PLATE_HOME,
                        CMD.CLOSE_LID, CMD.OPEN_LID}

    def _send_long_duration_cmd(self, func_code, desc="", timeout=15.0):
        """发送长耗时指令，通过上行帧温度变化判断动作完成
        机械类指令直接固定延时2秒，不检测温度"""
        import time as _t
        self._send_cmd(func_code, desc)
        # 机械类指令：固定2秒等待
        if func_code in self._MECHANICAL_CMDS:
            self._sleep(2.0)
            _log("mechanical cmd done: " + desc)
            return
        # 热工类指令：通过温度变化检测完成
        _, last_temp = self._read_uplink_temp()
        start = _t.time()
        stable_cycles = 0
        while self._running and (_t.time() - start) < timeout:
            self._sleep(0.5)
            _, temp = self._read_uplink_temp()
            if temp is not None and last_temp is not None:
                diff = abs(temp - last_temp)
                if diff < 0.5:
                    stable_cycles += 1
                else:
                    stable_cycles = 0
                last_temp = temp
                if stable_cycles >= 3:
                    _log("long cmd done: " + desc + " temp=" + str(round(temp,1)))
                    return
            self._sleep(0.3)
        _log("long cmd timeout: " + desc)

    def _read_uplink_temp(self):
        try:
            raw = self._serial.read_all()
        except Exception:
            return 0.0, None
        if not raw:
            return 0.0, None
        from protocol_layer import UplinkBuffer, FrameParser
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        if not frames:
            return 0.0, None
        f = frames[-1]
        if f is not None:
            self._last_uplink_time = time.time()
            self._serial.update_uplink_time()
            return f["weight"], f["temperature"]
        return 0.0, None

    def _send_move_to(self, position):
        """移动样盘到指定位"""
        from protocol_layer import CommandBuilder
        cmd = CommandBuilder.build_move_to(position)
        _log("样盘移动: pos=" + str(position) +
             " cmd=" + cmd.hex())
        n = self._serial.send(cmd)
        if n == 0:
            self.sig_error.emit("样盘移动指令发送失败 pos=" + str(position))

    def _read_uplink_weight(self):
        try:
            raw = self._serial.read_all()
        except Exception:
            return 0.0, False
        if not raw:
            return 0.0, False
        from protocol_layer import UplinkBuffer, FrameParser
        buf = UplinkBuffer()
        frames = buf.feed(raw)
        if frames:
            self._last_uplink_time = time.time()
        if not frames:
            return 0.0, False
        f = frames[-1]
        if f is not None:
            self._serial.update_uplink_time()
        return f["weight"], True

    def _wait_stable_with_display(self, seconds):
        end_time = time.time() + seconds
        last_weight = 0.0
        while time.time() < end_time:
            if not self._running:
                break
            weight, ok = self._read_uplink_weight()
            if ok:
                last_weight = weight
                self.sig_weight_update.emit(weight)
            self._sleep(0.1)
        weight, ok = self._read_uplink_weight()
        if ok:
            last_weight = weight
            self.sig_weight_update.emit(weight)
        return last_weight

    def _get_tare_weight(self, row):
        if self._table_ref is None:
            return 0.0
        item = self._table_ref.item(row, TARE_TARGET_COL)
        if item and item.text().strip():
            try:
                return float(item.text().strip())
            except ValueError:
                pass
        return 0.0

    def _sleep(self, secs):
        if secs <= 0:
            return
        time.sleep(secs)


class WeighController(QObject):
    sig_weighing_progress = Signal(dict)
    sig_weighing_done = Signal(str)
    sig_add_sample_prompt = Signal()
    sig_finished = Signal()
    sig_weight_update = Signal(float)
    sig_error = Signal(str)
    sig_confirm_weigh = Signal(int, str, float)
    sig_single_weigh_done = Signal(int, float)
    sig_weight_out_of_range = Signal(str, float, float, float)
    sig_status_msg = Signal(str)
    sig_real_time_sample_weight = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._valid_rows = []
        self._weigh_phase = ""
        self._table_ref = None
        self._worker = None
        self._serial_mgr = None

    def set_serial_manager(self, mgr):
        self._serial_mgr = mgr

    def set_table(self, table_widget):
        self._table_ref = table_widget

    def start_tare_weigh(self, valid_rows):
        self._valid_rows = self._filter_valid(valid_rows)
        self._weigh_phase = "tare"
        _log("start_tare_weigh: valid_rows=" + str(self._valid_rows))
        self.sig_status_msg.emit("准备称量器皿，正在初始化...")
        self._start_worker("tare")

    def start_open_lid(self):
        _log("start_open_lid")
        self.sig_add_sample_prompt.emit()

    def start_sample_weigh(self):
        self._weigh_phase = "sample"
        _log("start_sample_weigh: valid_rows=" + str(self._valid_rows))
        self.sig_status_msg.emit("准备称量样品，正在初始化...")
        self._start_worker("sample")

    def start_single_sample_weigh(self, valid_rows):
        self._valid_rows = self._filter_valid(valid_rows)
        self._weigh_phase = "single_sample"
        _log("start_single_sample_weigh: valid_rows=" + str(self._valid_rows))
        self.sig_status_msg.emit("准备称量样品，正在初始化...")
        self._start_worker("single_sample")

    def confirm_current_weigh(self):
        if self._worker and hasattr(self._worker, "confirm_current_weigh"):
            self._worker.confirm_current_weigh()

    def _filter_valid(self, rows):
        result = []
        for r in rows:
            if self._table_ref is None:
                break
            name_item = self._table_ref.item(r, 0)
            name = name_item.text().strip() if name_item and name_item.text() else ""
            if not name:
                continue
            mode_item = self._table_ref.item(r, 1)
            mode = mode_item.text().strip() if mode_item and mode_item.text() else "分析水"
            result.append((r, name, mode))
        return result

    def _start_worker(self, phase):
        if self._serial_mgr is None:
            self.sig_error.emit("串口管理器未设置，无法启动称量")
            return
        self._worker = WeighWorker(self._serial_mgr, self)
        self._worker.set_table(self._table_ref)
        self._worker.set_backfill(self._on_backfill)
        self._worker.sig_weigh_progress.connect(self._on_worker_progress)
        self._worker.sig_weigh_done.connect(self._on_worker_done)
        self._worker.sig_error.connect(self._on_worker_error)
        self._worker.sig_weight_update.connect(self.sig_weight_update)
        self._worker.sig_finished.connect(self._on_worker_finished)
        self._worker.sig_confirm_weigh.connect(self.sig_confirm_weigh)
        self._worker.sig_single_weigh_done.connect(self.sig_single_weigh_done)
        self._worker.sig_weight_out_of_range.connect(self.sig_weight_out_of_range)
        self._worker.sig_status_msg.connect(self.sig_status_msg)
        self._worker.sig_real_time_sample_weight.connect(self.sig_real_time_sample_weight)
        if phase == "tare":
            self._worker.run_tare(self._valid_rows)
        elif phase == "sample":
            self._worker.run_sample(self._valid_rows)
        elif phase == "single_sample":
            self._worker.run_single_sample(self._valid_rows)

    def _on_worker_progress(self, info):
        self.sig_weighing_progress.emit(info)

    def _on_worker_done(self, phase):
        self.sig_weighing_done.emit(phase)

    def _on_worker_error(self, msg):
        _log("Worker错误: " + msg)
        self.sig_error.emit(msg)

    def _on_worker_finished(self):
        _log("Worker线程结束")

    def _on_backfill(self, row, col, weight, phase, **extra):
        if self._table_ref is None:
            return
        item = self._table_ref.item(row, col)
        if item is None:
            item = QTableWidgetItem("{:.4f}".format(weight))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._table_ref.setItem(row, col, item)
        else:
            item.setText("{:.4f}".format(weight))
        from db import upsert_experiment_sample, ensure_experiment, save_sample
        eid = ensure_experiment()
        col_map = {2: "tare_weight", 3: "sample_weight"}
        db_key = col_map.get(col)
        if not db_key:
            return
        if phase == "sample":
            tare_w = extra.get("tare_weight")
            kwargs = {"sample_weight": weight}
            if tare_w is not None:
                kwargs["tare_weight"] = tare_w
            upsert_experiment_sample(eid, row, **kwargs)
        else:
            upsert_experiment_sample(eid, row, **{db_key: weight})
        try:
            from db import load_samples
            existing_rows = load_samples()
        except Exception:
            existing_rows = []
        merged = {}
        for rdata in existing_rows:
            if rdata.get("row_id") == row + 1:
                merged = dict(rdata)
                break
        merged[db_key] = weight
        if "name" not in merged or not merged.get("name"):
            name_item = self._table_ref.item(row, 0)
            if name_item and name_item.text().strip():
                merged["name"] = name_item.text().strip()
        if "mode" not in merged or not merged.get("mode"):
            mode_item = self._table_ref.item(row, 1)
            if mode_item and mode_item.text().strip():
                merged["mode"] = mode_item.text().strip()
        safe = {k: v for k, v in merged.items()
                if k not in ("row_id", "id", "experiment_id", "sample_no") and v is not None}
        save_sample(row + 1, **safe)
        _log("回填完成 row=" + str(row) + " col=" + str(col) +
             " weight=" + str(weight) + " phase=" + phase)

    def stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
