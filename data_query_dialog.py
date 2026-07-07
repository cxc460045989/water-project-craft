# -*- coding: utf-8 -*-
"""数据查询对话框 - 微机全自动水分测定仪
框架: PySide2 (Qt5) - 兼容Windows 7 / 麒麟Linux x86/ARM64
"""

import sys
from PySide2.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QGroupBox, QPushButton, QLabel, QLineEdit, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide2.QtCore import Qt
from PySide2.QtGui import QFont
from button_styles import apply_button_types
from button_styles import apply_button_types


# ============================================================
# 数据查询对话框
# ============================================================
class DataQueryDialog(QDialog):
    """数据查询弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("查询数据")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowMaximizeButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #E8EBF0;
            }
            QGroupBox {
                background-color: #F2F4F7;
                border: 1px solid #C8CED8;
                border-radius: 6px;
                margin-top: 14px;
                padding: 16px 12px 10px 12px;
                font-size: 14px;
                font-weight: bold;
                color: #1F2937;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 2px 12px;
                background-color: #E8EBF0;
                border: 1px solid #C8CED8;
                border-radius: 3px;
                left: 10px;
            }

            QLineEdit {
                background-color: #FFFFFF;
                color: #1F2937;
                border: 1px solid #B0B8C4;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 13px;
                min-height: 24px;
            }
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #1F2937;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
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
                text-overflow: clip;
            }
            QLabel {
                font-size: 13px;
                color: #1F2937;
            }
        """)
        self._build_ui()
        self.resize(900, 520)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ========== 上方：数据表格 ==========
        self._build_table(main_layout)

        # ========== 下方：操作区 ==========
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self._build_search_group(bottom_layout)
        self._build_upload_group(bottom_layout)
        self._build_button_area(bottom_layout)

        main_layout.addLayout(bottom_layout)

    def _build_table(self, pl):
        headers = ["序号", "打印", "样品名称", "测试日期", "模式",
                    "坩埚重量 (g)", "样品重量 (g)", "检查性干燥重量 (g)",
                    "干燥重量 (g)", "水分 (%)", "平均值 (%)", "精密度 (%)"]
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setRowCount(3)

        hf = QFont("Microsoft YaHei", 12, QFont.Bold)
        t.horizontalHeader().setFont(hf)
        t.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        t.horizontalHeader().setMinimumHeight(36)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        t.horizontalHeader().setStretchLastSection(False)
        t.horizontalHeader().setMinimumSectionSize(70)

        t.verticalHeader().setDefaultSectionSize(30)
        t.verticalHeader().setVisible(True)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setShowGrid(True)
        t.setWordWrap(False)

        col_widths = [50, 50, 80, 80, 70, 110, 110, 140, 110, 80, 80, 80]
        for i, w in enumerate(col_widths):
            t.setColumnWidth(i, w)

        self._fill_data(t)
        pl.addWidget(t, 1)

    def _fill_data(self, t):
        c = Qt.AlignCenter

        # Row 0
        self._set_item(t, 0, 0, "1", c)
        self._set_checkbox(t, 0, 1, True)
        self._set_item(t, 0, 2, "3", c)
        self._set_item(t, 0, 3, "260630", c)
        self._set_item(t, 0, 4, "分析水", c)
        self._set_item(t, 0, 5, "25.0236", c)
        self._set_item(t, 0, 6, "0.9675", c)
        self._set_item(t, 0, 7, "0.8769", c)
        self._set_item(t, 0, 8, "0.8764", c)
        self._set_item(t, 0, 9, "9.42", c)

        # Row 1
        self._set_item(t, 1, 0, "2", c)
        self._set_checkbox(t, 1, 1, True)
        self._set_item(t, 1, 2, "2", c)
        self._set_item(t, 1, 3, "260630", c)
        self._set_item(t, 1, 4, "分析水", c)
        self._set_item(t, 1, 5, "25.0237", c)
        self._set_item(t, 1, 6, "0.9684", c)
        self._set_item(t, 1, 7, "0.8770", c)
        self._set_item(t, 1, 8, "0.8765", c)
        self._set_item(t, 1, 9, "9.49", c)

        # Row 2
        self._set_item(t, 2, 0, "3", c)
        self._set_checkbox(t, 2, 1, False)

        t.resizeRowsToContents()

    def _set_item(self, t, row, col, text, align):
        i = QTableWidgetItem(text)
        i.setTextAlignment(align)
        t.setItem(row, col, i)

    def _set_checkbox(self, t, row, col, checked):
        cb = QWidget()
        layout = QHBoxLayout(cb)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        chk = QCheckBox()
        chk.setChecked(checked)
        layout.addWidget(chk)
        t.setCellWidget(row, col, cb)

    def _build_search_group(self, pl):
        grp = QGroupBox(" 查找数据 ")
        layout = QFormLayout(grp)
        layout.setSpacing(6)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # 时间范围行
        h = QHBoxLayout()
        h.setSpacing(4)
        for val in ["2026", "06", "30"]:
            le = QLineEdit(val)
            le.setFixedWidth(50)
            le.setAlignment(Qt.AlignCenter)
            h.addWidget(le)
        h.addWidget(QLabel(" 日 - "))
        for val in ["2026", "06", "30"]:
            le = QLineEdit(val)
            le.setFixedWidth(50)
            le.setAlignment(Qt.AlignCenter)
            h.addWidget(le)
        h.addWidget(QLabel(" 日 "))
        layout.addRow(" 时间范围 ", h)

        # 样品名称行
        h2 = QHBoxLayout()
        h2.setSpacing(6)
        le_name = QLineEdit()
        h2.addWidget(le_name)
        layout.addRow(" 样品名称：", h2)

        pl.addWidget(grp)

    def _build_upload_group(self, pl):
        grp = QGroupBox(" 数据上传 (Tcp) ")
        layout = QFormLayout(grp)
        layout.setSpacing(6)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h1 = QHBoxLayout()
        h1.setSpacing(6)
        le_ip = QLineEdit()
        le_ip.setPlaceholderText("")
        h1.addWidget(le_ip)
        btn_test = QPushButton(" 链接测试 "); apply_button_types(btn_test, "action")
        h1.addWidget(btn_test)
        layout.addRow(" 服务器 IP ", h1)

        h2 = QHBoxLayout()
        h2.setSpacing(6)
        le_port = QLineEdit("0")
        le_port.setFixedWidth(80)
        le_port.setAlignment(Qt.AlignCenter)
        h2.addWidget(le_port)
        btn_upload = QPushButton(" 上传数据 "); apply_button_types(btn_upload, "action")
        h2.addWidget(btn_upload)
        layout.addRow(" 监听端口 ", h2)

        pl.addWidget(grp)

    def _build_button_area(self, pl):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        btn_names = [
            ["开始查找", "打印全选", "打 印"],
            ["删除数据", "清除打印", "Excel"],
        ]

        for row_names in btn_names:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            row_layout.addStretch()
            for name in row_names:
                btn = QPushButton(" " + name + " ")
                row_layout.addWidget(btn)
            layout.addLayout(row_layout)

        pl.addWidget(widget)


# ============================================================
# 独立测试入口
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dlg = DataQueryDialog()
    dlg.exec_()


