"""
机房故障智能诊断助手 - 课表模块

解决什么问题：
  教室出故障时，最急的不是"这台怎么修"，而是**这节课怎么办** ——
  整间教室断电/断网，学生要立刻换个地方上课。
  这时需要马上知道：**现在这个时间，哪间教室空着。**

功能：
  1. 解析学校教务导出的场地课表（.xls / .xlsx，一间教室一个文件）
  2. 保存节次作息时间（全校统一一份，可在前端调整）
  3. 查询某个「星期 + 节次 + 周次」有哪些教室空闲 / 被占用

课表文件的结构（实测样本：第一实验楼机房C104.xls）：

    第 0 行   2026-2027学年第1学期 | 第一实验楼机房C104场地课表 | 座位数：80
    第 1 行   节次 | (空) | 星期一 … 星期日
    第 2-13 行  上午(一~四) / 下午(五~八) / 晚上(九~十二) × 星期一~日
    第 14 行  注--内容顺序为：课程<>周次<>教师<>教学班<>选课人数
              本学期2026-09-07正式上课至2027-01-24结束，共20周.

  每个格子里的格式：课程名/(N-N节)X-Y周/教师/教学班/选课人数：N
  一个格子里可能有多门课（不同周次交替），用换行分隔。

作者：liyishuo1
"""

import os
import re

from filelock import file_lock

# 课表与作息配置都存这一个文件：
# 两者是强相关的（没有作息时间，课表就无法回答"现在哪间空着"），
# 分开存反而要多维护一份一致性。
DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'schedule.json')

# 星期名称 → 1-7（周一到周日）
WEEKDAY_NAMES = ['星期一', '星期二', '星期三', '星期四',
                 '星期五', '星期六', '星期日']

# 中文节次 → 数字
_CN_PERIOD = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6,
    '七': 7, '八': 8, '九': 9, '十': 10,
    '十一': 11, '十二': 12,
}

# 上下午晚上 → 默认的节次范围，用于前端分组展示
PERIOD_SECTIONS = [
    ('上午', [1, 2, 3, 4]),
    ('下午', [5, 6, 7, 8]),
    ('晚上', [9, 10, 11, 12]),
]

# 一节课的格子内容形如：
#   专业软件CAD/SU/(5-5节)1-8周/石嘉伟/专业软件CAD/SU-0002/选课人数：26
# 课程名和教学班名里都可能带斜杠，所以不能简单按 '/' 切分，
# 而是用「(N-N节)X-Y周」这一段做锚点，前后分别处理。
_ANCHOR = re.compile(r'\((\d+)\s*-\s*(\d+)\s*节\)\s*(\d+)\s*-\s*(\d+)\s*周')

# 学期起止与总周数，从文件末尾的注释行里取：
#   本学期2026-09-07正式上课至2027-01-24结束，共20周.
_TERM_RE = re.compile(
    r'(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2}).{0,6}?至'
    r'\s*(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2}).{0,10}?共\s*(\d+)\s*周')


# ---------------- 教师姓名脱敏 ----------------
#
# 比赛中不得出现真实教师姓名。这里只保留姓，后面加「老师」。
#
# 为什么放在后端做：
#   前端脱敏的话，真名仍然出现在接口返回的 JSON 里，
#   打开浏览器开发者工具就能看到 —— 等于没隐藏。
#
# data/schedule.json 里仍存真名（该文件已加入 .gitignore，不进仓库），
# 只有出口这一层做转换。以后要换脱敏规则（比如改成「杨*」），改这里一处即可。

# 复姓：不能只取第一个字，否则「欧阳明」会变成「欧老师」
_COMPOUND_SURNAMES = [
    '欧阳', '司马', '上官', '诸葛', '东方', '皇甫', '尉迟', '公孙',
    '慕容', '长孙', '宇文', '司徒', '夏侯', '令狐', '端木', '独孤',
]


def mask_teacher(name):
    """
    教师姓名脱敏：只保留姓，后面加「老师」

    空名返回空串；复姓按两个字处理。
    """
    s = (name or '').strip()
    if not s:
        return ''

    for c in _COMPOUND_SURNAMES:
        if s.startswith(c):
            return c + '老师'

    return s[0] + '老师'


def mask_course(course):
    """返回一份脱敏后的课程（不改原对象）"""
    if not course:
        return course
    out = dict(course)
    out['teacher'] = mask_teacher(course.get('teacher'))
    return out


def mask_room(room_data):
    """返回一份脱敏后的教室课表（不改原对象）"""
    if not room_data:
        return room_data
    out = dict(room_data)
    out['courses'] = [mask_course(c) for c in (room_data.get('courses') or [])]
    return out


# ---------------- 文件读取 ----------------

# OLE2 复合文档的文件头（.xls）
_OLE2_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


def _read_grid(source):
    """
    把 Excel 读成二维字符串表

    source 可以是文件路径，也可以是上传上来的文件内容（bytes）——
    导入接口拿到的是内存里的字节，不必先落盘。

    兼容两种格式，**按文件头判断而不是看后缀** ——
    学校系统导出的后缀经常不准（见过把 xlsx 写成 xls 的）：
      · OLE2 的 .xls  → xlrd
      · ZIP 的 .xlsx  → openpyxl
    """
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        with open(source, 'rb') as f:
            data = f.read()

    if data[:8] == _OLE2_MAGIC:
        return _read_xls(data)
    if data[:4] == b'PK\x03\x04':
        return _read_xlsx(data)

    raise ValueError(
        '无法识别的文件格式。请上传教务系统导出的 .xls 或 .xlsx 文件')


def _read_xls(data):
    try:
        import xlrd
    except ImportError:
        raise ValueError(
            '读取 .xls 需要 xlrd：pip install xlrd\n'
            '（或者把课表另存为 .xlsx 再上传）') from None

    try:
        # file_contents 直接吃字节，省掉一次临时文件
        book = xlrd.open_workbook(file_contents=data)
    except Exception as e:
        raise ValueError(f'这个 .xls 文件读不出来：{e}') from None

    sh = book.sheet_by_index(0)

    grid = []
    for r in range(sh.nrows):
        row = []
        for c in range(sh.ncols):
            v = sh.cell_value(r, c)
            if isinstance(v, float) and v == int(v):
                v = int(v)
            row.append(str(v))
        grid.append(row)
    return grid


def _read_xlsx(data):
    from io import BytesIO

    from openpyxl import load_workbook

    try:
        wb = load_workbook(BytesIO(data), data_only=True)
    except Exception as e:
        raise ValueError(f'这个 .xlsx 文件读不出来：{e}') from None

    ws = wb.worksheets[0]

    grid = []
    for row in ws.iter_rows(values_only=True):
        grid.append(['' if v is None else str(v) for v in row])
    return grid


# ---------------- 解析 ----------------

def _parse_cell(text):
    """
    解析一个格子里的课程（可能有多门，用换行分隔）

    返回 [{'name', 'period_start', 'period_end', 'week_start', 'week_end',
           'teacher', 'class_name', 'students'}, ...]
    """
    out = []
    for line in (text or '').split('\n'):
        line = line.strip()
        if not line:
            continue

        m = _ANCHOR.search(line)
        if not m:
            continue

        # 锚点之前是「课程名/」，末尾那个斜杠要去掉
        name = line[:m.start()].rstrip('/').strip()

        # 锚点之后是「/教师/教学班/选课人数：N」
        rest = line[m.end():].lstrip('/')
        parts = [p for p in rest.split('/') if p != ''] if rest else []

        teacher = parts[0] if parts else ''

        students = None
        class_parts = parts[1:]
        if class_parts and '选课人数' in class_parts[-1]:
            num = re.search(r'\d+', class_parts[-1])
            if num:
                students = int(num.group())
            class_parts = class_parts[:-1]

        out.append({
            'name': name,
            'period_start': int(m.group(1)),
            'period_end': int(m.group(2)),
            'week_start': int(m.group(3)),
            'week_end': int(m.group(4)),
            'teacher': teacher,
            # 教学班名里也可能有斜杠，拼回去
            'class_name': '/'.join(class_parts),
            'students': students,
        })

    return out


def _parse_term(grid):
    """从表格末尾的注释行取学期开始日期与总周数"""
    for row in grid:
        for cell in row:
            m = _TERM_RE.search(cell or '')
            if m:
                start = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
                end = f'{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}'
                return {'start': start, 'end': end, 'weeks': int(m.group(7))}
    return None


def _parse_room_label(grid):
    """
    从标题行取教室名称，如「第一实验楼机房C104」

    标题格通常是「<教室名>场地课表」，把后缀去掉即可。
    """
    for row in grid[:3]:
        for cell in row:
            s = (cell or '').strip()
            if '场地课表' in s:
                return s.split('场地课表')[0].strip()
    return ''


def _parse_seats(grid):
    """从标题行取座位数"""
    for row in grid[:3]:
        for cell in row:
            m = re.search(r'座位数[:：]\s*(\d+)', cell or '')
            if m:
                return int(m.group(1))
    return None


def _period_from_name(name):
    """节次名 → 数字（'一' → 1，'十二' → 12）"""
    s = (name or '').strip()
    return _CN_PERIOD.get(s)


def parse_file(source):
    """
    解析一个课表文件

    source 可以是文件路径或上传的文件内容（bytes）。

    返回：
      {
        'room_label': '第一实验楼机房C104',
        'seats': 80,
        'term': {'start': '2026-09-07', 'end': '...', 'weeks': 20},
        'courses': [{'day': 1, 'period_start': 1, 'period_end': 1, ...}, ...],
      }
    """
    grid = _read_grid(source)

    if not grid:
        raise ValueError('文件是空的')

    room_label = _parse_room_label(grid)
    seats = _parse_seats(grid)
    term = _parse_term(grid)

    # 找表头行：包含「星期一」的那一行
    header_row = None
    day_cols = {}
    for r, row in enumerate(grid[:5]):
        for c, cell in enumerate(row):
            for i, wd in enumerate(WEEKDAY_NAMES, start=1):
                if (cell or '').strip() == wd:
                    day_cols[c] = i
        if day_cols:
            header_row = r
            break

    if header_row is None:
        raise ValueError(
            '没找到「星期一…星期日」的表头，这可能不是场地课表文件')

    courses = []
    for r in range(header_row + 1, len(grid)):
        row = grid[r]
        if len(row) < 2:
            continue

        period = _period_from_name(row[1])
        if period is None:
            continue

        for c, day in day_cols.items():
            if c >= len(row):
                continue
            for item in _parse_cell(row[c]):
                courses.append({'day': day, **item})

    return {
        'room_label': room_label,
        'seats': seats,
        'term': term,
        'courses': courses,
    }


# ---------------- 教室映射 ----------------

# 课表里的教室名形如「第一实验楼机房C104」，系统里叫「实验楼A-104」。
# 两者对不上，所以导入时要从课表名里抠出教室号去匹配。

_ROOM_TOKEN_RE = re.compile(r'([A-Za-z]*)\s*(\d+)\s*$')


def extract_room_number(label):
    """
    从课表教室名里取教室号

    '第一实验楼机房C104' → '104'
    '机房 A201'          → '201'
    '第一实验楼'          → ''    （没有数字，取不出来）
    """
    m = _ROOM_TOKEN_RE.search((label or '').strip())
    return m.group(2) if m else ''


def guess_room(label, rooms):
    """
    猜课表教室名对应系统里的哪间教室

    参数：
      label - 课表里的教室名，如「第一实验楼机房C104」
      rooms - classroom.flat_rooms() 的结果

    返回 (building, room) 或 None：
      · 只有唯一匹配才返回 —— 猜错了比猜不到更麻烦，
        因为用户会以为系统识别对了，直接点导入
      · 多个匹配（比如两栋楼都有 104）返回 None，留给用户手动选
    """
    num = extract_room_number(label)
    if not num or not rooms:
        return None

    hits = [r for r in rooms if str(r.get('name', '')).strip() == num]
    if len(hits) != 1:
        return None

    return hits[0].get('building', ''), hits[0].get('name', '')


# ---------------- 存储 ----------------

def _empty():
    return {
        'term': {'start': '', 'weeks': 0},
        'periods': {},
        'rooms': {},
    }


def load():
    """读取课表数据"""
    import json

    if not os.path.exists(DATA_FILE):
        return _empty()
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return _empty()

    base = _empty()
    for k, v in base.items():
        data.setdefault(k, v)
    return data


def save(data):
    """保存课表数据（调用方负责加锁，或直接用下面的高层函数）"""
    import json

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def room_key(building, room):
    return f'{building}|{room}'


def upsert_room(building, room, parsed, filename=''):
    """
    把一间教室的课表写进数据文件

    同一间教室重复导入时整体替换（课表是按学期整份导出的，
    逐条合并反而容易留下过期课程）。
    """
    with file_lock(DATA_FILE):
        data = load()

        # 学期信息以最近一次导入为准（同一学期的文件应该一致）
        if parsed.get('term'):
            data['term'] = parsed['term']

        data['rooms'][room_key(building, room)] = {
            'building': building,
            'room': room,
            'label': parsed.get('room_label', ''),
            'seats': parsed.get('seats'),
            'file': filename,
            'courses': parsed.get('courses', []),
        }

        save(data)
        return len(parsed.get('courses', []))


def remove_room(building, room):
    with file_lock(DATA_FILE):
        data = load()
        data['rooms'].pop(room_key(building, room), None)
        save(data)


# ---------------- 作息时间 ----------------

def set_periods(periods):
    """
    保存节次作息时间

    参数：{'1': {'start': '08:00', 'end': '08:45'}, ...}
    """
    with file_lock(DATA_FILE):
        data = load()
        data['periods'] = periods
        save(data)


def set_term(start, weeks):
    with file_lock(DATA_FILE):
        data = load()
        data['term'] = {'start': start, 'weeks': int(weeks)}
        save(data)


# ---------------- 查询 ----------------

def current_week(data=None, today=None):
    """
    今天属于学期第几周

    返回 0 表示还没开学，None 表示学期信息没配置。
    """
    from datetime import date, datetime

    data = data or load()
    term = data.get('term') or {}
    start = (term.get('start') or '').strip()
    weeks = int(term.get('weeks') or 0)
    if not start:
        return None

    try:
        d0 = datetime.strptime(start, '%Y-%m-%d').date()
    except ValueError:
        return None

    today = today or date.today()
    delta = (today - d0).days
    if delta < 0:
        return 0

    week = delta // 7 + 1
    if weeks and week > weeks:
        return week      # 超出学期，如实返回，调用方决定怎么提示
    return week


def current_period(data=None, now=None):
    """
    现在属于第几节（按作息时间判断）

    返回 None 表示当前不在任何一节课内（课间、午休、晚上没课）。
    """
    from datetime import datetime

    data = data or load()
    periods = data.get('periods') or {}
    if not periods:
        return None

    now = now or datetime.now().time()
    now_min = now.hour * 60 + now.minute

    for key, span in periods.items():
        try:
            p = int(key)
        except (TypeError, ValueError):
            continue

        s = (span or {}).get('start') or ''
        e = (span or {}).get('end') or ''
        sm = _hhmm_to_min(s)
        em = _hhmm_to_min(e)
        if sm is None or em is None:
            continue
        if sm <= now_min < em:
            return p
    return None


def _hhmm_to_min(s):
    m = re.match(r'^\s*(\d{1,2})\s*:\s*(\d{2})\s*$', s or '')
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h * 60 + mi


def room_is_busy(room_data, day, period, week):
    """某间教室在「星期 day 第 period 节 第 week 周」有没有课"""
    for c in (room_data.get('courses') or []):
        if c.get('day') != day:
            continue
        if not (c.get('period_start', 0) <= period <= c.get('period_end', 0)):
            continue
        if not (c.get('week_start', 0) <= week <= c.get('week_end', 0)):
            continue
        return c
    return None


def query(day, period, week):
    """
    查询某个时间点各教室的占用情况

    参数：
      day    - 星期几，1-7
      period - 第几节，1-12
      week   - 第几周

    返回：
      {
        'free': [{'building','room','seats','label'}, ...],
        'busy': [{'building','room','seats','label','course': {...}}, ...],
        'no_schedule': [ ... ],   # 没有导入课表的教室
      }

    「没导入课表的教室」单独列出，不能算成空闲 ——
    不知道有没有课就说"空着"，会把人引到正在上课的教室去。
    """
    import classroom

    data = load()
    rooms = data.get('rooms') or {}

    free, busy, unknown = [], [], []

    for r in classroom.flat_rooms():
        key = room_key(r['building'], r['name'])
        base = {
            'building': r['building'],
            'room': r['name'],
            'seats': r.get('total', 0),
        }

        rd = rooms.get(key)
        if not rd:
            unknown.append(base)
            continue

        c = room_is_busy(rd, day, period, week)
        if c:
            busy.append({**base, 'course': c})
        else:
            free.append({**base, 'label': rd.get('label', '')})

    return {'free': free, 'busy': busy, 'no_schedule': unknown}


def summary():
    """课表概览（给前端显示"导入了几间"）"""
    data = load()
    rooms = data.get('rooms') or {}
    periods = data.get('periods') or {}
    return {
        'term': data.get('term') or {},
        'rooms': len(rooms),
        'periods': len(periods),
        'course_count': sum(len(x.get('courses') or [])
                            for x in rooms.values()),
    }
