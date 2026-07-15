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
BEEPER_DURATION_S = 10
CMD_INTERVAL_S = 0.15
UPLINK_TIMEOUT_S = 3.0
LID_WAIT_S = 15.0            # 炉盖开关后等待时间
TARE_TARGET_COL = 2
SAMPLE_TARGET_COL = 3


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
    sig_status_msg = Signal(str)  # 使用 BlockingQueuedConnection 确保 UI 在串口指令前刷新
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
        self._last_btn_pressed = False          # 最近上行帧仪器按键状态
        self._reweigh_rows = None               # 重新称量模式: set of row indices
        self._skip_plate_ops = False            # 追加样品模式: 跳过样盘升降（样盘已在低位）

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

    def run_individual_sample(self, valid_rows):
        self._valid_rows = list(valid_rows)
        self._cur_phase = "individual_sample"
        self._running = True
        self.start()

    def run_reweigh_phase1(self, valid_rows):
        self._valid_rows = list(valid_rows)
        self._cur_phase = "reweigh_tare"
        self._running = True
        self.start()

    def run_reweigh_phase2(self, valid_rows):
        self._valid_rows = list(valid_rows)
        self._cur_phase = "reweigh_sample"
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
        # 屏蔽主线程 poll timer，避免竞争串口数据
        self._serial.set_bypass_poll(True)
        try:
            if self._cur_phase == "tare":
                self._batch_tare()
            elif self._cur_phase == "sample":
                self._batch_sample()
            elif self._cur_phase == "single_sample":
                self._single_sample()
            elif self._cur_phase == "individual_sample":
                self._individual_sample()
            elif self._cur_phase == "reweigh_tare":
                self._reweigh_tare()
            elif self._cur_phase == "reweigh_sample":
                self._reweigh_sample()
        except Exception as e:
            self.sig_error.emit("称量异常: " + str(e))
            import traceback
            traceback.print_exc()
        finally:
            self._running = False
            self._serial.set_bypass_poll(False)
            self.sig_finished.emit()

    # ===== 批量称坩埚 =====
    def _batch_tare(self):
        _log("批量坩埚称量开始, 共 " + str(len(self._valid_rows)) + " 个")
        self._send_long_duration_cmd(CMD.CLOSE_LID, desc="正在关闭炉盖")

        # 先发送坩埚校正值到仪器
        corr_w = self._get_crucible_correction_weight()
        if corr_w > 0:
            _log("发送坩埚校正值: {:.4f}g".format(corr_w))
            from protocol_layer import CommandBuilder
            corr_cmd = CommandBuilder.build_send_weight(corr_w)
            from protocol_layer import send_cmd_with_uplink_check
            send_cmd_with_uplink_check(self._serial, corr_cmd, "坩埚校正值")
            self._sleep(CMD_INTERVAL_S)

        # 称量1号坩埚（表格第0行）
        corr_name = "1号坩埚"
        if self._table_ref:
            item = self._table_ref.item(0, 0)
            if item and item.text().strip():
                corr_name = item.text().strip()
        if self._running:
            existing_tare = self._get_tare_weight(0)
            if existing_tare > 0:
                _log("1号坩埚已有重量 {:.4f}g，跳过称量".format(existing_tare))
            else:
                self._weigh_one_tare(0, corr_name)

        # 称量其余样品（row 1+）
        for row, name, mode in self._valid_rows:
            if not self._running:
                return
            if not name.strip():
                continue
            existing_tare = self._get_tare_weight(row)
            if existing_tare > 0:
                _log(name + " 坩埚已有重量 {:.4f}g，跳过称量".format(existing_tare))
                continue
            self._weigh_one_tare(row, name)
        _log("批量坩埚称量完成")
        self.sig_status_msg.emit("正在上升样盘...")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self._send_cmd(CMD.OPEN_LID, desc="打开炉盖")
        self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示")
        self.sig_weigh_done.emit("tare")

    # ===== 批量称样品 =====
    def _batch_sample(self):
        _log("批量样品称量开始, 共 " + str(len(self._valid_rows)) + " 个")
        self._send_long_duration_cmd(CMD.CLOSE_LID, desc="正在关闭炉盖")
        # 称量1号坩埚样品（表格第0行），样品重 = 坩埚重
        if self._running:
            corr_name = "1号坩埚"
            if self._table_ref:
                item = self._table_ref.item(0, 0)
                if item and item.text().strip():
                    corr_name = item.text().strip()
            self._weigh_one_sample_correction(0, corr_name)
        for row, name, mode in self._valid_rows:
            if not self._running:
                return
            if not name.strip():
                continue
            self._weigh_one_sample(row, name)
        _log("批量样品称量完成")
        self.sig_status_msg.emit("正在上升样盘...")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self._send_cmd(CMD.OPEN_LID, desc="打开炉盖")
        self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示")
        self.sig_weigh_done.emit("sample")

    # ===== 单个称样品 =====
    def _single_sample(self):
        _log("单个称量样品开始, 共 " + str(len(self._valid_rows)) + " 个")
        self.sig_status_msg.emit("正在进入称重模式...")
        self._send_cmd(CMD.ENTER_WEIGH_MODE, desc="进入称量样重状态")
        self._sleep(CMD_INTERVAL_S)
        for row, name, mode in self._valid_rows:
            if not self._running:
                return
            if not name.strip():
                continue
            position = row + 1
            _log("单个称量 row=" + str(row) + " name=" + name + " pos=" + str(position))
            while self._running:
                self._send_move_to(position)
                self._sleep(CMD_INTERVAL_S)
                self._sleep(1.0)
                self._send_cmd(CMD.TARE, desc="天平清零")
                _log("天平清零已发送")
                self._send_cmd(CMD.SAMPLE_PLATE_DOWN, desc="样盘下降")
                # 等上行帧确认下降完成
                _t0 = time.time()
                while self._running and (time.time() - _t0) < 15.0:
                    _, ok = self._read_uplink_weight()
                    if ok:
                        break
                    self._sleep(0.1)
                _log("样盘下降完成, 等待 5.0s 稳定...")
                _start = time.time()
                while self._running and (time.time() - _start) < 5.0:
                    w, ok = self._read_uplink_weight()
                    if ok:
                        self.sig_real_time_sample_weight.emit(round(w - self._get_tare_weight(row), 4))
                    self._sleep(0.5)
                self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示加样")
                self._sleep(CMD_INTERVAL_S)
                tare_weight = self._get_tare_weight(row)
                # 发送天平数据到仪器 (5A 58 ... 协议)
                total_raw, ok = self._read_uplink_weight()
                if ok:
                    sample_raw = round(total_raw - tare_weight, 4) if tare_weight else round(total_raw, 4)
                    self._send_send_weight_to_instrument(sample_raw)
                    _log("发送天平数据到仪器: 总重={:.4f}g 样重={:.4f}g".format(
                        total_raw, sample_raw))
                confirmed = self._wait_confirm_with_display(tare_weight)
                if not self._running:
                    return
                total_weight = self._wait_stable_with_display(1.0)
                total_weight = round(total_weight, 4)
                sample_weight = round(total_weight - tare_weight, 4) if tare_weight else round(total_weight, 4)
                _log("单个称量 row=" + str(row) +
                     " 总重=" + str(total_weight) +
                     " 坩埚重=" + str(tare_weight) +
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
        self.sig_status_msg.emit("正在上升样盘...")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self._send_cmd(CMD.EXIT_WEIGH_MODE, desc="解除称重状态")
        self.sig_weigh_done.emit("sample")

    # ===== 单独称样品(仪器按键确认模式) =====
    def _individual_sample(self):
        """单独称重模式: 逐个样位称量样品，UI按钮确认
        样位从2号开始(跳过1号校正坩埚)
        流程: 移样位→延时1s→去皮→(样盘下降→等待确认→超标判断)*重试
        当 _skip_plate_ops=True: 跳过样盘下降/上升/退出称重（追加样品模式，由调用方统一升降）
        """
        individual_rows = [(r, n, m) for r, n, m in self._valid_rows if r > 0]
        _log("单独称量样品开始, 有效样品 " + str(len(individual_rows)) + " 个")

        self._send_cmd(CMD.ENTER_WEIGH_MODE, desc="进入称量样重状态")
        self._sleep(CMD_INTERVAL_S)

        try:
            for row, name, mode in individual_rows:
                if not self._running:
                    return
                position = row + 1
                _log("单独称量 row=" + str(row) + " name=" + name + " pos=" + str(position))

                # 步骤1: 移动到指定位
                self.sig_weigh_progress.emit({"phase": "individual", "row": row, "name": name, "weight": 0.0})
                self._send_move_to(position)
                self._sleep(CMD_INTERVAL_S)
                # 步骤2: 延时1s等待机械稳定
                self._sleep(1.0)
                # 步骤3: 天平清零(去皮)
                self._send_cmd(CMD.TARE, desc="天平清零")
                _log("天平清零已发送")
                # 提前获取坩埚重，用于实时显示净重
                tare_weight = self._get_tare_weight(row)

                while self._running:
                    # 步骤4: 样盘下降 → 进入称重就绪（追加样品模式跳过，样盘已在低位）
                    if not self._skip_plate_ops:
                        self._send_cmd(CMD.SAMPLE_PLATE_DOWN, desc="样盘下降")
                        _t0 = time.time()
                        while self._running and (time.time() - _t0) < 15.0:
                            _, ok = self._read_uplink_weight()
                            if ok:
                                break
                            self._sleep(0.1)
                        _log("样盘下降完成, 等待确认...")

                    # 步骤5: 等待UI确认(持续刷新净重显示)
                    weight = self._wait_ui_confirm_with_display(row, name, tare_weight)
                    if not self._running:
                        return

                    # 步骤6: 计算样品净重
                    # skip_plate_ops 模式: 天平已用坩埚归零，读数即样品净重
                    if self._skip_plate_ops:
                        sample_weight = round(weight, 4)
                    else:
                        sample_weight = round(weight - tare_weight, 4)
                    _log("单独称量 row=" + str(row) +
                         " 总重=" + str(weight) +
                         " 坩埚重=" + str(tare_weight) +
                         " 样重=" + str(sample_weight))
                    lo, hi = self._get_weight_range_for_mode(mode)
                    if sample_weight < lo or sample_weight > hi:
                        self.sig_weight_out_of_range.emit(name, sample_weight, lo, hi)
                        _log("重量超限 row=" + str(row) + " weight=" + str(sample_weight) +
                             " range=[" + str(lo) + "," + str(hi) + "] 重新称量")
                        continue  # 回到步骤4(样盘下降)

                    # 合格: 保存数据
                    self.sig_single_weigh_done.emit(row, sample_weight)
                    _log("单独称量完成 row=" + str(row) + " weight=" + str(sample_weight))
                    if self._backfill_cb:
                        self._backfill_cb(row, SAMPLE_TARGET_COL, sample_weight, "sample",
                                          total_weight=weight, tare_weight=tare_weight)
                    break  # 进入下一个样位

            _log("单独称量全部完成")
            if not self._skip_plate_ops:
                self.sig_status_msg.emit("正在上升样盘...")
                self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
                self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示")
            self.sig_weigh_done.emit("sample")
        finally:
            if not self._skip_plate_ops:
                self._send_cmd(CMD.EXIT_WEIGH_MODE, desc="解除称重状态")

    # ===== 重新称量（独立封装）=====
    def _reweigh_tare(self):
        """重新称量-准备阶段: 只做机械动作和发送校正值，不称任何坩埚"""
        _log("重新称量准备阶段")
        self._send_long_duration_cmd(CMD.CLOSE_LID, desc="正在关闭炉盖")
        corr_w = self._get_crucible_correction_weight()
        if corr_w > 0:
            _log("发送坩埚校正值: {:.4f}g".format(corr_w))
            from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
            corr_cmd = CommandBuilder.build_send_weight(corr_w)
            send_cmd_with_uplink_check(self._serial, corr_cmd, "坩埚校正值")
            self._sleep(CMD_INTERVAL_S)
        self.sig_status_msg.emit("正在上升样盘...")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self._send_cmd(CMD.OPEN_LID, desc="打开炉盖")
        self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示")
        self.sig_weigh_done.emit("tare")

    def _reweigh_sample(self):
        """重新称量-样品阶段: 只称不合格样品，跳过校正坩埚和合格样品"""
        skip_set = self._reweigh_rows or set()
        _log("重新称量样品阶段, 待称 " + str(len(skip_set)) + " 个不合格样品")
        self._send_long_duration_cmd(CMD.CLOSE_LID, desc="正在关闭炉盖")
        for row, name, mode in self._valid_rows:
            if not self._running:
                return
            if not name.strip():
                continue
            if row not in skip_set:
                _log("row=" + str(row) + " " + name + " 已合格, 跳过")
                continue
            self._weigh_one_sample(row, name)
        _log("重新称量完成")
        self.sig_status_msg.emit("正在上升样盘...")
        self._send_long_duration_cmd(CMD.SAMPLE_PLATE_UP, desc="样盘上升")
        self._send_cmd(CMD.OPEN_LID, desc="打开炉盖")
        self._send_cmd(CMD.BEEPER_1S, desc="蜂鸣提示")
        self.sig_weigh_done.emit("sample")

    def _wait_ui_confirm_with_display(self, row, name, tare_weight=0.0):
        """等待UI确认按钮，期间持续刷新天平读数显示
        参数:
            tare_weight: 坩埚重量(g)，用于显示净重
        返回: 确认时的天平原始读数(g)
        """
        import threading
        self._confirm_event = threading.Event()
        # 通知UI进入确认等待状态
        self.sig_confirm_weigh.emit(row, name, 0.0)
        start = time.time()
        timeout = 300.0
        last_weight = 0.0
        while self._running and not self._confirm_event.is_set():
            if time.time() - start > timeout:
                self.sig_error.emit("等待确认超时(5分钟)")
                return 0.0
            weight, ok = self._read_uplink_weight()
            if ok:
                last_weight = round(weight, 4)
            else:
                self._sleep(0.3)
                continue
            # skip_plate_ops 模式: 天平已用坩埚归零，读数即样品净重
            if self._skip_plate_ops:
                net_weight = round(last_weight, 4)
            else:
                net_weight = round(last_weight - tare_weight, 4)
            self.sig_real_time_sample_weight.emit(net_weight)
            self.sig_weigh_progress.emit({
                "phase": "individual", "row": row, "name": name,
                "weight": net_weight
            })
            # 发送样品净重到仪器（发后不管，不等响应）
            self._send_weight_fire_and_forget(net_weight)
            # 检测仪器按键按下 → 自动确认
            if self._last_btn_pressed:
                self._confirm_event.set()
                break
            self._sleep(0.3)
        return last_weight

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
                self._send_weight_fire_and_forget(sample)
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
        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
        cmd = CommandBuilder.build_send_weight(weight_g)
        send_cmd_with_uplink_check(
            self._serial, cmd, "发送天平数据",
        )

    def _send_weight_fire_and_forget(self, weight_g):
        """发送天平数据到仪器，仅发送不等响应（发后不管）"""
        from protocol_layer import CommandBuilder
        cmd = CommandBuilder.build_send_weight(weight_g)
        self._serial.send(cmd)
        _log("发送天平数据到仪器: {:.4f}g 指令=".format(weight_g) + cmd.hex())

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
        position = row + 1
        _log("坩埚称量 row=" + str(row) + " name=" + name + " pos=" + str(position))
        self.sig_weigh_progress.emit({"phase": "tare", "row": row, "name": name, "weight": 0.0})
        self._send_move_to(position)
        self._sleep(CMD_INTERVAL_S)
        self._sleep(1.0)
        self._send_cmd(CMD.TARE, desc="天平清零")
        _log("天平清零已发送")
        weight = self._wait_descend_and_read(row, name, "tare")
        _log("坩埚重量 row=" + str(row) + " weight=" + str(weight))
        if self._backfill_cb:
            self._backfill_cb(row, TARE_TARGET_COL, weight, "tare")

    # ===== 单个样品称量(批量中使用) =====
    def _weigh_one_sample(self, row, name):
        position = row + 1
        _log("样品称量 row=" + str(row) + " name=" + name + " pos=" + str(position))
        self.sig_weigh_progress.emit({"phase": "sample", "row": row, "name": name, "weight": 0.0})
        self._send_move_to(position)
        self._sleep(CMD_INTERVAL_S)
        self._sleep(1.0)
        self._send_cmd(CMD.TARE, desc="天平清零")
        _log("天平清零已发送")
        tare_weight = self._get_tare_weight(row)
        total_weight = self._wait_descend_and_read(row, name, "sample", tare_weight)
        sample_weight = round(total_weight - tare_weight, 4)
        _log("样品称量 row=" + str(row) +
             " 总重=" + str(total_weight) +
             " 坩埚重=" + str(tare_weight) +
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

    def _weigh_one_sample_correction(self, row, name):
        """称量校正坩埚（样品阶段），样品重直接取坩埚重"""
        position = row + 1
        _log("坩埚样品称量 row=" + str(row) + " name=" + name + " pos=" + str(position))
        self.sig_weigh_progress.emit({"phase": "sample", "row": row, "name": name, "weight": 0.0})
        self._send_move_to(position)
        self._sleep(CMD_INTERVAL_S)
        self._sleep(1.0)
        self._send_cmd(CMD.TARE, desc="天平清零")
        _log("天平清零已发送")
        tare_weight = self._get_tare_weight(row)
        total_weight = self._wait_descend_and_read(row, name, "sample", 0.0)
        sample_weight = total_weight
        _log("校正坩埚样品 row=" + str(row) +
             " 总重=" + str(total_weight) +
             " 坩埚重=" + str(tare_weight) +
             " 样重(取天平读数)=" + str(sample_weight))
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
    def _wait_descend_and_read(self, row, name, phase, tare_weight=0.0):
        """发送样盘下降 → 等上行帧确认 → 5s 持续读数推送 UI → 返回最终重量"""
        self._send_cmd(CMD.SAMPLE_PLATE_DOWN, desc="样盘下降")
        _t0 = time.time()
        while self._running and (time.time() - _t0) < 15.0:
            _, ok = self._read_uplink_weight()
            if ok:
                break
            self._sleep(0.1)
        _log("样盘下降完成, 等待 5.0s 稳定...")
        start = time.time()
        weight = 0.0
        while time.time() - start < 5.0:
            if not self._running:
                break
            w, ok = self._read_uplink_weight()
            if ok:
                weight = w
                display_weight = round(weight - tare_weight, 4) if phase == "sample" else round(weight, 4)
                self.sig_weigh_progress.emit({
                    "phase": phase, "row": row, "name": name, "weight": display_weight
                })
            self._sleep(0.5)
        weight = round(weight, 4)
        _log("称量完成 row={} name={} 重量={:.4f}g".format(row, name, weight))
        return weight

    def _send_cmd(self, func_code, desc=""):
        """发送固定4字节指令（带上行检测+重试）"""
        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
        cmd = CommandBuilder.build_command(func_code)
        _log("发送指令: " + desc + " code=0x" + format(func_code, "02X") +
             " cmd=" + cmd.hex())
        ok = send_cmd_with_uplink_check(
            self._serial, cmd, desc,
        )
        if not ok:
            self.sig_error.emit("指令发送失败: " + desc)

    # 机械类指令（不改变炉温，无需温度检测）
    _MECHANICAL_CMDS = {CMD.SAMPLE_PLATE_UP, CMD.SAMPLE_PLATE_DOWN,
                        CMD.SAMPLE_PLATE_STEP, CMD.SAMPLE_PLATE_HOME,
                        CMD.CLOSE_LID, CMD.OPEN_LID}
    _LID_CMDS = {CMD.CLOSE_LID, CMD.OPEN_LID}

    def _send_long_duration_cmd(self, func_code, desc="", timeout=15.0):
        """发送长耗时指令
        机械类指令：炉盖固定延时，其他机械指令等上行帧确认完成
        热工类指令：通过温度变化检测完成"""
        import time as _t
        self._send_cmd(func_code, desc)
        # 机械类指令
        if func_code in self._MECHANICAL_CMDS:
            if func_code in self._LID_CMDS:
                # 炉盖指令：逐秒倒计时显示
                is_mock = getattr(self._serial._serial, 'port', '') == 'MOCK'
                wait_s = 3.0 if is_mock else LID_WAIT_S
                for remaining in range(int(wait_s), 0, -1):
                    if not self._running:
                        return
                    self.sig_status_msg.emit(f"{desc}... {remaining}s")
                    self._sleep(1)
                _log("mechanical cmd done: " + desc + " (waited " + str(wait_s) + "s)")
            else:
                # 非炉盖机械指令（样盘升降等）：上行帧到达即表示动作完成
                start = _t.time()
                while self._running and (_t.time() - start) < timeout:
                    _, ok = self._read_uplink_weight()
                    if ok:
                        break
                    self._sleep(0.1)
                elapsed = _t.time() - start
                _log("mechanical cmd done: " + desc + " (waited " + str(round(elapsed, 1)) + "s)")
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
        """移动样盘到指定位（带上行检测+重试）"""
        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
        cmd = CommandBuilder.build_move_to(position)
        _log("样盘移动: pos=" + str(position) +
             " cmd=" + cmd.hex())
        ok = send_cmd_with_uplink_check(
            self._serial, cmd, "移动到" + str(position) + "号位",
        )
        if not ok:
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
            self._last_btn_pressed = bool(f.get("btn_pressed", 0))
            raw_str = f.get("raw_str", "?")
            if not hasattr(self, "_last_uplink_raw") or self._last_uplink_raw != raw_str:
                _log("上行帧: raw=" + raw_str +
                     " 重量={:.4f}g 温度={:.1f}C 联机={} 按键={}".format(
                     f["weight"], f["temperature"], f["online"], f["btn_pressed"]))
                self._last_uplink_raw = raw_str
        return f["weight"], True

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

    def _get_crucible_correction_weight(self):
        """从 DB 读取坩埚校正值，优先分析水校正"""
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
    sig_status_msg = Signal(str)  # 使用 BlockingQueuedConnection 确保 UI 在串口指令前刷新
    sig_real_time_sample_weight = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._valid_rows = []
        self._weigh_phase = ""
        self._table_ref = None
        self._worker = None
        self._serial_mgr = None
        self._reweigh_rows = None

    def set_serial_manager(self, mgr):
        self._serial_mgr = mgr

    def set_table(self, table_widget):
        self._table_ref = table_widget

    def set_reweigh_rows(self, rows):
        """设置重新称量模式: 只称这些行的样品，合格行跳过"""
        self._reweigh_rows = set(rows) if rows else None

    def set_skip_plate_ops(self, skip):
        """追加样品模式: 跳过样盘升降操作（样盘已在低位）"""
        self._skip_plate_ops = skip
        if self._worker:
            self._worker._skip_plate_ops = skip

    def start_tare_weigh(self, valid_rows):
        self._valid_rows = self._filter_valid(valid_rows)
        self._weigh_phase = "tare"
        _log("start_tare_weigh: valid_rows=" + str(self._valid_rows))
        self._start_worker("tare")

    def show_add_sample_prompt(self):
        _log("show_add_sample_prompt")
        self.sig_add_sample_prompt.emit()

    def start_sample_weigh(self):
        self._weigh_phase = "sample"
        _log("start_sample_weigh: valid_rows=" + str(self._valid_rows))
        self._start_worker("sample")

    def start_single_sample_weigh(self, valid_rows):
        self._valid_rows = self._filter_valid(valid_rows)
        self._weigh_phase = "single_sample"
        _log("start_single_sample_weigh: valid_rows=" + str(self._valid_rows))
        self._start_worker("single_sample")

    def start_individual_sample_weigh(self, valid_rows):
        self._valid_rows = self._filter_valid(valid_rows)
        self._weigh_phase = "individual_sample"
        _log("start_individual_sample_weigh: valid_rows=" + str(self._valid_rows))
        self._start_worker("individual_sample")

    def start_reweigh_tare(self, valid_rows):
        self._valid_rows = self._filter_valid(valid_rows)
        self._weigh_phase = "reweigh_tare"
        _log("start_reweigh_tare: valid_rows=" + str(self._valid_rows))
        self._start_worker("reweigh_tare")

    def start_reweigh_sample(self):
        self._weigh_phase = "reweigh_sample"
        _log("start_reweigh_sample")
        self._start_worker("reweigh_sample")

    def start_reweigh_direct(self, valid_rows):
        """重新称量-直接模式: 跳过准备阶段，直接从关盖开始称量不合格样品"""
        self._valid_rows = self._filter_valid(valid_rows)
        self._weigh_phase = "reweigh_sample"
        _log("start_reweigh_direct: valid_rows=" + str(self._valid_rows))
        self._start_worker("reweigh_sample")

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
        self._worker.sig_status_msg.connect(self._on_status_msg, Qt.BlockingQueuedConnection)
        self._worker.sig_real_time_sample_weight.connect(self.sig_real_time_sample_weight)
        if self._reweigh_rows is not None:
            self._worker._reweigh_rows = self._reweigh_rows
        if getattr(self, '_skip_plate_ops', False):
            self._worker._skip_plate_ops = True
        if phase == "tare":
            self._worker.run_tare(self._valid_rows)
        elif phase == "sample":
            self._worker.run_sample(self._valid_rows)
        elif phase == "single_sample":
            self._worker.run_single_sample(self._valid_rows)
        elif phase == "individual_sample":
            self._worker.run_individual_sample(self._valid_rows)
        elif phase == "reweigh_tare":
            self._worker.run_reweigh_phase1(self._valid_rows)
        elif phase == "reweigh_sample":
            self._worker.run_reweigh_phase2(self._valid_rows)

    def _on_worker_progress(self, info):
        self.sig_weighing_progress.emit(info)

    def _on_worker_done(self, phase):
        self.sig_weighing_done.emit(phase)

    def _on_worker_error(self, msg):
        _log("Worker错误: " + msg)
        self.sig_error.emit(msg)

    def _on_worker_finished(self):
        _log("Worker线程结束")

    def _on_status_msg(self, msg):
        """从 Worker 线程 BlockingQueuedConnection 回调，确保 UI 在串口指令前更新"""
        self.sig_status_msg.emit(msg)

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
