"""教室台账与日常报备模块测试"""

import pytest

import classroom
import daily_task


class TestClassroom:

    def test_add_building_and_room(self, tmp_data):
        assert classroom.add_building('教学楼A')[0]
        assert classroom.add_room('教学楼A', 'A101', 60)[0]

        data = classroom.load()
        assert data['buildings'][0]['name'] == '教学楼A'
        assert data['buildings'][0]['rooms'][0]['name'] == 'A101'

    def test_duplicate_building(self, tmp_data):
        classroom.add_building('教学楼A')
        ok, msg = classroom.add_building('教学楼A')
        assert not ok

    def test_empty_building_name(self, tmp_data):
        assert not classroom.add_building('')[0]
        assert not classroom.add_building('   ')[0]

    def test_negative_rejected(self, tmp_data):
        classroom.add_building('教学楼A')
        assert not classroom.add_room('教学楼A', 'A101', -1)[0]

    def test_non_integer_rejected(self, tmp_data):
        classroom.add_building('教学楼A')
        ok, msg = classroom.add_room('教学楼A', 'A101', 'abc')
        assert not ok

    def test_room_in_missing_building(self, tmp_data):
        ok, msg = classroom.add_room('不存在的楼', 'A101', 10)
        assert not ok

    def test_duplicate_room(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)
        assert not classroom.add_room('教学楼A', 'A101', 60)[0]

    def test_update_room(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)
        ok, _ = classroom.update_room('教学楼A', 'A101', total=80)
        assert ok
        assert classroom.flat_rooms()[0]['total'] == 80

    def test_manual_broken_field_removed(self, tmp_data):
        """
        教室台账不再存"损坏数" —— 台数只从报修台账推导，
        避免两处记录同一件事、两边对不上
        """
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)

        # 即使调用方传了 broken，也不应被写入台账
        classroom.update_room('教学楼A', 'A101', total=60)
        room = classroom.load()['buildings'][0]['rooms'][0]
        assert 'broken' not in room

    def test_delete_room(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)
        assert classroom.delete_room('教学楼A', 'A101')[0]
        assert classroom.flat_rooms() == []

    def test_delete_building_removes_rooms(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)
        assert classroom.delete_building('教学楼A')[0]
        assert classroom.flat_rooms() == []

    def test_summary(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)
        classroom.add_room('教学楼A', 'A102', 60)

        s = classroom.summary()
        assert s['buildings'] == 1
        assert s['rooms'] == 2
        assert s['total_pcs'] == 120
        # 没有报修记录时，全部正常
        assert s['broken_pcs'] == 0
        assert s['healthy_pcs'] == 120

    def test_summary_counts_from_repair_log(self, tmp_data):
        """损坏台数应来自报修台账，而不是台账里手填的数字"""
        import repair_log

        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)

        repair_log.add_record('A101', '开不了机', '原因：电源坏',
                              building='教学楼A', quantity=3)

        s = classroom.summary()
        assert s['broken_pcs'] == 3
        assert s['healthy_pcs'] == 57

    def test_summary_three_states(self, tmp_data):
        """可自修要单独统计出来"""
        import repair_log

        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 60)

        repair_log.add_record('A101', '网线松', '原因：网线松',
                              status=repair_log.STATUS_SELF_FIX,
                              building='教学楼A', quantity=2)
        repair_log.add_record('A101', '电源坏', '原因：电源坏',
                              status=repair_log.STATUS_PENDING,
                              building='教学楼A', quantity=1)

        s = classroom.summary()
        assert s['self_fix_pcs'] == 2
        assert s['broken_pcs'] == 3       # 可自修也算不能用
        assert s['healthy_pcs'] == 57

    def test_healthy_never_negative(self, tmp_data):
        """损坏数超过总数时，正常数不应为负"""
        import repair_log

        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 2)
        for i in range(5):
            repair_log.add_record('A101', f'故障{i}', '原因：x',
                                  building='教学楼A')
        assert classroom.summary()['healthy_pcs'] >= 0

    def test_corrupt_file_returns_empty(self, tmp_data):
        with open(classroom.DATA_FILE, 'w', encoding='utf-8') as f:
            f.write('{ 坏掉的 JSON')
        assert classroom.summary()['rooms'] == 0


class TestBuildingsWithStats:
    """
    两级结构（教学楼 → 教室）必须带上实时统计

    历史缺陷：磁盘上的 classrooms.json 早期存过一个手工填写的 broken 字段，
    后来改为「损坏台数完全由报修台账推导」，但该字段残留了下来。
    前端教室列表直接读 b.rooms 的 broken，读到的是陈旧手工值，
    导致「教室列表」与「教室详情」显示不一致。
    """

    def test_stats_reflect_repair_log(self, tmp_data):
        """教室列表里的损坏数必须来自报修台账"""
        import repair_log

        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)
        repair_log.add_record('A101', '硬件故障', '原因：电源坏',
                              building='教学楼A', quantity=3)

        data = classroom.buildings_with_stats()
        room = data['buildings'][0]['rooms'][0]
        assert room['broken'] == 3
        assert room['healthy'] == 77

    def test_stale_disk_broken_is_ignored(self, tmp_data):
        """
        磁盘上残留的旧 broken 字段不得影响返回值

        这是本次缺陷的核心：不能把磁盘上的手工值透传给前端。
        """
        import repair_log

        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)

        # 人为写入一个陈旧的 broken（模拟历史遗留数据）
        data = classroom.load()
        data['buildings'][0]['rooms'][0]['broken'] = 99
        classroom.save(data)

        # 台账里实际只有 2 台损坏
        repair_log.add_record('A101', '故障', '原因：x',
                              building='教学楼A', quantity=2)

        room = classroom.buildings_with_stats()['buildings'][0]['rooms'][0]
        assert room['broken'] == 2, '读到了磁盘上的陈旧值，而不是台账统计'
        assert room['healthy'] == 78

    def test_three_state_fields_present(self, tmp_data):
        import repair_log

        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)
        repair_log.add_record('A101', '网线松', '原因：x',
                              status=repair_log.STATUS_SELF_FIX,
                              building='教学楼A', quantity=2)
        repair_log.add_record('A101', '电源坏', '原因：y',
                              status=repair_log.STATUS_PENDING,
                              building='教学楼A', quantity=1)

        room = classroom.buildings_with_stats()['buildings'][0]['rooms'][0]
        assert room['self_fix_pcs'] == 2
        assert room['pending_pcs'] == 1
        assert room['broken'] == 3

    def test_consistent_with_flat_rooms(self, tmp_data):
        """两级结构与拍平结构的统计必须一致（两处口径不能分叉）"""
        import repair_log

        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)
        classroom.add_room('教学楼A', 'A102', 60)
        repair_log.add_record('A101', '故障', '原因：x',
                              building='教学楼A', quantity=4)

        nested = {}
        for b in classroom.buildings_with_stats()['buildings']:
            for r in b['rooms']:
                nested[f"{b['name']}|{r['name']}"] = r

        for flat in classroom.flat_rooms():
            key = f"{flat['building']}|{flat['name']}"
            assert nested[key]['broken'] == flat['broken'], f'{key} 口径不一致'
            assert nested[key]['healthy'] == flat['healthy']

    def test_no_broken_key_written_on_update(self, tmp_data):
        """调用 update_room 时不应把废弃的 broken 字段写回磁盘"""
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)
        classroom.update_room('教学楼A', 'A101', total=90)

        raw = classroom.load()['buildings'][0]['rooms'][0]
        assert 'broken' not in raw
        assert raw['total'] == 90


class TestDailyTask:

    def test_add_task(self, tmp_data):
        ok, tid = daily_task.add_task(
            building='教学楼A', room='A101', task_type='安装新软件',
            teacher='张老师', due='2026-10-20', priority='高',
        )
        assert ok and tid == 'T001'

    def test_requires_room_and_type(self, tmp_data):
        assert not daily_task.add_task(room='', task_type='安装新软件')[0]
        assert not daily_task.add_task(room='A101', task_type='')[0]

    def test_invalid_priority_defaults(self, tmp_data):
        daily_task.add_task(room='A101', task_type='x', priority='超级高')
        assert daily_task.list_tasks()[0]['priority'] == daily_task.PRIORITY_MID

    def test_toggle_status(self, tmp_data):
        _, tid = daily_task.add_task(room='A101', task_type='x')
        daily_task.toggle_status(tid)
        assert daily_task.list_tasks()[0]['status'] == daily_task.STATUS_DONE

        daily_task.toggle_status(tid)
        assert daily_task.list_tasks()[0]['status'] == daily_task.STATUS_PENDING

    def test_finished_time_recorded(self, tmp_data):
        _, tid = daily_task.add_task(room='A101', task_type='x')
        daily_task.toggle_status(tid)
        assert daily_task.list_tasks()[0]['finished'] != ''

    def test_delete(self, tmp_data):
        _, tid = daily_task.add_task(room='A101', task_type='x')
        assert daily_task.delete_task(tid)[0]
        assert daily_task.list_tasks() == []

    def test_pending_sorts_before_done(self, tmp_data):
        _, t1 = daily_task.add_task(room='A101', task_type='x')
        _, t2 = daily_task.add_task(room='A102', task_type='y')
        daily_task.toggle_status(t1)

        ids = [t['id'] for t in daily_task.list_tasks()]
        assert ids[0] == t2, ids

    def test_summary(self, tmp_data):
        daily_task.add_task(room='A101', task_type='x', priority='高')
        _, t2 = daily_task.add_task(room='A102', task_type='y')
        daily_task.toggle_status(t2)

        s = daily_task.summary()
        assert s['total'] == 2
        assert s['pending'] == 1
        assert s['done'] == 1
        assert s['high'] == 1

    def test_overdue_detection(self, tmp_data):
        daily_task.add_task(room='A101', task_type='x', due='2000-01-01')
        assert daily_task.summary()['overdue'] == 1
