"""
机房故障智能诊断助手 - 报修记录导出（Excel）

设计目标：**给领导看的一页纸**
  领导不关心修没修，只关心「现在有多少台能用」。
  因此导出只有一张表，一间教室一行，一眼看出每间教室的现状。

表格结构（按教学楼分组，同一教学楼只显示一次）：

    ┌────────┬───────┬────────┬──────┬──────┬──────────────────┐
    │ 教学楼  │ 教室   │ 设备总数 │ 正常 │ 损坏 │ 损坏原因          │
    ├────────┼───────┼────────┼──────┼──────┼──────────────────┤
    │        │ 101   │   80   │  77  │   3  │ 电源损坏 ×3       │
    │ 实验楼A │───────┼────────┼──────┼──────┼──────────────────┤
    │        │ 102   │   80   │  80  │   0  │ —                │
    └────────┴───────┴────────┴──────┴──────┴──────────────────┘

状态归类（关键约定）：
  · 未报修 / 可自修 / 已报修  →  损坏
  · 已解决                   →  正常
  这样「正常 + 损坏 = 设备总数」，领导一眼能对上账。

数据来源：
  · repair_records.csv  报修台账（损坏台数与原因）
  · classrooms.json     教室台账（设备总数）

作者：liyishuo1
"""

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

# 表头：深蓝底白字，稳重（给领导看的报表不用花哨配色）
HEADER_FILL = PatternFill('solid', fgColor='2F5597')
HEADER_FONT = Font(color='FFFFFF', bold=True, size=12)

# 教学楼列：浅蓝底，作为分组标识
BUILDING_FILL = PatternFill('solid', fgColor='D9E2F3')
BUILDING_FONT = Font(bold=True, size=14, color='1F3864')

# 标题
TITLE_FONT = Font(bold=True, size=18, color='1F3864')
SUBTITLE_FONT = Font(size=10, color='808080')

# 行配色：完好的教室淡绿，有损坏的正常白底（让问题行更显眼）
OK_FILL = PatternFill('solid', fgColor='E2EFDA')
BAD_FILL = PatternFill('solid', fgColor='FCE4E4')

# 数字字体
NUM_FONT = Font(size=12)
BROKEN_FONT = Font(size=12, bold=True, color='C00000')
OK_NUM_FONT = Font(size=12, bold=True, color='375623')

MEDIUM = Side(style='medium', color='8EA9DB')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
LEFT_TOP = Alignment(horizontal='left', vertical='center', wrap_text=True)

# 列宽（字符数）
#
# 「损坏时间」放在损坏之后、原因之前：
# 领导看一行时，先看坏了几台，再看什么时候坏的，最后看为什么坏。
COLS = [
    ('教学楼', 14),
    ('教室', 11),
    ('设备总数', 11),
    ('正常', 8),
    ('损坏', 8),
    ('损坏时间', 18),
    ('损坏原因', 38),
    ('教室设施故障', 22),
]
NCOL = len(COLS)
LAST_COL = get_column_letter(NCOL)


# ---------------- 数据整理 ----------------

def _clean(v):
    return (v or '').strip()


def split_conclusion(text):
    """
    把「诊断结论」拆成「故障原因」和「处理结论」

    结论是 AI 按固定格式生成的：
        原因：xxx
        处理：yyy
    导出时只取「原因」部分，因为领导关心的是"为什么坏"。
    """
    text = (text or '').strip()
    if not text:
        return '', ''

    reason = ''
    action = ''

    m = re.search(r'原因[:：]\s*(.+?)(?=\n\s*数量[:：]|\n\s*处理[:：]|\Z)',
                  text, re.DOTALL)
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


def _shorten_reason(reason, limit=18):
    """
    把 AI 的长句原因压缩成领导一眼能懂的短语

    AI 生成的原因往往是完整的排查叙述，例如：
        「多台电脑按开机键无反应、指示灯不亮，排查电源线与插座后仍无效，
          判断为机箱电源或供电线路故障」
    放在汇总表里太长，也会把表格撑得很难看。

    处理策略（按优先级）：
      1. 优先取「判断为 / 是 / 属于」之后的核心结论 —— 那才是真正的故障
      2. 否则取最后一个分句（中文里结论通常在后半句）
      3. 再去掉修饰词，控制长度
    """
    r = (reason or '').strip()
    if not r:
        return ''

    # 去掉「原因：」前缀和句末标点
    r = re.sub(r'^原因[:：]\s*', '', r)
    r = re.sub(r'[。；;，,]+$', '', r)

    # 括号内的补充说明对领导是噪音，去掉
    r = re.sub(r'（[^）]*）', '', r)
    r = re.sub(r'\([^)]*\)', '', r)

    # 1) 取结论性短语：「判断为 xxx」「认定为 xxx」
    #    注意：不能用单独的「是」——它会匹配到「本身故障」「仍是」这类词内部
    m = re.search(r'(?:判断为|判断是|认定为|确认为|属于)\s*([^，,。；;]{2,20})', r)
    if m:
        core = m.group(1).strip()
        if len(core) >= 2:
            r = core
    else:
        # 2) 没有结论标记时，取第一个分句
        #    中文故障描述的写法是「<部件>损坏/故障，<后果>」，
        #    所以第一个分句才是故障本身，后面是影响
        parts = [p.strip() for p in re.split(r'[，,]', r) if p.strip()]
        if parts:
            r = parts[0]

    # 3) 修饰词精简：去掉冗长的前缀和无关主语
    r = re.sub(r'^(多台|该|这台|这台电脑|该电脑|电脑的?|机箱的?|教室的?)', '', r)

    # 去掉「导致…」「使得…」开头的后果描述（这些不是原因本身）
    r = re.sub(r'^(导致|使得|造成|引起)', '', r)

    r = r.strip()
    if len(r) > limit:
        r = r[:limit] + '…'
    return r


def build_rows():
    """
    组装导出的每一行数据

    返回：[(教学楼, 教室, 总数, 正常数, 损坏数, 原因列表), ...]

    规则：
      1. 以教室台账为准，每间教室一行
      2. 损坏 = 未报修 + 可自修 + 已报修（按数量累加）
      3. 已解决算正常
      4. 台账里没有、但故障记录里出现过的教室，也列出（标为未登记）
      5. 教室号对不上任何台账的记录，归入「未登记教室」分组，不丢数据
    """
    _, _, rooms = build_room_index()

    # 按 (教学楼, 教室) 汇总故障记录
    #
    # causes 记电脑损坏原因；facilities 记教室设施故障（总闸、交换机等）。
    # 两者必须分开：设施故障会让整间教室不能用，但一台电脑都没坏，
    # 算进"损坏台数"会得出"损坏 80 台"这种错误数字。
    stats = defaultdict(lambda: {
        'broken': 0,
        'causes': Counter(),
        'facilities': [],
        'times': [],
    })

    for rec in repair_log.load_records():
        building = _clean(rec.get('教学楼'))
        room = _clean(rec.get('教室'))
        status = _clean(rec.get('状态')) or repair_log.STATUS_PENDING
        if not room or room == '未填写':
            continue

        # 已解决 → 算正常，不计入损坏
        if status == repair_log.STATUS_RESOLVED:
            continue

        reason, _ = split_conclusion(rec.get('诊断结论'))
        key = (building, room)

        # 教室设施故障：单独记录，不计入电脑台数
        if repair_log.is_facility(rec):
            label = _shorten_reason(reason) if reason else _clean(
                rec.get('故障现象')) or '教室设施故障'
            stats[key]['facilities'].append(label)
            t = _clean(rec.get('时间'))
            if t:
                stats[key]['times'].append(t)
            continue

        qty = repair_log.get_quantity(rec)

        stats[key]['broken'] += qty
        if reason:
            stats[key]['causes'][_shorten_reason(reason)] += qty

        # 损坏时间：取最早的一条未解决记录（问题是什么时候开始出现的）
        t = _clean(rec.get('时间'))
        if t:
            stats[key]['times'].append(t)

    # 教室台账索引
    ledger = {(r['building'], r['name']): r for r in rooms}

    def earliest_time(st):
        """该教室最早的一条未解决故障时间（只显示到分钟）"""
        times = [t for t in st.get('times', []) if t]
        return min(times) if times else ''

    def facility_text(st):
        """把设施故障汇总成一句话"""
        facs = st.get('facilities') or []
        if not facs:
            return ''
        # 去重并计数，避免同一故障重复时列一堆
        cnt = Counter(facs)
        parts = [f'{k}' + (f' ×{v}' if v > 1 else '') for k, v in cnt.items()]
        return '；'.join(parts)

    # 组装行：先排台账里的教室（按教学楼 → 教室），再补记录里多出来的
    rows = []
    used = set()

    for r in rooms:
        key = (r['building'], r['name'])
        used.add(key)
        total = r.get('total', 0)
        st = stats.get(key, {'broken': 0, 'causes': Counter(),
                             'facilities': [], 'times': []})
        broken = st['broken']
        rows.append({
            'building': r['building'],
            'room': r['name'],
            'total': total,
            'healthy': max(total - broken, 0),
            'broken': broken,
            'broken_time': earliest_time(st),
            'causes': st['causes'],
            'facility': facility_text(st),
            'in_ledger': True,
        })

    # 记录里有、台账没有的教室
    for key in sorted(stats):
        if key in used:
            continue
        building, room = key
        if not building:
            building = '未标注教学楼'
        st = stats[key]
        rows.append({
            'building': building,
            'room': room,
            'total': 0,        # 台账未登记总数，未知
            'healthy': 0,
            'broken': st['broken'],
            'broken_time': earliest_time(st),
            'causes': st['causes'],
            'facility': facility_text(st),
            'in_ledger': False,
        })

    # 按教学楼、教室排序（教学楼保持台账出现顺序更自然）
    order = {}
    for i, r in enumerate(rooms):
        order.setdefault(r['building'], i)

    rows.sort(key=lambda x: (order.get(x['building'], 999), x['building'], x['room']))
    return rows


def build_room_index():
    """教室台账索引（复用 classroom 的拍平结构）"""
    by_key = {}
    by_name = defaultdict(list)
    rooms = []

    for r in classroom.flat_rooms():
        by_key[(r['building'], r['name'])] = r
        by_name[r['name']].append(r)
        rooms.append(r)

    return by_key, by_name, rooms


def format_causes(causes):
    """
    把原因计数格式化成单元格内容

    多个原因各占一行，带台数：
        电源损坏 ×3
        网线松动 ×1
    """
    if not causes:
        return '—'

    items = causes.most_common()
    lines = []
    for reason, n in items[:6]:      # 最多列 6 条，避免单元格过高
        lines.append(f'{reason} ×{n}')
    if len(items) > 6:
        lines.append(f'…另有 {len(items) - 6} 类原因')

    return '\n'.join(lines)


# ---------------- 生成工作簿 ----------------

def build_workbook():
    """生成只含一张汇总表的 Excel"""
    rows = build_rows()

    wb = Workbook()
    ws = wb.active
    ws.title = '教室设备现状'

    # 列宽
    for i, (_, width) in enumerate(COLS, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # ---- 标题行 ----
    ws.merge_cells(f'A1:{LAST_COL}1')
    t = ws['A1']
    t.value = '机房设备运行现状'
    t.font = TITLE_FONT
    t.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 32

    # ---- 副标题（生成时间）----
    ws.merge_cells(f'A2:{LAST_COL}2')
    s = ws['A2']
    s.value = f'统计时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}'
    s.font = SUBTITLE_FONT
    s.alignment = Alignment(horizontal='right', vertical='center')
    ws.row_dimensions[2].height = 18

    # ---- 表头 ----
    HEADER_ROW = 3
    for i, (name, _) in enumerate(COLS, 1):
        c = ws.cell(row=HEADER_ROW, column=i, value=name)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = CENTER
        c.border = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)
    ws.row_dimensions[HEADER_ROW].height = 26

    # ---- 数据行 ----
    start = HEADER_ROW + 1
    r = start

    for row in rows:
        ws.cell(row=r, column=1, value=row['building'])
        ws.cell(row=r, column=2, value=row['room'])

        # 台账未登记总数的教室，用「—」而不是 0，避免误读成"一台都没有"
        ws.cell(row=r, column=3,
                value=row['total'] if row['total'] else '—')
        healthy_cell = ws.cell(row=r, column=4,
                               value=row['healthy'] if row['total'] else '—')
        broken_cell = ws.cell(row=r, column=5, value=row['broken'])
        time_cell = ws.cell(row=r, column=6,
                            value=row.get('broken_time') or '—')
        cause_cell = ws.cell(row=r, column=7, value=format_causes(row['causes']))
        facility_cell = ws.cell(row=r, column=8,
                                value=row.get('facility') or '—')

        # 数字列居中
        for col in (3, 4, 5):
            ws.cell(row=r, column=col).alignment = CENTER
            ws.cell(row=r, column=col).border = BORDER
            ws.cell(row=r, column=col).font = NUM_FONT

        # 正常数用绿色、损坏数用红色加粗
        healthy_cell.font = OK_NUM_FONT
        if row['broken']:
            broken_cell.font = BROKEN_FONT

        # 时间列居中（只到分钟，不需要换行）
        time_cell.alignment = CENTER
        time_cell.border = BORDER
        time_cell.font = Font(size=10)

        # 原因列左对齐、自动换行
        cause_cell.alignment = LEFT_TOP
        cause_cell.border = BORDER
        cause_cell.font = Font(size=11)

        # 设施故障列：教室设施坏了但电脑没坏，用橙色提示
        facility_cell.alignment = LEFT_TOP
        facility_cell.border = BORDER
        if row.get('facility'):
            facility_cell.font = BROKEN_FONT
        else:
            facility_cell.font = Font(size=11, color='999999')

        # 底色：完好且无设施故障的教室淡绿，有问题的淡红（一眼扫出问题）
        has_issue = bool(row['broken'] or row.get('facility'))
        fill = BAD_FILL if has_issue else OK_FILL
        for col in range(1, NCOL + 1):
            ws.cell(row=r, column=col).fill = fill
            if col not in (7, 8):
                ws.cell(row=r, column=col).border = BORDER

        # 行高：原因/设施列行数多时自动增高
        n_lines = max(len(str(cause_cell.value or '').split('\n')),
                      len(str(facility_cell.value or '').split('\n')),
                      1)
        ws.row_dimensions[r].height = max(22, 17 * n_lines + 6)

        r += 1

    end = r - 1

    # ---- 合并「教学楼」列 ----
    # 同一教学楼的连续行合并成一格，视觉上形成分组，也避免重复文字
    merge_buildings(ws, start, end)

    # ---- 合计行 ----
    if end >= start:
        total_all = sum(x['total'] for x in rows)
        healthy_all = sum(x['healthy'] for x in rows)
        broken_all = sum(x['broken'] for x in rows)
        facility_rooms = sum(1 for x in rows if x.get('facility'))

        ws.cell(row=r, column=1, value='合计')
        ws.cell(row=r, column=2, value=f'{len(rows)} 间')
        ws.cell(row=r, column=3, value=total_all)
        ws.cell(row=r, column=4, value=healthy_all)
        ws.cell(row=r, column=5, value=broken_all)
        # 损坏时间在合计行没有意义，留空
        ws.cell(row=r, column=6, value='')
        ws.cell(row=r, column=7,
                value=f'正常率 {healthy_all / total_all * 100:.1f}%'
                      if total_all else '—')
        ws.cell(row=r, column=8,
                value=f'{facility_rooms} 间有设施故障'
                      if facility_rooms else '—')

        for col in range(1, NCOL + 1):
            c = ws.cell(row=r, column=col)
            c.font = Font(bold=True, size=12)
            c.alignment = CENTER
            c.fill = BUILDING_FILL
            c.border = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)
        ws.cell(row=r, column=7).alignment = LEFT_TOP
        ws.row_dimensions[r].height = 24

    # 冻结表头，滚动时始终看得到列名
    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)

    # 打印设置：横向、一页宽，方便直接打印或转 PDF 给领导
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f'{HEADER_ROW}:{HEADER_ROW}'

    return wb


def merge_buildings(ws, start, end):
    """
    按教学楼合并第一列

    同一教学楼的连续行合并成一格，文字竖排居中、字号加大，
    视觉上形成清晰的分组。
    """
    if end < start:
        return

    group_start = start
    current = ws.cell(row=start, column=1).value

    for r in range(start + 1, end + 2):
        val = ws.cell(row=r, column=1).value if r <= end else None

        if val != current:
            # [group_start, r-1] 是同一个教学楼
            if r - 1 > group_start:
                ws.merge_cells(start_row=group_start, start_column=1,
                               end_row=r - 1, end_column=1)

            cell = ws.cell(row=group_start, column=1)
            cell.value = current
            cell.font = BUILDING_FONT
            cell.fill = BUILDING_FILL
            # 竖排居中：楼层名竖着写，窄列也能放得下，且视觉更整齐
            cell.alignment = Alignment(horizontal='center', vertical='center',
                                       text_rotation=0, wrap_text=True)
            cell.border = Border(left=MEDIUM, right=MEDIUM,
                                 top=THIN, bottom=THIN)

            group_start = r
            current = val


# ---------------- 对外接口 ----------------

def export_to_bytes():
    """
    生成 Excel 并返回字节内容（供 Web 下载使用）

    返回：(文件名, bytes)
    """
    wb = build_workbook()

    buf = io.BytesIO()
    wb.save(buf)

    stamp = datetime.now().strftime('%Y-%m-%d_%H%M')
    filename = f'机房设备运行现状_{stamp}.xlsx'
    return filename, buf.getvalue()


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
    print()

    rows = build_rows()
    print(f'{"教学楼":<12}{"教室":<10}{"总数":>6}{"正常":>6}{"损坏":>6}  原因')
    print('-' * 72)
    for x in rows:
        cause = format_causes(x['causes']).replace('\n', '；')
        total = x['total'] if x['total'] else '—'
        print(f"{x['building']:<12}{x['room']:<10}{str(total):>6}"
              f"{str(x['healthy']) if x['total'] else '—':>6}{x['broken']:>6}  {cause}")
    print('-' * 72)
    print(f'合计 {len(rows)} 间｜总设备 {sum(x["total"] for x in rows)}'
          f'｜正常 {sum(x["healthy"] for x in rows)}'
          f'｜损坏 {sum(x["broken"] for x in rows)}')
