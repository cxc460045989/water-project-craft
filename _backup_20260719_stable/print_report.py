# -*- coding: utf-8 -*-
"""水分仪分析报表打印/打印预览 - 微机全自动水分测定仪
封装为独立函数，兼容打印预览与直接打印。
"""

from PySide2.QtWidgets import QTextBrowser, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog
from PySide2.QtPrintSupport import QPrinter, QPrintPreviewDialog, QPrintDialog
from PySide2.QtCore import Qt
from PySide2.QtGui import QFont, QTextDocument, QTextOption
from datetime import datetime
import os


def _build_html(unit, data, tech, reviewer, date_str):
    rows_html = ""
    for row in data:
        rows_html += "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body {{ font-family: "SimSun", "Microsoft YaHei", "Noto Sans CJK SC", serif; margin: 0; padding: 0; }}
h1 {{ text-align: center; font-size: 22pt; font-weight: bold; margin: 0 0 12px 0; }}
table.data {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
th, td {{ border: 0.5px solid #CCCCCC; text-align: center; padding: 3px 4px; }}
th {{ background-color: #F3F4F6; }}
</style></head><body>
<h1>水分仪分析报表</h1>
<pre style="font-size:10pt; font-family:'SimSun','Microsoft YaHei',serif; margin:0;">测试单位：{unit}                    打印日期：{date_str}</pre>
<table class="data">
<thead><tr><th>样品名称</th><th>模式</th><th>坩埚重(g)</th><th>样品重量(g)</th><th>检查性干燥重量(g)</th><th>干燥重量(g)</th><th>水分(%)</th><th>平均值(%)</th><th>精密度(%)</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
<pre style="font-size:10pt; font-family:'SimSun','Microsoft YaHei',serif; margin:8px 0 0 0;">化验员：{tech}                    审核：{reviewer}</pre>
</body></html>"""


def _collect_table_data(table_widget):
    """从 QTableWidget 收集数据（跳过第 0 行坩埚数据）"""
    data = []
    for r in range(1, table_widget.rowCount()):
        name = table_widget.item(r, 0)
        if not name or not name.text().strip():
            continue
        row = []
        for c in range(table_widget.columnCount()):
            item = table_widget.item(r, c)
            txt = item.text().strip() if item else ""
            if c in (2, 3, 4):
                try:
                    txt = f"{float(txt):.4f}"
                except ValueError:
                    pass
            elif c in (5, 6, 7):
                try:
                    txt = f"{float(txt):.2f}"
                except ValueError:
                    pass
            row.append(txt)
        if any(row):
            data.append(row)
    return data


def print_report(parent, table_widget, unit="", tech="", reviewer=""):
    """直接打印（无打印机时自动转为导出 PDF）"""
    data = _collect_table_data(table_widget)
    if not data:
        return

    doc = QTextDocument()
    doc.setDefaultFont(QFont("SimSun", 10))
    html = _build_html(unit, data, tech, reviewer, datetime.now().strftime("%Y/%#m/%#d"))
    doc.setHtml(html)

    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPrinter.A4)
    printer.setPageMargins(15, 15, 15, 15, QPrinter.Millimeter)

    from PySide2.QtPrintSupport import QPrinterInfo
    if not QPrinterInfo.availablePrinterNames():
        # 无打印机 -> 导出 PDF
        path, _ = QFileDialog.getSaveFileName(
            parent, "导出 PDF", "水分仪分析报表",
            "PDF 文件 (*.pdf)"
        )
        if not path:
            return
        if not path:
            return
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        doc.print_(printer)
        return

    # 直接打印
    doc.print_(printer)


def print_report_direct(parent, table_widget, unit="", tech="", reviewer=""):
    """直接调系统打印对话框"""
    data = _collect_table_data(table_widget)
    if not data:
        return

    doc = QTextDocument()
    doc.setDefaultFont(QFont("SimSun", 10))
    html = _build_html(unit, data, tech, reviewer, datetime.now().strftime("%Y/%#m/%#d"))
    doc.setHtml(html)

    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPrinter.A4)
    printer.setPageMargins(15, 15, 15, 15, QPrinter.Millimeter)

    dlg = QPrintDialog(printer, parent)
    if dlg.exec_() == QPrintDialog.Accepted:
        doc.print_(printer)


def print_export_prompt(parent, table_widget, unit="", tech="", reviewer=""):
    """弹出打印/导出选择对话框"""
    from PySide2.QtWidgets import QDialog, QVBoxLayout, QPushButton, QFileDialog
    from PySide2.QtPrintSupport import QPrinter, QPrintDialog
    from PySide2.QtGui import QFont, QTextDocument
    from datetime import datetime

    data = _collect_table_data(table_widget)
    if not data:
        return

    doc = QTextDocument()
    doc.setDefaultFont(QFont("SimSun", 10))
    html = _build_html(unit, data, tech, reviewer, datetime.now().strftime("%Y/%#m/%#d"))
    doc.setHtml(html)

    dlg = QDialog(parent)
    dlg.setWindowTitle("打印 / 导出")
    dlg.setFixedSize(300, 200)
    dlg.setStyleSheet("""
        QDialog { background-color: #F2F4F7; }
    """)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(8)
    layout.setContentsMargins(24, 16, 24, 16)

    btn_print = QPushButton("打  印")
    btn_print.setObjectName("btnPrint")
    btn_export = QPushButton("导出 PDF")
    btn_export.setObjectName("btnExport")

    layout.addWidget(btn_print)
    layout.addWidget(btn_export)

    btn_print.clicked.connect(lambda: _do_print(doc, parent, dlg))
    btn_export.clicked.connect(lambda: _do_export_pdf(doc, parent, dlg))

    dlg.exec_()


def _do_print(doc, parent, dlg):
    dlg.accept()
    from PySide2.QtPrintSupport import QPrinter, QPrintDialog
    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPrinter.A4)
    printer.setPageMargins(15, 15, 15, 15, QPrinter.Millimeter)
    dlg_print = QPrintDialog(printer, parent)
    if dlg_print.exec_() == QPrintDialog.Accepted:
        doc.print_(printer)


def _do_export_pdf(doc, parent, dlg):
    dlg.accept()
    from PySide2.QtWidgets import QFileDialog
    from PySide2.QtPrintSupport import QPrinter
    path, _ = QFileDialog.getSaveFileName(
        parent, "导出 PDF", "水分仪分析报表", "PDF 文件 (*.pdf)")
    if not path:
        return
    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPrinter.A4)
    printer.setPageMargins(15, 15, 15, 15, QPrinter.Millimeter)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    doc.print_(printer)
