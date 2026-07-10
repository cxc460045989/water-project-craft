# -*- coding: utf-8 -*-
"""数据查询对话框 - 微机全自动水分测定仪
框架: PySide2 (Qt5) - 兼容Windows 7 / 麒麟Linux x86/ARM64
从 experiment_results 表查询已完成实验的历史数据
"""

import sys, os
from PySide2.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QGroupBox, QPushButton, QLabel, QLineEdit, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
)
from PySide2.QtCore import Qt
from PySide2.QtGui import QFont
from button_styles import apply_button_types
from logging_util import logger


# ============================================================
# 数据查询对话框
# ============================================================
class DataQueryDialog(QDialog):
    """数据查询弹窗 — 查询/打印/删除/导出已完成实验数据"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_rows = []          # 当前查询结果 [{col:val}, ...]
        self._checkboxes = []        # QCheckBox 列表，对应打印勾选
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
        self.resize(960, 560)

    # ========== UI 构建 ==========

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        self._build_table(main_layout)

        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)
        self._build_search_group(bottom_layout)
        self._build_upload_group(bottom_layout)
        self._build_button_area(bottom_layout)
        main_layout.addLayout(bottom_layout)

    def _build_table(self, pl):
        headers = ["序号", "打印", "样品名称", "测试日期", "模式",
                    "坩埚重量(g)", "样品重量(g)", "检查性干燥重(g)",
                    "干燥重量(g)", "水分(%)", "平均值(%)", "精密度(%)"]
        self._table = QTableWidget()
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(0)

        hf = QFont("Microsoft YaHei", 12, QFont.Bold)
        self._table.horizontalHeader().setFont(hf)
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self._table.horizontalHeader().setMinimumHeight(36)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setMinimumSectionSize(60)

        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.verticalHeader().setVisible(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(True)
        self._table.setWordWrap(False)

        col_widths = [50, 50, 90, 85, 72, 108, 108, 130, 108, 80, 80, 80]
        for i, w in enumerate(col_widths):
            self._table.setColumnWidth(i, w)

        pl.addWidget(self._table, 1)

    def _build_search_group(self, pl):
        grp = QGroupBox(" 查找数据 ")
        layout = QFormLayout(grp)
        layout.setSpacing(6)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # 时间范围: 起始年/月/日 - 结束年/月/日
        h = QHBoxLayout()
        h.setSpacing(4)

        from datetime import date as _date
        _today = _date.today()
        _ty = str(_today.year); _tm = str(_today.month).zfill(2); _td = str(_today.day).zfill(2)

        lbl = QLabel(" 起 ")
        lbl.setStyleSheet("font-size:12px;")
        h.addWidget(lbl)
        self._le_sy = QLineEdit(_ty); self._le_sy.setFixedWidth(56); self._le_sy.setAlignment(Qt.AlignCenter); h.addWidget(self._le_sy)
        h.addWidget(QLabel("-"))
        self._le_sm = QLineEdit(_tm); self._le_sm.setFixedWidth(40); self._le_sm.setAlignment(Qt.AlignCenter); h.addWidget(self._le_sm)
        h.addWidget(QLabel("-"))
        self._le_sd = QLineEdit(_td); self._le_sd.setFixedWidth(40); self._le_sd.setAlignment(Qt.AlignCenter); h.addWidget(self._le_sd)

        h.addSpacing(16)

        lbl2 = QLabel(" 止 ")
        lbl2.setStyleSheet("font-size:12px;")
        h.addWidget(lbl2)
        self._le_ey = QLineEdit(_ty); self._le_ey.setFixedWidth(56); self._le_ey.setAlignment(Qt.AlignCenter); h.addWidget(self._le_ey)
        h.addWidget(QLabel("-"))
        self._le_em = QLineEdit(_tm); self._le_em.setFixedWidth(40); self._le_em.setAlignment(Qt.AlignCenter); h.addWidget(self._le_em)
        h.addWidget(QLabel("-"))
        self._le_ed = QLineEdit(_td); self._le_ed.setFixedWidth(40); self._le_ed.setAlignment(Qt.AlignCenter); h.addWidget(self._le_ed)

        layout.addRow(" 时间范围 ", h)

        # 样品名称
        h2 = QHBoxLayout()
        h2.setSpacing(6)
        self._le_name = QLineEdit()
        self._le_name.setPlaceholderText("留空查询全部")
        h2.addWidget(self._le_name)
        layout.addRow(" 样品名称 ", h2)

        pl.addWidget(grp)

    def _build_upload_group(self, pl):
        grp = QGroupBox(" 数据上传 (TCP) ")
        layout = QFormLayout(grp)
        layout.setSpacing(6)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h1 = QHBoxLayout()
        h1.setSpacing(6)
        self._le_ip = QLineEdit()
        h1.addWidget(self._le_ip)
        btn_test = QPushButton(" 链接测试 "); apply_button_types(btn_test, "action")
        btn_test.clicked.connect(self._on_link_test)
        h1.addWidget(btn_test)
        layout.addRow(" 服务器 IP ", h1)

        h2 = QHBoxLayout()
        h2.setSpacing(6)
        self._le_port = QLineEdit("0")
        self._le_port.setFixedWidth(80)
        self._le_port.setAlignment(Qt.AlignCenter)
        h2.addWidget(self._le_port)
        btn_upload = QPushButton(" 上传数据 "); apply_button_types(btn_upload, "action")
        btn_upload.clicked.connect(self._on_upload)
        h2.addWidget(btn_upload)
        layout.addRow(" 监听端口 ", h2)

        pl.addWidget(grp)

    def _build_button_area(self, pl):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row1 = QHBoxLayout(); row1.setSpacing(6); row1.addStretch()
        btn_search = QPushButton(" 开始查找 ")
        btn_search.clicked.connect(self._on_search)
        row1.addWidget(btn_search)

        btn_selall = QPushButton(" 打印全选 ")
        btn_selall.clicked.connect(self._on_select_all)
        row1.addWidget(btn_selall)

        btn_print = QPushButton(" 打  印 ")
        btn_print.clicked.connect(self._on_print)
        row1.addWidget(btn_print)
        layout.addLayout(row1)

        row2 = QHBoxLayout(); row2.setSpacing(6); row2.addStretch()
        btn_del = QPushButton(" 删除数据 ")
        btn_del.clicked.connect(self._on_delete)
        row2.addWidget(btn_del)

        btn_clear = QPushButton(" 清除打印 ")
        btn_clear.clicked.connect(self._on_clear_print)
        row2.addWidget(btn_clear)

        btn_excel = QPushButton(" Excel ")
        btn_excel.clicked.connect(self._on_export_excel)
        row2.addWidget(btn_excel)
        layout.addLayout(row2)

        pl.addWidget(widget)

    # ========== 数据查询逻辑 ==========

    def _on_search(self):
        """开始查找：按时间范围 + 样品名称查询 experiment_results"""
        start_date = self._build_date(self._le_sy, self._le_sm, self._le_sd)
        end_date = self._build_date(self._le_ey, self._le_em, self._le_ed)
        name = self._le_name.text().strip()

        from db import query_experiment_results
        try:
            rows = query_experiment_results(
                start_date=start_date if start_date else None,
                end_date=end_date if end_date else None,
                name_filter=name if name else None,
                limit=200,
            )
        except Exception as e:
            logger.info("[QUERY] 查询失败: %s" % str(e))
            QMessageBox.warning(self, "查询失败", str(e))
            return

        self._all_rows = rows
        self._populate_table(rows)
        logger.info("[QUERY] 查询完成, %d 条记录" % len(rows))

    def _build_date(self, le_y, le_m, le_d):
        """从年/月/日输入框构建 YYYY-MM-DD 字符串"""
        try:
            y = le_y.text().strip()
            m = le_m.text().strip().zfill(2)
            d = le_d.text().strip().zfill(2)
            if not y or not m or not d:
                return ""
            return "%s-%s-%s" % (y, m, d)
        except Exception:
            return ""

    def _populate_table(self, rows):
        """填充表格数据"""
        self._table.setRowCount(0)
        self._table.setRowCount(len(rows))
        self._checkboxes = []
        c = Qt.AlignCenter

        for i, r in enumerate(rows):
            seq = QTableWidgetItem(str(i + 1)); seq.setTextAlignment(c)
            self._table.setItem(i, 0, seq)

            cb_w = QWidget()
            cb_lo = QHBoxLayout(cb_w); cb_lo.setContentsMargins(0, 0, 0, 0); cb_lo.setAlignment(Qt.AlignCenter)
            chk = QCheckBox(); chk.setChecked(True)
            cb_lo.addWidget(chk)
            self._table.setCellWidget(i, 1, cb_w)
            self._checkboxes.append(chk)

            vals = [
                r.get("name", ""),
                r.get("test_date", ""),
                r.get("mode", ""),
                self._fmt(r.get("tare_weight"), 4),
                self._fmt(r.get("sample_weight"), 4),
                self._fmt(r.get("check_dry_weight"), 4),
                self._fmt(r.get("dry_weight"), 4),
                self._fmt(r.get("moisture"), 2),
                self._fmt(r.get("avg_moisture"), 2),
                self._fmt(r.get("precision_val"), 2),
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v); item.setTextAlignment(c)
                self._table.setItem(i, j + 2, item)

        self._table.resizeRowsToContents()

    @staticmethod
    def _fmt(val, decimals):
        if val is None:
            return ""
        try:
            return ("{:." + str(decimals) + "f}").format(float(val))
        except (ValueError, TypeError):
            return str(val)

    # ========== 按钮逻辑 ==========

    def _on_select_all(self):
        """打印全选"""
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _on_clear_print(self):
        """清除打印"""
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _on_print(self):
        """打印勾选行"""
        selected = self._get_selected_rows()
        if not selected:
            QMessageBox.information(self, "提示", "请至少勾选一行数据")
            return
        self._do_print_selected(selected)

    def _on_delete(self):
        """删除选中行（按勾选）"""
        selected = self._get_selected_rows()
        if not selected:
            QMessageBox.information(self, "提示", "请至少勾选一行数据")
            return

        ret = QMessageBox.question(
            self, "确认删除",
            "确定删除选中的 %d 条数据？此操作不可撤销。" % len(selected),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        from db import delete_experiment_result
        for r in selected:
            rid = r.get("id")
            if rid:
                try:
                    delete_experiment_result(rid)
                except Exception as e:
                    logger.info("[QUERY] 删除失败 id=%s: %s" % (rid, str(e)))

        self._on_search()
        logger.info("[QUERY] 已删除 %d 条" % len(selected))

    def _on_export_excel(self):
        """导出全部查询结果为 CSV (兼容 Excel)"""
        if not self._all_rows:
            QMessageBox.information(self, "提示", "请先执行查找")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel", "水分仪数据", "CSV 文件 (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8-sig") as f:
                headers = ["序号", "样品名称", "测试日期", "模式",
                           "坩埚重量(g)", "样品重量(g)", "检查性干燥重(g)",
                           "干燥重量(g)", "水分(%)", "平均值(%)", "精密度(%)"]
                f.write(",".join(headers) + "\n")
                for i, r in enumerate(self._all_rows):
                    row = [
                        str(i + 1),
                        str(r.get("name", "")),
                        str(r.get("test_date", "")),
                        str(r.get("mode", "")),
                        self._fmt(r.get("tare_weight"), 4),
                        self._fmt(r.get("sample_weight"), 4),
                        self._fmt(r.get("check_dry_weight"), 4),
                        self._fmt(r.get("dry_weight"), 4),
                        self._fmt(r.get("moisture"), 2),
                        self._fmt(r.get("avg_moisture"), 2),
                        self._fmt(r.get("precision_val"), 2),
                    ]
                    f.write(",".join(row) + "\n")
            QMessageBox.information(self, "导出成功", "数据已导出到:\n" + path)
            logger.info("[QUERY] Excel 导出成功: %s" % path)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _on_link_test(self):
        """TCP 链接测试（占位）"""
        QMessageBox.information(self, "提示", "TCP 上传功能开发中，敬请期待。")

    def _on_upload(self):
        """TCP 数据上传（占位）"""
        QMessageBox.information(self, "提示", "TCP 上传功能开发中，敬请期待。")

    # ========== 打印辅助 ==========

    def _get_selected_rows(self):
        """返回勾选的数据库行"""
        result = []
        for i, cb in enumerate(self._checkboxes):
            if cb.isChecked() and i < len(self._all_rows):
                result.append(self._all_rows[i])
        return result

    def _do_print_selected(self, rows):
        """打印勾选数据：构建 HTML → 打印/导出 PDF"""
        from PySide2.QtPrintSupport import QPrinter, QPrintDialog, QPrinterInfo
        from PySide2.QtGui import QTextDocument, QFont
        from datetime import datetime

        # 从 params 读单位/化验员
        unit = ""
        tech = ""
        try:
            from db import load_params
            p = load_params()
            unit = p.get("unit", "")
            hy = p.get("hy_current", "")
            tech = hy if hy else ""
        except Exception:
            pass

        rows_html = ""
        for r in rows:
            cells = [
                r.get("name", ""),
                r.get("mode", ""),
                self._fmt(r.get("tare_weight"), 4),
                self._fmt(r.get("sample_weight"), 4),
                self._fmt(r.get("check_dry_weight"), 4),
                self._fmt(r.get("dry_weight"), 4),
                self._fmt(r.get("moisture"), 2),
                self._fmt(r.get("avg_moisture"), 2),
                self._fmt(r.get("precision_val"), 2),
            ]
            rows_html += "<tr>" + "".join("<td>%s</td>" % c for c in cells) + "</tr>"

        date_str = datetime.now().strftime("%Y/%#m/%#d")

        html = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body { font-family: "SimSun", "Microsoft YaHei", sans-serif; margin: 0; padding: 0; }
h1 { text-align: center; font-size: 22pt; font-weight: bold; margin: 0 0 12px 0; }
table.data { width: 100%; border-collapse: collapse; font-size: 9pt; }
th, td { border: 0.5px solid #CCCCCC; text-align: center; padding: 3px 4px; }
th { background-color: #F3F4F6; }
</style></head><body>
<h1>水分仪分析报表</h1>
<pre style="font-size:10pt; font-family:'SimSun','Microsoft YaHei',sans-serif; margin:0;">
测试单位：%s                    打印日期：%s</pre>
<table class="data">
<thead><tr>
<th>样品名称</th><th>模式</th><th>器皿重(g)</th><th>样品重量(g)</th>
<th>检查性干燥重(g)</th><th>干燥重量(g)</th><th>水分(%)</th>
<th>平均值(%)</th><th>精密度(%)</th>
</tr></thead>
<tbody>%s</tbody>
</table>
<pre style="font-size:10pt; font-family:'SimSun','Microsoft YaHei',sans-serif; margin:8px 0 0 0;">
化验员：%s                    审核：</pre>
</body></html>""" % (unit, date_str, rows_html, tech)

        doc = QTextDocument()
        doc.setDefaultFont(QFont("SimSun", 10))
        doc.setHtml(html)

        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPrinter.A4)
        printer.setPageMargins(15, 15, 15, 15, QPrinter.Millimeter)

        if not QPrinterInfo.availablePrinterNames():
            path, _ = QFileDialog.getSaveFileName(
                self, "导出 PDF", "水分仪分析报表", "PDF 文件 (*.pdf)"
            )
            if not path:
                return
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(path)
            doc.print_(printer)
            logger.info("[QUERY] 已导出 PDF: %s" % path)
            return

        dlg = QPrintDialog(printer, self)
        if dlg.exec_() == QPrintDialog.Accepted:
            doc.print_(printer)


# ============================================================
# 独立测试入口
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dlg = DataQueryDialog()
    dlg.exec_()
