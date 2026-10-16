"""
机房故障智能诊断助手 - 报修记录导出（Excel）

导出内容围绕「一眼看清现状」设计，共 5 个工作表：

  1. 故障总表        按「未报修 → 已报修 → 已解决」排序，
                     每段内按「教学楼 → 教室」分组
  2. 教室现状        每间教室有多少台能用 / 不能用
  3. 损坏明细        不能用的一一对应：机位、损坏时间、原因
  4. 故障统计        每间教室的历史故障原因与次数
  5. 未录入台账的故障 教室号对不上台账的记录（单独列出，不丢数据）

数据来源：
  · repair_records.csv  报修台账
  · classrooms.json     教室与设备台账（电脑总数）

作者：liyishuo1
"""

import csv
import io
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import classroom
import repair_log

# ---------------- 样式 ----------------

# 状态配色：未报修（红）最需要处理，已报修（黄）在等，已解决（绿）完结
STATUS_FILL = {
    repair_log.STATUS_PENDING: PatternFill('solid', fgColor='FFC7CE'),
    repair_log.STATUS_REPORTED: PatternFill('solid', fgColor='FFEB9C'),
    repair_log.STATUS_RESOLVED: PatternFill('solid', fgColor='C6EFCE'),
}

HEADER_FILL = PatternFill('solid', fgColor='4472C4')
HEADER_FONT = Font(color='FFFFFF', bold=True, size=11)
TITLE_FONT = Font(bold=True, size=13)
GROUP_FONT = Font(bold=True, size=11, color='1F4E79')

THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical='top')
CENTER = Alignment(horizontal='center', vertical='center')


# ---------------- 数据整理 ----------------

def _clean(v):
    return (v or '').strip()


def split_conclusion(text):
    """
    把「诊断结论」拆成「故障原因」和「处理结论」

    结论是 AI 按固定格式生成的：
        原因：xxx
        处理：yyy
    这里拆成两列，便于在 Excel 里分别查看和统计。
    没有该格式时，整段作为原因返回。
    """
    text = (text or '').strip()
    if not text:
        return '', ''

    reason = ''
    action = ''

    m = re.search(r'原因[:：]\s*(.+?)(?=\n\s*处理[:：]|\Z)', text, re.DOTALL)
    if m:
        reason = m.group(1).strip()

    m = re.search(r'处理[:：]\s*(.+)', text, re.DOTALL)
    if m:
        action = m.group(1).strip()

    if not reason and not action:
        reason = text   # 不规范的结论：整段当原因

    # Excel 单元格里换行会影响阅读，压成一行
    reason = re.sub(r'\s*\n\s*', ' ', reason)
    action = re.sub(r'\s*\n\s*', ' ', action)
    return reason, action


def build_room_index():
    """
    教室台账索引

    返回：
      by_key    {(教学楼, 教室): 教室信息}
      by_name   {教室: [教室信息, ...]}   用于教室号能对上、但记录缺教学楼时补全
      rooms     全部教室列表（保持台账顺序）
    """
    by_key = {}
    by_name = defaultdict(list)
    rooms = []

    for r in classroom.flat_rooms():
        by_key[(r['building'], r['name'])] = r
        by_name[r['name']].append(r)
        rooms.append(r)

    return by_key, by_name, rooms


def normalize_records():
    """
    读取报修记录，并补全「教学楼」

    补全规则：若记录的教学楼为空，但教室号能在台账里唯一匹配到，
    则自动补上所在教学楼 —— 这样导出的表格才能按楼栋正确分组。
    """
    by_key, by_name, _ = build_room_index()
    out = []

    for r in repair_log.load_records():
        building = _clean(r.get('教学楼'))
        room = _clean(r.get('教室'))
        status = _clean(r.get('状态')) or repair_log.STATUS_PENDING
        time = _clean(r.get('时间'))
        symptom = _clean(r.get('故障现象'))
        note = _clean(r.get('备注'))
        reason, action = split_conclusion(r.get('诊断结论'))

        # 尝试补全教学楼
        matched = None
        if building and (building, room) in by_key:
            matched = by_key[(building, room)]
        elif room in by_name and len(by_name[room]) == 1:
            matched = by_name[room][0]
            if not building:
                building = matched['building']

        out.append({
            'id': _clean(r.get('记录编号')),
            'time': time,
            'building': building or '未标注教学楼',
            'room': room or '未填写',
            'symptom': symptom,
            'reason': reason,
            'action': action,
            'status': status,
            'note': note,
            'in_ledger': matched is not None,
            'matched': matched,
        })

    return out


def group_by_room(records):
    """按 (教学楼, 教室) 归组"""
    groups = defaultdict(list)
    for r in records:
        groups[(r['building'], r['room'])].append(r)
    return groups


def room_history(records):
    """
    统计每间教室的历史故障

    返回：{(教学楼, 教室): {...}}
      total       故障总次数
      pending / reported / resolved  各状态次数
      unresolved  未解决次数（未报修 + 已报修）
      causes      原因计数
      machines    有记录的机位/记录编号集合（用于去重统计"多少台不能用"）
    """
    info = {}

    for r in records:
        key = (r['building'], r['room'])
        d = info.setdefault(key, {
            'total': 0,
            'pending': 0,
            'reported': 0,
            'resolved': 0,
            'unresolved': 0,
            'causes': Counter(),
            'unresolved_ids': [],
            'all_ids': [],
        })

        d['total'] += 1
        d['all_ids'].append(r['id'])

        if r['status'] == repair_log.STATUS_PENDING:
            d['pending'] += 1
        elif r['status'] == repair_log.STATUS_REPORTED:
            d['reported'] += 1
        elif r['status'] == repair_log.STATUS_RESOLVED:
            d['resolved'] += 1

        if r['status'] != repair_log.STATUS_RESOLVED:
            d['unresolved'] += 1
            d['unresolved_ids'].append(r['id'])

        if r['reason']:
            d['causes'][r['reason'][:40]] += 1

    return info


# ---------------- 排序 ----------------

# 状态排序优先级：越需要处理越靠前
STATUS_ORDER = {
    repair_log.STATUS_PENDING: 0,
    repair_log.STATUS_REPORTED: 1,
    repair_log.STATUS_RESOLVED: 2,
}


def sort_key(r):
    """排序：状态 → 教学楼 → 教室 → 时间"""
    return (
        STATUS_ORDER.get(r['status'], 9),
        r['building'],
        r['room'],
        r['time'],
    )


# ---------------- 工作表写入 ----------------

def _write_header(ws, headers, widths=None):
    ws.append(headers)
    for i, _ in enumerate(headers, 1):
        c = ws.cell(row=ws.max_row, column=i)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = CENTER
        c.border = BORDER
    if widths:
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'


def sheet_overview(wb, records):
    """Sheet 1：故障总表（按状态 → 教学楼 → 教室 排序）"""
    ws = wb.create_sheet('故障总表')
    widths = [10, 14, 12, 10, 18, 30, 40, 40, 18]
    _write_header(
        ws,
        ['状态', '教学楼', '教室', '记录编号', '损坏时间',
         '故障现象', '故障原因', '处理结论', '备注'],
        widths,
    )

    ordered = sorted(records, key=sort_key)
    current_status = None

    for r in ordered:
        # 状态变化时插入分组标题，便于快速定位
        if r['status'] != current_status:
            current_status = r['status']
            count = sum(1 for x in ordered if x['status'] == current_status)
            ws.append([f'▼ {current_status}（{count} 条）'])
            ws.merge_cells(
                start_row=ws.max_row, start_column=1,
                end_row=ws.max_row, end_column=len(widths),
            )
            c = ws.cell(row=ws.max_row, column=1)
            c.font = GROUP_FONT
            c.fill = PatternFill('solid', fgColor='D9E2F3')

        ws.append([
            r['status'], r['building'], r['room'], r['id'], r['time'],
            r['symptom'], r['reason'], r['action'], r['note'],
        ])

        row = ws.max_row
        for i in range(1, len(widths) + 1):
            cell = ws.cell(row=row, column=i)
            cell.border = BORDER
            cell.alignment = WRAP
        ws.cell(row=row, column=1).fill = STATUS_FILL.get(r['status'], PatternFill())
        ws.cell(row=row, column=1).alignment = CENTER

    return ws


def sheet_current_status(wb, records):
    """
    Sheet 2：教室现状

    「不能用台数」按机器去重：
      同一间教室若同一机位有多次损坏记录，只算一台不能用，
      并在备注里说明历史损坏次数 —— 避免把同一台机器重复计数。
    """
    ws = wb.create_sheet('教室现状')
    widths = [14, 12, 10, 10, 12, 10, 46]
    _write_header(
        ws,
        ['教学楼', '教室', '电脑总数', '可用台数', '不能用台数',
         '损坏率', '备注'],
        widths,
    )

    _, _, rooms = build_room_index()
    hist = room_history(records)

    # 台账里的教室 + 记录里出现过的教室，合并展示
    seen = set()
    rows = []

    for room in rooms:
        key = (room['building'], room['name'])
        seen.add(key)
        rows.append((room['building'], room['name'], room.get('total', 0), key))

    for key in hist:
        # 「未填写」不是真实教室，不应出现在教室现状里
        # （它会在「未录入台账的故障」页单独说明）
        if key[1] == '未填写':
            continue
        if key not in seen:
            rows.append((key[0], key[1], 0, key))

    rows.sort(key=lambda x: (x[0], x[1]))

    totals = {'total': 0, 'free': 0, 'broken': 0}

    for building, name, total, key in rows:
        h = hist.get(key, {})
        unresolved = h.get('unresolved', 0)
        solved = h.get('resolved', 0)
        total_faults = h.get('total', 0)

        # 不能用台数 = 未解决的记录数（一台机器一条未解决记录）
        broken = unresolved
        # 台账手工登记的损坏数也算进去
        _, by_key2, _ = build_room_index()
        manual = by_key2.get(key, {}).get('broken', 0)
        broken_total = max(broken, manual) if manual else broken

        free = max(total - broken_total, 0) if total else 0
        rate = f'{broken_total / total * 100:.1f}%' if total else '—'

        notes = []
        if total == 0:
            notes.append('台账未登记电脑总数')
        if total_faults:
            parts = []
            if unresolved:
                parts.append(f'未解决 {unresolved} 条')
            if solved:
                parts.append(f'已解决 {solved} 条')
            notes.append(f'历史故障 {total_faults} 次（{"，".join(parts)}）')
        if h.get('causes'):
            top = h['causes'].most_common(1)[0][0]
            notes.append(f'主要故障：{top}')
        if total and broken_total > total:
            notes.append('⚠ 损坏数超过总数，请核对台账')
        if manual:
            notes.append(f'含手工登记损坏 {manual} 台')

        ws.append([
            building, name,
            total if total else '—',
            free if total else '—',
            broken_total,
            rate,
            '；'.join(notes),
        ])

        row = ws.max_row
        for i in range(1, len(widths) + 1):
            cell = ws.cell(row=row, column=i)
            cell.border = BORDER
            cell.alignment = WRAP if i == 7 else CENTER
        if broken_total:
            ws.cell(row=row, column=5).fill = STATUS_FILL[repair_log.STATUS_PENDING]

        totals['total'] += total
        totals['free'] += free if total else 0
        totals['broken'] += broken_total

    # 合计行
    ws.append([])
    ws.append(['合计', f'{len(rows)} 间', totals['total'],
               totals['free'], totals['broken'], '', ''])
    for i in range(1, 8):
        c = ws.cell(row=ws.max_row, column=i)
        c.font = Font(bold=True)
        c.border = BORDER
        c.alignment = CENTER

    return ws


def sheet_damage_detail(wb, records):
    """
    Sheet 3：损坏明细

    只列「未解决」的记录 —— 也就是当前不能用的机器，
    每台一行，损坏时间与原因一一对应。
    """
    ws = wb.create_sheet('损坏明细')
    widths = [14, 12, 10, 18, 46, 12, 22]
    _write_header(
        ws,
        ['教学楼', '教室', '记录编号', '损坏时间', '故障原因',
         '状态', '备注'],
        widths,
    )

    broken = [r for r in records if r['status'] != repair_log.STATUS_RESOLVED]

    if not broken:
        ws.append(['（当前没有未解决的故障）'])
        return ws

    # 按教室归组，同教室的机器排在一起
    groups = group_by_room(broken)
    for key in sorted(groups):
        items = sorted(groups[key], key=lambda r: r['time'])
        for r in items:
            ws.append([
                r['building'], r['room'], r['id'], r['time'],
                r['reason'] or r['symptom'], r['status'], r['note'],
            ])
            row = ws.max_row
            for i in range(1, len(widths) + 1):
                cell = ws.cell(row=row, column=i)
                cell.border = BORDER
                cell.alignment = WRAP
            ws.cell(row=row, column=6).fill = STATUS_FILL.get(
                r['status'], PatternFill())
            ws.cell(row=row, column=6).alignment = CENTER

    return ws


def sheet_statistics(wb, records):
    """Sheet 4：故障统计（每间教室的历史故障原因与次数）"""
    ws = wb.create_sheet('故障统计')
    widths = [14, 12, 12, 10, 10, 10, 50, 40]
    _write_header(
        ws,
        ['教学楼', '教室', '故障总次数', '未解决', '已报修', '已解决',
         '主要原因分布', '备注'],
        widths,
    )

    hist = room_history(records)
    if not hist:
        ws.append(['（暂无故障记录）'])
        return ws

    rows = sorted(hist.items(), key=lambda kv: (-kv[1]['total'], kv[0]))

    for (building, room), h in rows:
        causes = '；'.join(
            f'{c}×{n}' for c, n in h['causes'].most_common(5)
        ) or '—'

        note_parts = []
        if h['resolved']:
            note_parts.append(f'已修复 {h["resolved"]} 次')
        if h['unresolved']:
            note_parts.append(f'待处理 {h["unresolved"]} 次')
        if h['total'] > 1:
            note_parts.append('该教室多次出现故障，建议排查根源')

        ws.append([
            building, room, h['total'], h['unresolved'],
            h['reported'], h['resolved'], causes, '；'.join(note_parts),
        ])
        row = ws.max_row
        for i in range(1, len(widths) + 1):
            cell = ws.cell(row=row, column=i)
            cell.border = BORDER
            cell.alignment = WRAP if i in (7, 8) else CENTER

    return ws


def sheet_unlinked(wb, records):
    """
    Sheet 5：未录入台账的故障

    教室号对不上教室台账的记录单独列出。
    这些数据不能丢 —— 它们是真实发生过的故障，
    只是还没在「教室管理」里登记对应教室。
    """
    ws = wb.create_sheet('未录入台账的故障')
    widths = [14, 16, 10, 18, 30, 40, 12]
    _write_header(
        ws,
        ['教学楼', '教室', '记录编号', '损坏时间', '故障现象',
         '故障原因', '状态'],
        widths,
    )

    orphans = [r for r in records if not r['in_ledger']]

    if not orphans:
        ws.append(['（所有故障记录都已对应到教室台账）'])
        return ws

    for r in sorted(orphans, key=sort_key):
        ws.append([
            r['building'], r['room'], r['id'], r['time'],
            r['symptom'], r['reason'] or r['symptom'], r['status'],
        ])
        row = ws.max_row
        for i in range(1, len(widths) + 1):
            cell = ws.cell(row=row, column=i)
            cell.border = BORDER
            cell.alignment = WRAP
        ws.cell(row=row, column=7).fill = STATUS_FILL.get(r['status'], PatternFill())
        ws.cell(row=row, column=7).alignment = CENTER

    ws.append([])
    ws.append([f'以上 {len(orphans)} 条记录的教室未在「教室管理」中登记，'
               f'建议补录后再导出，以便纳入教室维度的统计。'])
    return ws


# ---------------- 对外接口 ----------------

def export_to_bytes():
    """
    生成 Excel 并返回字节内容（供 Web 下载使用）

    返回：(文件名, bytes)
    """
    records = normalize_records()

    wb = Workbook()
    wb.remove(wb.active)      # 去掉默认空表

    sheet_overview(wb, records)
    sheet_current_status(wb, records)
    sheet_damage_detail(wb, records)
    sheet_statistics(wb, records)
    sheet_unlinked(wb, records)

    # 首页放一张"总览"作为第一个表
    ws = wb.create_sheet('总览', 0)
    _fill_summary(ws, records)

    buf = io.BytesIO()
    wb.save(buf)

    stamp = datetime.now().strftime('%Y-%m-%d_%H%M')
    filename = f'机房故障报表_{stamp}.xlsx'
    return filename, buf.getvalue()


def _fill_summary(ws, records):
    """总览页：把关键数字放在最前面"""
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 18
    ws.column_dimensions['C'].width = 46

    ws.append(['机房故障报表'])
    ws['A1'].font = Font(bold=True, size=16)
    ws.append([f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}'])
    ws.append([])

    total = len(records)
    by_status = Counter(r['status'] for r in records)
    unresolved = total - by_status.get(repair_log.STATUS_RESOLVED, 0)

    _, _, rooms = build_room_index()
    total_pcs = sum(r.get('total', 0) for r in rooms)
    hist = room_history(records)

    # 真实教室数（排除「未填写」这类占位值）
    real_rooms = [k for k in hist if k[1] != '未填写']

    ws.append(['项目', '数值', '说明'])
    for i in range(1, 4):
        c = ws.cell(row=ws.max_row, column=i)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = CENTER

    rows = [
        ('故障记录总数', total, '报修台账中的全部记录'),
        ('未报修', by_status.get(repair_log.STATUS_PENDING, 0), '需要立即处理'),
        ('已报修', by_status.get(repair_log.STATUS_REPORTED, 0), '已联系维修，等待处理'),
        ('已解决', by_status.get(repair_log.STATUS_RESOLVED, 0), '已完结'),
        ('待处理合计', unresolved, '未报修 + 已报修'),
        ('涉及教室数', len(real_rooms), '有故障记录的教室（不含"未填写"）'),
        ('台账教室数', len(rooms), '已在「教室管理」登记的教室'),
        ('台账电脑总数', total_pcs, '各教室登记的总台数之和'),
    ]

    for name, val, desc in rows:
        ws.append([name, val, desc])
        for i in range(1, 4):
            ws.cell(row=ws.max_row, column=i).border = BORDER
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

    ws.append([])
    ws.append(['工作表说明'])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=12)

    sheets = [
        ('故障总表', '按「未报修 → 已报修 → 已解决」排序，组内按教学楼、教室分组'),
        ('教室现状', '每间教室有多少台能用 / 不能用，含损坏率'),
        ('损坏明细', '当前不能用的机器，逐台对应损坏时间与原因'),
        ('故障统计', '每间教室的历史故障原因与次数'),
        ('未录入台账的故障', '教室号对不上台账的记录（不丢失）'),
    ]
    for name, desc in sheets:
        ws.append([name, '', desc])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        for i in range(1, 4):
            ws.cell(row=ws.max_row, column=i).border = BORDER


def export_to_file(path=None):
    """
    生成 Excel 并写到文件

    参数：path - 目标路径；省略时写到项目根目录下的 exports/
    返回：实际写入的路径
    """
    filename, data = export_to_bytes()

    if path is None:
        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'exports',
        )
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, filename)

    with open(path, 'wb') as f:
        f.write(data)

    return path


# 命令行入口
if __name__ == '__main__':
    import sys

    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    p = export_to_file()
    print(f'已导出：{p}')

    recs = normalize_records()
    print(f'  记录 {len(recs)} 条')
    for r in recs:
        tag = '' if r['in_ledger'] else '  [未录入台账]'
        print(f"    {r['status']:<4} {r['building']} / {r['room']:<14} {r['id']}{tag}")
