"""
Excel 导出功能测试

重点验证：
  1. 排序：未报修 → 已报修 → 已解决，组内按教学楼、教室
  2. 「不能用台数」按机器去重，同一机位多次损坏只算一台
  3. 损坏明细与教室现状的口径一致（不能用 = 未解决）
  4. 对不上台账的记录不丢失，进入独立工作表
  5. 结论能拆成「原因」和「处理」
"""

import csv
import io
import os

import pytest
from openpyxl import load_workbook

import classroom
import excel_export
import repair_log


# ---------------- 辅助 ----------------

def seed(records):
    """写入若干报修记录（跳过真实文件的表头初始化）"""
    repair_log.init_file()
    with open(repair_log.RECORD_FILE, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        for r in records:
            w.writerow([
                r['id'], r.get('time', '2026-10-15 10:00'),
                r.get('building', ''), r.get('room', ''),
                r.get('symptom', '现象'), r.get('conclusion', '原因：x\n处理：y'),
                r.get('status', repair_log.STATUS_PENDING), r.get('note', ''),
            ])


def seed_rooms(rooms):
    """rooms: [(教学楼, 教室, 总数, 手动损坏数)]"""
    for b, n, total, broken in rooms:
        if not any(x['name'] == b for x in classroom.load()['buildings']):
            classroom.add_building(b)
        classroom.add_room(b, n, total, broken)


def read_sheet(name, data=None, skip_header=True):
    """把导出的 Excel 读成二维列表（默认跳过表头行）"""
    if data is None:
        _, data = excel_export.export_to_bytes()
    wb = load_workbook(io.BytesIO(data))
    ws = wb[name]
    rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
    return rows[1:] if skip_header else rows


# ---------------- 结论拆分 ----------------

class TestSplitConclusion:

    def test_standard_format(self):
        reason, action = excel_export.split_conclusion(
            '原因：电源线松动。\n处理：插紧即可。')
        assert reason == '电源线松动。'
        assert action == '插紧即可。'

    def test_fullwidth_colon(self):
        reason, action = excel_export.split_conclusion(
            '原因：主板故障\n处理：联系维修')
        assert reason == '主板故障'
        assert action == '联系维修'

    def test_multiline_merged(self):
        """原因里的换行应被压成一行，避免撑坏单元格"""
        reason, _ = excel_export.split_conclusion(
            '原因：第一行\n第二行\n处理：xxx')
        assert '\n' not in reason
        assert '第一行' in reason and '第二行' in reason

    def test_nonstandard_falls_back(self):
        """不符合格式的结论，整段作为原因，不应丢内容"""
        reason, action = excel_export.split_conclusion('就是电源坏了')
        assert reason == '就是电源坏了'
        assert action == ''

    def test_empty(self):
        assert excel_export.split_conclusion('') == ('', '')
        assert excel_export.split_conclusion(None) == ('', '')


# ---------------- 排序 ----------------

class TestOrdering:

    def test_status_order_pending_reported_resolved(self, tmp_data, seeded_rooms):
        seed([
            {'id': 'R001', 'room': 'A101', 'building': '教学楼A',
             'status': repair_log.STATUS_RESOLVED},
            {'id': 'R002', 'room': 'A101', 'building': '教学楼A',
             'status': repair_log.STATUS_PENDING},
            {'id': 'R003', 'room': 'A101', 'building': '教学楼A',
             'status': repair_log.STATUS_REPORTED},
        ])

        rows = read_sheet('故障总表')
        ids = [r[3] for r in rows if r and r[3] and str(r[3]).startswith('R')]
        assert ids == ['R002', 'R003', 'R001'], ids

    def test_grouped_by_building_then_room(self, tmp_data, seeded_rooms):
        seed([
            {'id': 'R001', 'building': '教学楼B', 'room': 'B201',
             'status': repair_log.STATUS_PENDING},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A201',
             'status': repair_log.STATUS_PENDING},
            {'id': 'R003', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING},
        ])

        rows = read_sheet('故障总表')
        ids = [r[3] for r in rows if r and r[3] and str(r[3]).startswith('R')]
        # 教学楼A 在前，其内 A101 先于 A201
        assert ids == ['R003', 'R002', 'R001'], ids

    def test_status_section_headers_present(self, tmp_data, seeded_rooms):
        seed([
            {'id': 'R001', 'room': 'A101', 'building': '教学楼A',
             'status': repair_log.STATUS_PENDING},
        ])
        rows = read_sheet('故障总表')
        text = ' '.join(str(c) for r in rows for c in r if c)
        assert '未报修' in text


# ---------------- 教室现状 ----------------

class TestCurrentStatus:

    def test_usable_and_broken_counts(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 60, 0)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
        ])

        rows = read_sheet('教室现状')
        row = [r for r in rows if r and r[1] == 'A101'][0]
        # 总数 60，未解决 1 台 → 可用 59
        assert row[2] == 60
        assert row[3] == 59
        assert row[4] == 1

    def test_resolved_does_not_count_as_broken(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 60, 0)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
        ])

        rows = read_sheet('教室现状')
        row = [r for r in rows if r and r[1] == 'A101'][0]
        assert row[4] == 0
        assert row[3] == 60

    def test_history_note_mentions_repeats(self, tmp_data, seeded_rooms):
        """同一教室多次损坏，备注要说明历史次数"""
        seed_rooms([('教学楼A', 'A101', 60, 0)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING},
        ])

        rows = read_sheet('教室现状')
        row = [r for r in rows if r and r[1] == 'A101'][0]
        note = str(row[6])
        assert '历史故障 2 次' in note
        assert '未解决 1' in note and '已解决 1' in note

    def test_placeholder_room_excluded(self, tmp_data, seeded_rooms):
        """「未填写」不是真实教室，不应出现在教室现状"""
        seed([
            {'id': 'R001', 'room': '未填写', 'status': repair_log.STATUS_PENDING},
        ])
        rows = read_sheet('教室现状')
        names = [r[1] for r in rows if r and r[1]]
        assert '未填写' not in names

    def test_no_negative_usable(self, tmp_data, seeded_rooms):
        """损坏数超过总数时，可用台数不应变成负数"""
        seed_rooms([('教学楼A', 'A101', 2, 0)])
        seed([
            {'id': f'R00{i}', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING}
            for i in range(1, 6)
        ])
        rows = read_sheet('教室现状')
        row = [r for r in rows if r and r[1] == 'A101'][0]
        assert row[3] >= 0


# ---------------- 损坏明细 ----------------

class TestDamageDetail:

    def test_only_unresolved(self, tmp_data, seeded_rooms):
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
        ])
        rows = read_sheet('损坏明细')
        ids = [r[2] for r in rows if r and r[2]]
        assert 'R001' in ids
        assert 'R002' not in ids, '已解决的机器不该出现在损坏明细'

    def test_has_time_and_reason(self, tmp_data, seeded_rooms):
        """每台不能用的机器都要有损坏时间和原因"""
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'time': '2026-10-15 09:30',
             'conclusion': '原因：电源损坏。\n处理：更换。',
             'status': repair_log.STATUS_PENDING},
        ])
        rows = read_sheet('损坏明细')
        row = [r for r in rows if r and r[2] == 'R001'][0]
        assert row[3] == '2026-10-15 09:30'
        assert '电源损坏' in str(row[4])

    def test_count_matches_status_sheet(self, tmp_data, seeded_rooms):
        """损坏明细条数应与教室现状的「不能用台数」合计一致"""
        seed_rooms([('教学楼A', 'A101', 60, 0)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_REPORTED},
            {'id': 'R003', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
        ])

        detail = read_sheet('损坏明细')
        n_detail = len([r for r in detail if r and r[2]])

        status = read_sheet('教室现状')
        row = [r for r in status if r and r[1] == 'A101'][0]
        assert n_detail == row[4] == 2

    def test_empty_when_all_resolved(self, tmp_data, seeded_rooms):
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
        ])
        rows = read_sheet('损坏明细')
        text = ' '.join(str(c) for r in rows for c in r if c)
        assert '没有未解决' in text


# ---------------- 故障统计 ----------------

class TestStatistics:

    def test_counts_by_room(self, tmp_data, seeded_rooms):
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED},
            {'id': 'R003', 'building': '教学楼A', 'room': 'A102',
             'status': repair_log.STATUS_RESOLVED},
        ])
        rows = read_sheet('故障统计')
        a101 = [r for r in rows if r and r[1] == 'A101'][0]
        assert a101[2] == 2      # 总次数
        assert a101[3] == 1      # 未解决
        assert a101[5] == 1      # 已解决

    def test_cause_distribution(self, tmp_data, seeded_rooms):
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'conclusion': '原因：电源损坏。\n处理：换。'},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'conclusion': '原因：电源损坏。\n处理：换。'},
            {'id': 'R003', 'building': '教学楼A', 'room': 'A101',
             'conclusion': '原因：网线松动。\n处理：插紧。'},
        ])
        rows = read_sheet('故障统计')
        row = [r for r in rows if r and r[1] == 'A101'][0]
        causes = str(row[6])
        assert '电源损坏。×2' in causes
        assert '网线松动。×1' in causes


# ---------------- 未录入台账 ----------------

class TestUnlinked:

    def test_orphan_records_preserved(self, tmp_data, seeded_rooms):
        """对不上台账的记录不丢失，进入独立工作表"""
        seed_rooms([('教学楼A', 'A101', 60, 0)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101'},
            {'id': 'R002', 'room': '999'},      # 台账里没有 999
        ])

        rows = read_sheet('未录入台账的故障')
        ids = [r[2] for r in rows if r and r[2]]
        assert 'R002' in ids
        assert 'R001' not in ids, '能对上台账的不该出现在这里'

    def test_all_linked_shows_placeholder(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 60, 0)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101'}])
        rows = read_sheet('未录入台账的故障')
        text = ' '.join(str(c) for r in rows for c in r if c)
        assert '都已对应' in text

    def test_building_backfilled_when_unambiguous(self, tmp_data, seeded_rooms):
        """教室号能唯一对上时，自动补全教学楼，便于分组"""
        seed_rooms([('教学楼A', 'A101', 60, 0)])
        seed([{'id': 'R001', 'room': 'A101'}])   # 没写教学楼

        recs = excel_export.normalize_records()
        assert recs[0]['building'] == '教学楼A'
        assert recs[0]['in_ledger'] is True


# ---------------- 工作簿整体 ----------------

class TestWorkbook:

    def test_all_sheets_present(self, tmp_data, seeded_rooms):
        _, data = excel_export.export_to_bytes()
        wb = load_workbook(io.BytesIO(data))
        for name in ['总览', '故障总表', '教室现状', '损坏明细',
                     '故障统计', '未录入台账的故障']:
            assert name in wb.sheetnames, f'缺少工作表 {name}'

    def test_filename_has_timestamp(self, tmp_data, seeded_rooms):
        filename, _ = excel_export.export_to_bytes()
        assert filename.startswith('机房故障报表_')
        assert filename.endswith('.xlsx')

    def test_empty_data_does_not_crash(self, tmp_data, seeded_rooms):
        """没有任何记录时也要能导出一份可用文件"""
        filename, data = excel_export.export_to_bytes()
        wb = load_workbook(io.BytesIO(data))
        assert '总览' in wb.sheetnames
        assert len(data) > 0
