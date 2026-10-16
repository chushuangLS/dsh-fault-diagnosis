"""
新增功能测试：损坏数量、可自修状态、批量登记

对应需求：
  1. AI 确定原因后追问损坏数量
  2. 一条记录可代表多台设备（数量字段）
  3. 新增「可自修」状态（非硬件问题、可自行修复）
  4. 「登记故障」表单可一次填多行
  5. 删除「手动登记损坏数」（台数只从报修台账推导）
"""

import pytest

import ai_diagnosis
import classroom
import repair_log


# ---------------- 数量解析 ----------------

class TestParseQuantity:

    @pytest.mark.parametrize('text,expect', [
        ('数量：3 台', 3),
        ('数量: 5', 5),
        ('这台教室有 12 台开不了机', 12),
        ('大概 7 台吧', 7),
        ('三台', 3),
        ('五台电脑', 5),
        ('十二台', 12),
        ('有十五台', 15),
    ])
    def test_parse(self, text, expect):
        assert ai_diagnosis.parse_quantity(text) == expect

    def test_defaults_to_one(self):
        """解析不出来时保守记为 1 台，不能是 0"""
        assert ai_diagnosis.parse_quantity('原因：电源坏了') == 1
        assert ai_diagnosis.parse_quantity('') == 1
        assert ai_diagnosis.parse_quantity(None) == 1

    def test_zero_not_allowed(self):
        assert ai_diagnosis.parse_quantity('数量：0 台') == 1


# ---------------- 状态常量 ----------------

class TestStatusConstants:

    def test_four_statuses(self):
        assert repair_log.ALL_STATUS == ['未报修', '可自修', '已报修', '已解决']

    def test_unresolved_includes_self_fix(self):
        """可自修也算"不能用" —— 自修完成前设备仍不可用"""
        assert repair_log.STATUS_SELF_FIX in repair_log.UNRESOLVED_STATUS
        assert repair_log.STATUS_RESOLVED not in repair_log.UNRESOLVED_STATUS

    def test_statistics_covers_every_status(self, tmp_data):
        """
        统计接口必须覆盖全部状态，各类相加要等于总数

        历史缺陷：app.py 里 by_status 是手写的固定映射，
        从三态扩到四态（新增「可自修」）时没有同步更新。
        结果看板上四类数字相加小于实际记录数（3+1+5=9，实际 11 条），
        状态分布图也少了一块。
        """
        import app as webapp

        # 四种状态各来一条
        for st in repair_log.ALL_STATUS:
            repair_log.add_record('A101', f'现象-{st}', '结论', status=st)

        client = webapp.app.test_client()
        resp = client.get('/api/statistics')
        assert resp.status_code == 200

        data = resp.get_json()
        by_status = data['by_status']

        # 每个状态都要有键，缺一个就说明映射又漏了
        for st in repair_log.ALL_STATUS:
            assert st in by_status, f'统计里缺少状态「{st}」'

        assert sum(by_status.values()) == data['total'], (
            f'各状态之和 {sum(by_status.values())} 与总数 {data["total"]} 不一致'
        )

    def test_legacy_status_is_migrated(self, tmp_data):
        """
        旧状态名「待自修」读取时自动归一为「可自修」

        历史 CSV 里可能存着旧值。若不归一，读出的状态不在 ALL_STATUS 中，
        会落到"未知状态"分支：排序排到最后、统计里也不计入。
        """
        old = '记录编号,时间,教学楼,教室,故障现象,诊断结论,状态,数量,备注\n'
        old += 'R001,2026-10-15 10:00,教学楼A,A101,网线松,原因：x,待自修,2,\n'
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(old)

        rec = repair_log.load_records()[0]
        assert rec['状态'] == '可自修'
        assert rec['状态'] in repair_log.ALL_STATUS
        assert repair_log.get_quantity(rec) == 2


# ---------------- 数量字段 ----------------

class TestQuantityField:

    def test_default_quantity_is_one(self, tmp_data):
        rid = repair_log.add_record('A101', '开不了机', '原因：电源')
        rec = repair_log.load_records()[0]
        assert rec['数量'] == '1'
        assert repair_log.get_quantity(rec) == 1

    def test_explicit_quantity(self, tmp_data):
        repair_log.add_record('A101', '开不了机', '原因：电源', quantity=5)
        assert repair_log.get_quantity(repair_log.load_records()[0]) == 5

    def test_invalid_quantity_falls_back_to_one(self, tmp_data):
        repair_log.add_record('A101', 'x', 'y', quantity='abc')
        assert repair_log.get_quantity(repair_log.load_records()[0]) == 1

    def test_zero_or_negative_becomes_one(self, tmp_data):
        repair_log.add_record('A101', 'x', 'y', quantity=0)
        repair_log.add_record('A101', 'x', 'y', quantity=-3)
        for r in repair_log.load_records():
            assert repair_log.get_quantity(r) == 1

    def test_old_record_without_quantity_column(self, tmp_data):
        """旧 CSV 没有「数量」列时，一律视为 1 台"""
        assert repair_log.get_quantity({'记录编号': 'R001'}) == 1
        assert repair_log.get_quantity({'数量': ''}) == 1

    def test_update_quantity(self, tmp_data):
        rid = repair_log.add_record('A101', 'x', 'y')
        ok, _ = repair_log.update_record(rid, quantity=4)
        assert ok
        assert repair_log.get_quantity(repair_log.load_records()[0]) == 4

    def test_count_machines_sums_quantity(self, tmp_data):
        repair_log.add_record('A101', 'a', 'x', quantity=3)
        repair_log.add_record('A101', 'b', 'x', quantity=2)
        recs = repair_log.load_records()
        assert repair_log.count_machines(recs) == 5

    def test_count_machines_by_status(self, tmp_data):
        repair_log.add_record('A101', 'a', 'x',
                              status=repair_log.STATUS_SELF_FIX, quantity=2)
        repair_log.add_record('A101', 'b', 'x',
                              status=repair_log.STATUS_RESOLVED, quantity=9)
        recs = repair_log.load_records()
        assert repair_log.count_machines(recs, [repair_log.STATUS_SELF_FIX]) == 2
        assert repair_log.count_machines(recs, [repair_log.STATUS_RESOLVED]) == 9


# ---------------- 旧文件迁移 ----------------

class TestMigration:

    def test_old_csv_without_quantity_migrates(self, tmp_data):
        """旧版 8 列 CSV（无数量列）应能自动迁移且不丢记录"""
        old = '记录编号,时间,教学楼,教室,故障现象,诊断结论,状态,备注\n'
        old += 'R001,2026-10-15 14:22,教学楼A,A101,开不了机,原因：电源,未报修,\n'
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(old)

        records = repair_log.load_records()
        assert len(records) == 1
        assert records[0]['教室'] == 'A101'
        assert repair_log.get_quantity(records[0]) == 1

    def test_migration_backfills_quantity_one(self, tmp_data):
        """
        迁移时必须把「数量」补成 1，不能留空

        留空会导致：读取时 get_quantity 兜底成 1，看起来没问题，
        但写回文件里是空值，任何按列直读的地方都会算成 0 台。
        """
        old = '记录编号,时间,教学楼,教室,故障现象,诊断结论,状态,备注\n'
        old += 'R001,2026-10-15 14:22,教学楼A,A101,开不了机,原因：电源,未报修,\n'
        old += 'R002,2026-10-15 14:23,教学楼A,A102,黑屏,原因：显卡,已解决,\n'
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(old)

        repair_log.load_records()          # 触发迁移

        # 直接读文件，确认落盘的「数量」列不是空的
        import csv
        with open(repair_log.RECORD_FILE, newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        assert all(r['数量'] == '1' for r in rows), rows

    def test_migration_preserves_all_rows(self, tmp_data):
        """迁移不能丢行 —— 这是数据安全底线"""
        old = '记录编号,时间,教学楼,教室,故障现象,诊断结论,状态,备注\n'
        for i in range(1, 6):
            old += f'R00{i},2026-10-15 14:2{i},教学楼A,A10{i},现象{i},原因{i},未报修,\n'
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(old)

        records = repair_log.load_records()
        assert len(records) == 5
        assert [r['记录编号'] for r in records] == ['R001', 'R002', 'R003', 'R004', 'R005']

    def test_migration_is_idempotent(self, tmp_data):
        """反复读取不应反复改写文件、也不应丢数据"""
        old = '记录编号,时间,教学楼,教室,故障现象,诊断结论,状态,备注\n'
        old += 'R001,2026-10-15 14:22,教学楼A,A101,开不了机,原因：电源,未报修,\n'
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(old)

        for _ in range(5):
            assert len(repair_log.load_records()) == 1

    def test_very_old_csv_without_building(self, tmp_data):
        """更旧的 7 列 CSV（无教学楼、无数量）也要兼容"""
        old = '记录编号,时间,教室,故障现象,诊断结论,状态,备注\n'
        old += 'R001,2026-10-15 14:22,208,开不了机,原因：电源,未报修,\n'
        with open(repair_log.RECORD_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            f.write(old)

        records = repair_log.load_records()
        assert records[0]['教室'] == '208'
        assert records[0]['教学楼'] == ''
        assert repair_log.get_quantity(records[0]) == 1


# ---------------- 批量登记 ----------------

class TestRegisterFaults:

    def test_register_multiple(self, tmp_data):
        n, ids, err = repair_log.register_faults('教学楼A', 'A101', [
            {'reason': '电源损坏', 'quantity': 3},
            {'reason': '网线松动', 'quantity': 1, 'status': '可自修'},
        ])
        assert err == ''
        assert n == 2
        assert len(ids) == 2

        recs = repair_log.load_records()
        assert len(recs) == 2
        assert repair_log.get_quantity(recs[0]) == 3
        assert recs[1]['状态'] == '可自修'

    def test_skips_empty_reason(self, tmp_data):
        n, ids, err = repair_log.register_faults('教学楼A', 'A101', [
            {'reason': '', 'quantity': 5},
            {'reason': '电源损坏', 'quantity': 2},
        ])
        assert n == 1
        assert len(repair_log.load_records()) == 1

    def test_all_empty_returns_error(self, tmp_data):
        n, ids, err = repair_log.register_faults('教学楼A', 'A101', [
            {'reason': '  ', 'quantity': 1},
        ])
        assert n == 0
        assert err

    def test_requires_classroom(self, tmp_data):
        n, ids, err = repair_log.register_faults('教学楼A', '', [
            {'reason': 'x', 'quantity': 1},
        ])
        assert n == 0
        assert '教室' in err

    def test_invalid_status_falls_back(self, tmp_data):
        repair_log.register_faults('教学楼A', 'A101', [
            {'reason': 'x', 'quantity': 1, 'status': '瞎写的状态'},
        ])
        assert repair_log.load_records()[0]['状态'] == repair_log.STATUS_PENDING

    def test_invalid_quantity_becomes_one(self, tmp_data):
        repair_log.register_faults('教学楼A', 'A101', [
            {'reason': 'x', 'quantity': 'abc'},
        ])
        assert repair_log.get_quantity(repair_log.load_records()[0]) == 1


# ---------------- 三种状态统计 ----------------

class TestThreeStateSummary:

    def test_flat_rooms_exposes_three_states(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 50)

        repair_log.add_record('A101', '电源坏', '原因：电源',
                              status=repair_log.STATUS_PENDING,
                              building='教学楼A', quantity=2)
        repair_log.add_record('A101', '网线松', '原因：网线',
                              status=repair_log.STATUS_SELF_FIX,
                              building='教学楼A', quantity=3)
        repair_log.add_record('A101', '修好了', '原因：x',
                              status=repair_log.STATUS_RESOLVED,
                              building='教学楼A', quantity=5)

        room = classroom.flat_rooms()[0]
        assert room['pending_pcs'] == 2
        assert room['self_fix_pcs'] == 3
        assert room['resolved_pcs'] == 5
        assert room['broken_pcs'] == 5        # 2 + 3（已解决不算）
        assert room['healthy_pcs'] == 45      # 50 - 5

    def test_summary_totals(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 50)

        repair_log.add_record('A101', 'x', '原因：x',
                              status=repair_log.STATUS_SELF_FIX,
                              building='教学楼A', quantity=4)

        s = classroom.summary()
        assert s['self_fix_pcs'] == 4
        assert s['broken_pcs'] == 4


# ---------------- 排序 ----------------

class TestStatusSortOrder:

    def test_order(self, tmp_data):
        repair_log.add_record('A101', 'a', 'x', status='已解决')
        repair_log.add_record('A101', 'b', 'x', status='已报修')
        repair_log.add_record('A101', 'c', 'x', status='可自修')
        repair_log.add_record('A101', 'd', 'x', status='未报修')

        ordered = [r['记录编号'] for r in
                   repair_log.sort_records(repair_log.load_records())]
        recs = {r['记录编号']: r['状态'] for r in repair_log.load_records()}
        assert [recs[i] for i in ordered] == ['未报修', '可自修', '已报修', '已解决']


# ---------------- 会话状态判定 ----------------

class TestStatusForSession:

    def test_need_repair(self):
        import app as appmod

        class S:
            need_repair = True
            self_fix = False
        assert appmod._status_for_session(S()) == repair_log.STATUS_PENDING

    def test_self_fix(self):
        import app as appmod

        class S:
            need_repair = False
            self_fix = True
        assert appmod._status_for_session(S()) == repair_log.STATUS_SELF_FIX

    def test_no_marker_defaults_to_pending(self):
        """AI 没打标记时保守记为未报修，避免故障被遗忘"""
        import app as appmod

        class S:
            need_repair = False
            self_fix = False
        assert appmod._status_for_session(S()) == repair_log.STATUS_PENDING
