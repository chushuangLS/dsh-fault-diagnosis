"""
运行总览的数据计算测试

这一层的核心不是"数得对不对"，而是**判定口径**：
  · 「影响上课」= 整间跳闸 / 教师机故障 / 可用台数 < 上课人数
  · 「未导入课表」的教室不能算空闲，也不能被推荐
  · 推荐调课教室时只推荐够坐的最小几间
"""

import pytest

import classroom
import overview
import repair_log
import schedule


def _rec(status=repair_log.STATUS_PENDING, target=repair_log.TARGET_PC,
         symptom='x', conclusion='', quantity=1):
    return {
        '状态': status,
        '故障对象': target,
        '故障现象': symptom,
        '诊断结论': conclusion,
        '数量': quantity,
    }


class TestImpactDetection:

    @pytest.mark.parametrize('symptom,expect', [
        ('教室总闸跳闸', True),
        ('教室没电', True),
        ('整间停电了', True),
        ('配电箱有异味', True),
        ('短路', True),
        ('内存条松动', False),
        ('硬盘故障', False),
    ])
    def test_breaker_trip(self, symptom, expect):
        assert overview.is_breaker_trip(_rec(symptom=symptom)) is expect

    @pytest.mark.parametrize('symptom,expect', [
        ('教师机开不了机', True),
        ('讲台的电脑坏了', True),
        ('教师电脑蓝屏', True),
        ('前排电脑坏了', False),
    ])
    def test_teacher_pc(self, symptom, expect):
        assert overview.is_teacher_pc_fault(_rec(symptom=symptom)) is expect

    def test_conclusion_also_scanned(self):
        """故障现象没写清楚、结论里提到教师机的，也要认出来"""
        r = _rec(symptom='电脑坏了', conclusion='确认是教师机的主板故障')
        assert overview.is_teacher_pc_fault(r) is True


class TestRoomImpact:
    """三条判定条件的组合"""

    def test_no_faults(self):
        imp = overview.room_impact([], 80)
        assert imp['impact'] is False
        assert imp['available'] == 80

    def test_breaker_impact(self):
        """整间跳闸：不管有没有课，一直算影响"""
        imp = overview.room_impact(
            [_rec(symptom='教室总闸跳闸', target=repair_log.TARGET_FACILITY)],
            total=80, has_class=False)
        assert imp['impact'] is True
        assert '整间跳闸' in imp['reasons']

    def test_teacher_pc_impact_without_class(self):
        """教师机坏了，即使现在没课也算影响（排在这个时段的课都上不了）"""
        imp = overview.room_impact(
            [_rec(symptom='教师机坏了')], total=80, has_class=False)
        assert imp['impact'] is True
        assert '教师机故障' in imp['reasons']

    def test_not_enough_seats(self):
        """坏了 5 台，可用 75，上课 78 人 → 影响"""
        imp = overview.room_impact(
            [_rec(symptom='内存条松动', quantity=5)],
            total=80, students=78, has_class=True)
        assert imp['impact'] is True
        assert '可用 75 台 < 78 人' in imp['reasons']

    def test_enough_seats_is_fine(self):
        """坏了 5 台，可用 75，上课只有 45 人 → 不影响"""
        imp = overview.room_impact(
            [_rec(symptom='内存条松动', quantity=5)],
            total=80, students=45, has_class=True)
        assert imp['impact'] is False

    def test_no_class_skips_seat_check(self):
        """
        没课时不能比人数

        「上课人数」在没课时没有意义，拿它去比会把所有空教室都标成受影响。
        """
        imp = overview.room_impact(
            [_rec(symptom='内存条松动', quantity=50)],
            total=80, students=None, has_class=False)
        assert imp['impact'] is False

    def test_facility_fault_not_counted_as_broken_machine(self):
        """设施故障不算电脑损坏台数"""
        imp = overview.room_impact(
            [_rec(symptom='空调坏了', target=repair_log.TARGET_FACILITY)],
            total=80)
        assert imp['broken'] == 0
        assert imp['available'] == 80

    def test_multiple_reasons(self):
        imp = overview.room_impact(
            [_rec(symptom='教室总闸跳闸', target=repair_log.TARGET_FACILITY),
             _rec(symptom='教师机坏了')],
            total=80)
        assert '整间跳闸' in imp['reasons']
        assert '教师机故障' in imp['reasons']


class TestSuggestRooms:
    """调课去处推荐"""

    def _setup(self, tmp_data):
        classroom.add_building('实验楼A')
        classroom.add_room('实验楼A', '101', total=80)
        classroom.add_room('实验楼A', '102', total=40)
        classroom.add_room('实验楼A', '103', total=120)
        classroom.add_room('实验楼A', '104', total=80)

        empty = {'room_label': 'x', 'seats': 0,
                 'term': {'start': '2026-09-07', 'weeks': 20},
                 'courses': []}
        for room in ('101', '102', '103'):
            schedule.upsert_room('实验楼A', room, dict(empty), 'x.xls')
        # 104 故意不导课表

        return schedule.load()

    def test_only_big_enough_rooms(self, tmp_data):
        """40 人的课不该推荐 40 座以下，但够坐的都要推荐"""
        data = self._setup(tmp_data)
        got = overview.suggest_rooms(data, day=2, period=1, week=5, students=45)

        names = [x['room'] for x in got]
        assert '102' not in names      # 40 座，坐不下 45 人
        assert '101' in names
        assert '103' in names

    def test_sorted_by_size_ascending(self, tmp_data):
        """按座位升序 —— 只推荐够坐的最小教室，25 人的课不该给 200 座的"""
        data = self._setup(tmp_data)
        got = overview.suggest_rooms(data, day=2, period=1, week=5, students=10)
        seats = [x['seats'] for x in got]
        assert seats == sorted(seats)

    def test_excludes_room_without_schedule(self, tmp_data):
        """没导课表的教室不能推荐 —— 不知道它是不是也满着"""
        data = self._setup(tmp_data)
        got = overview.suggest_rooms(data, day=2, period=1, week=5, students=10)
        assert '104' not in [x['room'] for x in got]

    def test_excludes_busy_room(self, tmp_data):
        self._setup(tmp_data)
        data = schedule.load()
        data['rooms'][schedule.room_key('实验楼A', '101')]['courses'] = [{
            'day': 2, 'period_start': 1, 'period_end': 1,
            'week_start': 1, 'week_end': 20, 'name': '占用了',
        }]

        got = overview.suggest_rooms(data, day=2, period=1, week=5, students=10)
        assert '101' not in [x['room'] for x in got]

    def test_excludes_itself(self, tmp_data):
        data = self._setup(tmp_data)
        got = overview.suggest_rooms(
            data, day=2, period=1, week=5, students=10,
            exclude=schedule.room_key('实验楼A', '103'))
        assert '103' not in [x['room'] for x in got]

    def test_limit(self, tmp_data):
        data = self._setup(tmp_data)
        got = overview.suggest_rooms(data, day=2, period=1, week=5,
                                     students=10, limit=2)
        assert len(got) <= 2


class TestCategoriesAndTrend:

    def test_category_distribution(self, tmp_data):
        repair_log.add_record(classroom='101', symptom='内存条松动',
                              conclusion='x', status=repair_log.STATUS_PENDING)
        repair_log.add_record(classroom='102', symptom='硬盘故障',
                              conclusion='x', status=repair_log.STATUS_PENDING)

        items = overview.category_distribution()
        names = [x['category'] for x in items]
        assert '内存故障' in names
        assert '存储故障' in names
        # 按次数降序
        assert [x['count'] for x in items] == sorted(
            [x['count'] for x in items], reverse=True)

    def test_trend_shape(self, tmp_data):
        t = overview.trend(days=14)
        assert len(t['dates']) == 14
        assert len(t['new']) == 14
        assert len(t['resolved']) == 14

    def test_trend_counts_today(self, tmp_data):
        repair_log.add_record(classroom='101', symptom='x', conclusion='x',
                              status=repair_log.STATUS_PENDING)
        t = overview.trend(days=14)
        assert sum(t['new']) >= 1
        assert t['active_days'] >= 1


class TestTodayWarnings:
    """
    今日预警：故障 + 今天有课 → 生成一条预警

    日期依赖是这里最容易出问题的地方，所以测试里直接构造
    "今天有课"的课表，而不是写死某个星期几。
    """

    def _build(self, tmp_data, with_class_today=True, students=80):
        from datetime import date, timedelta

        classroom.add_building('实验楼A')
        classroom.add_room('实验楼A', '101', total=80)
        classroom.add_room('实验楼A', '102', total=80)

        today = date.today().isoweekday()

        # 学期起点要落在"今天在第 20 周以内"的范围里，
        # 否则 today_warnings 会因超出学期直接返回空 —— 那是正确行为，
        # 但测试就测不到预警逻辑了。
        start = (date.today() - timedelta(days=28)).isoformat()   # 今天 = 第 5 周

        courses = []
        if with_class_today:
            courses.append({
                'day': today, 'period_start': 1, 'period_end': 1,
                'week_start': 1, 'week_end': 20,
                'name': '测试课', 'teacher': '张甲', 'students': students,
            })

        parsed = {'room_label': 'x', 'seats': 80,
                  'term': {'start': start, 'weeks': 20},
                  'courses': courses}
        schedule.upsert_room('实验楼A', '101', parsed, 'x.xls')
        schedule.set_periods({'1': {'start': '00:00', 'end': '23:59'}})

        # 101 有整间跳闸
        repair_log.add_record(
            classroom='101', symptom='教室总闸跳闸', conclusion='x',
            status=repair_log.STATUS_PENDING, building='实验楼A')

        return schedule.load()

    def test_warning_generated(self, tmp_data):
        data = self._build(tmp_data)
        ws = overview.today_warnings(data, overview._unresolved_by_room(),
                                     classroom.flat_rooms())
        assert len(ws) == 1
        assert ws[0]['room'] == '101'
        assert '整间跳闸' in ws[0]['reasons']

    def test_teacher_name_masked(self, tmp_data):
        """预警里出现的教师名必须已脱敏"""
        data = self._build(tmp_data)
        ws = overview.today_warnings(data, overview._unresolved_by_room(),
                                     classroom.flat_rooms())
        assert ws[0]['course']['teacher'] == '张老师'

    def test_no_class_no_warning(self, tmp_data):
        data = self._build(tmp_data, with_class_today=False)
        ws = overview.today_warnings(data, overview._unresolved_by_room(),
                                     classroom.flat_rooms())
        assert ws == []

    def test_no_fault_no_warning(self, tmp_data):
        data = self._build(tmp_data)
        ws = overview.today_warnings(data, {}, classroom.flat_rooms())
        assert ws == []

    def test_seat_shortage_creates_warning(self, tmp_data):
        """可用台数不够也算预警"""
        from datetime import date, timedelta

        classroom.add_building('实验楼A')
        classroom.add_room('实验楼A', '101', total=80)
        today = date.today().isoweekday()
        start = (date.today() - timedelta(days=28)).isoformat()
        parsed = {'room_label': 'x', 'seats': 80,
                  'term': {'start': start, 'weeks': 20},
                  'courses': [{
                      'day': today, 'period_start': 2, 'period_end': 2,
                      'week_start': 1, 'week_end': 20, 'name': '课',
                      'teacher': '李乙', 'students': 78}]}
        schedule.upsert_room('实验楼A', '101', parsed, 'x.xls')
        schedule.set_periods({'2': {'start': '00:00', 'end': '23:59'}})

        # 坏 5 台 → 可用 75 < 78
        repair_log.add_record(classroom='101', symptom='内存条松动',
                              conclusion='x', status=repair_log.STATUS_PENDING,
                              building='实验楼A', quantity=5)

        ws = overview.today_warnings(schedule.load(),
                                     overview._unresolved_by_room(),
                                     classroom.flat_rooms())
        assert len(ws) == 1
        assert any('可用' in r for r in ws[0]['reasons'])


class TestKpi:

    def test_kpi_shape(self, tmp_data):
        d = overview.overview()
        k = d['kpi']
        for key in ('total_pcs', 'broken_pcs', 'available_rate',
                    'pending_records', 'repeat_count', 'room_count'):
            assert key in k

    def test_available_rate_bounds(self, tmp_data):
        d = overview.overview()
        assert 0 <= d['kpi']['available_rate'] <= 100

    def test_empty_system_does_not_crash(self, tmp_data):
        """没有任何教室和记录时也要能返回，不能 500"""
        d = overview.overview()
        assert d['kpi']['room_count'] == 0
        assert d['rooms'] == []
        assert d['warnings'] == []
