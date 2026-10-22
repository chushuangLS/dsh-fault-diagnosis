"""
教学设备故障的判定

背景：教室里投影、幕布、音响坏了，电脑一台不缺，
但从教室详情看是「整间教室受影响」，运行总览却显示「正常」——
因为影响判定里根本没有这一类。

投影是上课要用的设备，坏了要提前知道（换设备还是换教室），
所以补上这一类。空调、灯故意不算：坏了课照样上。
"""

import pytest

import overview
import repair_log


def _rec(symptom, conclusion='', target=repair_log.TARGET_FACILITY):
    return {
        '故障现象': symptom,
        '诊断结论': conclusion,
        '故障对象': target,
        '状态': repair_log.STATUS_PENDING,
        '数量': '1',
    }


class TestTeachingDevice:

    @pytest.mark.parametrize('symptom', [
        '投影仪无信号',
        '教室投影坏了，放不了课件',
        '幕布降不下来',
        '音响没有声音',
        '中控面板黑屏',
    ])
    def test_counts_as_impact(self, symptom):
        assert overview.is_teaching_device_fault(_rec(symptom)) is True

    @pytest.mark.parametrize('symptom', [
        '教室空调不制冷',      # 课还能上，只是难受
        '教室灯管闪',
        '教室总闸跳闸',        # 归「整间跳闸」，不是教学设备
    ])
    def test_not_counted(self, symptom):
        assert overview.is_teaching_device_fault(_rec(symptom)) is False

    def test_pc_target_not_counted(self):
        """故障对象是电脑时不算 —— 「投影连的电脑黑屏」是电脑故障"""
        r = _rec('投影连的电脑黑屏', target=repair_log.TARGET_PC)
        assert overview.is_teaching_device_fault(r) is False

    def test_ignores_conclusion(self):
        """
        只看故障现象，不看诊断结论

        结论里有鉴别诊断（「排除投影故障」），拿它匹配会误判 ——
        这和故障分类器踩过的是同一个坑。
        """
        r = _rec('教室空调不制冷', '排除投影故障')
        assert overview.is_teaching_device_fault(r) is False


class TestImpactWithTeachingDevice:

    def test_room_impact_flags_it(self):
        imp = overview.room_impact([_rec('投影仪无信号')], total=72)
        assert imp['impact'] is True
        assert '教学设备故障' in imp['reasons']

    def test_aircon_does_not_flag(self):
        imp = overview.room_impact([_rec('教室空调不制冷')], total=72)
        assert imp['impact'] is False

    def test_reason_shows_in_warning(self, tmp_data):
        """预警里也要带出这条原因，不只是判断为受影响"""
        from datetime import date

        import classroom
        import schedule

        classroom.add_building('实验楼A')
        classroom.add_room('实验楼A', '201', total=80)

        today_wd = date.today().isoweekday()
        start = (date.today().isoformat())
        parsed = {'room_label': 'x', 'seats': 80,
                  'term': {'start': start, 'weeks': 30},
                  'courses': [{
                      'day': today_wd, 'period_start': 1, 'period_end': 1,
                      'week_start': 1, 'week_end': 20, 'name': '某课程',
                      'teacher': '张甲', 'students': 50}]}
        schedule.upsert_room('实验楼A', '201', parsed, 'x.xls')
        schedule.set_periods({'1': {'start': '08:00', 'end': '08:45'}})

        repair_log.add_record(classroom='201', symptom='投影仪无信号',
                              conclusion='x', status=repair_log.STATUS_PENDING,
                              building='实验楼A',
                              target=repair_log.TARGET_FACILITY)

        ws = overview.upcoming_warnings(schedule.load(),
                                        overview._unresolved_by_room(),
                                        classroom.flat_rooms())
        assert len(ws) == 1
        assert '教学设备故障' in ws[0]['reasons']
