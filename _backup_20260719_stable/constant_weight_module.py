# -*- coding: utf-8 -*-
"""恒重循环模块 — 微机全自动水分测定仪底层能力模块3

全局唯一，所有恒重场景复用。
自动执行多轮「加热→称重」循环，处理重量前移逻辑，
直到满足恒重精度或达到最大循环次数。
内部复用【控温恒温模块】与【批量称重模块】，不重复实现加热与称重逻辑。

技术约束:
  - 继承 QObject，通过信号槽对外传递数据与状态
  - 支持 moveToThread 多线程运行
  - 所有可变参数通过入参传入
  - 内部组合控温恒温模块与批量称重模块

用法:
    cycle_module = ConstantWeightCycleModule(device_op, parent)
    cycle_module.cycle_progress.connect(on_progress)
    cycle_module.cycle_finished.connect(on_finished)
    cycle_module.cycle_error.connect(on_error)
    cycle_module.start_cycle(
        temp_config=TempControlConfig(target_temp=105, constant_duration=600, ...),
        interval_duration=300,
        constant_precision=0.001,
        max_cycle_times=3,
        correct_diff=0.5,
        init_check_weight=10.0,
        positions=[1,2,3],
    )
"""

import time
from typing import List, Optional

from PySide2.QtCore import QObject, Signal, QTimer

from core_data_entities import (
    DeviceOperator, ConstantWeightConfig, ConstantWeightResult,
    CycleRecord, WeighRecord, TempControlConfig,
)
from batch_weigh_module import BatchWeighModule
from temp_control_module import TempControlModule

DEFAULT_TICK_MS = 200


class ConstantWeightCycleModule(QObject):
    """恒重循环模块 — 所有恒重场景复用

    执行逻辑（严格按需求实现）:
      1. 初始化: check_dry_weight = init_check_weight, dry_weight = 0
      2. 循环体:
          a. 调用控温恒温模块执行一轮加热
          b. 调用批量称重模块获取校正后重量
          c. 重量前移: 原 dry_weight → check_dry_weight, 新重量 → dry_weight
          d. 恒重判定: (check_dry_weight - dry_weight <= 恒重精度)
             或 循环次数 >= 最大次数 → 终止
          e. 不满足则重复循环
      3. 返回最终结果

    输入参数 (start_cycle):
        temp_config:        温度与气路配置 (TempControlConfig)
        interval_duration:  恒重称量间隔时长 (秒)
        constant_precision: 恒重精度阈值 (g)
        max_cycle_times:    最大循环次数（防死循环）
        correct_diff:       坩埚校正差值
        init_check_weight:  首轮检查性干燥重量 (g)
        positions:          称重样品位号列表
        weigh_scene:        称重场景标记

    输出信号:
        cycle_progress: 恒重循环进度
        cycle_finished: 恒重完成
        cycle_error:    异常
    """

    # ======== 信号定义 ========
    cycle_progress = Signal(dict)
    """循环进度: {"cycle_index":int, "max_cycles":int, "weight_diff":float,
       "precision":float, "check_dry_weight":float, "dry_weight":float}"""

    cycle_finished = Signal(object)
    """恒重完成: 携带 ConstantWeightResult 对象"""

    cycle_error = Signal(str)
    """异常信号"""

    # ======== 子模块信号透传 ========
    temp_progress = Signal(dict)
    """透传控温模块温区进度"""

    weigh_progress = Signal(dict)
    """透传称重模块称重进度"""

    # ======== 状态机常量 ========
    _ST_IDLE = "idle"
    _ST_INIT = "init"
    _ST_HEAT = "heat"
    _ST_WAIT_HEAT = "wait_heat"
    _ST_WEIGH = "weigh"
    _ST_WAIT_WEIGH = "wait_weigh"
    _ST_JUDGE = "judge"
    _ST_NEXT = "next"
    _ST_DONE = "done"

    def __init__(self, device_op: DeviceOperator, parent: QObject = None):
        """初始化恒重循环模块

        参数:
            device_op: DeviceOperator 实例
            parent:    父 QObject
        """
        super().__init__(parent)
        self._dev = device_op

        # 配置
        self._cfg = ConstantWeightConfig()

        # 子模块（复用控温恒温模块 + 批量称重模块）
        self._temp_module = TempControlModule(device_op, self)
        self._weigh_module = BatchWeighModule(device_op, self)

        # 连接子模块信号
        self._temp_module.temp_progress.connect(self.temp_progress)
        self._temp_module.temp_finished.connect(self._on_heat_done)
        self._temp_module.temp_error.connect(self.cycle_error)

        self._weigh_module.weigh_progress.connect(self.weigh_progress)
        self._weigh_module.weigh_finished.connect(self._on_weigh_done)
        self._weigh_module.weigh_error.connect(self.cycle_error)

        # 运行时状态
        self._state = self._ST_IDLE
        self._running = False
        self._cycle_index = 0
        self._check_dry_weight = 0.0  # 检查性干燥重量
        self._dry_weight = 0.0        # 当前干燥重量
        self._positions: List[int] = []
        self._weigh_scene = ""
        self._cycle_records: List[CycleRecord] = []
        self._current_cycle_record: Optional[CycleRecord] = None
        self._heat_done = False
        self._weigh_done = False
        self._weigh_result = None

        # 定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    # ================================================================
    # 公共接口
    # ================================================================

    def start_cycle(self, temp_config: TempControlConfig,
                    interval_duration: int, constant_precision: float,
                    max_cycle_times: int, correct_diff: float,
                    init_check_weight: float, positions: List[int],
                    weigh_scene: str = "恒重称重"):
        """启动恒重循环

        参数:
            temp_config:        温度与气路配置（透传给控温恒温模块）
            interval_duration:  恒重称量间隔时长 (秒), 每轮循环恒温时间
            constant_precision: 恒重精度阈值 (g)
            max_cycle_times:    最大循环次数
            correct_diff:       坩埚校正差值（透传称重模块）
            init_check_weight:  首轮检查性干燥重量 (g)
            positions:          称重样品位号列表
            weigh_scene:        称重场景标记
        """
        if self._running:
            self.cycle_error.emit("恒重循环模块已在运行中")
            return
        if not positions:
            self.cycle_error.emit("样品位号列表为空")
            return
        if max_cycle_times < 1:
            self.cycle_error.emit("最大循环次数必须 >= 1")
            return

        self._cfg.temp_config = temp_config
        self._cfg.interval_duration = interval_duration
        self._cfg.constant_precision = constant_precision
        self._cfg.max_cycle_times = max_cycle_times
        self._cfg.correct_diff = correct_diff
        self._cfg.init_check_weight = init_check_weight
        self._positions = list(positions)
        self._weigh_scene = weigh_scene

        # 初始化重量: check_dry_weight = 首轮检查性干燥重量, dry_weight = 0
        self._check_dry_weight = init_check_weight
        self._dry_weight = 0.0
        self._cycle_index = 0
        self._cycle_records = []
        self._heat_done = False
        self._weigh_done = False
        self._weigh_result = None

        self._running = True
        self._state = self._ST_INIT

        from logging_util import logger
        logger.info("[CONST_WEIGHT] 启动 precision=%.4f max_cycles=%d "
                     "init_check=%.4f interval=%ds positions=%s" %
                     (constant_precision, max_cycle_times,
                      init_check_weight, interval_duration, str(positions)))

        self._timer.start(DEFAULT_TICK_MS)

    def stop(self):
        """停止恒重循环 — 同时停止子模块"""
        self._running = False
        self._timer.stop()
        self._temp_module.stop()
        self._weigh_module.stop()
        self._state = self._ST_IDLE
        from logging_util import logger
        logger.info("[CONST_WEIGHT] 已停止")

    def reset(self):
        """重置模块"""
        self.stop()
        self._cfg = ConstantWeightConfig()
        self._temp_module.reset()
        self._weigh_module.reset()
        self._cycle_index = 0
        self._cycle_records = []

    @property
    def is_running(self) -> bool:
        return self._running

    # ================================================================
    # 状态机主循环
    # ================================================================

    def _on_tick(self):
        if not self._running:
            self._timer.stop()
            return
        handler = getattr(self, "_handle_" + self._state, None)
        if handler:
            handler()

    # ================================================================
    # 状态处理
    # ================================================================

    def _handle_init(self):
        """初始化: 创建当前循环记录，启动第一轮加热"""
        self._current_cycle_record = CycleRecord(cycle_index=self._cycle_index)
        self._heat_done = False
        self._weigh_done = False
        self._weigh_result = None

        from logging_util import logger
        logger.info("[CONST_WEIGHT] 第%d轮加热开始 check_dry=%.4f dry=%.4f" %
                     (self._cycle_index + 1, self._check_dry_weight, self._dry_weight))

        # 步骤a: 调用控温恒温模块，恒温时长使用 interval_duration
        cfg = self._cfg.temp_config
        self._temp_module.start_heating(
            target_temp=cfg.target_temp,
            constant_duration=self._cfg.interval_duration,
            blower_enable=cfg.blower_enable,
            nitrogen_enable=cfg.nitrogen_enable,
        )
        self._state = self._ST_WAIT_HEAT

    def _handle_wait_heat(self):
        """等待加热完成（由信号驱动 _on_heat_done）"""
        pass

    def _on_heat_done(self):
        """加热完成回调 → 启动称重"""
        if not self._running or self._state != self._ST_WAIT_HEAT:
            return

        from logging_util import logger
        logger.info("[CONST_WEIGHT] 第%d轮加热完成, 开始称重" % (self._cycle_index + 1))

        # 步骤b: 调用批量称重模块
        self._weigh_module.start_weigh(
            scene="%s-第%d轮" % (self._weigh_scene, self._cycle_index + 1),
            positions=self._positions,
            correct_diff=self._cfg.correct_diff,
        )
        self._state = self._ST_WAIT_WEIGH

    def _handle_wait_weigh(self):
        """等待称重完成（由信号驱动 _on_weigh_done）"""
        pass

    def _on_weigh_done(self, result):
        """称重完成回调 → 重量前移 + 恒重判定"""
        if not self._running or self._state != self._ST_WAIT_WEIGH:
            return
        self._weigh_result = result
        self._state = self._ST_JUDGE

    def _handle_judge(self):
        """恒重判定逻辑"""
        if self._weigh_result is None:
            self.cycle_error.emit("称重结果为空, 无法判定恒重")
            self._finish_with_error()
            return

        # 取本轮所有样品校正后重量的平均值作为本轮干燥重量
        records = self._weigh_result.records
        if records:
            self._dry_weight = round(
                sum(r.corrected_weight for r in records) / len(records), 4
            )
        else:
            self._dry_weight = 0.0

        # 重量前移逻辑:
        #   本轮 dry_weight = 称重均值（在上面已赋值）
        #   判定用差值 = |上一轮干燥重(check) - 本轮干燥重(dry)|
        weight_diff = round(abs(self._check_dry_weight - self._dry_weight), 6)

        from logging_util import logger
        logger.info("[CONST_WEIGHT] 第%d轮 check_dry=%.4f dry=%.4f diff=%.6f prec=%.4f" %
                     (self._cycle_index + 1, self._check_dry_weight,
                      self._dry_weight, weight_diff, self._cfg.constant_precision))

        # 记录本轮
        self._current_cycle_record.check_dry_weight = self._check_dry_weight
        self._current_cycle_record.dry_weight = self._dry_weight
        self._current_cycle_record.weight_diff = weight_diff
        self._current_cycle_record.weigh_records = list(records) if records else []
        self._cycle_records.append(self._current_cycle_record)

        # 发射循环进度
        self.cycle_progress.emit({
            "cycle_index": self._cycle_index,
            "max_cycles": self._cfg.max_cycle_times,
            "weight_diff": weight_diff,
            "precision": self._cfg.constant_precision,
            "check_dry_weight": self._check_dry_weight,
            "dry_weight": self._dry_weight,
        })

        # 步骤d: 恒重判定
        # 条件1: check_dry_weight - dry_weight <= 恒重精度
        # 条件2: 循环次数 >= 最大次数
        precision_met = weight_diff <= self._cfg.constant_precision
        max_reached = (self._cycle_index + 1) >= self._cfg.max_cycle_times

        if precision_met or max_reached:
            self._state = self._ST_DONE
        else:
            self._state = self._ST_NEXT

    def _handle_next(self):
        """准备下一轮循环: 重量前移"""
        # 重量前移: 原 dry_weight → check_dry_weight
        # (新 dry_weight 将在下一轮称重完成后赋值)
        self._check_dry_weight = self._dry_weight
        self._dry_weight = 0.0
        self._cycle_index += 1
        self._state = self._ST_INIT

        from logging_util import logger
        logger.info("[CONST_WEIGHT] 进入第%d轮, 前移后 check_dry=%.4f" %
                     (self._cycle_index + 1, self._check_dry_weight))

    def _handle_done(self):
        """恒重循环完成"""
        self._timer.stop()
        self._running = False

        precision_met = (
            self._cycle_records
            and self._cycle_records[-1].weight_diff <= self._cfg.constant_precision
        )
        max_reached = self._cycle_index + 1 >= self._cfg.max_cycle_times

        result = ConstantWeightResult(
            final_dry_weight=self._dry_weight,
            total_cycles=self._cycle_index + 1,
            cycle_records=self._cycle_records,
            is_precision_met=precision_met,
            is_max_cycle_reached=max_reached,
        )

        from logging_util import logger
        logger.info("[CONST_WEIGHT] 完成 cycles=%d final_dry=%.4f precision_met=%s max_reached=%s" %
                     (result.total_cycles, result.final_dry_weight,
                      precision_met, max_reached))

        self._state = self._ST_IDLE
        self.cycle_finished.emit(result)

    def _finish_with_error(self):
        """异常终止"""
        self._timer.stop()
        self._running = False
        self._temp_module.stop()
        self._weigh_module.stop()
        self._state = self._ST_IDLE

    def _handle_idle(self):
        pass
