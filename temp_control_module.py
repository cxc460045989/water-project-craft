# -*- coding: utf-8 -*-
"""控温恒温模块 — 微机全自动水分测定仪底层能力模块2

全局唯一，所有加热场景复用。
完成「升温判定→恒温计时→周期指令维护→结束关断」完整加热流程，
自动处理指令发送逻辑，与具体测试模式完全解耦。

技术约束:
  - 继承 QObject，通过信号槽对外传递数据与状态
  - 支持 moveToThread 多线程运行
  - 所有可变参数通过入参传入
  - 鼓风/氮气互斥逻辑内聚

用法:
    module = TempControlModule(device_op, parent)
    module.temp_progress.connect(on_progress)
    module.temp_finished.connect(on_finished)
    module.temp_error.connect(on_error)
    module.start_heating(
        target_temp=105,
        constant_duration=3600,
        blower_enable=False,
        nitrogen_enable=True,
    )
"""

import time
from typing import Optional

from PySide2.QtCore import QObject, Signal, QTimer

from core_data_entities import DeviceOperator, TempControlConfig
from protocol_layer import CMD

# ======== 可配置默认常量 ========
import os as _os
_SPEED = _os.environ.get('WATER_SPEED_MODE', '0') == '1'
DEFAULT_TICK_MS = 200
DEFAULT_TEMP_CHECK_INTERVAL_S = 1.0
DEFAULT_CMD_STOP_ADVANCE_S = 30.0
DEFAULT_CMD_ALTERNATE_INTERVAL_S = 3.0 if _SPEED else 10.0
DEFAULT_HEAT_THRESHOLD_OFFSET = 5.0


class TempControlModule(QObject):
    """控温恒温模块 — 所有加热场景复用

    执行逻辑（严格按需求实现）:
      1. 启动阶段: 发送「开始控温」→ 根据气路配置发送「水分开始测试」
      2. 升温判定: 实时读取箱内温度，当温度 >= (目标温度 - 5℃) 时进入恒温
      3. 恒温指令维护: 每隔10秒交替发送控温指令与水分测试指令
      4. 指令停止: 当恒温倒计时剩余 < 30秒时停止交替指令
      5. 结束关断: 倒计时归零后发送关鼓风+关氮气

    输入参数 (start_heating):
        target_temp:        目标设定温度 (℃)
        constant_duration:  恒温总时长 (秒)
        blower_enable:      是否开启鼓风（与氮气互斥）
        nitrogen_enable:    是否开启氮气（鼓风关闭时生效）

    输出信号:
        temp_progress:  温区进度
        temp_finished:  恒温完成
        temp_error:     异常
    """

    # ======== 信号定义 ========
    temp_progress = Signal(dict)
    """温区进度: {"stage":"heating"/"holding", "current_temp":float,
       "target_temp":int, "remaining_sec":float, "percent":float}"""

    temp_finished = Signal()
    """恒温完成信号"""

    temp_error = Signal(str)
    """异常信号"""

    # ======== 阶段常量 ========
    STAGE_START = "start"
    STAGE_HEATING = "heating"
    STAGE_HOLDING = "holding"
    STAGE_DONE = "done"

    def __init__(self, device_op: DeviceOperator, parent: QObject = None):
        """初始化控温恒温模块

        参数:
            device_op: DeviceOperator 实例
            parent:    父 QObject
        """
        super().__init__(parent)
        self._dev = device_op

        # 配置
        self._cfg = TempControlConfig()

        # 运行时状态
        self._stage = self.STAGE_START
        self._running = False
        self._current_temp = 0.0
        self._hold_elapsed = 0.0
        self._hold_target = 0.0
        self._last_cmd_time = 0.0
        self._cmd_toggle = False  # False=控温指令 True=水分测试指令

        # 定时器
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_main_tick)
        self._hold_timer = QTimer(self)
        self._hold_timer.timeout.connect(self._on_hold_tick)

    # ================================================================
    # 公共接口
    # ================================================================

    def start_heating(self, target_temp: int, constant_duration: int,
                      blower_enable: bool = False, nitrogen_enable: bool = False):
        """启动控温恒温流程

        参数:
            target_temp:        目标设定温度 (℃)
            constant_duration:  恒温总时长 (秒)
            blower_enable:      是否开启鼓风（与氮气互斥，鼓风优先）
            nitrogen_enable:    是否开启氮气（鼓风关闭时生效）
        """
        if self._running:
            self.temp_error.emit("控温模块已在运行中")
            return
        if target_temp <= 0 or constant_duration <= 0:
            self.temp_error.emit("目标温度与恒温时长必须 > 0")
            return

        self._cfg.target_temp = target_temp
        self._cfg.constant_duration = constant_duration
        self._cfg.blower_enable = blower_enable
        self._cfg.nitrogen_enable = nitrogen_enable

        self._stage = self.STAGE_START
        self._running = True
        self._current_temp = 0.0
        self._hold_elapsed = 0.0
        self._hold_target = float(constant_duration)
        self._last_cmd_time = 0.0
        self._cmd_toggle = False

        from logging_util import logger
        logger.info("[TEMP_CTRL] 启动 target=%dC duration=%ds blower=%s n2=%s" %
                     (target_temp, constant_duration, blower_enable, nitrogen_enable))

        # 阶段1: 启动指令
        self._do_start_commands()
        # 启动主循环
        self._tick_timer.start(DEFAULT_TICK_MS)

    def stop(self):
        """停止控温 — 关加热+关鼓风+关氮气"""
        if self._running:
            self._running = False
            self._tick_timer.stop()
            self._hold_timer.stop()
            self._dev.send_fixed_cmd(CMD.HEAT_OFF, "关加热")
            self._dev.send_fixed_cmd(CMD.FAN_OFF, "关鼓风")
            self._dev.send_fixed_cmd(CMD.N2_OFF, "关氮气")
            from logging_util import logger
            logger.info("[TEMP_CTRL] 已停止")

    def reset(self):
        """重置模块"""
        self.stop()
        self._cfg = TempControlConfig()
        self._stage = self.STAGE_START
        self._current_temp = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_temperature(self) -> float:
        return self._current_temp

    @property
    def current_stage(self) -> str:
        return self._stage

    # ================================================================
    # 启动阶段
    # ================================================================

    def _do_start_commands(self):
        """启动阶段指令发送:
        1. 发送「开始控温」
        2. 根据气路配置发送「水分开始测试」
           - 鼓风开启 → 发 CMD.MOISTURE_TEST_1 (开鼓风)
           - 鼓风关闭 → 发 CMD.MOISTURE_TEST_2 (开氮气)
        """
        # 先发控温指令
        self._dev.send_temp_control(self._cfg.target_temp,
                                     "控温%dC" % self._cfg.target_temp)

        # 再发气路配置对应的水分测试指令
        if self._cfg.blower_enable:
            self._dev.send_fixed_cmd(CMD.MOISTURE_TEST_1, "水分测试(开鼓风)")
        else:
            self._dev.send_fixed_cmd(CMD.MOISTURE_TEST_2, "水分测试(开氮气)")

        self._stage = self.STAGE_HEATING
        self._last_cmd_time = time.time()
        from logging_util import logger
        logger.info("[TEMP_CTRL] 启动指令已发送, 进入升温阶段")

    # ================================================================
    # 主循环 (200ms)
    # ================================================================

    def _on_main_tick(self):
        """主定时器: 200ms 读取温度 + 分阶段处理"""
        if not self._running:
            self._tick_timer.stop()
            return

        # 读取上行温度
        frame = self._dev.read_uplink_frame()
        if frame is not None:
            self._current_temp = frame.get("temperature", self._current_temp)

        if self._stage == self.STAGE_HEATING:
            self._check_heating()
        elif self._stage == self.STAGE_HOLDING:
            self._check_holding_commands()

    # ================================================================
    # 升温阶段: 判定是否达到 (目标温度 - 5℃)
    # ================================================================

    def _check_heating(self):
        """升温判定: 温度 >= (目标温度 - 5℃) → 进入恒温"""
        threshold = self._cfg.target_temp - DEFAULT_HEAT_THRESHOLD_OFFSET
        if self._current_temp >= threshold:
            self._enter_holding()

        # 持续发送进度
        self._emit_progress("heating", self._hold_target)

    def _enter_holding(self):
        """进入恒温状态: 启动恒温倒计时"""
        self._stage = self.STAGE_HOLDING
        self._hold_elapsed = 0.0
        self._last_cmd_time = time.time()
        self._cmd_toggle = False  # 从控温指令开始交替

        # 启动恒温每秒倒计时
        self._hold_timer.start(1000)

        from logging_util import logger
        logger.info("[TEMP_CTRL] 升温完成 %.1fC >= %dC, 进入恒温 %ds" %
                     (self._current_temp, self._cfg.target_temp - 5,
                      self._cfg.constant_duration))

        self._emit_progress("holding", self._hold_target)

    # ================================================================
    # 恒温阶段: 每秒倒计时 + 指令交替
    # ================================================================

    def _on_hold_tick(self):
        """恒温每秒 tick: 倒计时递减，归零 → 结束"""
        if not self._running or self._stage != self.STAGE_HOLDING:
            self._hold_timer.stop()
            return

        self._hold_elapsed += 1.0
        remaining = self._hold_target - self._hold_elapsed

        self._emit_progress("holding", remaining)

        if remaining <= 0:
            self._finish_heating()

    def _check_holding_commands(self):
        """恒温指令维护:
        - 隔10秒交替发送控温指令/水分测试指令
        - 剩余时间 < 30秒: 停止交替发送
        """
        remaining = self._hold_target - self._hold_elapsed
        if remaining <= 0:
            return

        # 剩余时间 < 30秒: 立即停止指令交替
        if remaining < DEFAULT_CMD_STOP_ADVANCE_S:
            return

        # 每10秒交替发送
        now = time.time()
        if now - self._last_cmd_time >= DEFAULT_CMD_ALTERNATE_INTERVAL_S:
            self._last_cmd_time = now
            self._cmd_toggle = not self._cmd_toggle

            if self._cmd_toggle:
                # 发送控温指令
                self._dev.send_temp_control(
                    self._cfg.target_temp,
                    "恒温控温%dC" % self._cfg.target_temp
                )
            else:
                # 发送对应模式的水分测试指令
                if self._cfg.blower_enable:
                    self._dev.send_fixed_cmd(CMD.MOISTURE_TEST_1, "水分测试(鼓风)")
                else:
                    self._dev.send_fixed_cmd(CMD.MOISTURE_TEST_2, "水分测试(氮气)")

            from logging_util import logger
            logger.info("[TEMP_CTRL] 恒温指令交替: %s 剩余=%.0fs" %
                         ("控温" if self._cmd_toggle else "水分测试", remaining))

    # ================================================================
    # 结束关断
    # ================================================================

    def _finish_heating(self):
        """恒温结束: 统一关鼓风 + 关氮气"""
        self._running = False
        self._tick_timer.stop()
        self._hold_timer.stop()

        # 关断气路
        self._dev.send_fixed_cmd(CMD.FAN_OFF, "关鼓风")
        self._dev.send_fixed_cmd(CMD.N2_OFF, "关氮气")
        self._dev.send_fixed_cmd(CMD.HEAT_OFF, "关加热")

        self._stage = self.STAGE_DONE

        from logging_util import logger
        logger.info("[TEMP_CTRL] 恒温完成, 已关断鼓风/氮气/加热")
        self.temp_finished.emit()

    # ================================================================
    # 信号发射
    # ================================================================

    def _emit_progress(self, stage: str, remaining_sec: float):
        """发射温区进度信号"""
        total = float(self._hold_target) if self._hold_target > 0 else 1.0
        if stage == "heating":
            # 升温阶段: 百分比基于温度接近程度
            progress = min(100.0, self._current_temp / max(1.0, float(self._cfg.target_temp)) * 100.0)
            remaining_display = self._hold_target
        else:
            # 恒温阶段: 百分比基于时间消耗
            elapsed = self._hold_elapsed
            progress = min(100.0, elapsed / total * 100.0)
            remaining_display = max(0.0, self._hold_target - self._hold_elapsed)

        self.temp_progress.emit({
            "stage": stage,
            "current_temp": round(self._current_temp, 1),
            "target_temp": self._cfg.target_temp,
            "remaining_sec": round(remaining_display, 1),
            "percent": round(progress, 1),
        })
