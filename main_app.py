# -*- coding: utf-8 -*-
"""微机全自动水分测定仪 - 现代专业重构版
框架: PySide2 (Qt5) - 兼容Windows 7 / 麒麟Linux x86/ARM
依赖: pip install pyside2 pyserial
"""

import sys, os, time
from PySide2.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, QLabel,
    QHeaderView, QAbstractItemView, QSizePolicy, QFrame, QStyle, QProgressBar,
    QMessageBox,
)
from PySide2.QtCore import Qt, QSize, QEvent, QTimer, QItemSelectionModel
from PySide2.QtGui import QFont
from db import load_params, save_params, load_techs
from button_styles import BUTTON_QSS, apply_button_types
from serial_comm import SerialManager
from logging_util import logger
from protocol_layer import FrameParser, UplinkBuffer, CommandBuilder, CMD, handshake

STYLESHEET = """
/* ===== 全局 ===== */
QMainWindow, QWidget {
    background-color: #F0F2F5;
    font-family: "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
    font-size: 14px;
    color: #1F2937;
}
/* ===== 顶部状态栏 ===== */
#topBar {
    background-color: #2B579A;
    min-height: 70px; max-height: 70px;
}
#topTitle {
    color: #FFFFFF; font-size: 28px; font-weight: bold; background: transparent;
    qproperty-alignment: AlignCenter;
}
#topLabel {
    color: #FFFFFF; font-size: 14px; background: transparent;
}
#topTempVal {
    color: #00FF00; font-size: 32px; font-weight: bold; background: #000000;
    border: 2px solid #FFD600;
    border-radius: 6px;
    padding: 2px 12px;
    font-family: "Courier New", "Consolas", monospace;
}
#topTempLabel {
    color: #FFD600; font-size: 18px; font-weight: bold; background: transparent;
}
#btnExit {
    background-color: #C62828;
    color: #FFFFFF; border: none; border-radius: 4px;
    padding: 4px 16px; font-size: 14px; min-height: 32px;
}
#btnExit:hover { background-color: #AD2222; }
#btnExit:pressed { background-color: #941C1C; }
/* ===== 工具栏 ===== */
#toolBar {
    background-color: #FFFFFF;
    min-height: 50px; max-height: 50px;
    border-bottom: 1px solid #E5E7EB;
}
#toolButton {
    background-color: #FFFFFF;
    color: #1F2937;
    border: 1px solid #E5E7EB;
    border-radius: 4px;
    padding: 4px 2px;
    text-align: center;
    font-size: 13px;
    min-height: 36px;
}
#toolButton:hover {
    background-color: #EBF0F8;
    color: #2B579A;
    border-color: #2B579A;
}
#toolButton:pressed {
    background-color: #DCE3EF;
}
/* ===== 表格 ===== */
QTableWidget {
    background-color: #FFFFFF;
    gridline-color: #D1D5DB;
    border: 1px solid #D1D5DB;
    border-radius: 4px;
    font-size: 13px;
}
QTableWidget::item {
    padding: 2px 6px;
}
QTableWidget::item:selected {
    background-color: #2B579A;
    color: #FFFFFF;
}
QHeaderView::section {
    background-color: #E5E7EB;
    color: #1F2937;
    font-weight: bold;
    border: 1px solid #D1D5DB;
    padding: 4px 2px;
    white-space: normal;
}
/* ===== 右侧面板 ===== */
#card {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
}
#groupTitle {
    font-size: 15px;
    font-weight: bold;
    color: #2B579A;
    padding: 0 2px;
    background: transparent;
}
#divider {
    color: #E5E7EB;
}
/* ===== 按钮变体 ===== */
StartButton, StopButton, BlueButton, SelectButton {
    border: 1px solid #9098A4;
    border-radius: 4px;
    padding: 8px 14px;
    font-size: 14px;
    font-weight: bold;
    min-height: 32px;
    text-align: center;
}
StartButton {
    background-color: #2E7D32;
    color: #FFFFFF;
}
StartButton:hover { background-color: #1B5E20; }
StopButton {
    background-color: #C62828;
    color: #FFFFFF;
}
StopButton:hover { background-color: #AD2222; }
BlueButton {
    background-color: #1565C0;
    color: #FFFFFF;
}
BlueButton:hover { background-color: #0D47A1; }
SelectButton {
    background-color: #4B5563;
    color: #FFFFFF;
}
SelectButton:hover { background-color: #374151; }
StartButton:pressed { background-color: #14521A; }
StopButton:pressed { background-color: #941C1C; }

StartButton:disabled {
    background-color: #A5C8A7;
    color: #E0E8E0;
    border: 1px solid #8BB88E;
}
StopButton:disabled {
    background-color: #C88A8A;
    color: #F0E0E0;
    border: 1px solid #B87A7A;
}
BlueButton:pressed { background-color: #0A3A7A; }
SelectButton:pressed { background-color: #2D3743; }

/* ===== 滚动条 ===== */
QScrollBar:vertical {
    background: #F0F2F5;
    width: 8px;
    margin: 0;
    border: none;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #B0B8C4;
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #9098A4;
}
QScrollBar::handle:vertical:pressed {
    background: #6B7280;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; width: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background: #F0F2F5;
    height: 8px;
    margin: 0;
    border: none;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #B0B8C4;
    min-width: 30px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #9098A4;
}
QScrollBar::handle:horizontal:pressed {
    background: #6B7280;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0; height: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* ===== 下拉框箭头 ===== */
QComboBox {
    background-color: #FFFFFF;
    color: #1F2937;
    border: 1px solid #B0B8C4;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 13px;
    min-height: 26px;
}
QComboBox:hover {
    border-color: #2B579A;
}
QComboBox:focus, QComboBox:on {
    border-color: #2B579A;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 4px;
    padding: 2px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 28px;
    padding: 2px 10px;
    color: #1F2937;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #EBF0F8;
    color: #2B579A;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #2B579A;
    color: #FFFFFF;
}"""

STYLESHEET += BUTTON_QSS

# QMessageBox 样式
STYLESHEET += """
/* ===== 现代对话框控件样式 ===== */
QDialog {
    background-color: #F0F2F5;
}
QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    margin-top: 16px;
    padding: 20px 16px 16px 16px;
    font-size: 14px;
    font-weight: bold;
    color: #1F2937;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 12px;
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 4px;
    left: 12px;
    color: #2B579A;
}
QLineEdit {
    background-color: #FFFFFF;
    color: #1F2937;
    border: 1px solid #D1D5DB;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    min-height: 26px;
    selection-background-color: #2B579A;
    selection-color: #FFFFFF;
}
QLineEdit:focus {
    border-color: #2B579A;
    border-width: 2px;
    padding: 5px 9px;
}
QLineEdit:disabled {
    background-color: #F3F4F6;
    color: #9CA3AF;
}
QCheckBox {
    font-size: 13px;
    font-weight: bold;
    color: #1F2937;
    spacing: 8px;
}
QRadioButton {
    font-size: 13px;
    font-weight: bold;
    color: #1F2937;
    spacing: 8px;
}
/* ===== QMessageBox ===== */
QMessageBox {
    background-color: #FFFFFF;
}
QMessageBox QLabel {
    font-size: 14px;
    color: #1F2937;
    padding: 16px 20px;
}
QMessageBox QPushButton {
    background-color: #2B579A;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 28px;
    font-size: 13px;
    min-height: 32px;
    font-weight: bold;
}
QMessageBox QPushButton:hover {
    background-color: #1E3F73;
}
QMessageBox QPushButton:pressed {
    background-color: #152D52;
}
"""

class ToolButton(QPushButton):
    def __init__(self, text, icon=None, parent=None):
        super().__init__(parent)
        self.setText(text); self.setObjectName("toolButton")
        if icon is not None:
            self.setIcon(icon); self.setIconSize(QSize(20, 20))

class StartButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("class", "StartButton")

class StopButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("class", "StopButton")

class BlueButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("class", "BlueButton")

class SelectButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("class", "SelectButton")

def _load_window_title():
    """从 exe 同级 title.txt 读取窗口标题，无文件则用默认值"""
    default = "鹤壁市淇天仪器仪表有限公司"
    try:
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        else:
            exe_dir = os.path.dirname(os.path.abspath(__file__))
        title_file = os.path.join(exe_dir, "title.txt")
        if os.path.exists(title_file):
            with open(title_file, 'r', encoding='utf-8-sig') as f:
                content = f.read().strip()
                if content:
                    return content
    except Exception:
        pass
    return default


class MoistureAnalyzer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_load_window_title())
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLESHEET)
        cw = QWidget(); self.setCentralWidget(cw)
        lo = QVBoxLayout(cw); lo.setContentsMargins(0,0,0,0); lo.setSpacing(0)
        self._build_topbar(lo)
        lo.addSpacing(4)
        self._build_toolbar(lo)
        lo.addSpacing(6)
        self._build_content(lo)
        # ---- 底部信息栏 ----
        self.progress_data = QLabel("")
        self.progress_data.setAlignment(Qt.AlignVCenter)
        self.progress_data.setStyleSheet("font-size: 22px; color: #1F2937; padding: 0 8px 4px 8px;")
        info_bar = QWidget()
        info_bar.setObjectName("bottomInfoBar")
        info_bar.setStyleSheet("#bottomInfoBar { margin-top: -10px; padding: 6px 0 14px 0; }")
        info_lo = QHBoxLayout(info_bar)
        info_lo.setContentsMargins(16,0,16,0)
        info_lo.setSpacing(8)
        info_lo.setAlignment(Qt.AlignVCenter)
        info_lo.addWidget(self.progress_data, 1)
        self.progress_widget = info_bar
        self.progress_widget.setVisible(True)
        lo.addWidget(self.progress_widget)
        lo.addSpacing(12)
        # ---- 串口管理器 ----
        self._uplink_buf = UplinkBuffer()
        self.serial_mgr = SerialManager(parent=self, use_mock=False)
        self.serial_mgr.connected.connect(self._on_serial_connected)
        self.serial_mgr.disconnected.connect(self._on_serial_disconnected)
        self.serial_mgr.data_received.connect(self._on_serial_data)
        self.serial_mgr.error_occurred.connect(self._on_serial_error)
        self._port_name = ""
        self._mock_sim = None  # MockInstrumentSimulator 实例 (仅 mock 模式)

        # ---- 统一适配器选择 (WATER_MODE 环境变量) ----
        self._init_serial_adapter()

        # ---- 测试流程控制器 ----
        from test_controller import TestController
        self.test_ctrl = TestController(self.serial_mgr, self)
        self._init_test_signals()
        # ---- 启动时自动打开串口 ----
        # mock/replay 模式已在 _init_serial_adapter 中完成连接，跳过 open()
        if self.serial_mgr._serial is not None and getattr(self.serial_mgr._serial, 'port', '') in ("MOCK", "REPLAY"):
            logger.info("[SERIAL] 适配器已注入 (port=%s), 跳过 open()" % self.serial_mgr._serial.port)
        else:
            from db import load_params
            _p = load_params()
            from serial_comm import DEFAULT_PORT
            _com = _p.get("com_port", DEFAULT_PORT) or DEFAULT_PORT
            if _com:
                logger.info("[SERIAL] 启动时自动打开串口: " + str(_com))
                self.serial_mgr.open(port=_com)
                # readyRead 信号驱动, 无需手动轮询
            else:
                logger.info("[SERIAL] 未配置串口号，启动后不自动打开")
    # ---- 串口回调 ----
    def _init_serial_adapter(self):
        """根据 WATER_MODE 环境变量初始化串口适配器

        WATER_MODE 取值:
            (未设置/空)  → 真实硬件模式 (QSerialPort)
            "mock"       → Mock 模拟器模式 (MockInstrumentSimulator)
            "replay"     → 回放模式 (HardwareReplayer + 录制文件)
            "record"     → 真实硬件 + 录制模式
        """
        import os as _os
        mode = _os.environ.get("WATER_MODE", "").strip().lower()
        if not mode:
            return  # 默认真实硬件

        if mode == "mock":
            self._init_mock_adapter()
        elif mode == "replay":
            self._init_replay_adapter()
        elif mode == "record":
            self._init_record_adapter()
        else:
            logger.info("[ADAPTER] 未知 WATER_MODE=%s, 使用真实硬件" % mode)

    def _init_mock_adapter(self):
        """Mock 模式: 注入 MockInstrumentSimulator"""
        _os = __import__("os")
        _os.environ.setdefault("WATER_SPEED_MODE", "1")
        from mock_instrument import MockInstrumentSimulator, SimSerialAdapter
        self._mock_sim = MockInstrumentSimulator()
        self._mock_sim.set_online(True)
        self._mock_sim.start()
        self.serial_mgr._serial = SimSerialAdapter(self._mock_sim, serial_mgr=self.serial_mgr)
        self.serial_mgr._serial.readyRead.connect(self.serial_mgr._on_ready_read)
        self.serial_mgr._config.port = "MOCK"
        self.serial_mgr._connected_emitted = True
        self.serial_mgr.connected.emit()
        logger.info("[ADAPTER] Mock 模拟器已注入, 端口=MOCK")

    def _init_replay_adapter(self):
        """回放模式: 用录制文件替代硬件"""
        _os = __import__("os")
        _os.environ.setdefault("WATER_SPEED_MODE", "1")
        from hardware_replayer import create_replay_adapter_from_env
        adapter, replayer = create_replay_adapter_from_env(serial_mgr=self.serial_mgr)
        if adapter is None:
            logger.info("[ADAPTER] 回放文件未指定(WATER_REPLAY), 降级为真实硬件")
            return
        self.serial_mgr._serial = adapter
        self.serial_mgr._serial.readyRead.connect(self.serial_mgr._on_ready_read)
        self.serial_mgr._config.port = "REPLAY"
        self.serial_mgr._connected_emitted = True
        self.serial_mgr.connected.emit()
        logger.info("[ADAPTER] 回放模式已启动")

    def _init_record_adapter(self):
        """录制模式: 真实硬件 + 流量录制"""
        from hardware_recorder import create_recorder_from_env
        recorder = create_recorder_from_env()
        if recorder:
            self.serial_mgr.set_recorder(recorder)
            logger.info("[ADAPTER] 流量录制已启用")

    def _on_serial_connected(self):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._port_name = self.serial_mgr.port_name or "?"
        logger.info("[SERIAL][" + self._port_name + "] " + ts + " 串口已连接")

    def _on_serial_disconnected(self):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        logger.info("[SERIAL][" + self._port_name + "] " + ts + " 串口已断开")

    def _on_serial_data(self, data):
        """串口回调: 接收上行帧并解析更新 UI"""
        self.serial_mgr.update_uplink_time()
        frames = self._uplink_buf.feed(data)
        for f in frames:
            self._frame_count = getattr(self, "_frame_count", 0) + 1
            corr = self._get_temp_corr_for_display()
            cal_temp = f["temperature"] + corr
            self.temp_val.setText("%.1f" % cal_temp)
            if f["btn_pressed"]:
                pass
            # 节流: 每秒最多打印一条上行帧日志
            _now = time.time()
            if _now - getattr(self, "_last_uplink_log_ts", 0) >= 1.0:
                self._last_uplink_log_ts = _now
                logger.info("[SERIAL][" + getattr(self, "_port_name", "?") + "] 上行帧: %s  temp=%.1f weight=%.4f online=%d btn=%d" % (
                    f["raw_str"], f["temperature"], f["weight"], f["online"], f["btn_pressed"]))


    def _get_temp_corr_for_display(self):
        """获取主界面温度校准值(缓存, 每30秒从DB刷新)"""
        _now = time.time()
        if _now - getattr(self, '_temp_corr_cache_ts', 0) > 30.0:
            try:
                from db import load_params
                params = load_params()
                self._cached_aw_temp_corr = float(params.get("aw_temp_corr", 0.0))
                self._temp_corr_cache_ts = _now
            except Exception:
                self._cached_aw_temp_corr = 0.0
        return getattr(self, '_cached_aw_temp_corr', 0.0)

    def _on_serial_error(self, msg):
        logger.info("[SERIAL][" + getattr(self, "_port_name", "?") + "] 收到: " + str(msg))


    def _init_test_signals(self):
        """连接 TestController 全部信号到 UI"""
        self.test_ctrl.sig_status_msg.connect(self._on_status_msg)
        self.test_ctrl.sig_error.connect(lambda m: self.progress_data.setText("<span style='color:#2B579A;font-weight:bold'>测试进度：</span>错误: " + m))
        self.test_ctrl.sig_temp_update.connect(self._on_test_temp_update)
        self.test_ctrl.sig_hold_countdown.connect(self._on_hold_countdown)
        self.test_ctrl.sig_hold_started.connect(self._on_hold_started)
        self.test_ctrl.sig_test_done.connect(self._on_test_done)
        self.test_ctrl.sig_const_check_result.connect(self._on_const_check_result)
        self.test_ctrl.sig_phase_changed.connect(lambda p: None)  # 阶段切换不单独显示
        self.test_ctrl.sig_weigh_result.connect(self._on_test_weigh_result)
        self.test_ctrl.sig_initial_weight.connect(self._on_initial_weight)

    def _on_status_msg(self, msg):
        self.progress_data.setText("<span style='color:#2B579A;font-weight:bold'>测试进度：</span>" + msg)

    def _on_test_temp_update(self, temp):
        """测试期间温度实时更新到界面"""
        self.temp_val.setText("%.1f" % temp)

    def _on_hold_countdown(self, remaining):
        mins = remaining // 60
        secs = remaining % 60
        self.progress_data.setText("<span style='color:#2B579A;font-weight:bold'>测试进度：</span>恒温倒计时 %02d:%02d" % (mins, secs))

    def _on_hold_started(self, total):
        """恒温保持启动: 显示总倒计时"""
        mins = total // 60
        secs = total % 60
        self.progress_data.setText("<span style='color:#2B579A;font-weight:bold'>测试进度：</span>恒温保持 %02d:%02d" % (mins, secs))

    def _on_test_done(self):
        from confirm_dialog import ConfirmDialog
        self.btn_start.setEnabled(True)
        self.btn_start.setText("开始测试")
        self.btn_stop.setEnabled(False)
        self.progress_widget.setVisible(False)
        # 延迟刷新表格, 确保 _finalize_experiment 的 DB 写入已提交
        QTimer.singleShot(500, self._refresh_table_after_test)
        # 检查是否自动清除数据
        auto_clear = bool(load_params().get("autoclear", 0))
        if auto_clear:
            self._do_clear_all_data()
            ConfirmDialog.info(self, "测试完成，数据已清除。", "测试完成")
        else:
            ConfirmDialog.info(self, "测试完成。", "测试完成")

    def _do_clear_all_data(self):
        """清除表格数据 + 数据库记录（保留模式列和校正坩埚名称）"""
        if self._table:
            self._table.blockSignals(True)
            try:
                for r in range(0, self._table.rowCount()):
                    for c in range(self._table.columnCount()):
                        if c == 1:  # 模式列保留
                            continue
                        if r == 0 and c == 0:  # 校正坩埚名称保留
                            continue
                        item = self._table.item(r, c)
                        if item:
                            item.setText("")
            finally:
                self._table.blockSignals(False)
            # 清理数据库
            from db import get_conn
            conn = get_conn()
            conn.execute("DELETE FROM experiment_samples")
            conn.execute("DELETE FROM samples")
            conn.commit()
            conn.close()

    def _refresh_table_after_test(self):
        """测试完成后刷新表格, 加载水分/平均值/精密度"""
        if self._table:
            self._restore_samples_from_db(self._table)
            logger.info("[TEST] 测试完成, 表格已刷新")

    def _on_const_check_result(self, row_idx, passed, dry_weight, check_dry):
        """恒重检查结果回调 — 仅更新进度提示文本

        col4/col5 表格更新由 _do_weighing 开头的前移逻辑统一处理。
        """
        diff = abs(dry_weight - check_dry)
        status = "✓ 通过" if passed else "✗ 不通过"
        self.progress_data.setText(
            "<span style='color:#2B579A;font-weight:bold'>测试进度：</span>恒重检查 样位%d: %s (本次=%.4f 上次=%.4f diff=%.4f)"
            % (row_idx + 1, status, dry_weight, check_dry, diff))

    def _on_test_weigh_result(self, row_idx, dry_weight, phase):
        """测试称重结果实时回填表格: 检查性→col4, 干燥→col5"""
        if not self._table or row_idx >= self._table.rowCount():
            return
        # 根据阶段判断写入列: 检查性干燥重量(col4) 或 干燥重量(col5)
        # 干燥阶段称重结果统一写入 col5（干燥重量）
        # col4（检查性干燥重量）由恒重检查前移时通过 DB 同步
        if "检查性" in phase or phase == "dry_aw" or phase == "dry_tw":
            col = 5
        else:
            col = 5
        item = self._table.item(row_idx, col)
        from PySide2.QtWidgets import QTableWidgetItem
        from PySide2.QtCore import Qt
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row_idx, col, item)
        item.setText("{:.4f}".format(dry_weight))
        logger.info("[TEST] 表格回填 row=%d col=%d weight=%.4f" % (row_idx, col, dry_weight))

    def _on_initial_weight(self, row_idx, col, value):
        """复检称重实时回填表格: col2=坩埚重, col3=样重, col4=检查性干燥重

        col4 写入时同步清空 col5(干燥重量) — 恒重前移场景:
        干燥重→检查性干燥重 后, 干燥重量列应为空, 等新一轮称重回填,
        避免两列同时显示相同数值的中间状态。
        """
        if not self._table or row_idx >= self._table.rowCount():
            return
        item = self._table.item(row_idx, col)
        from PySide2.QtWidgets import QTableWidgetItem
        from PySide2.QtCore import Qt
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row_idx, col, item)
        item.setText("{:.4f}".format(value))
        # 恒重前移: 写入检查性干燥重(col4)时同步清空干燥重量(col5)
        if col == 4:
            item5 = self._table.item(row_idx, 5)
            if item5 is not None:
                item5.setText("")
        logger.info("[TEST] 复检回填 row=%d col=%d value=%.4f" % (row_idx, col, value))

    def _on_append_tare_backfill(self, row, weight):
        """追加样品坩埚重回填 — 在主线程安全操作 UI"""
        if self._table is None:
            return
        from PySide2.QtWidgets import QTableWidgetItem
        from PySide2.QtCore import Qt
        item = self._table.item(row, 2)
        if item is None:
            item = QTableWidgetItem("%.4f" % weight)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 2, item)
        else:
            item.setText("%.4f" % weight)
        logger.info("[APPEND] 坩埚重回填 row=%d weight=%.4f" % (row, weight))

    def _on_append_finished(self, success, msg):
        """追加样品完成回调"""
        self.btn_append.setEnabled(True)
        if self._table:
            self._restore_samples_from_db(self._table)
        self._append_worker = None

    def _on_append_error(self, msg):
        """追加样品错误回调"""
        self.btn_append.setEnabled(True)
        self._append_worker = None



    # ---- 化验员联动 ----
    # ---- 化验员联动 ----

    def _batch_set_mode(self, mode):
        """批量设置所有样品的模式列，断开 cellChanged 避免逐行写库，最后单次批量写入 DB"""
        if not self._table:
            return
        tbl = self._table
        try:
            tbl.cellChanged.disconnect(self._on_cell_changed)
        except RuntimeError:
            pass
        for r in range(1, tbl.rowCount()):
            item = tbl.item(r, 1)
            if item:
                item.setText(mode)
                item.setTextAlignment(Qt.AlignCenter)
        tbl.cellChanged.connect(self._on_cell_changed)
        from db import batch_set_mode
        batch_set_mode(mode)
    def _load_hy_list(self):
        """从 SQLite 加载化验员列表更新 combo"""
        techs = load_techs()
        names = [t for t in techs if t]
        if not names:
            names = ["化验员1", "化验员2", "化验员3"]
        current = self.hy_combo.currentText()
        self.hy_combo.blockSignals(True)
        self.hy_combo.clear()
        self.hy_combo.addItems(names)
        # 恢复上次选中项
        p = load_params()
        saved = p.get("hy_current", "")
        idx = self.hy_combo.findText(saved if saved else current)
        if idx >= 0:
            self.hy_combo.setCurrentIndex(idx)
        else:
            self.hy_combo.setCurrentIndex(0)
        self.hy_combo.blockSignals(False)

    

    def _rebuild_table(self):
        """关闭试验参数后刷新表格行数"""
        sc = load_params().get("sample_count", 24) or 24
        self._table.setRowCount(int(sc))
        # 断开 cellChanged，防止 _fill_table 逐行写"分析水"覆盖 DB 中已保存的模式
        try:
            self._table.cellChanged.disconnect(self._on_cell_changed)
        except Exception:
            pass
        self._fill_table(self._table)
        self._restore_samples_from_db(self._table)
        self._table.cellChanged.connect(self._on_cell_changed)
        QTimer.singleShot(0, self._adjust_row_height)

    def _save_hy_current(self, text):
        """保存当前选中的化验员到 SQLite"""
        save_params(hy_current=text)

    def _build_topbar(self, pl):
        bar = QWidget(); bar.setObjectName("topBar")
        lo = QHBoxLayout(bar); lo.setContentsMargins(20,6,20,6)
        lo.addStretch()
        title = QLabel("微机全自动水分测定仪"); title.setObjectName("topTitle")
        lo.addWidget(title)
        lo.addStretch()
        pl.addWidget(bar)

    def _build_toolbar(self, pl):
        bar = QWidget(); bar.setObjectName("toolBar")
        lo = QHBoxLayout(bar); lo.setContentsMargins(20,8,20,8); lo.setSpacing(8)
        names = ["打印数据","硬件检测","试验参数","查询数据",
                  "手动存数","清除数据","重新计算"]
        style_map = {0:QStyle.SP_FileDialogContentsView,1:QStyle.SP_ComputerIcon,
                     2:QStyle.SP_FileDialogDetailedView,3:QStyle.SP_FileDialogListView,
                     4:QStyle.SP_DialogSaveButton,5:QStyle.SP_DialogCloseButton,
                     6:QStyle.SP_BrowserReload}
        for i,n in enumerate(names):
            btn = ToolButton(n, icon=self.style().standardIcon(style_map[i]))
            btn.clicked.connect(lambda checked=False, x=n: self._on_click(x))
            lo.addWidget(btn)
        lo.addStretch()
        pl.addWidget(bar)

    def _build_content(self, pl):
        w = QWidget()
        lo = QHBoxLayout(w); lo.setContentsMargins(16,16,16,16); lo.setSpacing(16)
        lc = QWidget(); lc.setObjectName("card")
        ll = QVBoxLayout(lc); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        self._build_table(ll)
        rc = QWidget(); rc.setObjectName("card")
        rl = QVBoxLayout(rc); rl.setContentsMargins(20,20,20,20); rl.setSpacing(0)
        self._build_panel(rl)
        lo.addWidget(lc, 75); lo.addWidget(rc, 25)
        pl.addWidget(w, 1)

    def _build_table(self, pl):
        hd = ["样品名称","模式","坩埚重(g)","样品重(g)",
               "检查性干燥重量(g)","干燥重量(g)","水分(%)","平均值(%)"]
        t = QTableWidget()
        sc = load_params().get("sample_count", 24) or 24
        t.setColumnCount(8); t.setHorizontalHeaderLabels(hd); t.setRowCount(int(sc))  # 总行数=样位数量，第0行校正坩埚
        t.setAlternatingRowColors(True)
        hf = QFont("Microsoft YaHei", 12, QFont.Bold)
        t.horizontalHeader().setFont(hf)
        t.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        t.horizontalHeader().setMinimumHeight(50)
        t.verticalHeader().setDefaultSectionSize(32)
        t.verticalHeader().setMinimumSectionSize(24)
        t.verticalHeader().setVisible(True)
        t.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        t.verticalHeader().setFixedWidth(50)  # 加宽防点击溢出到 col 0
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.CurrentChanged | QAbstractItemView.EditKeyPressed)
        t.setTabKeyNavigation(True)
        t.setWordWrap(True)
        t.setShowGrid(True)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setMinimumSectionSize(80)
        self._fill_table(t)
        self._restore_samples_from_db(t)
        # 第n行采样/温度查询都用F2键
        for r in range(t.rowCount()):
            for c in range(1, t.columnCount()):
                if t.item(r, c) is None:
                    i = QTableWidgetItem("")
                    i.setFlags(i.flags() & ~Qt.ItemIsEditable)
                    i.setTextAlignment(Qt.AlignCenter)
                    t.setItem(r, c, i)
                else:
                    # 确保 col 1（模式列）始终不可编辑（单击即切换模式）
                    if c == 1:
                        item = t.item(r, c)
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self._table = t; t.installEventFilter(self); t.cellDoubleClicked.connect(self._on_cell_double_clicked)
        t.cellChanged.connect(self._on_cell_changed)
        t.itemSelectionChanged.connect(self._on_selection_changed)
        self._vheader = t.verticalHeader()  # 缓存引用，PySide2 每次调用 verticalHeader() 返回新 Python 包装对象
        self._vheader.installEventFilter(self)
        pl.addWidget(t)
        QTimer.singleShot(100, self._adjust_row_height)

    def _fill_table(self, t):
        c = Qt.AlignCenter
        def s(r, col, txt):
            i = QTableWidgetItem(txt); i.setTextAlignment(c)
            if col != 0:
                i.setFlags(i.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, col, i)
        # 第0行：校正坩埚（1号样位）
        corr_name = "校正坩埚"
        corr_weight = ""
        try:
            from db import load_latest_samples
            latest = load_latest_samples()
            for row in latest:
                if row.get("row_idx") == 0:
                    db_name = row.get("name", "").strip()
                    if db_name:
                        corr_name = db_name
                    db_w = row.get("tare_weight")
                    if db_w is not None:
                        corr_weight = "{:.4f}".format(db_w)
                    break
        except Exception:
            pass
        s(0, 0, corr_name)
        if corr_weight:
            s(0, 2, corr_weight)
        for r in range(1, t.rowCount()):
            if t.item(r, 0) is None:
                empty = QTableWidgetItem("")
                empty.setTextAlignment(Qt.AlignCenter)
                t.setItem(r, 0, empty)
        # 默认模式=分析水
        for r in range(1, t.rowCount()):
            s(r, 1, "分析水")
        t.resizeRowsToContents()
    def _build_panel(self, pl):
        g1 = QLabel("运行控制"); g1.setObjectName("groupTitle")
        pl.addWidget(g1); pl.addSpacing(8)
        for n in ["开始测试","停止测试"]:
            btn = StartButton(n) if n == "开始测试" else StopButton(n)
            btn.clicked.connect(lambda checked=False, x=n: self._on_click(x))
            if n == "开始测试": self.btn_start = btn
            elif n == "停止测试":
                self.btn_stop = btn
                self.btn_stop.setEnabled(False)  # 初始无测试, 停止按钮不可用
            pl.addWidget(btn); pl.addSpacing(10)
        dv1 = QFrame(); dv1.setObjectName("divider"); dv1.setFrameShape(QFrame.HLine)
        pl.addSpacing(2); pl.addWidget(dv1); pl.addSpacing(14)
        g2 = QLabel("样品操作"); g2.setObjectName("groupTitle")
        pl.addWidget(g2); pl.addSpacing(8)
        for n in ["称量样重","追加样品"]:
            btn = BlueButton(n)
            btn.clicked.connect(lambda checked=False, x=n: self._on_click(x))
            pl.addWidget(btn); pl.addSpacing(10)
            if n == "追加样品": self.btn_append = btn
        dv2 = QFrame(); dv2.setObjectName("divider"); dv2.setFrameShape(QFrame.HLine)
        pl.addSpacing(2); pl.addWidget(dv2); pl.addSpacing(14)
        g3 = QLabel("快捷选择"); g3.setObjectName("groupTitle")
        pl.addWidget(g3); pl.addSpacing(8)
        for n in ["全水全选","分析水全选"]:
            btn = SelectButton(n)
            btn.clicked.connect(lambda checked=False, x=n: self._on_click(x))
            pl.addWidget(btn); pl.addSpacing(10)
        dv3 = QFrame(); dv3.setObjectName("divider"); dv3.setFrameShape(QFrame.HLine)
        pl.addSpacing(6); pl.addWidget(dv3); pl.addSpacing(10)
        # 底炉温度
        temp_row = QHBoxLayout()
        temp_row.setSpacing(6)
        tl = QLabel("炉膛温度："); tl.setStyleSheet("font-size: 14px; font-weight: bold; color: #2B579A; background: transparent;")
        tv = QLabel("000"); tv.setObjectName("topTempVal"); tv.setStyleSheet("color: #00FF00; font-size: 24px; font-weight: bold; background: #000000; border: 1px solid #FFD600; border-radius: 4px; padding: 4px 8px 5px 8px; font-family: Courier New, Consolas, monospace;")
        self.temp_val = tv
        tv.setAlignment(Qt.AlignCenter)
        temp_row.addWidget(tl); temp_row.addWidget(tv); lbl_unit = QLabel(" ℃ "); lbl_unit.setStyleSheet("background: transparent;"); temp_row.addWidget(lbl_unit); temp_row.addStretch()
        pl.addLayout(temp_row); pl.addSpacing(12)
        # 化验员
        hr = QHBoxLayout()
        hr.setSpacing(6)
        hl = QLabel("化验员："); hl.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2937; background: transparent;")
        self.hy_combo = QComboBox()
        self._load_hy_list()
        hr.addWidget(hl); hr.addWidget(self.hy_combo); hr.addStretch()
        self.hy_combo.currentTextChanged.connect(self._save_hy_current)
        pl.addLayout(hr); pl.addSpacing(16)
        # 退出程序
        exit_btn = QPushButton("退出程序")
        apply_button_types(exit_btn, "danger")
        exit_btn.clicked.connect(self._on_exit_clicked)
        pl.addWidget(exit_btn)
        pl.addStretch()



    # ---- 重新称量回退入口 ----
    def _on_reweigh_flow(self):
        """重新称量：直接关盖→称量不合格样品，跳过准备阶段和放样提示"""
        from weigh_dialog import WeighDialog
        from weigh_controller import WeighController
        from weight_check_dialog import WeightCheckDialog
        from db import load_params
        from PySide2.QtWidgets import QMessageBox
        from confirm_dialog import ConfirmDialog

        # 找出所有不合格样品
        params = load_params()
        tw_low = float(params.get("tw_low", 9.0))
        tw_high = float(params.get("tw_high", 12.0))
        aw_low = float(params.get("aw_low", 0.9))
        aw_high = float(params.get("aw_high", 1.1))

        failed_rows = []
        all_valid = []
        for r in range(1, self._table.rowCount()):
            item = self._table.item(r, 0)
            if not item or not item.text().strip():
                continue
            all_valid.append(r)
            weight_item = self._table.item(r, 3)
            weight = float(weight_item.text()) if weight_item and weight_item.text() else 0.0
            mode_item = self._table.item(r, 1)
            mode = mode_item.text().strip() if mode_item and mode_item.text() else "分析水"
            lo, hi = (tw_low, tw_high) if mode == "全水" else (aw_low, aw_high)
            if weight < lo or weight > hi:
                failed_rows.append(r)

        if not failed_rows:
            ConfirmDialog.info(self, "所有样品均已合格，无需重新称量。", "提示")
            return

        dlg = WeighDialog(self)
        ctrl = WeighController(self)
        ctrl.set_table(self._table)
        ctrl.set_serial_manager(self.serial_mgr)
        ctrl.set_reweigh_rows(failed_rows)

        def on_weigh_progress(info):
            dlg.show_weighing_sample(info["row"], info["name"], info["weight"])

        def on_weigh_done(phase):
            if phase == "sample":
                failed_samples = []
                for r in range(1, self._table.rowCount()):
                    name_item = self._table.item(r, 0)
                    if name_item and name_item.text().strip():
                        name = name_item.text().strip()
                        tare_item = self._table.item(r, 2)
                        tare = float(tare_item.text()) if tare_item and tare_item.text() else 0.0
                        weight_item = self._table.item(r, 3)
                        weight = float(weight_item.text()) if weight_item and weight_item.text() else 0.0
                        mode_item = self._table.item(r, 1)
                        mode = mode_item.text().strip() if mode_item and mode_item.text() else "分析水"
                        lo, hi = (tw_low, tw_high) if mode == "全水" else (aw_low, aw_high)
                        if weight < lo or weight > hi:
                            failed_samples.append({"row": r, "name": name, "weight": weight,
                                                  "tare": tare, "mode": mode})
                dlg.accept()
                if failed_samples:
                    check_dlg = WeightCheckDialog(self)
                    check_dlg.load_sample_data(failed_samples, params)
                    check_dlg.reweigh_clicked.connect(self._on_reweigh_flow)
                    check_dlg.exec_()

        ctrl.sig_weighing_progress.connect(on_weigh_progress)
        ctrl.sig_weighing_done.connect(on_weigh_done)
        ctrl.sig_status_msg.connect(dlg.show_status)
        ctrl.sig_error.connect(lambda msg: QMessageBox.warning(self, "称量错误", msg))

        # 直接启动：关盖→称量不合格样品
        ctrl.start_reweigh_direct(all_valid)
        dlg.exec_()
        ctrl.stop()
    # ---- table selection callback ----
    def _on_selection_changed(self):
        """选中行变化回调：打印当前选中行数据"""
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            return
        row = indexes[0].row()
        name_item = self._table.item(row, 0)
        mode_item = self._table.item(row, 1)
        name = name_item.text().strip() if name_item and name_item.text().strip() else "(空)"
        mode = mode_item.text().strip() if mode_item and mode_item.text().strip() else "-"
        sel_count = len(indexes)
        logger.info("[TABLE] 选中行: row=%d | 样品=%s | 模式=%s | 共选中%d行" % (row + 1, name, mode, sel_count))

    # ---- table real-time persistence ----
    def _on_cell_changed(self, row, col):
        import datetime
        _ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        try:
            item = self._table.item(row, col)
            if item is None: return
            val = item.text().strip()
            # 样品名称: 去掉所有空格（前后+中间）并回写表格
            if col == 0 and val:
                val = val.replace(" ", "").replace("\u3000", "")  # 半角+全角空格
                if item.text() != val:
                    item.setText(val)
            col_map = {0: "name", 1: "mode", 2: "tare_weight", 3: "sample_weight",
                       4: "check_dry_weight", 5: "dry_weight", 6: "moisture",
                       7: "avg_moisture"}
            if col not in col_map: return
            logger.debug("[DB-CELL] _on_cell_changed: row=" + str(row) + " col=" + str(col) + " key=" + col_map[col] + " val=" + val)
            # 同时写入 experiment_samples 和 samples（兼容）
            from db import upsert_experiment_sample, ensure_experiment
            eid = ensure_experiment()
            upsert_experiment_sample(eid, row, **{col_map[col]: val})
            logger.debug("[DB-CELL] upsert_experiment_sample OK: eid=" + str(eid))
            from db import save_sample
            save_sample(row + 1, **{col_map[col]: val})
            logger.debug("[DB-CELL] save_sample OK: row_id=" + str(row + 1))
        except Exception as e:
            logger.debug("[DB-CELL] ERROR: " + str(e))

    def save_all_samples_to_db(self):
        from db import save_all_samples
        data_list = []
        col_map = {0: "name", 1: "mode", 2: "tare_weight", 3: "sample_weight",
                   4: "check_dry_weight", 5: "dry_weight", 6: "moisture",
                   7: "avg_moisture"}
        for r in range(0, self._table.rowCount()):
            row_data = {}
            has_data = False
            for c in range(self._table.columnCount()):
                item = self._table.item(r, c)
                if item and item.text().strip():
                    row_data[col_map[c]] = item.text().strip()
                    has_data = True
            if has_data:
                data_list.append(row_data)
        if data_list:
            save_all_samples(data_list)

    def _restore_samples_from_db(self, t):
        import datetime
        _ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        try:
            from db import load_latest_samples
            rows = load_latest_samples()
            logger.debug("[RESTORE] load_latest_samples returned " + str(len(rows)) + " rows")
            for row in rows:
                rid = row.get("row_idx")
                logger.debug("[RESTORE] processing row_idx=" + str(rid) + " name=" + str(row.get("name")) + " tare=" + str(row.get("tare_weight")) + " sample=" + str(row.get("sample_weight")))
                if rid is None:
                    continue
                r = rid
                if r >= t.rowCount():
                    logger.debug("[RESTORE] SKIP: r=" + str(r) + " >= rowCount=" + str(t.rowCount()))
                    continue
                name = row.get("name", "") or ""
                if name:
                    item0 = t.item(r, 0)
                    if item0 is not None:
                        item0.setText(name)
                        logger.debug("[RESTORE] set row " + str(r) + " col0=" + name)
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i0 = QTableWidgetItem(name)
                        i0.setTextAlignment(Qt.AlignCenter)
                        t.setItem(r, 0, i0)
                        logger.debug("[RESTORE] created row " + str(r) + " col0=" + name)
                mode = row.get("mode", "") or ""
                if mode:
                    item1 = t.item(r, 1)
                    if item1 is not None:
                        item1.setText(mode)
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i1 = QTableWidgetItem(mode)
                        i1.setTextAlignment(Qt.AlignCenter)
                        t.setItem(r, 1, i1)
                tare = row.get("tare_weight")
                if tare is not None:
                    item2 = t.item(r, 2)
                    if item2 is not None:
                        item2.setText("{:.4f}".format(tare))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i2 = QTableWidgetItem("{:.4f}".format(tare))
                        i2.setTextAlignment(Qt.AlignCenter)
                        i2.setFlags(i2.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 2, i2)
                    logger.debug("[RESTORE] set row " + str(r) + " col2=" + str(tare))
                sw = row.get("sample_weight")
                if sw is not None:
                    item3 = t.item(r, 3)
                    if item3 is not None:
                        item3.setText("{:.4f}".format(sw))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i3 = QTableWidgetItem("{:.4f}".format(sw))
                        i3.setTextAlignment(Qt.AlignCenter)
                        i3.setFlags(i3.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 3, i3)
                    logger.debug("[RESTORE] set row " + str(r) + " col3=" + str(sw))
                cdw = row.get("check_dry_weight")
                if cdw is not None:
                    item4 = t.item(r, 4)
                    if item4 is not None:
                        item4.setText("{:.4f}".format(cdw))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i4 = QTableWidgetItem("{:.4f}".format(cdw))
                        i4.setTextAlignment(Qt.AlignCenter)
                        i4.setFlags(i4.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 4, i4)
                dw = row.get("dry_weight")
                if dw is not None:
                    item5 = t.item(r, 5)
                    if item5 is not None:
                        item5.setText("{:.4f}".format(dw))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i5 = QTableWidgetItem("{:.4f}".format(dw))
                        i5.setTextAlignment(Qt.AlignCenter)
                        i5.setFlags(i5.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 5, i5)
                mst = row.get("moisture")
                if mst is not None:
                    mode = row.get("mode", "") or ""
                    fmt = "{:.1f}" if mode == "全水" else "{:.2f}"
                    item6 = t.item(r, 6)
                    if item6 is not None:
                        item6.setText(fmt.format(mst))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i6 = QTableWidgetItem(fmt.format(mst))
                        i6.setTextAlignment(Qt.AlignCenter)
                        i6.setFlags(i6.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 6, i6)
                avg = row.get("avg_moisture")
                if avg is not None:
                    mode = row.get("mode", "") or ""
                    fmt = "{:.1f}" if mode == "全水" else "{:.2f}"
                    item7 = t.item(r, 7)
                    if item7 is not None:
                        item7.setText(fmt.format(avg))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i7 = QTableWidgetItem(fmt.format(avg))
                        i7.setTextAlignment(Qt.AlignCenter)
                        i7.setFlags(i7.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 7, i7)
        except Exception as e:
            logger.debug("[RESTORE] ERROR: " + str(e))
    
    def _on_manual_save(self):
        """手动存数: 扫描表格中完整实验数据行, 存入 experiment_results 表

        完整数据判断: 除"检查性干燥重量"(col4)外, 其余列均须存在。
        存入后可在"查询数据"中检索。
        """
        from PySide2.QtWidgets import QMessageBox
        from confirm_dialog import ConfirmDialog
        from db import (ensure_experiment, load_params, load_experiment,
                       save_experiment_results_batch)
        import datetime as _dt

        if self._table is None:
            QMessageBox.warning(self, "提示", "表格未初始化")
            return

        # 收集完整行数据
        complete_rows = []

        for r in range(1, self._table.rowCount()):  # 跳过第0行(校正坩埚)
            name_item = self._table.item(r, 0)
            mode_item = self._table.item(r, 1)
            tare_item = self._table.item(r, 2)
            sample_item = self._table.item(r, 3)
            # col4 = 检查性干燥重(可选)
            check_dry_item = self._table.item(r, 4)
            dry_item = self._table.item(r, 5)
            moisture_item = self._table.item(r, 6)
            avg_item = self._table.item(r, 7)

            # 提取文本值
            name = name_item.text().strip() if name_item and name_item.text() else ""
            mode = mode_item.text().strip() if mode_item and mode_item.text() else ""
            tare_text = tare_item.text().strip() if tare_item and tare_item.text() else ""
            sample_text = sample_item.text().strip() if sample_item and sample_item.text() else ""
            dry_text = dry_item.text().strip() if dry_item and dry_item.text() else ""
            moisture_text = moisture_item.text().strip() if moisture_item and moisture_item.text() else ""
            avg_text = avg_item.text().strip() if avg_item and avg_item.text() else ""

            # 1. 先判断这行有没有数据：样品名+坩埚重+样重至少有一项有值
            has_data = bool(name or tare_text or sample_text)
            if not has_data:
                continue  # 空行直接跳过

            # 2. 有数据的行，检查是否完整（除col4外，col0/1/2/3/5/6/7齐全）
            required = [name, mode, tare_text, sample_text, dry_text, moisture_text, avg_text]
            if all(v for v in required):
                try:
                    check_dry_text = check_dry_item.text().strip() if check_dry_item and check_dry_item.text() else None
                    complete_rows.append({
                        "row_idx": r,
                        "name": name,
                        "mode": mode,
                        "tare_weight": float(tare_text),
                        "sample_weight": float(sample_text),
                        "check_dry_weight": float(check_dry_text) if check_dry_text else None,
                        "dry_weight": float(dry_text),
                        "moisture": float(moisture_text),
                        "avg_moisture": float(avg_text) if avg_text else None,
                    })
                except (ValueError, TypeError) as e:
                    pass  # 数值异常的行跳过，不阻塞整体存数

        if not complete_rows:
            ConfirmDialog.info(self, "表格中没有可存储的完整数据。\n请检查有数据的行是否填写完整。", "提示")
            return

        # 获取实验上下文
        eid = ensure_experiment()
        params = load_params()
        exp_record, _ = load_experiment(eid)
        batch_no = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        test_date = _dt.datetime.now().strftime("%Y-%m-%d")
        unit = (exp_record or {}).get("unit", "") or params.get("unit", "")
        tech = params.get("hy_current", "") or (exp_record or {}).get("tech", "")

        # 构建结果列表
        results = []
        for row in complete_rows:
            mode = row["mode"]
            is_aw = (mode == "分析水")
            results.append({
                "实验ID": eid,
                "批次号": batch_no,
                "试验日期": test_date,
                "坩埚位号": str(row["row_idx"]),
                "样品名": row["name"],
                "模式": mode,
                "坩埚重": row["tare_weight"],
                "样重": row["sample_weight"],
                "检查性干燥重": row["check_dry_weight"],
                "干燥后重": row["dry_weight"],
                "原始检查性干燥重": row.get("check_dry_weight"),
                "原始干燥重": row["dry_weight"],
                "水分": row["moisture"],
                "平均水分": row["avg_moisture"],
                "精密度": None,
                "分析水温度": params.get("aw_temp") if is_aw else None,
                "分析水时间": params.get("aw_time") if is_aw else None,
                "全水温度": params.get("tw_temp") if not is_aw else None,
                "全水时间": params.get("tw_time") if not is_aw else None,
                "测试单位": unit,
                "化验员": tech,
            })

        try:
            save_experiment_results_batch(results)
        except Exception as e:
            logger.error("[MANUAL_SAVE] 存数失败: %s" % str(e))
            QMessageBox.warning(self, "存数失败", "写入数据库时出错:\n%s" % str(e))
            return

        # 同时更新 experiment_samples 的水分/平均值字段
        try:
            from db import upsert_experiment_sample
            for row in complete_rows:
                upsert_experiment_sample(eid, row["row_idx"],
                                          moisture=row["moisture"],
                                          avg_moisture=row["avg_moisture"])
        except Exception as e:
            logger.error("[MANUAL_SAVE] 同步 experiment_samples 失败: %s" % str(e))

        # 汇总提示
        detail_parts = []
        aw_count = sum(1 for r in complete_rows if r["mode"] == "分析水")
        tw_count = sum(1 for r in complete_rows if r["mode"] == "全水")
        if aw_count:
            detail_parts.append("分析水 %d 条" % aw_count)
        if tw_count:
            detail_parts.append("全水 %d 条" % tw_count)

        msg = "已成功存储 %d 条实验数据到数据库。\n(%s)\n\n可在「查询数据」中检索。" % (
            len(complete_rows), "、".join(detail_parts))

        ConfirmDialog.info(self, msg, "存数完成", extra_width=10, extra_height=50, extra_top=8)
        logger.info("[MANUAL_SAVE] 手动存数完成: experiment_id=%d, 存储%d条 (%s)"
                     % (eid, len(complete_rows), "、".join(detail_parts) if detail_parts else "无"))

    def _on_recalculate(self):
        """重新计算: 用原始干燥重量重新计算水分→平均值→反推显示干燥重

        数据源: experiment_samples 中的 orig_check_dry_weight / orig_dry_weight
        公式:   m1 = min(原始检查性干燥重, 原始干燥重)
               水分 = (样重 - m1) / 样重 * 100
               银行舍入 → 校正 → 反推显示干燥重
        """
        from PySide2.QtWidgets import QMessageBox
        from confirm_dialog import ConfirmDialog

        if not ConfirmDialog.confirm(self,
                "确定要重新计算吗？",
                title="重新计算", danger=False):
            return

        from db import ensure_experiment, load_params, load_experiment_samples
        from decimal import Decimal, ROUND_HALF_EVEN

        eid = ensure_experiment()
        params = load_params()

        # 加载当前实验的原始称重数据
        samples = load_experiment_samples(eid)

        if not samples:
            ConfirmDialog.info(self,
                "当前实验没有已存储的数据。\n请先完成实验或手动存数后再重新计算。", "提示")
            return

        # 银行舍入
        def bankers_round(value, decimals):
            d = Decimal(str(value))
            q = Decimal('0.' + '0' * decimals)
            return float(d.quantize(q, rounding=ROUND_HALF_EVEN))

        # 为每个模式组计算
        aw_count = 0
        tw_count = 0

        for mode in ("分析水", "全水"):
            mode_samples = [
                s for s in samples
                if s.get("mode") == mode
                and s.get("sample_weight") is not None
                and s.get("sample_weight", 0) != 0
            ]
            if not mode_samples:
                continue

            decimals = 2 if mode == "分析水" else 1
            corr = float(params.get("aw_corr", 0) if mode == "分析水" else params.get("tw_corr", 0))

            moistures = []
            recalc_data = []
            for s in mode_samples:
                sample_w = s.get("sample_weight")
                raw_check = s.get("orig_check_dry_weight")
                raw_dry = s.get("orig_dry_weight")

                if sample_w is None or sample_w == 0:
                    continue

                # 用原始值作为数据源重新计算
                m = Decimal(str(sample_w))
                cd = Decimal(str(raw_check)) if raw_check is not None else None
                dd = Decimal(str(raw_dry)) if raw_dry is not None else Decimal('0')
                m1 = cd if (cd is not None and cd < dd) else dd

                moisture_raw = float((m - m1) / m * Decimal('100'))
                moisture = bankers_round(moisture_raw, decimals)
                moisture_corrected = bankers_round(moisture + corr, decimals)

                # 反推显示干燥重, 保留原始检查性/干燥差值拆分
                display_dry = float(m * (Decimal('1') - Decimal(str(moisture_corrected)) / Decimal('100')))
                display_dry = bankers_round(display_dry, 4)

                orig_check = raw_check or 0
                orig_dry_val = raw_dry or 0
                diff = round(orig_check - orig_dry_val, 4)
                if orig_check <= orig_dry_val:
                    display_check = display_dry
                    display_dry_result = bankers_round(display_dry + abs(diff), 4)
                else:
                    display_dry_result = display_dry
                    display_check = bankers_round(display_dry + abs(diff), 4)

                moistures.append(moisture_corrected)
                recalc_data.append((s, moisture_corrected, display_check, display_dry_result))
                logger.info("[RECALC] row=%s mode=%s m=%.4f m1=%.4f raw_m=%.2f→校正%.*f%% chk=%.4f dry=%.4f diff=%.4f"
                             % (s.get("row_idx"), mode, sample_w, float(m1),
                                moisture_raw, decimals, moisture_corrected, display_check, display_dry_result, diff))

            if not moistures:
                continue

            avg_m = bankers_round(sum(moistures) / len(moistures), decimals)
            prec = bankers_round(max(moistures) - min(moistures), decimals) if len(moistures) >= 2 else 0.0

            logger.info("[RECALC] %s 完成: samples=%d avg=%.*f%% prec=%.*f%%"
                         % (mode, len(moistures), decimals, avg_m, decimals, prec))

            # 回写 experiment_samples（表格数据源），不写 experiment_results
            from db import upsert_experiment_sample
            for s, mst, chk, dry in recalc_data:
                row_idx = s["row_idx"]
                upsert_experiment_sample(eid, row_idx,
                                          moisture=mst,
                                          avg_moisture=avg_m,
                                          check_dry_weight=chk,
                                          dry_weight=dry)

            aw_count = aw_count + len(recalc_data) if mode == "分析水" else aw_count
            tw_count = tw_count + len(recalc_data) if mode == "全水" else tw_count

        if aw_count == 0 and tw_count == 0:
            ConfirmDialog.info(self, "没有可重新计算的数据。", "提示")
            return

        # 刷新主表格
        if self._table:
            self._restore_samples_from_db(self._table)

        parts = []
        if aw_count:
            parts.append("分析水 %d 条" % aw_count)
        if tw_count:
            parts.append("全水 %d 条" % tw_count)

        msg = "已重新计算 %d 条数据。\n(%s)\n\n如需更新实验数据库，请点击「手动存数」。" % (
            aw_count + tw_count, "、".join(parts))
        ConfirmDialog.info(self, msg, "重新计算完成")
        logger.info("[RECALC] 重新计算完成: experiment_id=%d, %d条"
                     % (eid, aw_count + tw_count))

    def _on_cell_double_clicked(self, row, col):
        tbl = self._table
        if tbl is None:
            return
        if col == 1 and row != 0:
            # 模式列：切换 分析水/全水（跳过校正坩埚）
            item = tbl.item(row, col)
            if item:
                txt = item.text().strip()
                if txt:
                    item.setText("全水" if txt == "分析水" else "分析水")
        elif col != 0:
            # 第2个从表布局
            it = tbl.item(row, col)
            if it:
                tbl.closePersistentEditor(it)
                tbl.removeCellWidget(row, col)
        # 弹出(选择)按钮布局

    def _adjust_row_height(self):
        """表格宽度变化时等比调整行高
        首次宽度>=400时记录基准比例(行高24/列宽), 后续按此比例缩放, 不低于24"""
        if self._table is None:
            return
        vp_w = self._table.viewport().width()
        if vp_w < 400:
            return
        col_w = vp_w / self._table.columnCount()
        if getattr(self, '_row_base_ratio', 0) <= 0:
            self._row_base_ratio = (32.0 / col_w) * 0.8
            self._row_base_size = 32.0
            self._font_base_size = 10.0
        rh = max(24, int(col_w * self._row_base_ratio))
        self._table.verticalHeader().setDefaultSectionSize(rh)
        fs = max(9, int(self._font_base_size * rh / self._row_base_size + 0.5))
        f = self._table.font()
        f.setPointSize(fs)
        self._table.setFont(f)
        self._update_main_header_text()

    def _update_main_header_text(self):
        """检查性干燥重量列宽度够则一行, 不够则换行"""
        if self._table is None:
            return
        col4_w = self._table.columnWidth(4)
        item = self._table.horizontalHeaderItem(4)
        if item is None:
            return
        if col4_w >= 140:
            item.setText("检查性干燥重量(g)")
        else:
            item.setText("检查性\n干燥重量(g)")

    def eventFilter(self, obj, event):
        if obj is self._table and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._adjust_row_height)
        if (self._table is not None
                and hasattr(self, '_vheader') and obj is self._vheader
                and event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease)):
            # 点击序号列：用 selectionModel().select(Rows) 选中整行，不改变 currentIndex，
            # 因此不会触发 CurrentChanged → col 0 不会进入编辑
            if event.type() == QEvent.MouseButtonRelease:
                return True
            row = self._vheader.logicalIndexAt(event.pos().y())
            if row >= 0:
                self._table.selectionModel().select(
                    self._table.model().index(row, 0),
                    QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            return True
        if obj is self._table and event.type() == QEvent.KeyPress:
            k = event.key(); m = event.modifiers()
            if k == Qt.Key_C and m == Qt.ControlModifier:
                item = self._table.currentItem()
                if item and item.text():
                    QApplication.clipboard().setText(item.text())
                return True
            if k == Qt.Key_V and m == Qt.ControlModifier:
                txt = QApplication.clipboard().text()
                if txt:
                    item = self._table.currentItem()
                    if item: item.setText(txt)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                r = obj.currentRow(); c = obj.currentColumn()
                if c == 0 and r + 1 < obj.rowCount():
                    # 样品名称列：跳下一行并自动进入编辑
                    obj.setCurrentCell(r + 1, 0)
                    item = obj.item(r + 1, 0)
                    if item and (item.flags() & Qt.ItemIsEditable):
                        obj.editItem(item)
                elif r + 1 < obj.rowCount():
                    obj.setCurrentCell(r + 1, c)
                return True
        if obj is self._table and event.type() == QEvent.MouseButtonDblClick:
            idx = obj.indexAt(event.pos())
            if idx.isValid() and idx.column() == 1:
                # 采样数据列采用等宽字体
                self._on_cell_double_clicked(idx.row(), idx.column())
                return True
        return super().eventFilter(obj, event)

    def _on_exit_clicked(self):
        """退出程序 - 带确认提示"""
        from confirm_dialog import ConfirmDialog
        # 检查是否有测试在运行
        warning = "确定要退出程序吗？"
        if hasattr(self, 'test_ctrl') and self.test_ctrl and self.test_ctrl.is_running:
            warning = "当前有测试正在运行！\n确定要退出程序吗？\n退出后测试数据将不完整。"
        if ConfirmDialog.confirm(self, warning, title="退出程序", danger=True):
            from PySide2.QtWidgets import QApplication
            QApplication.instance().quit()

    def closeEvent(self, event):
        """窗口关闭事件 - 带确认提示"""
        from confirm_dialog import ConfirmDialog
        warning = "确定要退出程序吗？"
        if hasattr(self, 'test_ctrl') and self.test_ctrl and self.test_ctrl.is_running:
            warning = "当前有测试正在运行！\n确定要退出程序吗？\n退出后测试数据将不完整。"
        if ConfirmDialog.confirm(self, warning, title="退出程序", danger=True):
            event.accept()
        else:
            event.ignore()

    def _on_click(self, name):
        logger.debug(f"[MAIN] 按钮点击: {name}")
        # ===== status: start test(TestController) =====
        if name == "开始测试":
            self.btn_start.setDisabled(True)
            self.btn_start.setText("测试中")
            self.btn_stop.setEnabled(True)
            self.progress_widget.setVisible(True)
            self.progress_data.setText("<span style='color:#2B579A;font-weight:bold'>测试进度：</span>")
            from db import load_params
            params = load_params()
            sample_list = []
            if self._table:
                # 行0: 1号校正坩埚
                corr_name_item = self._table.item(0, 0)
                corr_name = corr_name_item.text().strip() if corr_name_item and corr_name_item.text() else "1号坩埚"
                sample_list.append((0, corr_name, "", 0.0))
                for r in range(1, self._table.rowCount()):
                    item_name = self._table.item(r, 0)
                    if item_name and item_name.text().strip():
                        name = item_name.text().strip()
                        item_mode = self._table.item(r, 1)
                        mode = item_mode.text().strip() if item_mode and item_mode.text() else ""
                        item_weight = self._table.item(r, 3)
                        weight = float(item_weight.text()) if item_weight and item_weight.text() else 0.0
                        sample_list.append((r, name, mode, weight))
            from test_controller import TestConfig
            config = TestConfig.from_db_params(params, sample_list)
            if self._table:
                corr_item = self._table.item(0, 2)
                if corr_item and corr_item.text():
                    config.aw_corr_crucible = float(corr_item.text())
                    config.tw_corr_crucible = float(corr_item.text())
            self.test_ctrl.start_test(config)
            return

        # ===== status: stop test(TestController) =====
        if name == "停止测试":
            from confirm_dialog import ConfirmDialog
            if not ConfirmDialog.confirm(
                self, "确定要停止当前测试吗？\n停止后测试数据将不完整。",
                title="停止测试", danger=True
            ):
                return
            self.test_ctrl.stop_test()
            self.btn_start.setEnabled(True)
            self.btn_start.setText("开始测试")
            self.btn_stop.setEnabled(False)
            self.progress_widget.setVisible(False)
            return

        if name == "打印数据":
            try:
                # 直接触发打印, 跳过选择弹窗
                from print_report import print_report_direct, _collect_table_data
                from db import load_params
                logger.debug("[PRINT] 打印数据按钮被点击")
                p = load_params()
                unit = p.get("unit", "")
                tech = self.hy_combo.currentText() if hasattr(self, "hy_combo") else ""
                data = _collect_table_data(self._table) if self._table else []
                logger.debug("[PRINT] 收集到 {} 条样品数据".format(len(data)))
                if not data:
                    from confirm_dialog import ConfirmDialog
                    ConfirmDialog.info(self, "当前表格中没有样品数据，请先输入样品名称。", "提示")
                    return
                print_report_direct(self, self._table, unit=unit, tech=tech, reviewer="")
            except Exception as e:
                logger.error("[PRINT] 打印异常: " + str(e))
                import traceback
                logger.error(traceback.format_exc())
                from PySide2.QtWidgets import QMessageBox
                QMessageBox.warning(self, "打印错误", f"打印/导出时发生错误：\n{str(e)}")
        elif name == "硬件检测":
            from hardware_check_dialog import HardwareCheckDialog
            dlg = HardwareCheckDialog(self, serial_mgr=self.serial_mgr)
            dlg.exec_()
        elif name == "试验参数":
            from password_dialog import PasswordDialog
            if not PasswordDialog.verify(self, "user"):
                return
            from settings_dialog import SettingsDialog
            dlg = SettingsDialog(self)
            dlg.params_changed.connect(self._rebuild_table)
            dlg.exec_()
            self._load_hy_list()
        elif name == "查询数据":
            from data_query_dialog import DataQueryDialog
            dlg = DataQueryDialog(self)
            dlg.exec_()
        elif name == "称量样重":
            from weigh_dialog import WeighDialog
            from weigh_controller import WeighController
            from db import load_params

            p = load_params()
            weigh_mode = p.get("weigh_mode", 0)
            if weigh_mode == 1:
                # 单独称量模式(仪器按键确认)
                valid_rows = []
                for r in range(1, self._table.rowCount()):
                    item = self._table.item(r, 0)
                    if item and item.text().strip():
                        valid_rows.append(r)

                if not valid_rows:
                    QMessageBox.warning(self, "警告", "没有找到有效的样品行")
                    return

                dlg = WeighDialog(self)
                ctrl = WeighController(self)
                ctrl.set_table(self._table)
                ctrl.set_serial_manager(self.serial_mgr)

                def on_weigh_progress_individual(info):
                    if info["phase"] == "tare":
                        dlg.show_weighing(info["row"], info["name"], info["weight"])
                    elif info["phase"] == "individual":
                        dlg.show_individual_weighing(info["row"], info["name"], info["weight"])

                def on_weigh_done_individual(phase):
                    if phase == "tare":
                        # 单独称量模式: 称完坩埚后直接进入样品称量，跳过"请添加样品"提示
                        ctrl.start_individual_sample_weigh(valid_rows)
                    elif phase == "sample":
                        # 单独称重: 不显示结果界面，数据已在回填时写入 DB，直接关闭
                        dlg.accept()

                def on_add_sample_prompt_individual():
                    dlg.show_add_sample_prompt()

                def on_real_time_weight_individual(weight):
                    dlg.update_real_time_weight(weight)

                def on_single_weigh_done_individual(row, weight):
                    dlg.show_single_weigh_done(row, weight)

                def on_weight_out_of_range_individual(name, weight, lo, hi):
                    dlg.show_individual_range_warning(lo, hi)

                ctrl.sig_weighing_progress.connect(on_weigh_progress_individual)
                ctrl.sig_weighing_done.connect(on_weigh_done_individual)
                ctrl.sig_add_sample_prompt.connect(on_add_sample_prompt_individual)
                ctrl.sig_status_msg.connect(dlg.show_status)
                ctrl.sig_error.connect(lambda msg: QMessageBox.warning(self, "称量错误", msg))
                ctrl.sig_real_time_sample_weight.connect(on_real_time_weight_individual)
                ctrl.sig_single_weigh_done.connect(on_single_weigh_done_individual)
                ctrl.sig_weight_out_of_range.connect(on_weight_out_of_range_individual)
                ctrl.sig_confirm_weigh.connect(lambda row, name, w: dlg.show_individual_weighing(row, name, w))

                dlg.confirm_weigh_clicked.connect(ctrl.confirm_current_weigh)

                dlg.start_sample_clicked.connect(lambda: ctrl.start_individual_sample_weigh(valid_rows))

                ctrl.start_tare_weigh(valid_rows)
                dlg.exec_()
                ctrl.stop()
                return

            valid_rows = []
            for r in range(1, self._table.rowCount()):
                item = self._table.item(r, 0)
                if item and item.text().strip():
                    valid_rows.append(r)

            from PySide2.QtWidgets import QMessageBox
            if not valid_rows:
                QMessageBox.warning(self, "警告", "没有找到有效的样品行")
                return

            dlg = WeighDialog(self)
            ctrl = WeighController(self)
            ctrl.set_table(self._table)
            ctrl.set_serial_manager(self.serial_mgr)

            def on_weigh_progress(info):
                if info["phase"] == "tare":
                    dlg.show_weighing(info["row"], info["name"], info["weight"])
                else:
                    dlg.show_weighing_sample(info["row"], info["name"], info["weight"])

            def on_weigh_done(phase):
                if phase == "tare":
                    ctrl.show_add_sample_prompt()
                elif phase == "sample":
                    from weight_check_dialog import WeightCheckDialog
                    from db import create_experiment, save_experiment_samples

                    sample_list = []
                    # 第0行: 校正坩埚（必须包含，否则重启后丢失）
                    corr_name_item = self._table.item(0, 0)
                    corr_name = corr_name_item.text().strip() if corr_name_item and corr_name_item.text() else "校正坩埚"
                    corr_tare_item = self._table.item(0, 2)
                    corr_tare = float(corr_tare_item.text()) if corr_tare_item and corr_tare_item.text() else 0.0
                    corr_sample_item = self._table.item(0, 3)
                    corr_sample = float(corr_sample_item.text()) if corr_sample_item and corr_sample_item.text() else 0.0
                    if corr_tare > 0:
                        sample_list.append({"row": 0, "name": corr_name, "weight": corr_sample, "tare": corr_tare, "mode": ""})
                    for r in range(1, self._table.rowCount()):
                        name_item = self._table.item(r, 0)
                        if name_item and name_item.text().strip():
                            name = name_item.text().strip()
                            tare_item = self._table.item(r, 2)
                            tare = float(tare_item.text()) if tare_item and tare_item.text() else 0.0
                            weight_item = self._table.item(r, 3)
                            weight = float(weight_item.text()) if weight_item and weight_item.text() else 0.0
                            mode_item = self._table.item(r, 1)
                            mode = mode_item.text().strip() if mode_item and mode_item.text() else "分析水"
                            sample_list.append({"row": r, "name": name, "weight": weight, "tare": tare, "mode": mode})

                    if sample_list:
                        exp_id = create_experiment()
                        exp_samples = []
                        for s in sample_list:
                            exp_samples.append({"row_idx": s["row"], "name": s["name"],
                                "mode": s["mode"], "tare_weight": s["tare"], "sample_weight": s["weight"]})
                        save_experiment_samples(exp_id, exp_samples)
                        params = load_params()
                        # 只传不合格样品到结果界面，全合格不弹窗
                        tw_low = float(params.get("tw_low", 9.0))
                        tw_high = float(params.get("tw_high", 12.0))
                        aw_low = float(params.get("aw_low", 0.9))
                        aw_high = float(params.get("aw_high", 1.1))
                        failed_samples = []
                        for s in sample_list:
                            if s.get("row") == 0:
                                continue  # 跳过校正坩埚
                            lo, hi = (tw_low, tw_high) if s.get("mode") == "全水" else (aw_low, aw_high)
                            if s["weight"] < lo or s["weight"] > hi:
                                failed_samples.append(s)
                        dlg.accept()
                        if failed_samples:
                            check_dlg = WeightCheckDialog(self)
                            check_dlg.load_sample_data(failed_samples, params)
                            check_dlg.reweigh_clicked.connect(self._on_reweigh_flow)
                            check_dlg.exec_()
                    else:
                        dlg.accept()

            def on_add_sample_prompt():
                dlg.show_add_sample_prompt()

            ctrl.sig_weighing_progress.connect(on_weigh_progress)
            ctrl.sig_weighing_done.connect(on_weigh_done)
            ctrl.sig_add_sample_prompt.connect(on_add_sample_prompt)
            ctrl.sig_status_msg.connect(dlg.show_status)
            ctrl.sig_error.connect(lambda msg: QMessageBox.warning(self, "称量错误", msg))

            dlg.start_sample_clicked.connect(ctrl.start_sample_weigh)

            ctrl.start_tare_weigh(valid_rows)
            dlg.exec_()
            ctrl.stop()
        elif name == "追加样品":
            from weigh_dialog import WeighDialog
            from weigh_controller import WeighController
            # ---- 1. 选中行校验 ----
            sel = self._table.selectedIndexes()
            if not sel:
                QMessageBox.warning(self, "提示", "请先选择要追加的样品行")
                return
            target_row = sel[0].row()
            if target_row < 1:
                QMessageBox.warning(self, "提示", "第0行为校正坩埚，请选择有效样品行（第1行起）")
                return

            # ---- 2. 读取样品名和模式 ----
            name_item = self._table.item(target_row, 0)
            sample_name = name_item.text().strip() if name_item and name_item.text().strip() else ""
            mode_item = self._table.item(target_row, 1)
            mode = mode_item.text().strip() if mode_item and mode_item.text() else "分析水"

            # ---- 3. 数据检查 + 清除确认 ----
            tare_item = self._table.item(target_row, 2)
            sample_item = self._table.item(target_row, 3)
            has_tare = tare_item and tare_item.text().strip()
            has_sample = sample_item and sample_item.text().strip()
            if has_tare or has_sample:
                from confirm_dialog import ConfirmDialog
                if not ConfirmDialog.confirm(
                    self,
                    "第%d行「%s」已有称量数据，确定清除后重新追加？" % (target_row + 1, sample_name or "未命名"),
                    title="追加样品确认", danger=True
                ):
                    return
                from db import clear_sample_row
                clear_sample_row(target_row)
                if has_tare:
                    tare_item.setText("")
                if has_sample:
                    sample_item.setText("")

            # ---- 4. 禁用按钮，创建共用弹窗 ----
            self.btn_append.setEnabled(False)
            dlg = WeighDialog(self)

            # ============================================================
            # 阶段1: 单坩埚称量（AppendSampleWorker）
            # ============================================================
            from append_sample_worker import AppendSampleWorker
            self._append_worker = AppendSampleWorker(
                self.serial_mgr, self._table, target_row, sample_name, mode)

            def on_phase1_status(msg):
                dlg.show_status(msg)

            def on_phase1_progress(info):
                if info["phase"] == "tare":
                    dlg.show_weighing(info["row"], info["name"], info["weight"])

            def on_phase1_done(success, msg):
                self._append_worker = None
                if not success:
                    self._on_append_finished(False, msg)
                    dlg.reject()
                    return
                # 开盖完成，直接进入样品称量（不显示中间UI）
                _start_phase2()

            def on_phase1_error(msg):
                QMessageBox.warning(self, "错误", msg)
                self._on_append_error(msg)
                self._append_worker = None
                dlg.reject()

            self._append_worker.sig_status_msg.connect(on_phase1_status)
            self._append_worker.sig_progress.connect(on_phase1_progress)
            self._append_worker.sig_done.connect(on_phase1_done)
            self._append_worker.sig_error.connect(on_phase1_error)
            # 跨线程安全: 在主线程写表格
            self._append_worker.sig_tare_backfill.connect(self._on_append_tare_backfill)
            dlg.rejected.connect(self._append_worker.stop)

            # ============================================================
            # 阶段2: 单样品称量（复用 WeighController）
            # 追加样品模式: 样盘在阶段1已下降，跳过降升操作，流程结束时统一抬起
            # ============================================================
            def _start_phase2():
                valid_rows = [target_row]
                ctrl = WeighController(self)
                ctrl.set_table(self._table)
                ctrl.set_serial_manager(self.serial_mgr)
                ctrl.set_skip_plate_ops(True)

                def on_progress(info):
                    if info["phase"] == "individual":
                        dlg.show_individual_weighing(info["row"], info["name"], info["weight"])

                def on_done(phase):
                    if phase == "sample":
                        # 统一收尾: 样盘上升 + 解除称重状态
                        from protocol_layer import CommandBuilder, send_cmd_with_uplink_check
                        cmd_up = CommandBuilder.build_command(CMD.SAMPLE_PLATE_UP)
                        send_cmd_with_uplink_check(self.serial_mgr, cmd_up, "样盘上升")
                        cmd_exit = CommandBuilder.build_command(CMD.EXIT_WEIGH_MODE)
                        send_cmd_with_uplink_check(self.serial_mgr, cmd_exit, "解除称重状态")
                        self._on_append_finished(True, "追加样品完成")
                        dlg.accept()

                def on_real_time(weight):
                    dlg.update_real_time_weight(weight)

                def on_single_done(row, weight):
                    pass

                def on_range_warning(name, weight, lo, hi):
                    dlg.show_individual_range_warning(lo, hi)

                ctrl.sig_weighing_progress.connect(on_progress)
                ctrl.sig_weighing_done.connect(on_done)
                ctrl.sig_status_msg.connect(dlg.show_status)
                ctrl.sig_error.connect(lambda msg: QMessageBox.warning(self, "称量错误", msg))
                ctrl.sig_real_time_sample_weight.connect(on_real_time)
                ctrl.sig_single_weigh_done.connect(on_single_done)
                ctrl.sig_weight_out_of_range.connect(on_range_warning)
                ctrl.sig_confirm_weigh.connect(lambda row, name, w: dlg.show_individual_weighing(row, name, w))
                dlg.confirm_weigh_clicked.connect(ctrl.confirm_current_weigh)
                def on_phase2_reject():
                    """阶段2取消: 停止称量 → 样盘上升 → 解除称重 → 恢复按钮"""
                    ctrl.stop()
                    from protocol_layer import CommandBuilder, CMD, send_cmd_with_uplink_check
                    cmd_up = CommandBuilder.build_command(CMD.SAMPLE_PLATE_UP)
                    send_cmd_with_uplink_check(self.serial_mgr, cmd_up, "样盘上升")
                    cmd_exit = CommandBuilder.build_command(CMD.EXIT_WEIGH_MODE)
                    send_cmd_with_uplink_check(self.serial_mgr, cmd_exit, "解除称重状态")
                    self._on_append_finished(True, "追加样品已取消")

                dlg.rejected.connect(on_phase2_reject)

                ctrl.start_individual_sample_weigh(valid_rows)

            # ---- 启动阶段1 ----
            self._append_worker.start()
            dlg.exec_()
            # 清理
            if self._append_worker and self._append_worker.isRunning():
                self._append_worker.stop()
                self._append_worker.wait(3000)
            self._append_worker = None
            return

        elif name == "全水全选":
            self._batch_set_mode("全水")

        elif name == "分析水全选":
            self._batch_set_mode("分析水")

        elif name == "清除数据":
            from confirm_dialog import ConfirmDialog
            if not ConfirmDialog.confirm(self, "确定要清除所有实验数据吗？此操作不可撤销！",
                                         title="清除确认", danger=True):
                return
            self._do_clear_all_data()

        elif name == "手动存数":
            self._on_manual_save()

        elif name == "重新计算":
            self._on_recalculate()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 单实例锁 — socket 端口绑定，进程退出 OS 自动释放
    import socket
    _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_sock.bind(("127.0.0.1", 51234))
    except socket.error:
        QMessageBox.warning(None, "提示", "程序已在运行中，不能重复打开。")
        sys.exit(1)

    # 开机密码验证
    from password_dialog import PasswordDialog
    if not PasswordDialog.verify(None, "boot"):
        sys.exit(0)

    # 启动画面
    w = MoistureAnalyzer()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()


