# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn
import datetime, random

conn = get_conn()
conn.execute("DELETE FROM experiment_results WHERE batch_no LIKE 'MOCK_%'")
conn.commit()

today = datetime.date.today()
names_aw = ['煤样-A1', '煤样-A2', '煤样-A3', '焦炭-B1']
names_tw = ['原煤-T1', '原煤-T2', '褐煤-L1']
rows = []
row_id = 0

for days_ago in range(0, 5):
    test_date = today - datetime.timedelta(days=days_ago)
    batch_no = 'MOCK_%s_%02d' % (test_date.strftime('%Y%m%d'), days_ago + 1)

    for _mode, _names, lo_s, hi_s, lo_m, hi_m in [
        ('分析水', names_aw, 0.90, 1.10, 0.05, 0.12),
        ('全水',   names_tw, 9.00, 11.50, 0.06, 0.15),
    ]:
        cnt = random.choice([2, 3])
        samples = random.sample(_names, min(cnt, len(_names)))
        weights = []
        for name in samples:
            tare = round(random.uniform(24.5000, 26.5000), 4)
            sample = round(random.uniform(lo_s, hi_s), 4)
            dry = round(sample * (1 - random.uniform(lo_m, hi_m)), 4)
            moisture = round((sample - dry) / sample * 100, 2)
            weights.append(moisture)
            row_id += 1
            rows.append((-1, test_date.strftime('%Y-%m-%d'), batch_no, str(row_id),
                         name, _mode, tare, sample, dry, dry, moisture,
                         None, None, 105, 60, 105, 60, '测试单位', '测试员'))
        if weights:
            avg_m = round(sum(weights) / len(weights), 2)
            prec = round(max(weights) - min(weights), 2) if len(weights) >= 2 else 0.0
            for i in range(len(rows) - len(weights), len(rows)):
                r = list(rows[i]); r[11] = avg_m; r[12] = prec; rows[i] = tuple(r)

conn.executemany('INSERT INTO experiment_results ("实验ID", "试验日期", "批次号", "器皿位号", "样品名", "模式", "器皿重", "样重", "检查性干燥重", "干燥后重", "水分", "平均水分", "精密度", "分析水温度", "分析水时间", "全水温度", "全水时间", "测试单位", "化验员") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
conn.commit()
count = conn.execute("SELECT COUNT(*) FROM experiment_results WHERE batch_no LIKE 'MOCK_%'").fetchone()[0]
conn.close()
print('已插入 %d 条 mock 数据 (日期: %s ~ %s)' % (count, (today - datetime.timedelta(days=4)).strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')))
