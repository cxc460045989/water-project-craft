# -*- coding: utf-8 -*-
"""主流程控制器 — 微机全自动水分测定仪

负责前置校验、模式优先级调度、模块调用编排、数据汇总、结果落库、
状态同步至现有进度组件。所有称重/控温/恒重逻辑必须调用底层模块。

状态机生命周期:
  IDLE → INIT → (RECHECK_WEIGH) → AW_HEAT → AW_WEIGH → (AW_CONST) → AW_CALC
  → TW_HEAT → TW_WEIGH → (TW_CONST) → TW_CALC → FINISHING → DONE
  任意状态 → ERROR（异常）或 STOPPING（手动停止）

控制接口:
  start() — 原有界面「开始测试」按钮调用
  stop()  — 原有界面「停止测试」按钮调用

技术约束:
  - Python 3.8 + PySide2 QObject + QTimer 状态机
  - 不开发界面，仅通过标准化信号推送至项目原有测试进度组件
  - 流程运行在独立工作线程，非阻塞主线程
"""

import time, json
from typing import List, Dict, Optional
from datetime import datetime

from PySide2.QtCore import QObject, Signal, QTimer

from core_data_entities import (
    DeviceOperator, TempControlConfig, ConstantWeightResult,
    BatchWeighResult, WeighRecord,
)
from batch_weigh_module import BatchWeighModule
from temp_control_module import TempControlModule
from constant_weight_module import ConstantWeightCycleModule

# ======== 状态机阶段常量 ========
class Stage:
    IDLE = "idle"                    # 待机
    INIT = "init"                    # 初始化（加载参数、校验）
    RECHECK_WEIGH = "recheck"        # 复检称重
    AW_HEAT = "aw_heat"              # 分析水升温恒温
    AW_WEIGH = "aw_weigh"            # 分析水称重
    AW_CONST = "aw_const"            # 分析水恒重循环
    AW_CALC = "aw_calc"              # 分析水计算
    TW_HEAT = "tw_heat"              # 全水升温恒温
    TW_WEIGH = "tw_weigh"            # 全水称重
    TW_CONST = "tw_const"            # 全水恒重循环
    TW_CALC = "tw_calc"              # 全水计算
    FINISHING = "finishing"          # 全流程收尾
    DONE = "done"                    # 已完成
    ERROR = "error"                  # 异常停止
    STOPPING = "stopping"            # 手动停止中

# 有序阶段列表（用于进度索引）
_ORDERED_STAGES = [
    Stage.INIT, Stage.RECHECK_WEIGH,
    Stage.AW_HEAT, Stage.AW_WEIGH, Stage.AW_CONST, Stage.AW_CALC,
    Stage.TW_HEAT, Stage.TW_WEIGH, Stage.TW_CONST, Stage.TW_CALC,
    Stage.FINISHING, Stage.DONE,
]

# ======== 超时/重试配置 ========
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_S = 30.0


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class TestProcessController(QObject):
    """主流程控制器 — 点击开始测试后的全流程编排

    信号（标准化输出，对接原有测试进度组件）:
      stage_changed(str, int, int, str)  — 阶段变更: 阶段名, 当前索引, 总阶段数, 模式
      process_update(dict)               — 实时进度: 温度/剩余时间/轮次/重量差值...
      test_finished(object)              — 测试完成: FullTestResult
      test_error(str)                    — 异常: 错误描述
      test_stopped()                     — 手动停止
    """

    # ======== 标准化信号 ========
    stage_changed = Signal(str, int, int, str)
    """阶段变更: stage_name, stage_index, total_stages, mode"""

    process_update = Signal(dict)
    """实时进度: {"temp":float, "remaining_sec":float, "cycle":int,
       "weight_diff":float, "stage_desc":str, ...}"""

    test_finished = Signal(object)
    """测试完成: FullTestResult"""

    test_error = Signal(str)
    """异常: 错误描述"""

    test_stopped = Signal()
    """手动停止"""

    # ======== 透传底层模块进度（供界面组件直接监听） ========
    sub_temp_progress = Signal(dict)
    sub_weigh_progress = Signal(dict)
    sub_cycle_progress = Signal(dict)

    def __init__(self, device_op: DeviceOperator, parent: QObject = None):
        """
        参数:
            device_op: DeviceOperator 实例
            parent:    父 QObject
        """
        super().__init__(parent)
        self._dev = device_op

        # ---- 子模块（在 start 时创建，stop 时销毁） ----
        self._weigh_module: Optional[BatchWeighModule] = None
        self._temp_module: Optional[TempControlModule] = None
        self._cycle_module: Optional[ConstantWeightCycleModule] = None

        # ---- 状态机 ----
        self._stage = Stage.IDLE
        self._running = False
        self._stopping = False

        # ---- 运行时数据 ----
        self._params: Dict = {}              # DB 参数
        self._samples: List[Dict] = []       # 样品列表
        self._experiment_id: int = 0
        self._session_id: int = 0

        # 当前模式上下文
        self._current_mode = ""              # "分析水" / "全水"
        self._mode_params: Dict = {}          # 当前模式参数快照
        self._mode_calc_data: Dict = {}       # 当前模式计算结果

        # 汇总结果
        self._aw_results: Dict = {}
        self._tw_results: Dict = {}
        self._check_dry_weights: Dict[int, float] = {}  # row_idx → weight
        self._dry_weights: Dict[int, float] = {}

        # ---- 定时器 ----
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_interval_ms = 200

    # ================================================================
    # 公共接口: start / stop
    # ================================================================

    def start(self):
        """启动测试流程 — 原有界面「开始测试」按钮调用"""
        if self._running:
            self.test_error.emit("测试已在运行中")
            return
        self._running = True
        self._stopping = False
        self._stage = Stage.IDLE
        self._aw_results = {}
        self._tw_results = {}
        self._check_dry_weights = {}
        self._dry_weights = {}
        self._current_mode = ""

        from logging_util import logger
        logger.info("[PROCESS] ========== 开始测试 ==========")

        # 短延时让 UI 刷新，然后进入 INIT
        QTimer.singleShot(100, self._transition_init)

    def stop(self):
        """停止测试 — 原有界面「停止测试」按钮调用
        任意状态均可安全终止，复位硬件，记录中断状态
        """
        if not self._running:
            return
        self._stopping = True
        from logging_util import logger
        logger.info("[PROCESS] 收到停止指令, 当前阶段=%s" % self._stage)

        # 立即停止所有子模块
        self._stop_all_submodules()

        # 复位硬件
        self._safe_hardware_off()

        # 更新数据库状态
        self._update_session_status("cancelled")
        self._log_event("stop", "manual_stop", {"stage": self._stage})

        self._running = False
        self._tick_timer.stop()
        self._stage = Stage.IDLE
        self.test_stopped.emit()

    # ================================================================
    # 状态转换引擎
    # ================================================================

    def _transition_init(self):
        """→ INIT: 加载参数、校验串口、创建实验记录"""
        if not self._running or self._stopping:
            return
        self._set_stage(Stage.INIT)

        try:
            # 1. 加载试验参数
            from db import load_params, load_latest_samples, ensure_experiment
            self._params = load_params()
            if not self._params:
                raise RuntimeError("无法读取试验参数配置")

            # 2. 校验串口连接
            if not self._dev.is_connected:
                raise RuntimeError("串口未连接，请先连接设备")

            # 3. 加载样品列表
            raw_samples = load_latest_samples()
            self._samples = [s for s in raw_samples
                             if s.get("name", "").strip() and s.get("sample_weight") is not None]
            if not self._samples:
                raise RuntimeError("无有效样品数据，请先完成称样")

            # 4. 创建实验记录与会话
            self._experiment_id = ensure_experiment()
            self._session_id = self._create_session()
            self._update_experiment_status("testing")

            # 5. 记录事件
            self._log_event("init", "stage_enter",
                            {"samples_count": len(self._samples)})

            from logging_util import logger
            logger.info("[PROCESS] INIT 完成: exp_id=%d session_id=%d samples=%d" %
                         (self._experiment_id, self._session_id, len(self._samples)))

            # 判断是否进入复检
            retest = bool(int(self._params.get("retest", 0)))
            if retest:
                self._transition_recheck()
            else:
                self._transition_mode_branch()

        except Exception as e:
            self._handle_error("初始化失败: " + str(e))

    def _transition_recheck(self):
        """→ RECHECK_WEIGH: 复检称重"""
        if not self._check_running():
            return
        self._set_stage(Stage.RECHECK_WEIGH)
        self._log_event("recheck", "stage_enter")

        self._create_weigh_module()
        self._weigh_module.weigh_finished.connect(self._on_recheck_done)
        self._weigh_module.weigh_error.connect(self._on_sub_error)

        # 构造样品位号列表
        positions = [s["row_idx"] + 1 for s in self._samples]

        # 计算校正坩埚差值
        aw_corr = float(self._params.get("aw_corr", 0.0))
        tw_corr = float(self._params.get("tw_corr", 0.0))
        correct_diff = aw_corr if aw_corr > 0 else tw_corr

        self._weigh_module.start_weigh(
            scene="复检称重",
            positions=positions,
            correct_diff=correct_diff,
        )
        self._emit_process_update({"stage_desc": "复检称重中..."})

    def _transition_mode_branch(self):
        """模式优先级调度: 先分析水 → 后全水"""
        if not self._check_running():
            return

        has_aw = any(s.get("mode", "") == "分析水" for s in self._samples)
        has_tw = any(s.get("mode", "") == "全水" for s in self._samples)

        if has_aw and not self._aw_results:
            self._start_mode_flow("分析水")
        elif has_tw and not self._tw_results:
            self._start_mode_flow("全水")
        else:
            # 无任何有效模式
            self._transition_finishing()

    # ================================================================
    # 单模式通用测试流程（分析水/全水 100% 复用）
    # ================================================================

    def _start_mode_flow(self, mode: str):
        """启动单模式测试流程"""
        self._current_mode = mode
        self._load_mode_params(mode)

        from logging_util import logger
        logger.info("[PROCESS] ===== %s 测试开始 =====" % mode)
        self._log_event("%s_start" % self._mode_prefix, "mode_start",
                        self._mode_params)

        # 步骤2: 调用控温恒温模块（标准恒温时长）
        stage_heat = Stage.AW_HEAT if mode == "分析水" else Stage.TW_HEAT
        self._set_stage(stage_heat)
        self._log_event("%s_heat" % self._mode_prefix, "stage_enter")

        self._create_temp_module()
        self._temp_module.temp_finished.connect(self._on_mode_heat_done)
        self._temp_module.temp_error.connect(self._on_sub_error)
        self._temp_module.temp_progress.connect(self.sub_temp_progress)

        self._temp_module.start_heating(
            target_temp=self._mode_params["target_temp"],
            constant_duration=self._mode_params["standard_time"],
            blower_enable=self._mode_params["blower_enable"],
            nitrogen_enable=self._mode_params["nitrogen_enable"],
        )
        self._emit_process_update({
            "stage_desc": "%s 升温中..." % mode,
            "target_temp": self._mode_params["target_temp"],
        })

    def _on_mode_heat_done(self):
        """恒温完成 → 步骤3: 批量称重"""
        if not self._check_running():
            return
        self._cleanup_temp_module()

        stage_weigh = Stage.AW_WEIGH if self._current_mode == "分析水" else Stage.TW_WEIGH
        self._set_stage(stage_weigh)
        self._log_event("%s_weigh" % self._mode_prefix, "stage_enter")

        self._create_weigh_module()
        self._weigh_module.weigh_finished.connect(self._on_mode_weigh_done)
        self._weigh_module.weigh_error.connect(self._on_sub_error)
        self._weigh_module.weigh_progress.connect(self.sub_weigh_progress)

        mode_samples = self._get_mode_samples()
        positions = [s["row_idx"] + 1 for s in mode_samples]
        correct_diff = float(self._mode_params.get("correct_diff", 0.0))

        self._weigh_module.start_weigh(
            scene="%s首轮称重" % self._current_mode,
            positions=positions,
            correct_diff=correct_diff,
        )
        self._emit_process_update({
            "stage_desc": "%s 称重中..." % self._current_mode,
        })

    def _on_mode_weigh_done(self, result: BatchWeighResult):
        """称重完成 → 步骤4: 写入检查性干燥重量 → 恒重判断
        
        检查性干燥重量 = 校正后称重值 - 坩埚重
        (因称重模块返回含坩埚的总重，需减坩埚重得到样品的净干燥重)
        """
        if not self._check_running():
            return
        self._cleanup_weigh_module()

        mode_samples = self._get_mode_samples()
        # 建立 row_idx → tare_weight 映射
        tare_map = {s["row_idx"]: (s.get("tare_weight") or 0.0) for s in mode_samples}

        for record in result.records:
            row_idx = record.position - 1  # position 是 1-based
            tare_w = tare_map.get(row_idx, 0.0)
            # 样品净干燥重 = 校正后称重值 - 坩埚重
            sample_dry = round(max(0.0, record.corrected_weight - tare_w), 4)
            self._check_dry_weights[row_idx] = sample_dry
            self._save_check_dry_weight(row_idx, record, sample_dry)

        self._log_event("%s_weigh_done" % self._mode_prefix, "stage_exit",
                        {"check_dry_weights": self._check_dry_weights})

        # 步骤5: 恒重检查开关
        const_check = bool(int(self._mode_params.get("const_check", 1)))
        if not const_check:
            # 不恒重: 直接将检查性干燥重量作为干燥重量，进入计算
            for row_idx, w in self._check_dry_weights.items():
                self._dry_weights[row_idx] = w
            self._transition_mode_calc()
        else:
            # 步骤5: 调用恒重循环模块
            self._transition_const_cycle()

    def _transition_const_cycle(self):
        """→ CONST_CYCLE: 恒重循环"""
        if not self._check_running():
            return

        stage_const = Stage.AW_CONST if self._current_mode == "分析水" else Stage.TW_CONST
        self._set_stage(stage_const)
        self._log_event("%s_const" % self._mode_prefix, "stage_enter")

        self._create_cycle_module()
        self._cycle_module.cycle_finished.connect(self._on_const_cycle_done)
        self._cycle_module.cycle_error.connect(self._on_sub_error)
        self._cycle_module.cycle_progress.connect(self.sub_cycle_progress)
        self._cycle_module.temp_progress.connect(self.sub_temp_progress)
        self._cycle_module.weigh_progress.connect(self.sub_weigh_progress)

        mode_samples = self._get_mode_samples()
        positions = [s["row_idx"] + 1 for s in mode_samples]

        # 取第一个样品的信息: 恒重模块对比的是含坩埚总重
        first_sample = mode_samples[0] if mode_samples else {}
        first_tare = first_sample.get("tare_weight", 0.0) or 0.0
        first_check_dry = list(self._check_dry_weights.values())[0] if self._check_dry_weights else 0.0
        # init_check 使用总重（含坩埚），保证模块内部 diff 对比一致
        init_check_total = first_check_dry + first_tare if first_check_dry > 0 else 0.0

        temp_cfg = TempControlConfig(
            target_temp=self._mode_params["target_temp"],
            constant_duration=self._mode_params["interval_duration"],
            blower_enable=self._mode_params["blower_enable"],
            nitrogen_enable=self._mode_params["nitrogen_enable"],
        )

        self._cycle_module.start_cycle(
            temp_config=temp_cfg,
            interval_duration=self._mode_params["interval_duration"],
            constant_precision=self._mode_params["precision"],
            max_cycle_times=self._mode_params["max_cycles"],
            correct_diff=float(self._mode_params.get("correct_diff", 0.0)),
            init_check_weight=init_check_total,
            positions=positions,
            weigh_scene="%s恒重" % self._current_mode,
        )
        self._emit_process_update({
            "stage_desc": "%s 恒重循环中..." % self._current_mode,
        })

    def _on_const_cycle_done(self, result: ConstantWeightResult):
        """恒重完成 → 步骤6: 写入干燥重量（减坩埚重得到样品净重）"""
        if not self._check_running():
            return
        self._cleanup_cycle_module()

        mode_samples = self._get_mode_samples()
        # 取第一个样品的坩埚重用于从总重恢复净重
        first_tare = (mode_samples[0].get("tare_weight") or 0.0) if mode_samples else 0.0
        # 干燥后样品净重 = 恒重结果总重 - 坩埚重
        dry_sample = round(max(0.0, result.final_dry_weight - first_tare), 4)

        # 将干燥重量写入所有模式样品
        for s in mode_samples:
            row_idx = s["row_idx"]
            self._dry_weights[row_idx] = dry_sample
            self._save_dry_weight(row_idx, dry_sample)

        from logging_util import logger
        logger.info("[PROCESS] %s 恒重完成: cycles=%d final_dry=%.4f" %
                     (self._current_mode, result.total_cycles,
                      result.final_dry_weight))

        self._log_event("%s_const_done" % self._mode_prefix, "stage_exit",
                        {"cycles": result.total_cycles,
                         "final_dry": result.final_dry_weight})

        self._transition_mode_calc()

    # ================================================================
    # 结果计算（国标公式）
    # ================================================================

    def _transition_mode_calc(self):
        """→ CALC: 按国标公式计算当前模式水分
        
        公式: 水分% = (样重 - 干燥后样重) / 样重 * 100
        干燥后样重 = 校正后称重值 - 坩埚重 (因称重值含坩埚)
        """
        if not self._check_running():
            return

        stage_calc = Stage.AW_CALC if self._current_mode == "分析水" else Stage.TW_CALC
        self._set_stage(stage_calc)
        self._log_event("%s_calc" % self._mode_prefix, "stage_enter")

        mode_samples = self._get_mode_samples()
        moistures = []

        for s in mode_samples:
            row_idx = s["row_idx"]
            sample_weight = s.get("sample_weight", 0.0) or 0.0
            # dry_weights 已存储样品净重（上游已减坩埚重），直接使用
            dry_sample = self._dry_weights.get(row_idx, 0.0)

            if sample_weight > 0:
                moisture = round((sample_weight - dry_sample) / sample_weight * 100, 4)
            else:
                moisture = 0.0
            moistures.append(moisture)

            # 保存到 DB (dry_weight 存干燥后样重)
            self._save_sample_moisture(row_idx, moisture, dry_sample)

        # 平均水分 & 精密度
        if moistures:
            avg_moisture = round(sum(moistures) / len(moistures), 4)
            precision_val = round(max(moistures) - min(moistures), 4) if len(moistures) >= 2 else 0.0
        else:
            avg_moisture = 0.0
            precision_val = 0.0

        decimals = 2 if self._current_mode == "分析水" else 1
        corr = float(self._mode_params.get("corr_value", 0.0))

        results = {
            "mode": self._current_mode,
            "moistures": moistures,
            "avg_moisture": self._bankers_round(avg_moisture, decimals),
            "precision": self._bankers_round(precision_val, decimals),
            "corr_value": corr,
            "sample_count": len(mode_samples),
        }

        if self._current_mode == "分析水":
            self._aw_results = results
        else:
            self._tw_results = results

        from logging_util import logger
        logger.info("[PROCESS] %s 计算完成: avg=%.4f prec=%.4f" %
                     (self._current_mode, results["avg_moisture"],
                      results["precision"]))

        self._log_event("%s_calc_done" % self._mode_prefix, "stage_exit", results)

        # 继续下一个模式或收尾
        self._transition_mode_branch()

    # ================================================================
    # 收尾
    # ================================================================

    def _transition_finishing(self):
        """→ FINISHING: 汇总结果、复位硬件、保存数据库"""
        if not self._check_running():
            return
        self._set_stage(Stage.FINISHING)
        self._log_event("finishing", "stage_enter")

        # 1. 复位所有硬件
        self._safe_hardware_off()

        # 2. 保存最终实验结果
        try:
            self._save_final_results()
        except Exception as e:
            from logging_util import logger
            logger.error("[PROCESS] 保存最终结果失败: %s" % str(e))
            import traceback
            traceback.print_exc()

        # 3. 更新状态
        self._update_session_status("done")
        self._update_experiment_status("done")

        # 4. 完成
        self._stage = Stage.DONE
        self._running = False
        self._tick_timer.stop()

        from logging_util import logger
        logger.info("[PROCESS] ========== 测试完成 ==========")

        self._log_event("done", "test_complete", {
            "aw": self._aw_results,
            "tw": self._tw_results,
        })

        self.test_finished.emit({
            "experiment_id": self._experiment_id,
            "session_id": self._session_id,
            "aw_results": self._aw_results,
            "tw_results": self._tw_results,
            "finished_at": _now_str(),
        })

    # ================================================================
    # 参数加载
    # ================================================================

    def _load_mode_params(self, mode: str):
        """从 params 加载指定模式的参数"""
        import os as _os
        _speed = _os.environ.get('WATER_SPEED_MODE', '0') == '1'
        p = self._params
        if mode == "分析水":
            self._mode_params = {
                "target_temp": int(float(p.get("aw_temp", 105))),
                "standard_time": int(p.get("aw_time", 60)) * (1 if _speed else 60),
                "blower_enable": bool(int(p.get("aw_fan", 0))),
                "nitrogen_enable": not bool(int(p.get("aw_fan", 0))),
                "const_check": bool(int(p.get("aw_const_check", 1))),
                "precision": float(p.get("aw_prec", 0.001)),
                "interval_duration": int(p.get("aw_interval", 5)) * (1 if _speed else 60),
                "max_cycles": 3,
                "correct_diff": float(p.get("aw_corr", 0.0)),
                "corr_value": float(p.get("aw_corr", 0.0)),
            }
        else:
            self._mode_params = {
                "target_temp": int(float(p.get("tw_temp", 105))),
                "standard_time": int(p.get("tw_time", 60)) * (1 if _speed else 60),
                "blower_enable": bool(int(p.get("tw_fan", 1))),
                "nitrogen_enable": not bool(int(p.get("tw_fan", 1))),
                "const_check": bool(int(p.get("tw_const_check", 1))),
                "precision": float(p.get("tw_prec", 0.003)),
                "interval_duration": int(p.get("tw_interval", 5)) * (1 if _speed else 60),
                "max_cycles": 3,
                "correct_diff": float(p.get("tw_corr", 0.0)),
                "corr_value": float(p.get("tw_corr", 0.0)),
            }

    @property
    def _mode_prefix(self) -> str:
        return "aw" if self._current_mode == "分析水" else "tw"

    def _get_mode_samples(self) -> List[Dict]:
        return [s for s in self._samples if s.get("mode", "") == self._current_mode]

    # ================================================================
    # 子模块生命周期
    # ================================================================

    def _create_weigh_module(self):
        self._cleanup_weigh_module()
        self._weigh_module = BatchWeighModule(self._dev, self)

    def _cleanup_weigh_module(self):
        if self._weigh_module:
            try:
                self._weigh_module.weigh_finished.disconnect()
                self._weigh_module.weigh_error.disconnect()
                self._weigh_module.weigh_progress.disconnect()
            except Exception:
                pass
            self._weigh_module.stop()
            self._weigh_module.deleteLater()
            self._weigh_module = None

    def _create_temp_module(self):
        self._cleanup_temp_module()
        self._temp_module = TempControlModule(self._dev, self)

    def _cleanup_temp_module(self):
        if self._temp_module:
            try:
                self._temp_module.temp_finished.disconnect()
                self._temp_module.temp_error.disconnect()
                self._temp_module.temp_progress.disconnect()
            except Exception:
                pass
            self._temp_module.stop()
            self._temp_module.deleteLater()
            self._temp_module = None

    def _create_cycle_module(self):
        self._cleanup_cycle_module()
        self._cycle_module = ConstantWeightCycleModule(self._dev, self)

    def _cleanup_cycle_module(self):
        if self._cycle_module:
            try:
                self._cycle_module.cycle_finished.disconnect()
                self._cycle_module.cycle_error.disconnect()
                self._cycle_module.cycle_progress.disconnect()
                self._cycle_module.temp_progress.disconnect()
                self._cycle_module.weigh_progress.disconnect()
            except Exception:
                pass
            self._cycle_module.stop()
            self._cycle_module.deleteLater()
            self._cycle_module = None

    def _stop_all_submodules(self):
        self._cleanup_weigh_module()
        self._cleanup_temp_module()
        self._cleanup_cycle_module()

    # ================================================================
    # 信号回调
    # ================================================================

    def _on_recheck_done(self, _result):
        """复检称重完成"""
        self._cleanup_weigh_module()
        self._log_event("recheck", "stage_exit")
        self._transition_mode_branch()

    def _on_sub_error(self, msg: str):
        """子模块异常"""
        self._handle_error("子模块异常: " + msg)

    # ================================================================
    # 硬件控制
    # ================================================================

    def _safe_hardware_off(self):
        """安全关闭所有硬件输出"""
        from protocol_layer import CMD
        for cmd, desc in [
            (CMD.HEAT_OFF, "关加热"),
            (CMD.FAN_OFF, "关鼓风"),
            (CMD.N2_OFF, "关氮气"),
        ]:
            try:
                self._dev.send_fixed_cmd(cmd, desc)
            except Exception:
                pass

    # ================================================================
    # 数据库操作
    # ================================================================

    def _create_session(self) -> int:
        """创建测试会话记录"""
        import sqlite3
        from db import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        # 确保表存在
        self._ensure_migration_tables(conn)
        session_no = datetime.now().strftime("%Y%m%d_%H%M%S")
        cur = conn.execute(
            "INSERT INTO test_sessions (experiment_id, session_no, status) VALUES (?,?,?)",
            (self._experiment_id, session_no, "running")
        )
        sid = cur.lastrowid
        conn.commit()
        conn.close()
        return sid

    def _ensure_migration_tables(self, conn):
        """确保迁移表存在"""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS test_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                session_no TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                current_stage TEXT DEFAULT 'idle',
                current_mode TEXT DEFAULT '',
                aw_completed INTEGER DEFAULT 0,
                tw_completed INTEGER DEFAULT 0,
                recheck_enabled INTEGER DEFAULT 0,
                recheck_done INTEGER DEFAULT 0,
                error_message TEXT,
                started_at TEXT DEFAULT (datetime('now','localtime')),
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS raw_weigh_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                experiment_id INTEGER NOT NULL,
                row_idx INTEGER NOT NULL,
                position INTEGER NOT NULL,
                sample_name TEXT DEFAULT '',
                mode TEXT DEFAULT '',
                weigh_scene TEXT DEFAULT '',
                cycle_index INTEGER DEFAULT 0,
                raw_weight REAL NOT NULL,
                corrected_weight REAL NOT NULL,
                correct_diff REAL DEFAULT 0.0,
                is_stable INTEGER DEFAULT 1,
                weigh_timestamp TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS process_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                experiment_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                mode TEXT DEFAULT '',
                event_type TEXT NOT NULL,
                event_data TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
        """)

    def _update_session_status(self, status: str):
        import sqlite3
        from db import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE test_sessions SET status=?, finished_at=? WHERE id=?",
                      (status, _now_str(), self._session_id))
        conn.commit()
        conn.close()

    def _update_experiment_status(self, status: str):
        from db import update_experiment_status
        update_experiment_status(self._experiment_id, status)

    def _log_event(self, stage: str, event_type: str, data=None):
        if not self._session_id:
            return
        import sqlite3
        from db import DB_PATH
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO process_events (session_id, experiment_id, stage, mode, event_type, event_data) "
                "VALUES (?,?,?,?,?,?)",
                (self._session_id, self._experiment_id, stage,
                 self._current_mode, event_type,
                 json.dumps(data or {}, ensure_ascii=False))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _save_check_dry_weight(self, row_idx: int, record: WeighRecord, sample_dry: float):
        """保存检查性干燥重量（样品净重，不含坩埚）到 experiment_samples"""
        from db import upsert_experiment_sample
        upsert_experiment_sample(self._experiment_id, row_idx,
                                 check_dry_weight=sample_dry)
        # 同时写入原始称重数据表
        self._save_raw_weigh(row_idx, record, "首轮检查")

    def _save_dry_weight(self, row_idx: int, dry_sample: float):
        """保存最终干燥重量（样品净重）到 experiment_samples"""
        from db import upsert_experiment_sample
        upsert_experiment_sample(self._experiment_id, row_idx,
                                 dry_weight=dry_sample)

    def _save_raw_weigh(self, row_idx: int, record: WeighRecord, scene: str):
        """写入原始称重数据表"""
        import sqlite3
        from db import DB_PATH
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO raw_weigh_data (session_id, experiment_id, row_idx, "
                "position, sample_name, mode, weigh_scene, raw_weight, "
                "corrected_weight, correct_diff) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self._session_id, self._experiment_id, row_idx,
                 record.position, record.sample_name, self._current_mode,
                 scene, record.raw_weight, record.corrected_weight,
                 record.raw_weight - record.corrected_weight if record.raw_weight else 0.0)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _save_sample_moisture(self, row_idx: int, moisture: float, dry_weight: float):
        """保存样品水分计算结果"""
        from db import upsert_experiment_sample
        upsert_experiment_sample(self._experiment_id, row_idx,
                                 moisture=moisture, dry_weight=dry_weight)

    def _save_final_results(self):
        """保存最终结果到 experiment_results"""
        import datetime as _dt
        from db import save_experiment_results_batch

        params = self._params
        batch_no = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        test_date = _dt.datetime.now().strftime("%Y-%m-%d")
        unit = params.get("unit", "")
        tech = params.get("hy_current", "")

        results = []
        for mode_results, mode_name in [
            (self._aw_results, "分析水"),
            (self._tw_results, "全水"),
        ]:
            if not mode_results:
                continue
            mode_samples = [s for s in self._samples if s.get("mode", "") == mode_name]
            moistures = mode_results.get("moistures", [])

            for i, s in enumerate(mode_samples):
                row_idx = s["row_idx"]
                moisture_val = moistures[i] if i < len(moistures) else 0.0
                dry_w = self._dry_weights.get(row_idx, 0.0)
                check_w = self._check_dry_weights.get(row_idx)

                results.append({
                    "实验ID": self._experiment_id,
                    "批次号": batch_no,
                    "试验日期": test_date,
                    "坩埚位号": str(row_idx + 1),
                    "样品名": s.get("name", ""),
                    "模式": mode_name,
                    "坩埚重": s.get("tare_weight"),
                    "样重": s.get("sample_weight"),
                    "检查性干燥重": self._bankers_round(check_w, 4) if check_w else None,
                    "干燥后重": self._bankers_round(dry_w, 4),
                    "水分": self._bankers_round(moisture_val, 2 if mode_name == "分析水" else 1),
                    "平均水分": mode_results.get("avg_moisture"),
                    "精密度": mode_results.get("precision"),
                    "分析水温度": params.get("aw_temp") if mode_name == "分析水" else None,
                    "分析水时间": params.get("aw_time") if mode_name == "分析水" else None,
                    "全水温度": params.get("tw_temp") if mode_name == "全水" else None,
                    "全水时间": params.get("tw_time") if mode_name == "全水" else None,
                    "测试单位": unit,
                    "化验员": tech,
                })

        if results:
            save_experiment_results_batch(results)

    @staticmethod
    def _bankers_round(value, decimals):
        """银行舍入法"""
        from decimal import Decimal, ROUND_HALF_EVEN
        d = Decimal(str(value))
        quantize = Decimal('0.' + '0' * decimals)
        return float(d.quantize(quantize, rounding=ROUND_HALF_EVEN))

    # ================================================================
    # 状态机与信号
    # ================================================================

    def _set_stage(self, stage: str):
        self._stage = stage
        stage_index = _ORDERED_STAGES.index(stage) if stage in _ORDERED_STAGES else 0
        total = len(_ORDERED_STAGES)
        self.stage_changed.emit(stage, stage_index, total, self._current_mode)

        # 更新会话状态
        if self._session_id:
            import sqlite3
            from db import DB_PATH
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE test_sessions SET current_stage=?, current_mode=? WHERE id=?",
                    (stage, self._current_mode, self._session_id)
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

    def _emit_process_update(self, extra: Dict = None):
        data = {
            "stage": self._stage,
            "mode": self._current_mode,
        }
        if extra:
            data.update(extra)
        self.process_update.emit(data)

    def _on_tick(self):
        """定时器 tick（预留，主要用于超时检测）"""
        if not self._running:
            self._tick_timer.stop()

    def _check_running(self) -> bool:
        if not self._running or self._stopping:
            if self._stopping:
                self.stop()
            return False
        return True

    def _handle_error(self, msg: str):
        """异常处理: 停止流程、复位硬件、推送错误信号"""
        self._running = False
        self._tick_timer.stop()
        self._stop_all_submodules()
        self._safe_hardware_off()

        self._stage = Stage.ERROR
        self._log_event("error", "error", {"message": msg})

        if self._session_id:
            self._update_session_status("error")
        if self._experiment_id:
            self._update_experiment_status("cancelled")

        from logging_util import logger
        logger.error("[PROCESS] 异常停止: " + msg)

        self.test_error.emit(msg)
