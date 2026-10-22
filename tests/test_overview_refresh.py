"""
总览数据必须随台账状态变化

这是使用中报的一个问题：在台账里把故障标成「已解决」，
回到运行总览点刷新，数字没变 —— 看起来像假刷新。
实际原因有两个，都在前端：
  · 刷新按钮压根没绑事件（纯装饰）
  · 请求没带 no-store

后端本来每次都是重新读文件的，所以这里补一条测试锁住这个契约：
改了状态，overview() 的待处理数必须立刻跟着变。
"""

import overview
import repair_log


class TestOverviewFollowsStatus:

    def test_pending_drops_after_resolved(self, tmp_data):
        repair_log.add_record(classroom='101', symptom='内存条松动',
                              conclusion='x',
                              status=repair_log.STATUS_PENDING,
                              building='实验楼A')

        before = overview.overview()['kpi']['pending_records']
        assert before == 1, '登记一条未报修，待处理应为 1'

        rec_id = repair_log.load_records()[0]['记录编号']
        repair_log.update_status(rec_id, repair_log.STATUS_RESOLVED)

        after = overview.overview()['kpi']['pending_records']
        assert after == 0, '标成已解决后，待处理必须变 0'

    def test_warning_disappears_after_resolved(self, tmp_data):
        """故障解决后，那条「即将受影响的课」也要消失"""
        from datetime import date

        import classroom
        import schedule

        classroom.add_building('实验楼A')
        classroom.add_room('实验楼A', '201', total=80)

        today_wd = date.today().isoweekday()
        parsed = {'room_label': 'x', 'seats': 80,
                  'term': {'start': date.today().isoformat(), 'weeks': 30},
                  'courses': [{
                      'day': today_wd, 'period_start': 1, 'period_end': 1,
                      'week_start': 1, 'week_end': 20, 'name': '某课程',
                      'teacher': '张甲', 'students': 50}]}
        schedule.upsert_room('实验楼A', '201', parsed, 'x.xls')
        schedule.set_periods({'1': {'start': '08:00', 'end': '08:45'}})

        repair_log.add_record(classroom='201', symptom='教室总闸跳闸',
                              conclusion='x', status=repair_log.STATUS_PENDING,
                              building='实验楼A')

        assert len(overview.overview()['warnings']) == 1

        rec_id = repair_log.load_records()[0]['记录编号']
        repair_log.update_status(rec_id, repair_log.STATUS_RESOLVED)

        assert overview.overview()['warnings'] == [], \
            '解决之后不该再有预警'
