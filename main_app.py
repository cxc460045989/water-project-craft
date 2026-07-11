# -*- coding: utf-8 -*-
"""微机全自动水分测定仪 - 现代专业重构版
框架: PySide2 (Qt5) - 兼容Windows 7 / 麒麟Linux x86/ARM
依赖: pip install pyside2 pyserial
"""

import sys, os, subprocess
from PySide2.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, QLabel,
    QHeaderView, QAbstractItemView, QSizePolicy, QFrame, QStyle, QProgressBar,
)
from PySide2.QtCore import Qt, QSize, QEvent, QTimer
from PySide2.QtGui import QFont, QKeySequence
from db import load_params, save_params, load_techs
from button_styles import BUTTON_QSS, apply_button_types
from PySide2.QtWidgets import QShortcut
from PySide2.QtGui import QFont
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

class MoistureAnalyzer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("鹤壁市淇天仪器仪表有限公司 demo")
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
        # ---- 底部信息栏（默认隐藏） ----
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2B579A; padding: 0 8px;")
        self.progress_data = QLabel("")
        self.progress_data.setStyleSheet("font-size: 13px; color: #1F2937; padding: 0 8px;")
        info_bar = QWidget()
        info_bar.setObjectName("bottomInfoBar")
        info_bar.setFixedHeight(36)
        info_lo = QHBoxLayout(info_bar)
        info_lo.setContentsMargins(16,0,16,0)
        info_lo.setSpacing(8)
        info_lo.addWidget(self.progress_label)
        info_lo.addWidget(self.progress_data, 1)
        self.progress_widget = info_bar
        self.progress_widget.setVisible(True)
        lo.addWidget(self.progress_widget)
        # ---- 串口管理器 (Mock 模式) ----
        self._uplink_buf = UplinkBuffer()
        self.serial_mgr = SerialManager(parent=self, use_mock=False)
        self.serial_mgr.connected.connect(self._on_serial_connected)
        self.serial_mgr.disconnected.connect(self._on_serial_disconnected)
        self.serial_mgr.data_received.connect(self._on_serial_data)
        self.serial_mgr.error_occurred.connect(self._on_serial_error)
        self._port_name = ""

        # ---- ????? ----
        from test_controller import TestController
        self.test_ctrl = TestController(self.serial_mgr, self)
        self._init_test_signals()
        # ---- 启动时自动打开串口 ----
        from db import load_params
        _p = load_params()
        _com = _p.get("com_port", "COM1") or "COM1"
        if _com:
            logger.info("[SERIAL] 启动时自动打开串口: " + str(_com))
            self.serial_mgr.open(port=_com)
            # 启动上行帧轮询: 每200ms读取串口上行帧并触发 data_received 信号
            if not hasattr(self.serial_mgr, '_mock_poll_timer'):
                self._uplink_poll_timer = QTimer(self)
                self._uplink_poll_timer.timeout.connect(self._poll_uplink)
                self._uplink_poll_timer.start(200)
        else:
            logger.info("[SERIAL] 未配置串口号，启动后不自动打开")
        # ---- QShortcut（仅开发模式可用） ----
        if not getattr(sys, "frozen", False):
            QShortcut(QKeySequence('F5'), self).activated.connect(self._restart)

    def _restart(self):
        subprocess.Popen([sys.executable, __file__])
        self.close()
        QApplication.instance().quit()

    # ---- 串口回调 ----
    def _on_serial_connected(self):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._port_name = self.serial_mgr.port_name or "?"
        logger.info("[SERIAL][" + self._port_name + "] " + ts + " 串口已连接")

    def _poll_uplink(self):
        """周期性轮询串口上行帧, 触发 data_received 更新 UI"""
        if not self.serial_mgr.is_connected:
            return
        try:
            raw = self.serial_mgr.read_all()
        except Exception:
            return
        if raw:
            self.serial_mgr.update_uplink_time()
            self.serial_mgr.data_received.emit(raw)

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
            self.temp_val.setText("%.1f" % f["temperature"])
            online_str = "联机" if f["online"] else "脱机"
            self.progress_data.setText("炉温: %.1f\u2103  状态: %s" % (f["temperature"], online_str))
            if f["btn_pressed"]:
                pass
            if getattr(self, "_print_counter", 0) % 5 == 0:
                logger.info("[SERIAL][" + getattr(self, "_port_name", "?") + "] 上行帧: %s  temp=%.1f weight=%.4f online=%d btn=%d" % (
                    f["raw_str"], f["temperature"], f["weight"], f["online"], f["btn_pressed"]))
            self._print_counter = getattr(self, "_print_counter", 0) + 1


    def _on_serial_error(self, msg):
        logger.info("[SERIAL][" + getattr(self, "_port_name", "?") + "] 收到: " + str(msg))


    def _init_test_signals(self):
        """??TestController???UI??"""
        self.test_ctrl.sig_status_msg.connect(self.progress_data.setText)
        self.test_ctrl.sig_error.connect(lambda m: self.progress_data.setText("??: " + m))
        self.test_ctrl.sig_temp_update.connect(lambda t: setattr(self, '_test_temp', t))
        self.test_ctrl.sig_hold_countdown.connect(self._on_hold_countdown)
        self.test_ctrl.sig_test_done.connect(self._on_test_done)

    def _on_hold_countdown(self, remaining):
        mins = remaining // 60
        secs = remaining % 60
        self.progress_data.setText("恒温倒计时: %02d:%02d" % (mins, secs))

    def _on_test_done(self):
        self.btn_start.setEnabled(True)
        self.btn_start.setText("开始测试")
        self.progress_label.setText("")
        self.progress_data.setText("测试完成")

    def _on_append_finished(self, success, msg):
        """追加样品完成回调"""
        self.btn_append.setEnabled(True)
        self.progress_label.setText("")
        if self._table:
            from db import load_latest_samples
            self._restore_samples_from_db(self._table)
        if success:
            self.progress_data.setText("追加样品完成")
        else:
            self.progress_data.setText("追加失败: " + msg)
        if hasattr(self, "_append_thread") and self._append_thread:
            self._append_thread.quit()
            self._append_thread.wait(3000)
            self._append_thread = None
            self._append_worker = None

    def _on_append_error(self, msg):
        """追加样品错误回调"""
        self.btn_append.setEnabled(True)
        self.progress_label.setText("")
        self.progress_data.setText("错误: " + msg)
        if hasattr(self, "_append_thread") and self._append_thread:
            self._append_thread.quit()
            self._append_thread.wait(3000)
            self._append_thread = None
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
        self.progress_data.setText("正在更新表格...")
        QApplication.processEvents()
        sc = load_params().get("sample_count", 24) or 24
        self._table.setRowCount(int(sc))
        self._fill_table(self._table)
        self._restore_samples_from_db(self._table)
        self.progress_data.setText("")

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
        hd = ["样品名称","模式","器皿重(g)","样品重(g)",
               "检查性干燥重量(g)","干燥重量(g)","水分(%)","平均值(%)","精密度(%)"]
        t = QTableWidget()
        sc = load_params().get("sample_count", 24) or 24
        t.setColumnCount(9); t.setHorizontalHeaderLabels(hd); t.setRowCount(int(sc))  # 总行数=样位数量，第0行校正坩埚
        t.setAlternatingRowColors(True)
        hf = QFont("Microsoft YaHei", 12, QFont.Bold)
        t.horizontalHeader().setFont(hf)
        t.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        t.horizontalHeader().setMinimumHeight(50)
        t.verticalHeader().setDefaultSectionSize(36)
        t.verticalHeader().setMinimumSectionSize(30)
        t.verticalHeader().setVisible(True)
        t.setSelectionBehavior(QAbstractItemView.SelectItems)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.CurrentChanged | QAbstractItemView.EditKeyPressed)
        t.setTabKeyNavigation(True)
        t.setWordWrap(True)
        t.setShowGrid(True)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(False)
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
        pl.addWidget(t)

    def _fill_table(self, t):
        c = Qt.AlignCenter
        def s(r, col, txt):
            i = QTableWidgetItem(txt); i.setTextAlignment(c)
            if col != 0:
                i.setFlags(i.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, col, i)
        # 第0行：校正坩埚（写死）
        s(0, 0, "校正坩埚")
        s(0, 2, "25.0235")
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
            elif n == "停止测试": self.btn_stop = btn
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
        tv = QLabel("000"); tv.setObjectName("topTempVal"); tv.setStyleSheet("color: #00FF00; font-size: 24px; font-weight: bold; background: #000000; border: 1px solid #FFD600; border-radius: 4px; padding: 2px 8px; font-family: Courier New, Consolas, monospace;")
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
        exit_btn.clicked.connect(self.close)
        pl.addWidget(exit_btn)
        pl.addStretch()



    # ---- table data real-time persistence ----

    def _on_cell_changed(self, row, col):
        import datetime
        _ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        try:
            item = self._table.item(row, col)
            if item is None: return
            val = item.text().strip()
            col_map = {0: "name", 1: "mode", 2: "tare_weight", 3: "sample_weight",
                       4: "check_dry_weight", 5: "dry_weight", 6: "moisture",
                       7: "avg_moisture", 8: "precision_val"}
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
                   7: "avg_moisture", 8: "precision_val"}
        for r in range(1, self._table.rowCount()):
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



    # ---- 重新称量回退入口 ----
    def _on_reweigh_flow(self):
        from weigh_dialog import WeighDialog
        from weigh_controller import WeighController
        from weight_check_dialog import WeightCheckDialog
        from db import create_experiment, save_experiment_samples, load_params
        from PySide2.QtWidgets import QMessageBox

        valid_rows = []
        for r in range(1, self._table.rowCount()):
            item = self._table.item(r, 0)
            if item and item.text().strip():
                valid_rows.append(r)
        if not valid_rows:
            return

        dlg = WeighDialog(self)
        dlg.enable_cancel(True)
        ctrl = WeighController(self)
        ctrl.set_table(self._table)

        def on_weigh_progress(info):
            if info["phase"] == "tare":
                dlg.show_weighing(info["row"], info["name"], info["weight"])
            else:
                dlg.show_weighing_sample(info["row"], info["name"], info["weight"])

        def on_weigh_done(phase):
            if phase == "tare":
                ctrl.show_add_sample_prompt()
            elif phase == "sample":
                sample_list = []
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
                    check_dlg = WeightCheckDialog(self)
                    check_dlg.load_sample_data(sample_list, params)
                    check_dlg.reweigh_clicked.connect(self._on_reweigh_flow)
                    check_dlg.exec_()
                dlg.accept()

        def on_add_sample_prompt():
            dlg.show_add_sample_prompt()

        ctrl.sig_weighing_progress.connect(on_weigh_progress)
        ctrl.sig_weighing_done.connect(on_weigh_done)
        ctrl.sig_add_sample_prompt.connect(on_add_sample_prompt)
        ctrl.sig_status_msg.connect(dlg.show_status)

        dlg.start_sample_clicked.connect(ctrl.start_sample_weigh)

        ctrl.start_tare_weigh(valid_rows)
        dlg.exec_()
        ctrl.stop()
    # ---- table real-time persistence ----
    def _on_cell_changed(self, row, col):
        import datetime
        _ts = lambda: datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        try:
            item = self._table.item(row, col)
            if item is None: return
            val = item.text().strip()
            col_map = {0: "name", 1: "mode", 2: "tare_weight", 3: "sample_weight",
                       4: "check_dry_weight", 5: "dry_weight", 6: "moisture",
                       7: "avg_moisture", 8: "precision_val"}
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
                   7: "avg_moisture", 8: "precision_val"}
        for r in range(1, self._table.rowCount()):
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
                if rid is None or rid == 0:
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
                    item6 = t.item(r, 6)
                    if item6 is not None:
                        item6.setText("{:.2f}".format(mst))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i6 = QTableWidgetItem("{:.2f}".format(mst))
                        i6.setTextAlignment(Qt.AlignCenter)
                        i6.setFlags(i6.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 6, i6)
                avg = row.get("avg_moisture")
                if avg is not None:
                    item7 = t.item(r, 7)
                    if item7 is not None:
                        item7.setText("{:.2f}".format(avg))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i7 = QTableWidgetItem("{:.2f}".format(avg))
                        i7.setTextAlignment(Qt.AlignCenter)
                        i7.setFlags(i7.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 7, i7)
                prec = row.get("precision_val")
                if prec is not None:
                    item8 = t.item(r, 8)
                    if item8 is not None:
                        item8.setText("{:.2f}".format(prec))
                    else:
                        from PySide2.QtWidgets import QTableWidgetItem
                        from PySide2.QtCore import Qt
                        i8 = QTableWidgetItem("{:.2f}".format(prec))
                        i8.setTextAlignment(Qt.AlignCenter)
                        i8.setFlags(i8.flags() & ~Qt.ItemIsEditable)
                        t.setItem(r, 8, i8)
        except Exception as e:
            logger.debug("[RESTORE] ERROR: " + str(e))
    
    def _on_cell_double_clicked(self, row, col):
        tbl = self._table
        if tbl is None:
            return
        if col == 1:
            # 模式列：切换 分析水/全水
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

    def eventFilter(self, obj, event):
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

    def _on_click(self, name):
        logger.debug(f"[MAIN] 按钮点击: {name}")
        # ===== status: start test(TestController) =====
        if name == "开始测试":
            self.btn_start.setDisabled(True)
            self.btn_start.setText("测试中")
            self.progress_label.setText("测试进度")
            self.progress_data.setText("正在初始化测试...")
            from db import load_params
            params = load_params()
            sample_list = []
            if self._table:
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
            self.test_ctrl.stop_test()
            self.btn_start.setEnabled(True)
            self.btn_start.setText("开始测试")
            self.progress_label.setText("")
            self.progress_data.setText("测试已停止")
            return

        if name == "打印数据":
            try:
                from print_report import print_export_prompt, _collect_table_data
                from db import load_params
                logger.debug("[PRINT] 打印数据按钮被点击")
                p = load_params()
                unit = p.get("unit", "")
                tech = self.hy_combo.currentText() if hasattr(self, "hy_combo") else ""
                # 先检查是否有数据
                data = _collect_table_data(self._table) if self._table else []
                logger.debug("[PRINT] 收集到 {} 条样品数据".format(len(data)))
                if not data:
                    from PySide2.QtWidgets import QMessageBox
                    QMessageBox.information(self, "提示", "当前表格中没有样品数据，请先输入样品名称。")
                    return
                print_export_prompt(self, self._table, unit=unit, tech=tech, reviewer="")
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
            if weigh_mode != 0:
                # 单个称量模式
                valid_rows = []
                for r in range(1, self._table.rowCount()):
                    item = self._table.item(r, 0)
                    if item and item.text().strip():
                        valid_rows.append(r)

                if not valid_rows:
                    QMessageBox.warning(self, "警告", "没有找到有效的样品行")
                    return

                dlg = WeighDialog(self)
                dlg.enable_cancel(True)
                ctrl = WeighController(self)
                ctrl.set_table(self._table)
                ctrl.set_serial_manager(self.serial_mgr)

                def on_weigh_progress_single(info):
                    if info["phase"] == "tare":
                        dlg.show_weighing(info["row"], info["name"], info["weight"])

                def on_weigh_done_single(phase):
                    if phase == "tare":
                        ctrl.show_add_sample_prompt()
                    elif phase == "sample":
                        from weight_check_dialog import WeightCheckDialog
                        from db import create_experiment, save_experiment_samples
                        sample_list = []
                        for r in range(1, self._table.rowCount()):
                            name_item = self._table.item(r, 0)
                            if name_item and name_item.text().strip():
                                name = name_item.text().strip()
                                tare_item = self._table.item(r, 2)
                                tare = float(tare_item.text()) if tare_item and tare_item.text() else 0.0
                                weight_item = self._table.item(r, 3)
                                weight = float(weight_item.text()) if weight_item and weight_item.text() else 0.0
                                mode_item = self._table.item(r, 1)
                                mode = mode_item.text().strip() if mode_item and mode_item.text() else "\u5206\u6790\u6c34"
                                sample_list.append({"row": r, "name": name, "weight": weight, "tare": tare, "mode": mode})
                        if sample_list:
                            exp_id = create_experiment()
                            exp_samples = []
                            for s in sample_list:
                                exp_samples.append({"row_idx": s["row"], "name": s["name"],
                                    "mode": s["mode"], "tare_weight": s["tare"], "sample_weight": s["weight"]})
                            save_experiment_samples(exp_id, exp_samples)
                            params = load_params()
                            check_dlg = WeightCheckDialog(self)
                            check_dlg.load_sample_data(sample_list, params)
                            check_dlg.reweigh_clicked.connect(self._on_reweigh_flow)
                            check_dlg.exec_()
                        dlg.accept()

                def on_add_sample_prompt_single():
                    dlg.show_add_sample_prompt()

                # 单个称量信号
                def on_confirm_weigh(row, name, weight):
                    dlg.show_single_weigh_waiting(row, name, weight)

                def on_real_time_weight(weight):
                    dlg.update_real_time_weight(weight)

                def on_single_weigh_done(row, weight):
                    dlg.show_single_weigh_done(row, weight)

                def on_weight_out_of_range(name, weight, lo, hi):
                    dlg.show_single_out_of_range(name, weight, lo, hi)

                ctrl.sig_weighing_progress.connect(on_weigh_progress_single)
                ctrl.sig_weighing_done.connect(on_weigh_done_single)
                ctrl.sig_add_sample_prompt.connect(on_add_sample_prompt_single)
                ctrl.sig_status_msg.connect(dlg.show_status)
                ctrl.sig_confirm_weigh.connect(on_confirm_weigh)
                ctrl.sig_real_time_sample_weight.connect(on_real_time_weight)
                ctrl.sig_single_weigh_done.connect(on_single_weigh_done)
                ctrl.sig_weight_out_of_range.connect(on_weight_out_of_range)

                dlg.confirm_weigh_clicked.connect(ctrl.confirm_current_weigh)
                dlg.start_sample_clicked.connect(lambda: ctrl.start_single_sample_weigh(valid_rows))

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
            dlg.enable_cancel(True)
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
                        check_dlg = WeightCheckDialog(self)
                        check_dlg.load_sample_data(sample_list, params)
                        check_dlg.reweigh_clicked.connect(self._on_reweigh_flow)
                        check_dlg.exec_()
                    dlg.accept()

            def on_add_sample_prompt():
                dlg.show_add_sample_prompt()

            ctrl.sig_weighing_progress.connect(on_weigh_progress)
            ctrl.sig_weighing_done.connect(on_weigh_done)
            ctrl.sig_add_sample_prompt.connect(on_add_sample_prompt)
            ctrl.sig_status_msg.connect(dlg.show_status)

            dlg.start_sample_clicked.connect(ctrl.start_sample_weigh)

            ctrl.start_tare_weigh(valid_rows)
            dlg.exec_()
            ctrl.stop()
        elif name == "追加样品":
            self.btn_append.setEnabled(False)
            self.progress_label.setText("追加样品")
            self.progress_data.setText("启动追加样品流程...")
            # 获取当前未使用的第一个样位
            target_row = 1
            if self._table:
                for r in range(1, self._table.rowCount()):
                    item = self._table.item(r, 3)
                    if not item or not item.text().strip():
                        target_row = r
                        break
                else:
                    target_row = self._table.rowCount() - 1
            _name_item = self._table.item(target_row, 0) if self._table else None
            sample_name = _name_item.text().strip() if _name_item and _name_item.text().strip() else ""
            # 从数据库读取重量范围
            from db import load_params
            params = load_params()
            # 根据样品模式选择范围
            _mode_item = self._table.item(target_row, 1) if self._table else None
            mode = _mode_item.text().strip() if _mode_item and _mode_item.text().strip() else ""
            if mode == "全水":
                lo = float(params.get("tw_low", 9.0))
                hi = float(params.get("tw_high", 12.0))
            else:
                lo = float(params.get("aw_low", 0.9))
                hi = float(params.get("aw_high", 1.1))
            # 启动追加样品Worker
            from sample_append import SampleAppendWorker
            from PySide2.QtCore import QThread
            self._append_thread = QThread(self)
            self._append_worker = SampleAppendWorker(self.serial_mgr)
            self._append_worker.moveToThread(self._append_thread)
            self._append_thread.started.connect(
                lambda: self._append_worker.start_append(target_row, lo, hi, sample_name))
            self._append_worker.sig_status_update.connect(self.progress_data.setText)
            self._append_worker.sig_weight_update.connect(
                lambda w: self.progress_data.setText(
                    "实时重量: %.4fg" % w) if self._append_worker and getattr(self._append_worker, "_tare_weight", 0) > 0 else None)
            self._append_worker.sig_sample_weight_update.connect(
                lambda w: self.progress_data.setText("样品重: %.4fg" % w))
            self._append_worker.sig_finished.connect(self._on_append_finished)
            self._append_worker.sig_error.connect(self._on_append_error)
            self._append_thread.start()
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
            if self._table:
                for r in range(1, self._table.rowCount()):
                    for c in range(self._table.columnCount()):
                        if c == 1:  # 模式列保留
                            continue
                        item = self._table.item(r, c)
                        if item:
                            item.setText("")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 启动画面
    w = MoistureAnalyzer(); w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()


