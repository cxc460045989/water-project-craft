# -*- coding: utf-8 -*-
"""Mock 版启动入口 — 微机全自动水分测定仪
无需硬件，一键启动完整 UI 进行功能测试。

用法:
    python main_app_mock.py

与真实版差异:
    - 串口后端替换为 MockInstrumentSimulator（智能仪器模拟器）
    - 温度/天平数据由模拟器自动生成
    - 所有按钮功能正常可用（开始测试、称量、追加样品等）
    - 数据库、报表打印完全一致
"""

import sys, os

# ===== 补丁：拦截 serial_comm 模块，注入 Mock 模拟器 =====
# 在 main_app 导入 serial_comm 之前完成注入，确保 MoistureAnalyzer
# 创建 SerialManager 时自动获得模拟后端

_import_orig = __builtins__.__import__ if isinstance(__builtins__, dict) else __builtins__.__import__
_mock_sim = None  # 全局引用，供外部获取模拟器状态


def _mock_import(name, *args, **kwargs):
    global _mock_sim
    mod = _import_orig(name, *args, **kwargs)

    if name == "serial_comm":
        # 在 SerialManager 导入后、main_app 使用前完成注入
        _patch_for_mock(mod)

    return mod


def _patch_for_mock(mod):
    """注入 Mock 逻辑：替换 SerialManager.open 使其自动走模拟通道"""
    _orig_open = mod.SerialManager.open
    _orig_init = mod.SerialManager.__init__

    def _mock_open(self, port=None, baudrate=None, config=None):
        # 强制走模拟通道
        self._mock = False
        if self._serial is None:
            from mock_instrument import SimSerialAdapter
            self._serial = SimSerialAdapter(_mock_sim, serial_mgr=self)
        self._config.port = "MOCK"
        # 模拟器已启动，直接触发 connected
        if getattr(self, "_connected_emitted", False):
            return True
        self._connected_emitted = True
        self.connected.emit()
        # 启动上行帧轮询定时器: 每200ms读取模拟器上行帧并触发 data_received 信号
        from PySide2.QtCore import QTimer
        def _poll():
            try:
                raw = self._serial.read_all()
            except Exception:
                return
            if raw:
                self.update_uplink_time()
                self.data_received.emit(raw)
        self._mock_poll_timer = QTimer(self)
        self._mock_poll_timer.timeout.connect(_poll)
        self._mock_poll_timer.start(200)
        return True

    def _mock_init(self, parent=None, use_mock=False):
        # 调用原始 __init__ 但绕过 serial 创建
        _orig_init(self, parent, use_mock=False)
        self._serial = None  # 由 _mock_open 创建

    mod.SerialManager.__init__ = _mock_init
    mod.SerialManager.open = _mock_open

    print("[MOCK] serial_comm 模块已注入 Mock 补丁")


if isinstance(__builtins__, dict):
    __builtins__["__import__"] = _mock_import
else:
    __builtins__.__import__ = _mock_import


# ===== 启动模拟器 =====
from mock_instrument import MockInstrumentSimulator

_mock_sim = MockInstrumentSimulator()
_mock_sim.set_online(True)
_mock_sim.start()

print("=" * 60)
print("  微机全自动水分测定仪 — Mock 演示版")
print("  仪器模拟器已启动，无需连接硬件")
print("=" * 60)
print("  模拟器初始状态: 温度 25°C, 天平 0g, 联机")
print("  所有功能可正常使用，数据存入 data.db")
print("=" * 60)
print()

# ===== 模拟器控制台 =====
from PySide2.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSlider, QDoubleSpinBox,
)
from PySide2.QtCore import Qt, QTimer


class MockControlPanel(QWidget):
    """模拟器控制台 — 独立小窗口，实时控制仪器模拟器"""

    def __init__(self, sim):
        super().__init__()
        self._sim = sim
        self.setWindowTitle("仪器模拟器控制台")
        self.setFixedSize(360, 380)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self._build_ui()
        # 每秒刷新状态
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(500)

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 10, 12, 10)

        # ---- 状态显示 ----
        grp_state = QGroupBox("仪器状态")
        slo = QVBoxLayout(grp_state)
        slo.setSpacing(4)
        self._lbl_temp = QLabel()
        self._lbl_weight = QLabel()
        self._lbl_target = QLabel()
        self._lbl_heat = QLabel()
        self._lbl_online = QLabel()
        self._lbl_pos = QLabel()
        for lbl in [self._lbl_temp, self._lbl_weight, self._lbl_target,
                     self._lbl_heat, self._lbl_online, self._lbl_pos]:
            lbl.setStyleSheet("font-size:13px; font-family:Consolas,monospace; padding:2px 4px;")
            slo.addWidget(lbl)
        lo.addWidget(grp_state)

        # ---- 温度控制 ----
        grp_temp = QGroupBox("温度控制")
        tlo = QVBoxLayout(grp_temp)
        h = QHBoxLayout()
        self._slider_temp = QSlider(Qt.Horizontal)
        self._slider_temp.setRange(0, 200)
        self._slider_temp.setValue(25)
        self._slider_temp.valueChanged.connect(self._on_temp_slider)
        h.addWidget(QLabel("0"))
        h.addWidget(self._slider_temp)
        h.addWidget(QLabel("200"))
        tlo.addLayout(h)
        self._lbl_slider = QLabel("25 °C")
        self._lbl_slider.setAlignment(Qt.AlignCenter)
        self._lbl_slider.setStyleSheet("font-size:16px; font-weight:bold; color:#2B579A;")
        tlo.addWidget(self._lbl_slider)
        lo.addWidget(grp_temp)

        # ---- 天平控制 ----
        grp_w = QGroupBox("天平控制")
        wlo = QHBoxLayout(grp_w)
        self._spin_weight = QDoubleSpinBox()
        self._spin_weight.setRange(0, 200)
        self._spin_weight.setDecimals(4)
        self._spin_weight.setValue(0)
        self._spin_weight.setSuffix(" g")
        self._spin_weight.valueChanged.connect(lambda v: self._sim.set_weight(v))
        wlo.addWidget(QLabel("读数:"))
        wlo.addWidget(self._spin_weight)
        lo.addWidget(grp_w)

        # ---- 快捷操作 ----
        grp_btn = QGroupBox("快捷操作")
        blo = QVBoxLayout(grp_btn)
        blo.setSpacing(6)

        r1 = QHBoxLayout()
        btn_online = QPushButton("联机/脱机")
        btn_online.clicked.connect(self._toggle_online)
        r1.addWidget(btn_online)
        btn_btn = QPushButton("模拟按键按下")
        btn_btn.clicked.connect(lambda: self._sim.press_button())
        r1.addWidget(btn_btn)
        blo.addLayout(r1)

        r2 = QHBoxLayout()
        btn_25 = QPushButton("设25°C")
        btn_25.clicked.connect(lambda: self._set_temp(25))
        r2.addWidget(btn_25)
        btn_105 = QPushButton("设105°C")
        btn_105.clicked.connect(lambda: self._set_temp(105))
        r2.addWidget(btn_105)
        btn_150 = QPushButton("设150°C")
        btn_150.clicked.connect(lambda: self._set_temp(150))
        r2.addWidget(btn_150)
        blo.addLayout(r2)

        r3 = QHBoxLayout()
        btn_w0 = QPushButton("天平清零")
        btn_w0.clicked.connect(lambda: self._spin_weight.setValue(0))
        r3.addWidget(btn_w0)
        btn_w25 = QPushButton("设25g")
        btn_w25.clicked.connect(lambda: self._spin_weight.setValue(25.0))
        r3.addWidget(btn_w25)
        btn_w1 = QPushButton("设1g")
        btn_w1.clicked.connect(lambda: self._spin_weight.setValue(1.0))
        r3.addWidget(btn_w1)
        blo.addLayout(r3)

        lo.addWidget(grp_btn)

        self._refresh()

    def _set_temp(self, val):
        self._slider_temp.setValue(val)
        self._sim.set_temperature(val)

    def _on_temp_slider(self, val):
        self._lbl_slider.setText("%d °C" % val)
        self._sim.set_temperature(val)

    def _toggle_online(self):
        st = self._sim.state_summary
        self._sim.set_online(not st["online"])

    def _refresh(self):
        st = self._sim.state_summary
        self._lbl_temp.setText("炉温: %.1f °C" % st["temperature"])
        self._lbl_weight.setText("天平: %.4f g" % st["weight"])
        self._lbl_target.setText("目标: %d °C  %s" % (
            st["target_temp"], "加热中" if st["heating"] else "待机"))
        self._lbl_heat.setText("鼓风: %s  氮气: %s" % (
            "开" if st["fan"] else "关", "开" if st["n2"] else "关"))
        self._lbl_online.setText("联机: %s  样位: %d  称重模式: %s" % (
            "是" if st["online"] else "否", st["position"],
            "是" if st["weigh_mode"] else "否"))
        self._lbl_pos.setText("样盘: %s  测试中: %s" % (
            "上位" if st["plate_up"] else "下位",
            "是" if st["moisture_testing"] else "否"))


# ===== 启动 =====
from PySide2.QtWidgets import QApplication
from main_app import main as main_app_main
import main_app

# 先创建 QApplication（main_app.main 内部也会创建，这里先创建避免冲突）
app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

# 启动控制台
panel = MockControlPanel(_mock_sim)
panel.show()

# 启动主界面
w = main_app.MoistureAnalyzer()
w.show()

sys.exit(app.exec_())
