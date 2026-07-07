# -*- coding: utf-8 -*-
"""??????? - ??????????
???????-??????????
??????(??-??-??)??????????????
????????????????(???????)
??: protocol_layer.py, serial_comm.py, db.py
??: QTimer?? + ???
"""

import time
from PySide2.QtCore import QObject, Signal, QTimer
from protocol_layer import CommandBuilder, CMD, UplinkBuffer
from logging_util import logger

HANDSHAKE_RETRIES = 10
CMD_INTERVAL_S = 0.15
STABLE_WEIGHT_SAMPLES = 15
STABLE_TOLERANCE = 0.0005
UPLINK_TIMEOUT_S = 3.0
CMD_REPEAT_INTERVAL_S = 30
BEEPER_DURATION_S = 10


def _log(msg):
    logger.info("[TEST] " + msg)


class TestConfig:
    """?????????????????"""

    def __init__(self):
        # ?????
        self.aw_temp = 105
        self.aw_time = 60
        self.aw_precision = 0.0010
        self.aw_fan = False
        self.aw_const_check = True
        self.aw_interval = 5
        self.aw_corr_crucible = 0.0
        self.aw_corr_dry = 0.0
        self.aw_tare_weight = 0.0
        # ????
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
        """? db.load_params() + ??????"""
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
    """?????????"""
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
    """??????? - QTimer??????"""

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

    # ========= ???? =========

    def start_test(self):
        """??????? - ????????"""
        _log("????")
        self._running = True
        self._paused = False
        self._phase = ""
        self._start_phase("analysis_water", self.cfg)
        self._timer.start(self._tick_interval_ms)

    def stop_test(self):
        """???? - ??????????"""
        _log("????")
        self._running = False
        self._paused = False
        self._timer.stop()
        self._hold_timer.stop()
        self._safe_send_cmd(CMD.HEAT_OFF, "????")
        self._safe_send_cmd(CMD.GAS_ALL_OFF, "??????")
        self._safe_send_cmd(CMD.BEEPER_OFF, "????")

    def pause_test(self):
        self._paused = True
        _log("????")

    def resume_test(self):
        self._paused = False
        _log("????")

    @property
    def is_running(self):
        return self._running

    # ========= ???? =========

    def _start_phase(self, phase_name, cfg):
        """????????????????"""
        self._phase = phase_name
        self._state = TestPhaseState(cfg)
        # ??????
        mode_filter = "分析水" if phase_name == "analysis_water" else "全水"
        self._state.samples = [
            s for s in cfg.samples
            if s[1].strip() and (s[2] == mode_filter or not s[2]) and s[3] is not None
        ]
        _log("?? %s ??, ???? %d ?" % (phase_name, len(self._state.samples)))
        self.sig_phase_changed.emit(phase_name)
        label = "?????" if phase_name == "analysis_water" else "????"
        self.sig_status_msg.emit("??: " + label)

        if not self._state.samples:
            _log("?? %s ?????, ??" % phase_name)
            self._on_phase_done()
            return

        self._state.stage_done = False
        self._state.cycle_count = 0
        self._step_start_moisture_test()

    def _on_phase_done(self):
        """????????????????"""
        if self._phase == "analysis_water":
            _log("???????, ???????")
            self.sig_phase_done.emit("analysis_water")
            self._start_phase("total_water", self.cfg)
        else:
            _log("??????, ????")
            self.sig_phase_done.emit("total_water")
            self._on_test_complete()

    def _on_test_complete(self):
        """????? - ????+????"""
        self._timer.stop()
        self._hold_timer.stop()
        self._running = False
        self.sig_status_msg.emit("????")
        self.sig_test_done.emit()
        # ????
        if self.cfg.beep_enabled:
            self._safe_send_cmd(CMD.BEEPER_ON, "???")
            self.sig_beeper_start.emit()
            QTimer.singleShot(BEEPER_DURATION_S * 1000, self._auto_stop_beeper)

    def _auto_stop_beeper(self):
        """??????"""
        if self._serial and self._serial.is_connected:
            self._safe_send_cmd(CMD.BEEPER_OFF, "???")
        self.sig_beeper_stop.emit()

    # ========= ??2: ???????? =========

    def _step_start_moisture_test(self):
        """??????????(?/???)"""
        fan_on = self._state.cfg.aw_fan if self._phase == "analysis_water" else self._state.cfg.tw_fan
        func = CMD.MOISTURE_TEST_1 if fan_on else CMD.MOISTURE_TEST_2
        label = "???" if fan_on else "???"
        desc = "??????(" + label + ")"
        self.sig_step_progress.emit(desc)
        _log(desc)
        self._send_cmd_with_handshake(func, desc, callback=self._step_send_temp_control)

    # ========= ??3: ?????? =========

    def _step_send_temp_control(self):
        """??????(???? 5A 57 x1-x4 44)"""
        temp_c = self._state.cfg.aw_temp if self._phase == "analysis_water" else self._state.cfg.tw_temp
        cmd = CommandBuilder.build_temp_control(temp_c)
        desc = "???? %dC" % temp_c
        self.sig_step_progress.emit(desc)
        _log(desc)
        self._send_raw_with_handshake(cmd, desc, callback=self._step_wait_heating)

    # ========= ??4: ?????????? =========

    def _step_wait_heating(self):
        """??????(?_on_tick????)"""
        if not self._running:
            return
        temp = self._state.cfg.aw_temp if self._phase == "analysis_water" else self._state.cfg.tw_temp
        hold_minutes = self._state.cfg.aw_time if self._phase == "analysis_water" else self._state.cfg.tw_time
        self._state.hold_target = hold_minutes * 60
        self._state.holding = False
        self._state.hold_elapsed = 0.0
        self._state.last_cmd_time = time.time()
        self.sig_status_msg.emit("???? >=" + str(temp - 5) + "C...")
        _log("???? ??>=" + str(temp - 5) + "C ??" + str(hold_minutes) + "??")

    def _on_hold_tick(self):
        """?????????"""
        if not self._running or self._paused:
            return
        self._state.hold_elapsed += 1
        remaining = int(self._state.hold_target - self._state.hold_elapsed)
        if remaining <= 0:
            self._hold_timer.stop()
            self.sig_hold_countdown.emit(0)
            _log("????")
            self._step_hold_end()
        else:
            self.sig_hold_countdown.emit(remaining)
            # ??>1??: ?30???????
            if remaining > 60:
                now = time.time()
                if now - self._state.last_cmd_time >= CMD_REPEAT_INTERVAL_S:
                    self._state.last_cmd_time = now
                    fan_on = self._state.cfg.aw_fan if self._phase == "analysis_water" else self._state.cfg.tw_fan
                    func = CMD.MOISTURE_TEST_1 if fan_on else CMD.MOISTURE_TEST_2
                    self._send_cmd_with_handshake(func, "??????", callback=None)
            # ??30?: ???????
            if remaining == 30:
                _log("????30?, ????")
                self._send_cmd_with_handshake(CMD.N2_OFF, "???", callback=None)
                self._send_cmd_with_handshake(CMD.FAN_OFF, "???", callback=None)

    # ========= ??5: ????-?? =========

    def _step_hold_end(self):
        """???????-????"""
        self.sig_step_progress.emit("????, ????")
        self.sig_status_msg.emit("????...")
        _log("????, ???? %d ???" % len(self._state.samples))
        self._do_weighing()

    # ========= ???(200ms) =========

    def _on_tick(self):
        """200ms??: ?????????????????"""
        if not self._running or self._paused:
            return
        # ??????
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

        # ????: ????????????
        if self._state and not self._state.holding and not self._state.stage_done:
            temp = self._state.cfg.aw_temp if self._phase == "analysis_water" else self._state.cfg.tw_temp
            if self._current_temp >= (temp - 5):
                self._state.holding = True
                self._state.hold_elapsed = 0
                self._state.last_cmd_time = time.time()
                hold_min = int(self._state.hold_target / 60)
                self.sig_hold_started.emit(hold_min)
                self.sig_status_msg.emit("????? %d:00" % hold_min)
                _log("?? %.1fC ??, ???? %d ??" % (self._current_temp, hold_min))
                self._hold_timer.start(1000)

    # ========= ???? =========

    def _do_weighing(self):
        """????: ???????? -> ?????? -> ??"""
        corr_w = self._state.cfg.aw_corr_crucible if self._phase == "analysis_water" else self._state.cfg.tw_corr_crucible
        if corr_w > 0:
            cmd = CommandBuilder.build_send_weight(corr_w)
            self._send_raw_with_handshake(cmd, "???????? %.4fg" % corr_w)
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
                self.sig_error.emit("???? row=%d %s" % (row_idx, name))
                continue
            # ????: ???? = ???? - ??? + (????? - ???????)
            dry_weight = round(stable_weight - tare + tare_offset, 4)
            mid_val = int(round(dry_weight * 10000)) + 1000000
            _log("?? row=%d name=%s ??=%.4f ???=%.4f ???=%.4f" %
                 (row_idx, name, stable_weight, tare, dry_weight))
            self.sig_weigh_result.emit(row_idx, dry_weight, self._phase)
            self._save_weigh_result(row_idx, name, mode, stable_weight, mid_val, dry_weight, tare, tare_offset)
            results.append((row_idx, dry_weight))

        self.sig_status_msg.emit("????, %d ???" % len(results))
        self.sig_weigh_batch_done.emit(self._phase)
        _log("???? %d ?" % len(results))
        self._step_const_check(results)

    # ========= ??6: ???? =========

    def _step_const_check(self, weigh_results):
        """???? + ??????"""
        const_check = self._state.cfg.aw_const_check if self._phase == "analysis_water" else self._state.cfg.tw_const_check
        if not const_check:
            _log("??????, ????")
            self._state.stage_done = True
            self._on_phase_done()
            return

        precision = self._state.cfg.aw_precision if self._phase == "analysis_water" else self._state.cfg.tw_precision
        all_passed = True
        for row_idx, dry_weight in weigh_results:
            check_dry = self._load_check_dry_weight(row_idx)
            if check_dry is None:
                self._save_check_dry_weight(row_idx, dry_weight)
                _log("??????????? row=%d weight=%.4f" % (row_idx, dry_weight))
                all_passed = False
                continue
            # ??: abs(????? - ????) <= ????
            diff = abs(check_dry - dry_weight)
            passed = diff <= precision
            self.sig_const_check_result.emit(row_idx, passed, dry_weight, check_dry)
            _log("???? row=%d ?????=%.4f ????=%.4f diff=%.4f prec=%.4f %s" %
                 (row_idx, check_dry, dry_weight, diff, precision, "??" if passed else "???"))
            if not passed:
                all_passed = False
                self._save_check_dry_weight(row_idx, dry_weight)
                _log("???, ?????? row=%d weight=%.4f" % (row_idx, dry_weight))

        if all_passed:
            _log("??????????")
            self._state.stage_done = True
            self._on_phase_done()
        else:
            self._state.cycle_count += 1
            _log("???????, ????(? %d ?)" % self._state.cycle_count)
            self.sig_status_msg.emit("???????, ????(? %d ?)" % self._state.cycle_count)
            self._state.holding = False
            self._state.hold_elapsed = 0.0
            self._step_send_temp_control()

    # ========= ???????? =========

    def _send_cmd_with_handshake(self, func_code, desc, callback=None):
        """?? -> ????4??????"""
        if not self._running:
            return
        if not self._do_handshake():
            self.sig_error.emit("????: " + desc)
            return
        self._serial.flush_input()
        cmd = CommandBuilder.build_command(func_code)
        n = self._serial.send(cmd)
        if n == 0:
            self.sig_error.emit("??????: " + desc)
            return
        _log("?????: %s %s" % (desc, cmd.hex()))
        if callback:
            QTimer.singleShot(int(CMD_INTERVAL_S * 1000), callback)

    def _send_raw_with_handshake(self, cmd_bytes, desc, callback=None):
        """?????????????"""
        if not self._running:
            return
        if not self._do_handshake():
            self.sig_error.emit("????: " + desc)
            return
        self._serial.flush_input()
        n = self._serial.send(cmd_bytes)
        if n == 0:
            self.sig_error.emit("??????: " + desc)
            return
        _log("?????: %s %s" % (desc, cmd_bytes.hex()))
        if callback:
            QTimer.singleShot(int(CMD_INTERVAL_S * 1000), callback)

    def _safe_send_cmd(self, func_code, desc):
        """????????(?????)"""
        if not self._serial or not self._serial.is_connected:
            return
        try:
            self._serial.flush_input()
            cmd = CommandBuilder.build_command(func_code)
            self._serial.send(cmd)
            _log("????: %s %s" % (desc, cmd.hex()))
        except Exception as e:
            _log("????????: " + str(e))

    def _do_handshake(self):
        """????, ????????
        ????????OK???????100ms??
        ???????3?+???????????
        """
        self._serial.flush_input()
        self._serial.send(CommandBuilder.build_command(CMD.HANDSHAKE))
        time.sleep(0.08)
        resp = self._serial.read_all()
        if resp and b"OK" in resp:
            return True

        for attempt in range(HANDSHAKE_RETRIES * 3):
            if not self._running:
                return False
            elapsed = time.time() - self._last_uplink_time
            if elapsed > UPLINK_TIMEOUT_S:
                _log("??+?????? %.1fs, ??????" % elapsed)
                return False
            time.sleep(0.1)
            self._serial.flush_input()
            self._serial.send(CommandBuilder.build_command(CMD.HANDSHAKE))
            time.sleep(0.08)
            resp = self._serial.read_all()
            if resp and b"OK" in resp:
                return True
            _log("???, ???? %d..." % (attempt + 1))
        return False

    def _wait_stable_weight(self, timeout=15.0):
        """????????, ??????
        ??STABLE_WEIGHT_SAMPLES?????<=STABLE_TOLERANCE????
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
        """?????????"""
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

    # ========= ????? =========

    def _save_weigh_result(self, row_idx, name, mode, raw_weight, mid_val, dry_weight, tare_weight, tare_offset):
        """??????????(????+??????)"""
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
            _log("DB?? row=%d dry=%.4f" % (row_idx, dry_weight))
        except Exception as e:
            _log("DB????: %s" % str(e))

    def _save_raw_data_backup(self, experiment_id, row_idx, name, mode,
                               raw_weight, mid_val, dry_weight,
                               tare_weight, tare_offset, phase):
        """????????????raw_data_backup?"""
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
            _log("????????: %s" % str(e))

    def _load_check_dry_weight(self, row_idx):
        """????????????"""
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
        """?????????????????"""
        try:
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            upsert_experiment_sample(eid, row_idx, check_dry_weight=weight)
            _log("????????? row=%d weight=%.4f" % (row_idx, weight))
        except Exception as e:
            _log("???????????: %s" % str(e))


class TestController(QObject):
    """?????-????,??Worker????"""

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
        """??????
        ??: config - TestConfig ??
        """
        if self._worker and self._worker.is_running:
            _log("???????")
            return
        _log("?? TestWorker")
        self._worker = TestWorker(self._serial, config, self)
        # ??????
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
        """????"""
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