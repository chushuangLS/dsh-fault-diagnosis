"""
课表模块的测试

覆盖：
  · .xls / .xlsx 两种格式解析结果一致
  · 课程名与教学班名含斜杠时不错位（真实数据里就有「专业软件CAD/SU」）
  · 一个格子里两门课（不同周次交替）
  · 教师姓名脱敏（比赛要求：不得出现真实姓名）
  · 教室名映射（唯一匹配才自动选，多个匹配留给用户）
  · 周次 / 节次推算
  · 空余查询把「未导入课表」单独分类
"""

import os

import pytest

import classroom
import schedule

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
SAMPLE_XLS = os.path.join(FIXTURES, 'schedule_sample.xls')
SAMPLE_XLSX = os.path.join(FIXTURES, 'schedule_sample.xlsx')


class TestParse:
    """课表文件解析"""

    @pytest.mark.parametrize('path', [SAMPLE_XLS, SAMPLE_XLSX])
    def test_basic_fields(self, path):
        d = schedule.parse_file(path)

        assert d['room_label'] == '第一测试楼机房T101'
        assert d['seats'] == 60
        assert d['term']['start'] == '2026-09-07'
        assert d['term']['weeks'] == 20
        assert len(d['courses']) == 7

    def test_both_formats_identical(self):
        """xls 与 xlsx 是同一份内容，解析结果必须完全一致"""
        a = schedule.parse_file(SAMPLE_XLS)
        b = schedule.parse_file(SAMPLE_XLSX)
        assert a['courses'] == b['courses']

    def test_slash_in_course_and_class_name(self):
        """
        课程名和教学班名里都可能带斜杠

        「测试课程丁/戊/(3-3节)1-8周/赵丁/测试课程丁/戊-0004/选课人数：30」
        按 '/' 硬切会碎成 7 段，必须用「(N-N节)X-Y周」做锚点才切得对。
        """
        d = schedule.parse_file(SAMPLE_XLS)
        c = [x for x in d['courses'] if x['name'] == '测试课程丁/戊']
        assert len(c) == 1
        assert c[0]['teacher'] == '赵丁'
        assert c[0]['class_name'] == '测试课程丁/戊-0004'
        assert c[0]['students'] == 30

    def test_two_courses_in_one_cell(self):
        """同一个格子里的两门课都要提取出来"""
        d = schedule.parse_file(SAMPLE_XLS)
        # 星期二第 1 节有两门
        got = [x for x in d['courses'] if x['day'] == 2 and x['period_start'] == 1]
        assert len(got) == 2
        assert {x['name'] for x in got} == {'测试课程甲', '测试课程乙'}

    def test_week_range_parsed(self):
        d = schedule.parse_file(SAMPLE_XLS)
        c = [x for x in d['courses'] if x['name'] == '测试课程己'][0]
        assert (c['week_start'], c['week_end']) == (9, 16)

    def test_period_parsed(self):
        d = schedule.parse_file(SAMPLE_XLS)
        c = [x for x in d['courses'] if x['name'] == '测试课程庚'][0]
        assert (c['period_start'], c['period_end']) == (9, 9)
        assert c['day'] == 5

    def test_accepts_bytes(self):
        """导入接口传的是内存里的字节，不落盘也要能解析"""
        with open(SAMPLE_XLS, 'rb') as f:
            data = f.read()
        d = schedule.parse_file(data)
        assert len(d['courses']) == 7

    def test_rejects_unknown_format(self):
        with pytest.raises(ValueError, match='无法识别'):
            schedule.parse_file(b'this is not excel')

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            schedule.parse_file(b'')


class TestMaskTeacher:
    """教师姓名脱敏 —— 比赛要求不得出现真实姓名"""

    @pytest.mark.parametrize('name,expect', [
        ('张甲', '张老师'),
        ('李乙', '李老师'),
        ('欧阳明', '欧阳老师'),      # 复姓不能只取一个字
        ('司马光', '司马老师'),
        ('', ''),
        ('   ', ''),
        (None, ''),
    ])
    def test_mask(self, name, expect):
        assert schedule.mask_teacher(name) == expect

    def test_masked_output_has_no_real_name(self):
        """脱敏后不能残留原名的任何字（除了姓）"""
        for name in ['张甲', '任雅馨', '欧阳明']:
            masked = schedule.mask_teacher(name)
            assert masked.endswith('老师')
            # 去掉「姓+老师」后，不应再剩名字
            surname = masked[:-2]
            assert name.startswith(surname)

    def test_mask_course_does_not_mutate(self):
        c = {'name': 'x', 'teacher': '张甲'}
        m = schedule.mask_course(c)
        assert m['teacher'] == '张老师'
        assert c['teacher'] == '张甲'   # 原对象不受影响

    def test_mask_room(self):
        rd = {'courses': [{'teacher': '张甲'}, {'teacher': '李乙'}]}
        m = schedule.mask_room(rd)
        assert [x['teacher'] for x in m['courses']] == ['张老师', '李老师']
        assert [x['teacher'] for x in rd['courses']] == ['张甲', '李乙']


class TestRoomMapping:

    @pytest.mark.parametrize('label,expect', [
        ('第一实验楼机房C104', '104'),
        ('机房 A201', '201'),
        ('C509', '509'),
        ('第一实验楼', ''),
        ('', ''),
    ])
    def test_extract_room_number(self, label, expect):
        assert schedule.extract_room_number(label) == expect

    def test_guess_unique_match(self):
        rooms = [{'building': '实验楼A', 'name': '104', 'total': 80},
                 {'building': '实验楼A', 'name': '105', 'total': 80}]
        assert schedule.guess_room('第一实验楼机房C104', rooms) == ('实验楼A', '104')

    def test_guess_ambiguous_returns_none(self):
        """
        多栋楼都有 104 时不猜

        猜错了比猜不到更麻烦 —— 用户会以为系统识别对了，直接点导入。
        """
        rooms = [{'building': '实验楼A', 'name': '104', 'total': 80},
                 {'building': '实验楼B', 'name': '104', 'total': 80}]
        assert schedule.guess_room('第一实验楼机房C104', rooms) is None

    def test_guess_no_match(self):
        rooms = [{'building': '实验楼A', 'name': '201', 'total': 80}]
        assert schedule.guess_room('第一实验楼机房C104', rooms) is None


class TestTime:
    """周次与节次推算"""

    def test_current_week_before_term(self):
        from datetime import date
        data = {'term': {'start': '2026-09-07', 'weeks': 20}}
        assert schedule.current_week(data, date(2026, 9, 1)) == 0

    def test_current_week_first_day(self):
        from datetime import date
        data = {'term': {'start': '2026-09-07', 'weeks': 20}}
        assert schedule.current_week(data, date(2026, 9, 7)) == 1

    def test_current_week_second(self):
        from datetime import date
        data = {'term': {'start': '2026-09-07', 'weeks': 20}}
        # 第 8 天 → 第 2 周
        assert schedule.current_week(data, date(2026, 9, 14)) == 2

    def test_current_week_beyond_term(self):
        """放假后如实返回超出学期的周数，由调用方决定怎么提示"""
        from datetime import date
        data = {'term': {'start': '2026-09-07', 'weeks': 20}}
        assert schedule.current_week(data, date(2027, 3, 1)) > 20

    def test_current_week_unconfigured(self):
        assert schedule.current_week({'term': {}}) is None

    @pytest.mark.parametrize('hhmm,expect', [
        ('08:00', 480),
        ('8:00', 480),
        ('23:59', 1439),
        ('24:00', None),
        ('08:60', None),
        ('abc', None),
        ('', None),
        (None, None),
    ])
    def test_hhmm_to_min(self, hhmm, expect):
        assert schedule._hhmm_to_min(hhmm) == expect

    def test_current_period(self):
        from datetime import time
        data = {'periods': {
            '1': {'start': '08:00', 'end': '08:45'},
            '2': {'start': '08:55', 'end': '09:40'},
        }}
        assert schedule.current_period(data, time(8, 0)) == 1
        assert schedule.current_period(data, time(8, 30)) == 1
        assert schedule.current_period(data, time(8, 45)) is None   # 课间
        assert schedule.current_period(data, time(8, 50)) is None   # 课间
        assert schedule.current_period(data, time(8, 55)) == 2
        assert schedule.current_period(data, time(12, 0)) is None

    def test_current_period_unconfigured(self):
        assert schedule.current_period({'periods': {}}) is None


class TestRoomBusy:

    def _room(self):
        return {'courses': [
            {'day': 2, 'period_start': 1, 'period_end': 2,
             'week_start': 1, 'week_end': 12, 'name': 'A'},
            {'day': 3, 'period_start': 5, 'period_end': 5,
             'week_start': 9, 'week_end': 16, 'name': 'B'},
        ]}

    def test_match(self):
        rd = self._room()
        assert schedule.room_is_busy(rd, 2, 1, 5)['name'] == 'A'
        assert schedule.room_is_busy(rd, 2, 2, 5)['name'] == 'A'  # 跨节
        assert schedule.room_is_busy(rd, 3, 5, 10)['name'] == 'B'

    def test_wrong_week(self):
        rd = self._room()
        assert schedule.room_is_busy(rd, 2, 1, 15) is None   # 超出 1-12 周
        assert schedule.room_is_busy(rd, 3, 5, 5) is None    # 还没到 9 周

    def test_wrong_day_or_period(self):
        rd = self._room()
        assert schedule.room_is_busy(rd, 4, 1, 5) is None
        assert schedule.room_is_busy(rd, 2, 3, 5) is None


class TestStorage:

    def test_load_empty(self, tmp_data):
        d = schedule.load()
        assert d['rooms'] == {}
        assert d['periods'] == {}

    def test_upsert_and_load(self, tmp_data):
        parsed = schedule.parse_file(SAMPLE_XLS)
        n = schedule.upsert_room('实验楼A', '104', parsed, 'x.xls')
        assert n == 7

        d = schedule.load()
        assert schedule.room_key('实验楼A', '104') in d['rooms']
        assert d['term']['start'] == '2026-09-07'

    def test_reimport_replaces(self, tmp_data):
        """重复导入整份替换，不合并"""
        parsed = schedule.parse_file(SAMPLE_XLS)
        schedule.upsert_room('实验楼A', '104', parsed, 'x.xls')

        smaller = dict(parsed)
        smaller['courses'] = parsed['courses'][:2]
        schedule.upsert_room('实验楼A', '104', smaller, 'x.xls')

        d = schedule.load()
        assert len(d['rooms'][schedule.room_key('实验楼A', '104')]['courses']) == 2

    def test_remove_room(self, tmp_data):
        parsed = schedule.parse_file(SAMPLE_XLS)
        schedule.upsert_room('实验楼A', '104', parsed, 'x.xls')
        schedule.remove_room('实验楼A', '104')
        assert schedule.load()['rooms'] == {}

    def test_set_periods(self, tmp_data):
        schedule.set_periods({'1': {'start': '08:00', 'end': '08:45'}})
        assert schedule.load()['periods']['1']['start'] == '08:00'

    def test_summary(self, tmp_data):
        parsed = schedule.parse_file(SAMPLE_XLS)
        schedule.upsert_room('实验楼A', '104', parsed, 'x.xls')
        schedule.set_periods({'1': {'start': '08:00', 'end': '08:45'}})

        s = schedule.summary()
        assert s['rooms'] == 1
        assert s['periods'] == 1
        assert s['course_count'] == 7


class TestQuery:
    """空余查询 —— 三类必须分开"""

    # 一份「有学期、但没有任何课」的课表：
    # 用来模拟"已导入课表、但这节课没有安排"的教室（这类才算空闲）
    EMPTY_PARSED = {
        'room_label': '测试空课表',
        'seats': 80,
        'term': {'start': '2026-09-07', 'weeks': 20},
        'courses': [],
    }

    def _setup(self, tmp_data):
        classroom.add_building('实验楼A')
        classroom.add_room('实验楼A', '104', total=80)
        classroom.add_room('实验楼A', '105', total=80)
        classroom.add_room('实验楼A', '106', total=80)

        # 104：星期二第 1 节有课
        schedule.upsert_room('实验楼A', '104',
                             schedule.parse_file(SAMPLE_XLS), 'x.xls')
        # 105：已导入课表，但星期二第 1 节没有安排 → 空闲
        schedule.upsert_room('实验楼A', '105',
                             dict(self.EMPTY_PARSED), 'y.xls')
        # 106：没有导入课表 → 无法判断

    def test_three_categories(self, tmp_data):
        self._setup(tmp_data)
        res = schedule.query(day=2, period=1, week=5)

        assert [x['room'] for x in res['busy']] == ['104']
        assert [x['room'] for x in res['free']] == ['105']
        assert [x['room'] for x in res['no_schedule']] == ['106']

    def test_no_schedule_not_counted_as_free(self, tmp_data):
        """
        没导课表的教室必须归到 no_schedule，不能算空闲

        不知道有没有课就说"空着"，会把人引到正在上课的教室去。
        """
        self._setup(tmp_data)
        res = schedule.query(day=2, period=1, week=5)

        free_rooms = [x['room'] for x in res['free']]
        assert '106' not in free_rooms
        assert '106' in [x['room'] for x in res['no_schedule']]

    def test_all_rooms_accounted_for(self, tmp_data):
        """三类的教室数相加应等于台账里的教室总数，不能漏也不能重"""
        self._setup(tmp_data)
        res = schedule.query(day=2, period=1, week=5)
        total = (len(res['free']) + len(res['busy'])
                 + len(res['no_schedule']))
        assert total == len(classroom.flat_rooms()) == 3

    def test_busy_carries_course_info(self, tmp_data):
        self._setup(tmp_data)
        res = schedule.query(day=2, period=1, week=5)
        c = res['busy'][0]['course']
        assert c['name'] == '测试课程甲'
        assert c['students'] == 50
