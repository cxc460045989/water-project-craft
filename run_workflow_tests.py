# -*- coding: utf-8 -*-
import sys, os, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.chdir(r"E:\ai demo\demo1\water-project\water-project")
sys.path.insert(0, ".")
from PySide2.QtWidgets import QApplication
app = QApplication(sys.argv)
from workflow_validator import TestScenario, run_all_scenarios
results = []
scenarios = [
    ("追加样品流程", TestScenario.validate_append_sample),
    ("分析水测试流程", lambda: TestScenario.validate_moisture_test_phase("analysis_water")),
]
for name, fn in scenarios:
    print()
    print("#" * 60)
    print("#  " + name)
    print("#" * 60)
    try:
        r = fn()
        results.append(r)
    except Exception as e:
        import traceback; traceback.print_exc()
        results.append({"name": name, "passed": 0, "failed": 1, "total": 1, "rate": "0%"})
tp, tf = 0, 0
for r in results:
    print("  %-20s  PASS: %d  FAIL: %d  RATE: %s" % (r["name"], r["passed"], r["failed"], r["rate"]))
    tp += r["passed"]; tf += r["failed"]
tt = tp + tf
print("  " + "-" * 50)
print("  %-20s  PASS: %d  FAIL: %d  TOTAL: %d  RATE: %.1f%%" % ("合计", tp, tf, tt, tp/tt*100 if tt else 0))
