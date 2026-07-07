# -*- coding: utf-8 -*-
"""水灰样品重量检查弹窗 - 微机全自动水分测定仪
批量称重流程完成后自动弹出，校验样品重量上下限、计算偏差、超标标红、重新称量回退
"""

from PySide2.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QColor, QFont
from button_styles import apply_button_types


class WeightCheckDialog(QDialog):
    """水灰样品重量检查弹窗"""
    reweigh_clicked = Signal()  # "重新称量"信号，触发整套流程重跑

    # 表格列索引
    COL_IDX = 0   # 样号
    COL_NAME = 1  # 样品名称
    COL_WEIGHT = 2  # 样品重量(g)
    COL_DEVIATION = 3  # 样重偏差(g)
    COL_PASS = 4  # 是否合格

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("水灰样品重量检查")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(600, 480)
        self.setModal(True)
        # 外部注入的数据
        self._sample_list = []   # [{row, name, weight, mode}, ...]
        self._params = {}        # 试验参数字典
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(16, 12, 16, 16)

        # ---- 顶部表格 ----
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["样号", "样品名称", "样品重量(g)", "样重偏差(g)", "是否合格"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(80)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        layout.addWidget(self.table, 1)

        # ---- 底部信息区 ----
        bottom_widget = QWidget()
        bottom_widget.setObjectName("checkBottom")
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(4, 10, 4, 4)
        bottom_layout.setSpacing(4)

        self.label_tw_range = QLabel("全水重量范围  -- g")
        self.label_tw_range.setObjectName("rangeLabel")
        bottom_layout.addWidget(self.label_tw_range)

        self.label_aw_range = QLabel("分析水重量范围  -- g")
        self.label_aw_range.setObjectName("rangeLabel")
        bottom_layout.addWidget(self.label_aw_range)

        layout.addWidget(bottom_widget)

        # ---- 按钮行 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self.btn_reweigh = QPushButton("重新称量")
        apply_button_types(self.btn_reweigh, "action")
        self.btn_reweigh.setMinimumWidth(140)
        self.btn_reweigh.setMinimumHeight(36)
        self.btn_reweigh.clicked.connect(self._on_reweigh)
        btn_layout.addWidget(self.btn_reweigh)

        layout.addLayout(btn_layout)

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #E8EBF0;
            }
            QLabel#rangeLabel {
                font-size: 14px;
                font-weight: bold;
                color: #1F2937;
                background: transparent;
                padding: 2px 4px;
            }
            QWidget#checkBottom {
                background-color: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
            }
            QTableWidget {
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 2px 6px;
            }
            QHeaderView::section {
                font-weight: bold;
                font-size: 13px;
                padding: 4px 2px;
            }
        """)
        from button_styles import BUTTON_QSS
        self.setStyleSheet(self.styleSheet() + BUTTON_QSS)

    # ---- 对外接口 ----

    def load_sample_data(self, sample_list, param_config):
        """加载样品数据并填充表格
        Args:
            sample_list: [{row(int), name(str), weight(float), mode(str)}, ...]
                有效样品列表，row为主表格行号
            param_config: dict 试验参数配置，含 aw_low/aw_high/tw_low/tw_high
        """
        self._sample_list = sample_list
        self._params = param_config
        self._refresh_ui()

    def _refresh_ui(self):
        """刷新表格数据和底部信息"""
        self._update_range_labels()
        self._populate_table()

    def _update_range_labels(self):
        """【试验参数读取位置】实时读取上下限并更新底部文字"""
        p = self._params
        tw_low = float(p.get("tw_low", 9.0000))
        tw_high = float(p.get("tw_high", 12.0000))
        aw_low = float(p.get("aw_low", 0.9000))
        aw_high = float(p.get("aw_high", 1.1000))
        self.label_tw_range.setText(
            "全水重量范围  {:.4f}g-{:.4f}g".format(tw_low, tw_high))
        self.label_aw_range.setText(
            "分析水重量范围  {:.4f}g-{:.4f}g".format(aw_low, aw_high))

    def _populate_table(self):
        """填充表格数据、计算偏差、超标标红"""
        p = self._params
        tw_low = float(p.get("tw_low", 9.0000))
        tw_high = float(p.get("tw_high", 12.0000))
        aw_low = float(p.get("aw_low", 0.9000))
        aw_high = float(p.get("aw_high", 1.1000))

        self.table.setRowCount(len(self._sample_list))

        for i, s in enumerate(self._sample_list):
            row = s["row"]
            name = s.get("name", "")
            weight = s.get("weight", 0.0)
            mode = s.get("mode", "分析水")

            # 【上下限读取】根据模式选择对应限值
            if mode == "全水":
                lo, hi = tw_low, tw_high
            else:
                lo, hi = aw_low, aw_high

            # 【偏差计算公式】实际样品重量 - 该模式标准下限重量
            deviation = weight - lo

            # 填充样号
            item_idx = QTableWidgetItem(str(row))
            item_idx.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, self.COL_IDX, item_idx)

            # 填充样品名称
            item_name = QTableWidgetItem(name)
            item_name.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, self.COL_NAME, item_name)

            # 填充样品重量
            item_weight = QTableWidgetItem("{:.4f}".format(weight))
            item_weight.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, self.COL_WEIGHT, item_weight)

            # 填充样重偏差
            item_dev = QTableWidgetItem("{:.4f}".format(deviation))
            item_dev.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, self.COL_DEVIATION, item_dev)

            # 填充是否合格（绿色/红色）
            passed = (weight >= lo) and (weight <= hi)
            pass_text = "合格" if passed else "不合格"
            item_pass = QTableWidgetItem(pass_text)
            item_pass.setTextAlignment(Qt.AlignCenter)
            pass_color = QColor(20, 150, 20) if passed else QColor(200, 30, 30)
            item_pass.setForeground(pass_color)
            item_pass.setFont(QFont("", -1, QFont.Bold))
            self.table.setItem(i, self.COL_PASS, item_pass)

            # 前4列保持黑色
            default_color = QColor(30, 30, 30)
            for col in range(4):
                item = self.table.item(i, col)
                if item:
                    item.setForeground(default_color)

    # ---- 重新称量 ----

    def _on_reweigh(self):
        """【重新称量流程跳转入口】关闭弹窗，发射信号"""
        self.reweigh_clicked.emit()
        self.accept()

    # ---- 工具 ----

    def get_sample_list(self):
        """外部获取当前弹窗的样品数据列表"""
        return self._sample_list