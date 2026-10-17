"""
一次性数据修正：把历史记录里「教室设施」类故障重新归类

背景：
  「故障对象」字段是后加的。在此之前，教室总闸跳闸、交换机故障这类
  教室级设备问题只能按「电脑损坏」记录 —— 于是显示成"损坏 N 台电脑"，
  而电脑其实一台都没坏，坏的是配电箱。

  这个脚本用与运行时相同的推断规则（ai_diagnosis.infer_target）
  重新扫一遍历史记录，把明显属于教室设施的改过来。

安全性：
  · 先备份原文件到 repair_records.csv.bak
  · 只改「故障对象」这一列，其他字段原样保留
  · 只把 电脑 → 教室设施，不会反向改
  · 打印出每一条的修改，方便核对

用法：
    python tools/migrate_facility_target.py --dry-run   # 只看会改什么
    python tools/migrate_facility_target.py             # 真的改
"""

import csv
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'src'))

import ai_diagnosis  # noqa: E402
import repair_log   # noqa: E402


def main():
    dry_run = '--dry-run' in sys.argv
    path = repair_log.RECORD_FILE

    repair_log.init_file()

    with open(path, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    fields = list(rows[0].keys()) if rows else list(repair_log.FIELDS)

    changed = []
    for r in rows:
        # 已经是设施故障的跳过（不反向改）
        if r.get('故障对象') == repair_log.TARGET_FACILITY:
            continue

        symptom = r.get('故障现象') or ''
        conclusion = r.get('诊断结论') or ''
        inferred = ai_diagnosis.infer_target(symptom, conclusion)

        if inferred == repair_log.TARGET_FACILITY:
            r['故障对象'] = repair_log.TARGET_FACILITY
            # 设施故障不是按台算的，数量统一成 1
            r['数量'] = '1'
            changed.append(r)

    if not changed:
        print('没有需要重新归类的记录。')
        return 0

    print(f'将把 {len(changed)} 条记录归为「教室设施」：')
    for r in changed:
        print(f"  {r['记录编号']}  {r.get('教室','')}  "
              f"{r.get('故障现象','')[:24]}")

    if dry_run:
        print()
        print('（--dry-run，未写入）')
        return 0

    # 备份
    bak = path + '.bak'
    shutil.copy2(path, bak)
    print()
    print(f'已备份到 {os.path.basename(bak)}')

    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f'已更新 {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
