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

from filelock import file_lock

import paths

# 记录文件路径
RECORD_FILE = paths.data_file('repair_records.csv')

# 表头
# 说明：教学楼、数量、故障对象 三列是后加的，旧记录可能为空，读取时做兼容处理
FIELDS = ['记录编号', '时间', '教学楼', '教室', '故障现象', '诊断结论',
          '状态', '数量', '故障对象', '备注']

# 状态常量
#
# 三种状态对应设备的三种处境：
#   未报修  —— 硬件故障，需要报修，自己修不了（红）
#   可自修  —— 非硬件问题，可自行修复（黄）
#   已报修  —— 已联系维修，等待处理（橙）
#   已解决  —— 已完结（绿）
STATUS_PENDING = '未报修'
STATUS_SELF_FIX = '可自修'
STATUS_REPORTED = '已报修'
STATUS_RESOLVED = '已解决'

ALL_STATUS = [STATUS_PENDING, STATUS_SELF_FIX, STATUS_REPORTED, STATUS_RESOLVED]

# 历史状态名（已改名，读取时自动归一）
# 「待自修」→「可自修」：旧值仍可能存在于历史 CSV 中
LEGACY_STATUS_SELF_FIX = '待自修'

# 「未解决」= 设备当前还不能正常使用
UNRESOLVED_STATUS = [STATUS_PENDING, STATUS_SELF_FIX, STATUS_REPORTED]

# 哪些状态算「非硬件问题、可自行修复」
# AI 判断为"自己修"的故障会落到这里，不占用报修资源
SELF_FIXABLE = [STATUS_SELF_FIX]

# ---------------- 故障对象 ----------------
#
# 只分两类，不细分：
#
#   电脑     —— 个别机器坏了。数量字段表示坏了几台，
#                计入教室的「损坏台数」
#   教室设施 —— 总闸、交换机、投影、网络、空调这类教室级设备坏了。
#                它们会让整间教室不能用，但**电脑本身没坏**，
#                所以不计入损坏台数，而是单独标记「设施故障」。
#
# 为什么必须区分：
#   曾经总闸跳闸只能记成"损坏 80 台电脑" —— 电脑其实是好的，
#   坏的是配电箱。这既歪曲了设备状态，也让"损坏台数"失去意义。
TARGET_PC = '电脑'
TARGET_FACILITY = '教室设施'
ALL_TARGETS = [TARGET_PC, TARGET_FACILITY]

# 旧数据没有这一列，一律按电脑故障处理
LEGACY_TARGET = TARGET_PC


def init_file():
    """
    如果记录文件不存在，创建并写入表头。

    如果文件已存在但表头是旧版本（缺少新增的列），
    则自动迁移：把旧表头替换为新表头，旧记录补空值。

    ⚠ 整个过程必须持锁：
      这是典型的「检查-写入」竞态。多个线程同时首次调用时，
      如果都通过了 os.path.exists() 的检查，
      后到的那个会以 'w' 模式打开文件 —— 而 'w' 是**截断写**，
      把先到者刚写入的表头/记录全部清掉。
      实测 60 轮并发首次创建中有 47 轮丢数据。
    """
    with file_lock(RECORD_FILE):
        _init_file_locked()


def _init_file_locked():
    """init_file 的实际逻辑（调用方须已持锁）"""
    if not os.path.exists(RECORD_FILE):
        # 文件不存在：创建并写表头。
        # 用 'x' 模式做二次保护 —— 万一还是并发进来了，
        # 后者会拿到 FileExistsError 而不是把文件截断。
        try:
            with open(RECORD_FILE, 'x', newline='', encoding='utf-8-sig') as f:
                csv.writer(f).writerow(FIELDS)
        except FileExistsError:
            pass
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
        new_row = []
        for field in FIELDS:
            val = mapping.get(field, '')
            # 「数量」是后加的列：旧记录一律补 1（至少坏了一台），
            # 留空会让统计台数时算成 0
            if field == '数量' and not str(val).strip():
                val = '1'
            # 「故障对象」也是后加的列：旧记录按电脑故障处理
            if field == '故障对象' and not str(val).strip():
                val = LEGACY_TARGET
            new_row.append(val)
        migrated.append(new_row)

    with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f).writerows(migrated)


def load_records():
    """读取所有记录（兼容缺少「教学楼」「故障对象」等列的旧文件）"""
    init_file()
    with open(RECORD_FILE, 'r', newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    # 兼容处理：补齐可能缺失的列
    for r in rows:
        for field in FIELDS:
            r.setdefault(field, '')

        # 状态值迁移：早期版本叫「待自修」，后改名为「可自修」。
        # 旧文件里的值要就地归一，否则读出来的状态不在 ALL_STATUS 里，
        # 会落到"未知状态"分支、排序和统计都会漏掉。
        if r.get('状态') == LEGACY_STATUS_SELF_FIX:
            r['状态'] = STATUS_SELF_FIX

        # 故障对象缺失或值不认识时，按电脑故障处理
        if r.get('故障对象') not in ALL_TARGETS:
            r['故障对象'] = LEGACY_TARGET

    return rows


def get_target(record):
    """读取记录的故障对象（电脑 / 教室设施）"""
    t = (record.get('故障对象') or '').strip()
    return t if t in ALL_TARGETS else LEGACY_TARGET


def is_facility(record):
    """这条记录是不是「教室设施」故障（总闸、交换机等，电脑本身没坏）"""
    return get_target(record) == TARGET_FACILITY


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


def add_record(classroom, symptom, conclusion, status=STATUS_PENDING,
               note='', building='', quantity=1, target=TARGET_PC):
    """
    新增一条报修记录

    参数：
      classroom  - 教室号，如 "A101"
      symptom    - 故障现象
      conclusion - 诊断结论
      status     - 状态，默认"未报修"
      note       - 备注
      building   - 教学楼名称，如 "教学楼A"（可选）
      quantity   - 损坏数量，默认 1
      target     - 故障对象：TARGET_PC（电脑，默认）或 TARGET_FACILITY（教室设施）

    关于 target：
      「教室设施」指总闸、交换机、投影、网络、空调这类教室级设备。
      它们坏了会让整间教室不能用，但电脑本身没坏 ——
      因此这类记录**不计入**教室的损坏台数，而是单独标记为设施故障。
      quantity 对设施故障没有意义（不是按台算的）。

    关于 quantity：
      一台机器一个故障对应一条记录；当同一批损坏原因相同
      （如"第三排 5 台都开不了机"）时，用数量字段合并记录，
      避免重复登记 5 条，同时保证统计台数正确。

    返回：记录编号
    """
    init_file()

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1:
        quantity = 1

    # 故障对象只接受两个合法值，其他一律按电脑处理
    if target not in ALL_TARGETS:
        target = TARGET_PC

    # 设施故障不是按台算的，数量没有意义，统一记 1
    if target == TARGET_FACILITY:
        quantity = 1

    # 加锁：编号分配基于当前文件内容，
    # 并发提交时不锁会生成重复编号或丢失记录
    with file_lock(RECORD_FILE):
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
                quantity,
                target,
                note,
            ])

    return record_id


def get_quantity(record):
    """
    读取记录的损坏数量

    兼容旧记录（没有"数量"列，或为空）——一律视为 1 台。
    """
    try:
        q = int(str(record.get('数量') or '').strip())
        return q if q >= 1 else 1
    except (TypeError, ValueError):
        return 1


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

    with file_lock(RECORD_FILE):
        return _update_status_locked(record_id, new_status, note)


def _update_status_locked(record_id, new_status, note):
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

    允许改：故障现象、诊断结论、备注、教室、教学楼、数量
    （状态用 update_status，时间不允许改）

    返回：(是否成功, 提示信息)
    """
    editable = {
        '故障现象': 'symptom',
        '诊断结论': 'conclusion',
        '备注': 'note',
        '教室': 'classroom',
        '教学楼': 'building',
        '数量': 'quantity',
    }

    with file_lock(RECORD_FILE):
        return _update_record_locked(record_id, editable, fields)


def _update_record_locked(record_id, editable, fields):
    records = load_records()
    for r in records:
        if r['记录编号'] != record_id:
            continue

        for cn, en in editable.items():
            if en in fields and fields[en] is not None:
                val = str(fields[en]).strip()
                # 数量必须是不小于 1 的整数
                if cn == '数量':
                    try:
                        val = str(max(int(val), 1))
                    except (TypeError, ValueError):
                        continue
                r[cn] = val

        with open(RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records)

        return True, f'记录 {record_id} 已更新'

    return False, f'未找到记录 {record_id}'


def delete_record(record_id):
    """删除一条记录"""
    with file_lock(RECORD_FILE):
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
    STATUS_PENDING: 0,     # 未报修  —— 需要报修，最紧急
    STATUS_SELF_FIX: 1,    # 可自修  —— 可自行处理，稍缓
    STATUS_REPORTED: 2,    # 已报修  —— 等维修
    STATUS_RESOLVED: 3,    # 已解决  —— 已完结
}


def sort_records(records, by='priority'):
    """
    给记录排序

    参数：
      records - 记录列表
      by      - 排序方式
                'priority' 按状态分级（默认）：未报修 → 可自修 → 已报修 → 已解决
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


def count_machines(records, statuses=None):
    """
    统计一批记录代表的「机器台数」（累加数量字段）

    为什么要按数量累加而不是数记录条数：
      一条记录可以代表多台同因损坏的机器（如"第三排 5 台都开不了机"），
      所以台数 = 各记录数量之和，而不是记录条数。

    参数：
      records  - 记录列表
      statuses - 只统计这些状态；None 表示全部

    返回：台数
    """
    total = 0
    for r in records:
        if statuses is not None and r.get('状态') not in statuses:
            continue
        total += get_quantity(r)
    return total


# ---------------- 反复故障 ----------------

# 判定阈值
#
# REPEAT_MIN_COUNT：同一教室同一分类累计多少次算「反复」
# REPEAT_MIN_RECUR：其中「修好后又出现」多少次才标「复发」
#
# 复发门槛设得比反复高得多，是有意的：
# 标上「复发」意味着"这台机器/这间教室修了还是坏"，
# 是要求人去查根因的强信号，宁可少标，标了就要有分量。
REPEAT_MIN_COUNT = 3
REPEAT_MIN_RECUR = 4


def _days_between(first, last):
    """两个 'YYYY-MM-DD HH:MM' 之间隔了几天（不足一天算 0）"""
    from datetime import datetime

    try:
        a = datetime.strptime((first or '')[:16], '%Y-%m-%d %H:%M')
        b = datetime.strptime((last or '')[:16], '%Y-%m-%d %H:%M')
    except ValueError:
        return 0
    return max((b - a).days, 0)


def repeated_faults(min_count=None, min_recur=None):
    """
    找出「同一间教室、同一类故障反复出现」的情况

    为什么需要这个：
      同一间教室反复报同一种故障，指向的往往不是配件，而是根因 ——
      反复换内存条，可能是插槽氧化；反复报电源故障，可能是教室供电不稳。
      这类信息在逐条记录里看不出来，必须聚合。

    分类口径见 fault_category 模块（按故障现象判，不按诊断结论）。

    参数：
      min_count - 累计多少次算反复，默认 REPEAT_MIN_COUNT（3）
      min_recur - 「修好后又出现」多少次才算复发，默认 REPEAT_MIN_RECUR（4）

    返回：按次数降序的列表，每项：
      {
        'building', 'room', 'category',
        'count',        # 累计次数
        'recur',        # 修好后又出现的次数
        'recurring',    # recur 是否达到复发门槛
        'first_time', 'last_time', 'span_days',
        'record_ids',
      }
    """
    import fault_category

    min_count = REPEAT_MIN_COUNT if min_count is None else min_count
    min_recur = REPEAT_MIN_RECUR if min_recur is None else min_recur

    groups = {}
    for r in load_records():
        room = (r.get('教室') or '').strip()
        if not room or room == '未填写':
            continue
        building = (r.get('教学楼') or '').strip()
        cat = fault_category.classify(r)
        groups.setdefault((building, room, cat), []).append(r)

    out = []
    for (building, room, cat), recs in groups.items():
        if len(recs) < min_count:
            continue

        recs.sort(key=lambda x: (x.get('时间') or ''))

        # 复发：上一条记录的当前状态是「已解决」，后面又出现了新记录
        # （状态是当前值而非历史，所以这是"修好后又报"的近似判断）
        recur = 0
        for i in range(1, len(recs)):
            if (recs[i - 1].get('状态') or '') == STATUS_RESOLVED:
                recur += 1

        times = [t for t in ((x.get('时间') or '') for x in recs) if t]
        first_time = times[0] if times else ''
        last_time = times[-1] if times else ''

        out.append({
            'building': building,
            'room': room,
            'category': cat,
            'count': len(recs),
            'recur': recur,
            'recurring': recur >= min_recur,
            'first_time': first_time,
            'last_time': last_time,
            'span_days': _days_between(first_time, last_time),
            'record_ids': [x.get('记录编号') for x in recs],
        })

    out.sort(key=lambda x: (-x['count'], -x['recur'],
                            x['building'], x['room']))
    return out


def register_faults(building, classroom, causes):
    """
    批量登记同一教室的多个损坏原因

    参数：
      building  - 教学楼
      classroom - 教室
      causes    - [{'reason': '原因描述', 'quantity': 3, 'status': '未报修',
                    'target': '电脑'}, ...]
                  target 可省略，默认「电脑」

    返回：(成功条数, 记录编号列表, 错误信息)

    这个函数用于「登记故障」表单：用户在表格里一次填多行，
    每行是一个损坏原因 + 数量，提交后一次性写入台账。
    """
    if not classroom:
        return 0, [], '请选择教室'
    if not causes:
        return 0, [], '请至少填写一条故障'

    ids = []
    for item in causes:
        reason = (item.get('reason') or '').strip()
        if not reason:
            continue

        try:
            qty = int(item.get('quantity') or 1)
        except (TypeError, ValueError):
            qty = 1
        if qty < 1:
            qty = 1

        status = item.get('status') or STATUS_PENDING
        if status not in ALL_STATUS:
            status = STATUS_PENDING

        target = item.get('target') or TARGET_PC
        if target not in ALL_TARGETS:
            target = TARGET_PC

        rid = add_record(
            classroom=classroom,
            symptom=reason,
            conclusion=f'原因：{reason}',
            status=status,
            note=item.get('note', '') or '',
            building=building,
            quantity=qty,
            target=target,
        )
        ids.append(rid)

    if not ids:
        return 0, [], '请至少填写一条有效的故障描述'

    return len(ids), ids, ''


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
