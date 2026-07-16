# -*- coding: utf-8 -*-
"""主流程控制器 — 对接原有界面示例

演示原有界面如何通过 start() / stop() 接口触发流程、
如何监听标准化信号对接现有测试进度显示组件。
"""


# ================================================================
# 一、初始化: 在 main_app.py 的初始化阶段创建控制器
# ================================================================
"""
from serial_comm import SerialManager
from core_data_entities import DeviceOperator
from test_process_controller import TestProcessController

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ... 原有初始化代码 ...

        # 串口管理器（假设已连接）
        # self.serial_mgr = SerialManager()

        # 创建设备操作封装
        self.device_op = DeviceOperator(self.serial_mgr)

        # 创建主流程控制器（唯一实例）
        self.test_controller = TestProcessController(self.device_op, self)

        # 连接标准化信号 → 现有进度组件
        self._wire_controller_signals()
"""


# ================================================================
# 二、信号对接: 连接标准化信号到现有进度组件
# ================================================================

def _wire_controller_signals(main_window, controller):
    """将控制器信号连接到原有进度组件

    对接组件:
      - 状态栏 (status_bar)
      - 温度显示 (temp_label)
      - 进度条 (progress_bar)
      - 阶段说明标签 (stage_label)
      - 恒重轮次标签 (cycle_label)
      - 原有 sig_status_msg / sig_step_progress 信号
    """
    from PySide2.QtWidgets import QMessageBox

    # ---- 信号1: stage_changed(str, int, int, str) ----
    # 阶段变更 → 更新阶段说明 + 进度条
    _STAGE_CN_MAP = {
        "init":     "初始化",
        "recheck":  "复检称重",
        "aw_heat":  "分析水-升温恒温",
        "aw_weigh": "分析水-称重",
        "aw_const": "分析水-恒重循环",
        "aw_calc":  "分析水-计算结果",
        "tw_heat":  "全水-升温恒温",
        "tw_weigh": "全水-称重",
        "tw_const": "全水-恒重循环",
        "tw_calc":  "全水-计算结果",
        "finishing":"收尾处理",
        "done":     "测试完成",
    }

    def on_stage_changed(stage_name, stage_index, total_stages, mode):
        cn_name = _STAGE_CN_MAP.get(stage_name, stage_name)
        main_window.stage_label.setText(cn_name)
        main_window.status_bar.showMessage(
            "当前阶段: %s  [%d/%d]" % (cn_name, stage_index + 1, total_stages)
        )
        main_window.progress_bar.setValue(
            int((stage_index + 1) / max(1, total_stages) * 100)
        )

    controller.stage_changed.connect(on_stage_changed)

    # ---- 信号2: process_update(dict) ----
    # 实时进度 → 对接原有 sig_status_msg 组件
    def on_process_update(data: dict):
        desc = data.get("stage_desc", "")
        if desc:
            main_window.sig_status_msg.emit(desc)

        temp = data.get("target_temp")
        if temp:
            main_window.temp_label.setText("目标: %d℃" % temp)

    controller.process_update.connect(on_process_update)

    # ---- 信号3: 透传底层子模块进度 ----
    controller.sub_temp_progress.connect(
        lambda d: main_window.temp_label.setText(
            "%.1f℃ / %d℃" % (d.get("current_temp", 0), d.get("target_temp", 0))
        )
    )
    controller.sub_weigh_progress.connect(
        lambda d: main_window.status_bar.showMessage(
            "称重: 位号%d 读数%.4fg" % (d.get("position", 0), d.get("weight", 0))
        )
    )
    controller.sub_cycle_progress.connect(
        lambda d: main_window.cycle_label.setText(
            "恒重第%d/%d轮 diff=%.4fg" % (
                d.get("cycle_index", 0) + 1,
                d.get("max_cycles", 0),
                d.get("weight_diff", 0),
            )
        )
    )

    # ---- 信号4: test_finished(object) ----
    def on_test_finished(result: dict):
        main_window.status_bar.showMessage("测试完成")
        main_window.progress_bar.setValue(100)

        aw = result.get("aw_results", {})
        tw = result.get("tw_results", {})

        msg = "测试完成!\n"
        if aw:
            msg += "分析水: 平均水分=%.2f%% 精密度=%.4f\n" % (
                aw.get("avg_moisture", 0), aw.get("precision", 0))
        if tw:
            msg += "全水:   平均水分=%.1f%% 精密度=%.4f" % (
                tw.get("avg_moisture", 0), tw.get("precision", 0))

        QMessageBox.information(main_window, "测试完成", msg)

        # 自动打开炉盖
        from protocol_layer import CMD
        controller._dev.send_fixed_cmd(CMD.OPEN_LID, "开炉盖")

    controller.test_finished.connect(on_test_finished)

    # ---- 信号5: test_error(str) ----
    def on_test_error(msg: str):
        main_window.status_bar.showMessage("异常: " + msg)
        QMessageBox.critical(main_window, "测试异常", msg)

    controller.test_error.connect(on_test_error)

    # ---- 信号6: test_stopped() ----
    def on_test_stopped():
        main_window.status_bar.showMessage("测试已停止")

    controller.test_stopped.connect(on_test_stopped)


# ================================================================
# 三、按钮对接: 开始 / 停止按钮调用
# ================================================================
"""
class MainWindow(QMainWindow):
    def __init__(self):
        # ... 初始化 controller + 信号连接 ...

        # 「开始测试」按钮
        self.btn_start.clicked.connect(self._on_start_clicked)

        # 「停止测试」按钮
        self.btn_stop.clicked.connect(self._on_stop_clicked)

    def _on_start_clicked(self):
        # 禁用开始按钮，启用停止按钮
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        # 启动测试流程
        self.test_controller.start()

    def _on_stop_clicked(self):
        # 确认停止
        reply = QMessageBox.question(
            self, "确认停止",
            "确定要停止当前测试吗？\n停止后需重新开始。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.test_controller.stop()
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
"""


# ================================================================
# 四、数据库迁移: 首次使用时执行
# ================================================================
"""
def migrate_database():
    '''执行数据库增量迁移，新增 test_sessions / raw_weigh_data / process_events 表'''
    import sqlite3
    from db import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    with open("db_migration_v2.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print("数据库迁移完成: 已创建 test_sessions, raw_weigh_data, process_events 表")
"""


# ================================================================
# 五、状态转换说明
# ================================================================
"""
状态机生命周期（阶段→下一阶段→终止）:

  IDLE ──start()──▶ INIT
                      │
                 ┌────┴────┐
            retest=1   retest=0
                 │          │
                 ▼          │
           RECHECK_WEIGH    │
                 │          │
                 └────┬─────┘
                      ▼
              ┌─ 有分析水样品? ─┐
              │ YES        NO  │
              ▼                │
           AW_HEAT             │
              │                │
              ▼                │
          AW_WEIGH             │
              │                │
         ┌────┴────┐           │
    const=1    const=0         │
         │          │          │
         ▼          │          │
    AW_CONST        │          │
         │          │          │
         └────┬─────┘          │
              ▼                │
          AW_CALC              │
              │                │
              └────────┬───────┘
                       ▼
               ┌─ 有全水样品? ─┐
               │ YES       NO  │
               ▼               │
            TW_HEAT            │
               │               │
               ▼               │
           TW_WEIGH            │
               │               │
          ┌────┴────┐          │
     const=1    const=0        │
          │          │         │
          ▼          │         │
     TW_CONST        │         │
          │          │         │
          └────┬─────┘         │
               ▼               │
           TW_CALC             │
               │               │
               └───────┬───────┘
                       ▼
                  FINISHING
                       │
                       ▼
                     DONE

任意状态 ──stop()──▶ STOPPING → (硬件复位) → IDLE
任意状态 ──异常───▶ ERROR → (硬件复位)

异常处理机制:
  - 所有 try/except 块捕获异常后调用 _handle_error()
  - _handle_error(): 停止所有子模块 → 关加热/鼓风/氮气 → 
    更新 DB 状态为 'cancelled' → 推送 test_error 信号
  - 子模块异常通过 _on_sub_error 回调统一处理
  - 手动停止通过 stop() → _stopping=True → 各状态检查 _check_running()
"""


# ================================================================
# 六、完整集成示例（最小可运行骨架）
# ================================================================
"""
import sys
from PySide2.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide2.QtWidgets import QPushButton, QLabel, QProgressBar, QStatusBar

from serial_comm import SerialManager
from core_data_entities import DeviceOperator
from test_process_controller import TestProcessController


class TestMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("水分测定仪 - 测试流程控制")

        # 串口 + 设备操作
        self.serial_mgr = SerialManager()
        self.device_op = DeviceOperator(self.serial_mgr)

        # 主流程控制器
        self.controller = TestProcessController(self.device_op, self)

        # UI 组件
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.stage_label = QLabel("待机")
        self.temp_label = QLabel("--℃")
        self.cycle_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.status_bar = QStatusBar()

        self.btn_start = QPushButton("开始测试")
        self.btn_stop = QPushButton("停止测试")
        self.btn_stop.setEnabled(False)

        layout.addWidget(self.stage_label)
        layout.addWidget(self.temp_label)
        layout.addWidget(self.cycle_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        self.setStatusBar(self.status_bar)

        # 信号连接
        _wire_controller_signals(self, self.controller)

        # 按钮
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

    def _start(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.controller.start()

    def _stop(self):
        self.controller.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TestMainWindow()
    win.resize(500, 300)
    win.show()
    sys.exit(app.exec_())
"""
