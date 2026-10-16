"""报修记录模块测试"""

import os

import pytest

import repair_log


class TestCrud:

    def test_add_and_load(self, tmp_data):
        rid = repair_log.add_record('501', '电脑打不开', '电源故障', building='教学楼A')
        assert rid == 'R001'

        records = repair_log.load_records()
        assert len(records) == 1
        assert records[0]['教室'] == '501'
        assert records[0]['教学楼'] == '教学楼A'

    def test_sequential_ids(self, tmp_data):
        a = repair_log.add_record('501', 'x', 'y')
        b = repair_log.add_record('502', 'x', 'y')
        assert (a, b) == ('R001', 'R002')

    def test_update_status(self, tmp_data):
        rid = repair_log.add_record('501', 'x', 'y')
        ok, msg = repair_log.update_status(rid, repair_log.STATUS_REPORTED)
        assert ok
        assert repair_log.load_records()[0]['状态'] == repair_log.STATUS_REPORTED

    def test_update_status_rejects_invalid(self, tmp_data):
        rid = repair_log.add_record('501', 'x', 'y')
        ok, msg = repair_log.update_status(rid, '莫名其妙的状态')
        assert not ok

    def test_note_appends(self, tmp_data):
        rid = repair_log.add_record('501', 'x', 'y')
        repair_log.update_status(rid, repair_log.STATUS_REPORTED, '已电话联系')
        repair_log.update_status(rid, repair_log.STATUS_RESOLVED, '已更换电源')
        note = repair_log.load_records()[0]['备注']
        assert '已电话联系' in note and '已更换电源' in note

    def test_update_record_fields(self, tmp_data):
        rid = repair_log.add_record('501', '旧现象', '旧结论')
        ok, _ = repair_log.update_record(rid, symptom='新现象', conclusion='新结论')
        assert ok
        r = repair_log.load_records()[0]
        assert r['故障现象'] == '新现象'
        assert r['诊断结论'] == '新结论'

    def test_delete_record(self, tmp_data):
        rid = repair_log.add_record('501', 'x', 'y')
        ok, _ = repair_log.delete_record(rid)
        assert ok
        assert repair_log.load_records() == []

    def test_delete_missing(self, tmp_data):
        ok, _ = repair_log.delete_record('R999')
        assert not ok


class TestSortRecords:
    """排序：未报修优先，同状态内新的在前"""

    def test_priority_order(self, tmp_data):
        a = repair_log.add_record('501', 'a', 'x')
        b = repair_log.add_record('502', 'b', 'x')
        c = repair_log.add_record('503', 'c', 'x')

        repair_log.update_status(a, repair_log.STATUS_RESOLVED)
        repair_log.update_status(b, repair_log.STATUS_REPORTED)
        # c 保持「未报修」

        ordered = [r['记录编号'] for r in repair_log.sort_records(repair_log.load_records())]
        assert ordered == [c, b, a], ordered

    def test_time_order(self, tmp_data):
        """
        按时间倒序：新的在前

        注意：记录时间只精确到「分钟」，同一分钟内创建的两条时间完全相同，
              而排序是稳定排序、平局保持原顺序。
              因此这里直接构造不同时间的记录来验证排序本身。
        """
        import csv

        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=repair_log.FIELDS)
            w.writeheader()
            w.writerow(dict(zip(repair_log.FIELDS, [
                'R001', '2026-10-15 09:00', '', '501', 'a', 'x', '未报修', ''])))
            w.writerow(dict(zip(repair_log.FIELDS, [
                'R002', '2026-10-16 18:30', '', '502', 'b', 'x', '未报修', ''])))

        ordered = [r['记录编号'] for r in
                   repair_log.sort_records(repair_log.load_records(), by='time')]
        assert ordered == ['R002', 'R001'], ordered


class TestHeaderMigration:
    """旧版 CSV（缺「教学楼」列）读取时应自动补齐"""

    def test_migrates_old_header(self, tmp_data):
        # 写入一个旧格式文件（7 列，没有教学楼）
        old = '记录编号,时间,教室,故障现象,诊断结论,状态,备注\n'
        old += 'R001,2026-10-15 14:22,208,电脑开不了机,电源故障,已解决,\n'
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(old)

        records = repair_log.load_records()
        assert len(records) == 1
        assert records[0]['教室'] == '208'
        assert records[0]['教学楼'] == ''      # 缺失字段补空，不丢记录

    def test_next_id_after_migration(self, tmp_data):
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write('记录编号,时间,教室,故障现象,诊断结论,状态,备注\n')
            f.write('R001,2026-10-15 14:22,208,x,y,已解决,\n')
        assert repair_log.next_id() == 'R002'
