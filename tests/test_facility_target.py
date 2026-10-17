"""故障对象（电脑 / 教室设施）与安全提示的回归测试"""
import csv
import sys

sys.stdout.reconfigure(encoding='utf-8')

import pytest

import ai_diagnosis
import classroom
import repair_log


class TestTargetField:
    """故障对象字段：电脑 / 教室设施"""

    def test_default_is_pc(self, tmp_data):
        rid = repair_log.add_record('A101', '内存坏了', '原因：x')
        rec = [r for r in repair_log.load_records() if r['记录编号'] == rid][0]
        assert rec['故障对象'] == repair_log.TARGET_PC
        assert repair_log.is_facility(rec) is False

    def test_facility_record(self, tmp_data):
        rid = repair_log.add_record(
            'A101', '整间没电', '原因：总闸跳闸',
            target=repair_log.TARGET_FACILITY)
        rec = [r for r in repair_log.load_records() if r['记录编号'] == rid][0]
        assert repair_log.is_facility(rec) is True

    def test_facility_quantity_forced_to_one(self, tmp_data):
        """
        设施故障不是按台算的

        如果不强制成 1，一条"整间停电 80 台"的记录会污染台数统计。
        """
        rid = repair_log.add_record(
            'A101', '整间没电', '原因：总闸跳闸',
            quantity=80, target=repair_log.TARGET_FACILITY)
        rec = [r for r in repair_log.load_records() if r['记录编号'] == rid][0]
        assert repair_log.get_quantity(rec) == 1

    def test_unknown_target_falls_back_to_pc(self, tmp_data):
        rid = repair_log.add_record('A101', 'x', 'y', target='乱七八糟')
        rec = [r for r in repair_log.load_records() if r['记录编号'] == rid][0]
        assert rec['故障对象'] == repair_log.TARGET_PC

    def test_legacy_rows_default_to_pc(self, tmp_data):
        """
        旧 CSV 没有「故障对象」列，读取时应按电脑处理

        迁移时补 '电脑'，避免旧数据落到"未知"分支被漏统计。
        """
        legacy = ('记录编号,时间,教学楼,教室,故障现象,诊断结论,状态,数量,备注\n'
                  'R001,2026-10-15 10:00,教学楼A,A101,旧数据,原因：x,未报修,2,\n')
        with open(repair_log.RECORD_FILE, 'w', newline='',
                  encoding='utf-8-sig') as f:
            f.write(legacy)

        rec = repair_log.load_records()[0]
        assert rec['故障对象'] == repair_log.TARGET_PC
        assert repair_log.is_facility(rec) is False


class TestInferTarget:
    """从现象/结论推断故障对象"""

    @pytest.mark.parametrize('symptom,conclusion', [
        ('整间教室没电', '原因：总闸跳闸'),
        ('教室跳闸了', '原因：空气开关跳闸'),
        ('交换机坏了', '原因：交换机端口故障'),
        ('投影不亮', '原因：投影仪电源故障'),
        ('教室空调不制冷', '原因：空调缺氟'),
    ])
    def test_facility_detected(self, symptom, conclusion):
        assert ai_diagnosis.infer_target(symptom, conclusion) == '教室设施'

    @pytest.mark.parametrize('symptom,conclusion', [
        ('电脑开不了机', '原因：电源线松了'),
        ('内存条坏了', '原因：内存条接触不良'),
        ('显示器黑屏', '原因：视频线没插紧'),
    ])
    def test_pc_detected(self, symptom, conclusion):
        assert ai_diagnosis.infer_target(symptom, conclusion) == '电脑'

    def test_marker_takes_precedence(self):
        """AI 明确输出了标记时，以标记为准"""
        assert ai_diagnosis.infer_target(
            '电脑打不开', f'原因：x {ai_diagnosis.FACILITY_MARKER}'
        ) == '教室设施'


class TestFacilityNotCountedAsBroken:
    """设施故障不能算进教室的电脑损坏台数"""

    def test_classroom_stats_exclude_facility(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)

        repair_log.add_record('A101', '内存坏了', '原因：内存条损坏',
                              building='教学楼A', quantity=3)
        repair_log.add_record('A101', '整间没电', '原因：总闸跳闸',
                              building='教学楼A', quantity=80,
                              target=repair_log.TARGET_FACILITY)

        room = classroom.buildings_with_stats()['buildings'][0]['rooms'][0]
        assert room['broken'] == 3, '设施故障被算进了电脑损坏台数'
        assert room['healthy'] == 77
        assert room['facility_count'] == 1

    def test_summary_excludes_facility(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)

        repair_log.add_record('A101', '整间没电', '原因：总闸跳闸',
                              building='教学楼A', quantity=80,
                              target=repair_log.TARGET_FACILITY)

        s = classroom.summary()
        assert s['broken_pcs'] == 0, '设施故障不应计入损坏电脑台数'
        assert s['facility_rooms'] == 1
        assert s['facility_issues'] == 1

    def test_flat_rooms_exposes_facility(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)
        repair_log.add_record('A101', '整间没电', '原因：总闸跳闸',
                              building='教学楼A',
                              target=repair_log.TARGET_FACILITY)

        r = classroom.flat_rooms()[0]
        assert r['facility_count'] == 1
        assert r['facility_issues'][0]['symptom'] == '整间没电'

    def test_resolved_facility_not_listed(self, tmp_data):
        classroom.add_building('教学楼A')
        classroom.add_room('教学楼A', 'A101', 80)
        repair_log.add_record('A101', '整间没电', '原因：总闸跳闸',
                              building='教学楼A',
                              status=repair_log.STATUS_RESOLVED,
                              target=repair_log.TARGET_FACILITY)

        assert classroom.summary()['facility_rooms'] == 0


class TestSafetyPrompt:
    """
    总闸相关的安全约束

    真实使用中发现：AI 曾经让学生反复推闸。
    短路状态下反复合闸可能产生电弧甚至火灾，必须约束住。
    """

    def test_prompt_forbids_repeated_breaker_reset(self):
        p = ai_diagnosis.SYSTEM_PROMPT
        assert '不要再反复推闸' in p
        assert '只允许让用户推一次' in p

    def test_prompt_lists_electrical_warnings(self):
        p = ai_diagnosis.SYSTEM_PROMPT
        for kw in ['焦糊味', '冒烟', '发烫', '漏电']:
            assert kw in p, f'提示词里缺少电气安全提示：{kw}'

    def test_breaker_not_listed_as_self_fixable_forever(self):
        """
        「总闸跳闸，合闸即可」不能再作为无条件的自修项

        必须带上"推一次就恢复"的限定，否则 AI 会让学生反复推闸。
        """
        p = ai_diagnosis.SYSTEM_PROMPT
        assert '教室总闸跳闸，合闸即可' not in p
        assert '推一次就恢复正常' in p

    def test_facility_marker_defined(self):
        assert ai_diagnosis.FACILITY_MARKER == '【教室设施】'

    def test_clean_markers_removes_facility_marker(self):
        raw = f'原因：总闸跳闸 {ai_diagnosis.FACILITY_MARKER}'
        cleaned = ai_diagnosis.clean_markers(raw)
        assert ai_diagnosis.FACILITY_MARKER not in cleaned
        assert '总闸跳闸' in cleaned
