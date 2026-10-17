"""
Excel 导出功能测试

导出设计：**给领导看的一页纸**
  只有一张表，一间教室一行，一眼看出每间教室的现状。

  列：教学楼 | 教室 | 设备总数 | 正常 | 损坏 | 损坏时间 | 损坏原因 | 教室设施故障

关键约定：
  · 未报修 / 可自修 / 已报修 → 损坏
  · 已解决                   → 正常
  这样「正常 + 损坏 = 设备总数」，领导能对上账。

  · 教室设施故障（总闸、交换机等）**不计入损坏台数** ——
    电脑本身没坏，坏的是教室的设备，单独一列展示。
"""

import csv
import io

import pytest
from openpyxl import load_workbook

import classroom
import excel_export
import repair_log


# ---------------- 辅助 ----------------

def seed(records):
    """写入若干报修记录"""
    repair_log.init_file()
    with open(repair_log.RECORD_FILE, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        for r in records:
            w.writerow([
                r['id'], r.get('time', '2026-10-15 10:00'),
                r.get('building', ''), r.get('room', ''),
                r.get('symptom', '现象'), r.get('conclusion', '原因：x\n处理：y'),
                r.get('status', repair_log.STATUS_PENDING),
                r.get('quantity', 1),
                r.get('target', repair_log.TARGET_PC),
                r.get('note', ''),
            ])


def seed_rooms(rooms):
    """rooms: [(教学楼, 教室, 总数)]"""
    for b, n, total in rooms:
        if not any(x['name'] == b for x in classroom.load()['buildings']):
            classroom.add_building(b)
        classroom.add_room(b, n, total)


def read_rows(data=None, include_total=False):
    """
    读出导出的数据行（跳过标题、时间、表头）

    参数：include_total - 是否包含最后的「合计」行
    """
    if data is None:
        _, data = excel_export.export_to_bytes()
    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    out = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        if row[0] is None and row[1] is None:
            continue
        if not include_total and row[0] == '合计':
            continue
        out.append(list(row))
    return out


def col(name):
    """
    按表头名取列序号（0-based）

    以前测试里直接写 row[col('损坏')]、row[col('损坏原因')]，一加列就全部错位。
    改成按名字查，加列不会再把测试搞坏。
    """
    return [c[0] for c in excel_export.COLS].index(name)


# ---------------- 工作簿结构 ----------------

class TestWorkbookStructure:

    def test_single_sheet_only(self, tmp_data, seeded_rooms):
        """只保留一张表 —— 领导不需要多张明细"""
        _, data = excel_export.export_to_bytes()
        wb = load_workbook(io.BytesIO(data))
        assert len(wb.sheetnames) == 1

    def test_headers(self, tmp_data, seeded_rooms):
        _, data = excel_export.export_to_bytes()
        wb = load_workbook(io.BytesIO(data))
        ws = wb.active
        headers = [ws.cell(row=3, column=i).value for i in range(1, 9)]
        assert headers == [c[0] for c in excel_export.COLS]

    def test_no_removed_sheets(self, tmp_data, seeded_rooms):
        """旧的多表设计已删除"""
        _, data = excel_export.export_to_bytes()
        wb = load_workbook(io.BytesIO(data))
        for old in ['总览', '故障总表', '损坏明细', '故障统计', '未录入台账的故障']:
            assert old not in wb.sheetnames

    def test_title_and_time_present(self, tmp_data, seeded_rooms):
        _, data = excel_export.export_to_bytes()
        ws = load_workbook(io.BytesIO(data)).active
        assert '机房设备运行现状' in str(ws['A1'].value)
        assert '统计时间' in str(ws['A2'].value)

    def test_filename(self, tmp_data, seeded_rooms):
        fn, _ = excel_export.export_to_bytes()
        assert fn.startswith('机房设备运行现状_')
        assert fn.endswith('.xlsx')


# ---------------- 一行一间教室 ----------------

class TestOneRowPerRoom:

    def test_each_room_gets_a_row(self, tmp_data, seeded_rooms):
        seed_rooms([
            ('教学楼A', 'A101', 80),
            ('教学楼A', 'A102', 80),
            ('实验楼B', '201', 40),
        ])
        rows = read_rows()
        rooms = [r[1] for r in rows]
        assert rooms == ['A101', 'A102', '201']

    def test_grouped_by_building(self, tmp_data, seeded_rooms):
        """同一教学楼的教室连续排列"""
        seed_rooms([
            ('教学楼A', 'A101', 80),
            ('教学楼B', 'B101', 80),
            ('教学楼A', 'A102', 80),
        ])
        rows = read_rows()
        # 教学楼A 的两间应排在一起
        buildings = [r[0] or '' for r in rows]
        non_empty = [b for b in buildings if b]
        assert non_empty == ['教学楼A', '教学楼B']

    def test_building_merged_vertically(self, tmp_data, seeded_rooms):
        """同一教学楼合并成一格，只显示一次"""
        seed_rooms([
            ('教学楼A', 'A101', 80),
            ('教学楼A', 'A102', 80),
            ('教学楼A', 'A103', 80),
        ])
        _, data = excel_export.export_to_bytes()
        ws = load_workbook(io.BytesIO(data)).active

        merges = [str(m) for m in ws.merged_cells.ranges]
        assert any(m.startswith('A4:A') for m in merges), merges

        # 合并后只有第一行有值
        assert ws.cell(row=4, column=1).value == '教学楼A'
        assert ws.cell(row=5, column=1).value is None


# ---------------- 状态归类 ----------------

class TestStatusMapping:
    """未报修 / 可自修 / 已报修 都算损坏；已解决 算正常"""

    @pytest.mark.parametrize('status', [
        repair_log.STATUS_PENDING,
        repair_log.STATUS_SELF_FIX,
        repair_log.STATUS_REPORTED,
    ])
    def test_unresolved_counts_as_broken(self, tmp_data, seeded_rooms, status):
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'status': status, 'quantity': 5}])

        row = read_rows()[0]
        assert row[col('损坏')] == 5            # 损坏
        assert row[col('正常')] == 75           # 正常 = 80 - 5

    def test_resolved_counts_as_healthy(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED, 'quantity': 5},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED, 'quantity': 3},
        ])

        row = read_rows()[0]
        assert row[col('损坏')] == 0            # 已解决不计损坏
        assert row[col('正常')] == 80           # 全算正常

    def test_normal_plus_broken_equals_total(self, tmp_data, seeded_rooms):
        """正常 + 损坏 = 总数（领导能对上账）"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING, 'quantity': 4},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_SELF_FIX, 'quantity': 2},
            {'id': 'R003', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_RESOLVED, 'quantity': 9},
        ])

        row = read_rows()[0]
        assert row[col('设备总数')] == 80
        assert row[col('正常')] + row[col('损坏')] == row[col('设备总数')]

    def test_multiple_faults_accumulate(self, tmp_data, seeded_rooms):
        """多条记录的台数累加"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_PENDING, 'quantity': 3},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'status': repair_log.STATUS_REPORTED, 'quantity': 2},
        ])
        assert read_rows()[0][4] == 5


# ---------------- 损坏原因 ----------------

class TestCauses:

    def test_dash_when_healthy(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 80)])
        assert read_rows()[0][col('损坏原因')] == '—'

    def test_reason_with_count(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'conclusion': '原因：电源供应器损坏，无法供电。\n处理：更换。',
               'quantity': 3}])

        cause = read_rows()[0][col('损坏原因')]
        assert '电源供应器损坏' in cause
        assert '×3' in cause

    def test_multiple_reasons_on_separate_lines(self, tmp_data, seeded_rooms):
        """多个原因各占一行，便于阅读"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'conclusion': '原因：电源损坏。\n处理：换。', 'quantity': 2},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'conclusion': '原因：网线松动。\n处理：插紧。', 'quantity': 1},
        ])

        cause = read_rows()[0][col('损坏原因')]
        lines = cause.split('\n')
        assert len(lines) == 2
        assert any('电源损坏' in x and '×2' in x for x in lines)
        assert any('网线松动' in x and '×1' in x for x in lines)

    def test_reason_is_shortened(self, tmp_data, seeded_rooms):
        """长句原因要压成短语，不能把表格撑爆"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{
            'id': 'R001', 'building': '教学楼A', 'room': 'A101',
            'conclusion': '原因：多台电脑按开机键无反应、指示灯不亮，'
                          '排查电源线与插座后仍无效，判断为机箱电源或供电线路故障\n'
                          '处理：报修。',
            'quantity': 3,
        }])

        cause = read_rows()[0][col('损坏原因')]
        # 应提取出真正的故障（电源相关），而不是整段叙述
        assert len(cause) < 30
        assert '电源' in cause


class TestShortenReason:
    """原因精简的单元测试"""

    @pytest.mark.parametrize('raw,expect_kw', [
        ('电源供应器损坏，无法供电。', '电源供应器损坏'),
        ('显示器本身故障，接其他机位也无画面。', '显示器'),
        ('教室总电源跳闸，导致整间教室电脑无法供电。', '跳闸'),
        ('外部供电已排除，判断为主机电源或主板故障。', '电源'),
        ('内存条接触不良', '内存条'),
    ])
    def test_shorten(self, raw, expect_kw):
        out = excel_export._shorten_reason(raw)
        assert expect_kw in out
        assert len(out) <= 22

    def test_empty(self):
        assert excel_export._shorten_reason('') == ''


# ---------------- 台账外教室 ----------------

class TestUnregisteredRooms:

    def test_room_not_in_ledger_still_listed(self, tmp_data, seeded_rooms):
        """记录里有、台账没有的教室也要列出，不能丢数据"""
        seed([{'id': 'R001', 'building': '教学楼A', 'room': '999',
               'quantity': 2}])
        rows = read_rows()
        rooms = [r[1] for r in rows]
        assert '999' in rooms

    def test_unknown_total_shows_dash(self, tmp_data, seeded_rooms):
        """台账未登记总数时用「—」，不能用 0（会被误读成没有设备）"""
        seed([{'id': 'R001', 'building': '教学楼A', 'room': '999',
               'quantity': 2}])
        row = [r for r in read_rows() if r[1] == '999'][0]
        assert row[col('设备总数')] == '—'
        assert row[col('损坏')] == 2


# ---------------- 合计行 ----------------

class TestTotalRow:

    def test_totals(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 80), ('教学楼A', 'A102', 60)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'quantity': 4}])

        total_row = read_rows(include_total=True)[-1]
        assert total_row[0] == '合计'
        assert total_row[col('设备总数')] == 140       # 80 + 60
        assert total_row[col('正常')] == 136       # 140 - 4
        assert total_row[col('损坏')] == 4

    def test_healthy_rate(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 100)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'quantity': 5}])
        assert '95.0%' in str(read_rows(include_total=True)[-1][col('损坏原因')])


# ---------------- 边界情况 ----------------

class TestEdgeCases:

    def test_empty_data(self, tmp_data, seeded_rooms):
        """没有任何记录时也要能打开"""
        fn, data = excel_export.export_to_bytes()
        wb = load_workbook(io.BytesIO(data))
        assert len(wb.sheetnames) == 1
        assert len(data) > 0

    def test_no_ledger_no_records(self, tmp_data, seeded_rooms):
        rows = read_rows()
        assert rows == [] or rows[-1][0] == '合计'

    def test_broken_exceeds_total(self, tmp_data, seeded_rooms):
        """损坏数超过总数时，正常数不应为负"""
        seed_rooms([('教学楼A', 'A101', 2)])
        seed([{'id': f'R00{i}', 'building': '教学楼A', 'room': 'A101'}
              for i in range(1, 6)])
        row = read_rows()[0]
        assert row[col('正常')] >= 0

    def test_placeholder_room_skipped(self, tmp_data, seeded_rooms):
        """「未填写」不是真实教室，不应占一行"""
        seed([{'id': 'R001', 'room': '未填写', 'quantity': 3}])
        rooms = [r[1] for r in read_rows() if r[0] != '合计']
        assert '未填写' not in rooms


# ---------------- 损坏时间 ----------------

class TestBrokenTime:
    """报表里「损坏」后面要跟一列「损坏时间」"""

    def test_time_column_present(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'time': '2026-10-15 09:30', 'quantity': 2}])
        row = read_rows()[0]
        assert row[col('损坏时间')] == '2026-10-15 09:30'

    def test_earliest_time_wins(self, tmp_data, seeded_rooms):
        """多条未解决记录时，取最早的那条 —— 问题是什么时候开始出现的"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'time': '2026-10-16 14:00', 'quantity': 1},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'time': '2026-10-14 08:05', 'quantity': 1},
        ])
        assert read_rows()[0][col('损坏时间')] == '2026-10-14 08:05'

    def test_no_damage_shows_dash(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 80)])
        assert read_rows()[0][col('损坏时间')] == '—'

    def test_resolved_not_counted_in_time(self, tmp_data, seeded_rooms):
        """已解决的记录不该占用损坏时间"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'time': '2026-10-01 08:00', 'quantity': 3,
               'status': repair_log.STATUS_RESOLVED}])
        assert read_rows()[0][col('损坏时间')] == '—'


# ---------------- 教室设施故障 ----------------

class TestFacilityFaults:
    """
    总闸、交换机这类教室级设备故障

    它们会让整间教室不能用，但**电脑本身没坏**。
    所以不能算进「损坏」台数，而是单独一列展示。
    """

    def test_facility_not_counted_as_broken(self, tmp_data, seeded_rooms):
        """总闸故障不应让"损坏"变成整间教室的台数"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'symptom': '整间教室没电', 'conclusion': '原因：总闸跳闸',
               'quantity': 80,
               'target': repair_log.TARGET_FACILITY}])

        row = read_rows()[0]
        assert row[col('损坏')] == 0, '设施故障被误算成电脑损坏'
        assert row[col('正常')] == 80

    def test_facility_shown_in_own_column(self, tmp_data, seeded_rooms):
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'symptom': '整间教室没电', 'conclusion': '原因：总闸跳闸',
               'target': repair_log.TARGET_FACILITY}])

        cell = str(read_rows()[0][col('教室设施故障')])
        assert '总闸' in cell

    def test_facility_and_pc_coexist(self, tmp_data, seeded_rooms):
        """设施故障与电脑故障同时存在时，两者各自统计"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([
            {'id': 'R001', 'building': '教学楼A', 'room': 'A101',
             'symptom': '内存坏了', 'conclusion': '原因：内存条损坏',
             'quantity': 3, 'target': repair_log.TARGET_PC},
            {'id': 'R002', 'building': '教学楼A', 'room': 'A101',
             'symptom': '教室没电', 'conclusion': '原因：总闸跳闸',
             'target': repair_log.TARGET_FACILITY},
        ])

        row = read_rows()[0]
        assert row[col('损坏')] == 3, '电脑损坏台数不对'
        assert '总闸' in str(row[col('教室设施故障')])

    def test_resolved_facility_not_shown(self, tmp_data, seeded_rooms):
        """已解决的设施故障不再提示"""
        seed_rooms([('教学楼A', 'A101', 80)])
        seed([{'id': 'R001', 'building': '教学楼A', 'room': 'A101',
               'conclusion': '原因：总闸跳闸', 'target': repair_log.TARGET_FACILITY,
               'status': repair_log.STATUS_RESOLVED}])
        assert read_rows()[0][col('教室设施故障')] == '—'
