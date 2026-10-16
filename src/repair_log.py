"""
机房故障智能诊断助手 - 报修记录模块

功能：
  1. 把需要报修的故障记录到 CSV 文件
  2. 支持查看历史记录
  3. 支持修改记录状态（未报修 / 已报修 / 已解决）

作者：liyishuo1
"""

import csv
import os
from datetime import datetime

# 记录文件路径
RECORD_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'repair_records.csv')

# 表头
# 说明：教学楼 列是后加的，旧记录的该列可能为空，读取时做兼容处理
FIELDS = ['记录编号', '时间', '教学楼', '教室', '故障现象', '诊断结论', '状态', '备注']

# 状态常量
STATUS_PENDING = '未报修'
STATUS_REPORTED = '已报修'
STATUS_RESOLVED = '已解决'

ALL_STATUS = [STATUS_PENDING, STATUS_REPORTED, STATUS_RESOLVED]


def init_file():
    """
    如果记录文件不存在，创建并写入表头。

    如果文件已存在但表头是旧版本（缺少新增的列），
    则自动迁移：把旧表头替换为新表头，旧记录补空值。
    """
    if not os.path.exists(RECORD_FILE):
        with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow(FIELDS)
        return

    # 检查表头是否需要迁移
    try:
        with open(RECORD_FILE, 'r', newline='', encoding='utf-8-sig') as f:
            rows = list(csv.reader(f))
    except Exception:
        return

    if not rows:
        with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow(FIELDS)
        return

    header = rows[0]
    if header == FIELDS:
        return  # 已是最新，无需处理

    # 按旧表头重建：逐列映射到新字段，缺失的补空
    migrated = [FIELDS]
    for old_row in rows[1:]:
        mapping = dict(zip(header, old_row))
        migrated.append([mapping.get(field, '') for field in FIELDS])

    with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f).writerows(migrated)


def load_records():
    """读取所有记录（兼容缺少「教学楼」列的旧文件）"""
    init_file()
    with open(RECORD_FILE, 'r', newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    # 兼容处理：补齐可能缺失的列
    for r in rows:
        for field in FIELDS:
            r.setdefault(field, '')
    return rows


def next_id():
    """生成下一个记录编号"""
    records = load_records()
    if not records:
        return 'R001'
    # 取最后一个编号，加 1
    last = records[-1]['记录编号']
    try:
        num = int(last[1:]) + 1
    except ValueError:
        num = len(records) + 1
    return f'R{num:03d}'


def add_record(classroom, symptom, conclusion, status=STATUS_PENDING, note='', building=''):
    """
    新增一条报修记录

    参数：
      classroom  - 教室号，如 "A101"
      symptom    - 故障现象
      conclusion - 诊断结论
      status     - 状态，默认"未报修"
      note       - 备注
      building   - 教学楼名称，如 "教学楼A"（可选）

    返回：记录编号
    """
    init_file()
    record_id = next_id()

    with open(RECORD_FILE, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow([
            record_id,
            datetime.now().strftime('%Y-%m-%d %H:%M'),
            building or '',
            classroom,
            symptom,
            conclusion,
            status,
            note,
        ])

    return record_id


def update_status(record_id, new_status, note=''):
    """
    修改某条记录的状态

    参数：
      record_id  - 记录编号，如 "R001"
      new_status - 新状态（未报修/已报修/已解决）
      note       - 追加的备注

    返回：(是否成功, 提示信息)
    """
    if new_status not in ALL_STATUS:
        return False, f"状态必须是：{'/'.join(ALL_STATUS)}"

    records = load_records()
    found = False

    for r in records:
        if r['记录编号'] == record_id:
            r['状态'] = new_status
            if note:
                old_note = r.get('备注', '')
                r['备注'] = (old_note + '; ' + note).strip('; ') if old_note else note
            found = True
            break

    if not found:
        return False, f"未找到记录 {record_id}"

    # 写回
    with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    return True, f"记录 {record_id} 已更新为「{new_status}」"


def update_record(record_id, **fields):
    """
    修改记录的任意字段

    允许改：故障现象、诊断结论、备注、教室、教学楼
    （状态用 update_status，时间不允许改）

    返回：(是否成功, 提示信息)
    """
    editable = {
        '故障现象': 'symptom',
        '诊断结论': 'conclusion',
        '备注': 'note',
        '教室': 'classroom',
        '教学楼': 'building',
    }

    records = load_records()
    for r in records:
        if r['记录编号'] != record_id:
            continue

        for cn, en in editable.items():
            if en in fields and fields[en] is not None:
                r[cn] = str(fields[en]).strip()

        with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records)

        return True, f'记录 {record_id} 已更新'

    return False, f'未找到记录 {record_id}'


def delete_record(record_id):
    """删除一条记录"""
    records = load_records()
    kept = [r for r in records if r['记录编号'] != record_id]

    if len(kept) == len(records):
        return False, f'未找到记录 {record_id}'

    with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(kept)

    return True, f'记录 {record_id} 已删除'


# 状态的展示优先级：数字越小越靠前
#   越需要处理的状态排越前，已完成的沉到底部
STATUS_ORDER = {
    STATUS_PENDING: 0,    # 未报修  —— 最需要处理
    STATUS_REPORTED: 1,   # 已报修  —— 等维修
    STATUS_RESOLVED: 2,   # 已解决  —— 已完结
}


def sort_records(records, by='priority'):
    """
    给记录排序

    参数：
      records - 记录列表
      by      - 排序方式
                'priority' 按状态分级（默认）：未报修 → 已报修 → 已解决
                           同状态内按时间倒序（最新的在前）
                'time'     纯按时间倒序

    返回：排序后的新列表
    """
    if by == 'time':
        return sorted(records, key=lambda r: r.get('时间', ''), reverse=True)

    def key(r):
        # 未知状态排在最后
        order = STATUS_ORDER.get(r.get('状态', ''), 9)
        # 时间倒序：取负值实现"新的在前"
        return (order, _neg_time(r.get('时间', '')))

    return sorted(records, key=key)


def _neg_time(t):
    """
    把时间字符串转成可比较的数值（越大表示越新）
    用于在升序排序中实现"新的在前"
    """
    # "2026-10-16 11:55" → 202610161155
    digits = ''.join(ch for ch in (t or '') if ch.isdigit())
    try:
        return -int(digits) if digits else 0
    except ValueError:
        return 0


def show_records(status_filter=None):
    """打印记录列表"""
    records = load_records()

    if not records:
        print("（暂无报修记录）")
        return

    if status_filter:
        records = [r for r in records if r['状态'] == status_filter]

    if not records:
        print(f"（没有状态为「{status_filter}」的记录）")
        return

    print()
    print(f"{'编号':<7}{'时间':<18}{'教室':<8}{'状态':<8}故障现象")
    print('-' * 70)
    for r in records:
        symptom = r['故障现象']
        if len(symptom) > 28:
            symptom = symptom[:28] + '...'
        print(f"{r['记录编号']:<7}{r['时间']:<18}{r['教室']:<8}{r['状态']:<8}{symptom}")
    print()
    print(f"共 {len(records)} 条记录")


def show_detail(record_id):
    """显示某条记录的详情"""
    records = load_records()
    for r in records:
        if r['记录编号'] == record_id:
            print()
            print('=' * 55)
            for field in FIELDS:
                print(f"{field}：{r[field]}")
            print('=' * 55)
            return True
    print(f"未找到记录 {record_id}")
    return False


# 测试
if __name__ == '__main__':
    print("报修记录模块测试")
    print()

    rid = add_record('107', '电脑开机没反应', '电源供应器故障，需更换')
    print(f"✅ 新增记录：{rid}")

    rid2 = add_record('203', '整间教室断网', '交换机上联中断，需网络中心处理')
    print(f"✅ 新增记录：{rid2}")

    print()
    show_records()

    print()
    ok, msg = update_status(rid, STATUS_REPORTED, '已电话联系维修')
    print(f"{'✅' if ok else '❌'} {msg}")

    print()
    show_detail(rid)
