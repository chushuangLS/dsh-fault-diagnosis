"""
故障分类与反复故障分析的测试

分类口径：按「故障现象」判，不按诊断结论。
  结论里会写一串鉴别诊断（"换线后显示器正常，问题在主机端"），
  拿它做关键词匹配会把分类带偏 —— 实测踩过这个坑。
"""

import pytest

import fault_category
import repair_log


class TestClassifyText:

    @pytest.mark.parametrize('text,expect', [
        ('电脑指示灯不亮', fault_category.CATEGORY_POWER),
        ('电脑打不开', fault_category.CATEGORY_POWER),
        ('插座无电', fault_category.CATEGORY_POWER),
        ('内存条松动', fault_category.CATEGORY_MEMORY),
        ('硬盘故障', fault_category.CATEGORY_STORAGE),
        ('主板故障', fault_category.CATEGORY_BOARD),
        ('风扇异响', fault_category.CATEGORY_COOLING),
        ('电脑没画面', fault_category.CATEGORY_DISPLAY),
        ('黑屏无信号', fault_category.CATEGORY_DISPLAY),
        ('没有网络', fault_category.CATEGORY_NETWORK),
        ('网线松动', fault_category.CATEGORY_NETWORK),
        ('键盘失灵', fault_category.CATEGORY_PERIPHERAL),
        ('系统故障需重装', fault_category.CATEGORY_SYSTEM),
        ('投影仪无信号', fault_category.CATEGORY_PROJECTOR),
        ('音响没声音', fault_category.CATEGORY_AUDIO),
        ('打印机卡纸', fault_category.CATEGORY_PRINT),
        ('教室总闸跳闸', fault_category.CATEGORY_FACILITY),
        ('空调打不开了', fault_category.CATEGORY_FACILITY),
        ('教室没电', fault_category.CATEGORY_FACILITY),
        ('完全看不懂的描述xyz', fault_category.CATEGORY_OTHER),
    ])
    def test_keyword_mapping(self, text, expect):
        assert fault_category.classify_text(text) == expect

    def test_empty_text(self):
        assert fault_category.classify_text('') == fault_category.CATEGORY_OTHER
        assert fault_category.classify_text(None) == fault_category.CATEGORY_OTHER


class TestClassifyRecord:
    """整条记录的分类"""

    def test_facility_target_wins(self):
        """
        故障对象是「教室设施」时，不管现象写的是什么，都归教室设施

        否则会出现"故障对象是设施、分类却是网络故障"这种自相矛盾。
        """
        rec = {'故障现象': '没有网络', '诊断结论': '',
               '故障对象': repair_log.TARGET_FACILITY}
        assert fault_category.classify(rec) == fault_category.CATEGORY_FACILITY

    def test_pc_target_uses_symptom(self):
        rec = {'故障现象': '内存条松动', '诊断结论': '',
               '故障对象': repair_log.TARGET_PC}
        assert fault_category.classify(rec) == fault_category.CATEGORY_MEMORY

    def test_symptom_beats_conclusion(self):
        """
        现象与结论冲突时以现象为准

        这是踩过的坑：结论里会提到"显示器""主板"等排除项，
        按结论匹配会把「电脑打不开」误判成显示故障或主板故障。
        """
        rec = {
            '故障现象': '电脑打不开',
            '诊断结论': '原因：换线后显示器正常，判断为电源供应器或主板供电故障',
            '故障对象': repair_log.TARGET_PC,
        }
        assert fault_category.classify(rec) == fault_category.CATEGORY_POWER

    def test_vague_symptom_falls_back_to_conclusion(self):
        """现象太模糊时退回看结论"""
        rec = {
            '故障现象': '坏了',
            '诊断结论': '原因：硬盘磁头损坏',
            '故障对象': repair_log.TARGET_PC,
        }
        assert fault_category.classify(rec) == fault_category.CATEGORY_STORAGE

    def test_none_record(self):
        assert fault_category.classify(None) == fault_category.CATEGORY_OTHER


class TestRepeatedFaults:
    """反复故障：同一教室 + 同一分类累计 ≥3 次"""

    def _add(self, room, symptom, status=repair_log.STATUS_PENDING,
             building='实验楼A', time_note=''):
        return repair_log.add_record(
            classroom=room, symptom=symptom, conclusion='原因：x',
            status=status, building=building)

    def test_below_threshold_hidden(self, tmp_data):
        """2 次不列出来"""
        self._add('101', '内存条松动')
        self._add('101', '内存条松动')
        assert repair_log.repeated_faults() == []

    def test_at_threshold_listed(self, tmp_data):
        """3 次就列出来"""
        for _ in range(3):
            self._add('101', '内存条松动')

        out = repair_log.repeated_faults()
        assert len(out) == 1
        assert out[0]['room'] == '101'
        assert out[0]['category'] == fault_category.CATEGORY_MEMORY
        assert out[0]['count'] == 3

    def test_different_rooms_not_merged(self, tmp_data):
        """不同教室的同类故障不能合并计数"""
        for _ in range(2):
            self._add('101', '内存条松动')
        for _ in range(2):
            self._add('102', '内存条松动')
        assert repair_log.repeated_faults() == []

    def test_different_categories_not_merged(self, tmp_data):
        """同一教室的不同分类不能合并计数"""
        self._add('101', '内存条松动')
        self._add('101', '硬盘故障')
        self._add('101', '主板故障')
        assert repair_log.repeated_faults() == []

    def test_facility_grouped_separately(self, tmp_data):
        """教室设施故障单独成组，不与电脑故障混在一起"""
        for _ in range(3):
            self._add('101', '教室总闸跳闸',
                      building='实验楼A')
        # 需要把这三条标成设施故障
        for r in repair_log.load_records():
            repair_log.update_record(r['记录编号'],
                                     **{'故障对象': repair_log.TARGET_FACILITY})

        out = repair_log.repeated_faults()
        assert len(out) == 1
        assert out[0]['category'] == fault_category.CATEGORY_FACILITY

    def test_recur_counts_resolved_then_new(self, tmp_data):
        """
        复发 = 上一条已解决之后又出现

        这里 3 条：已解决 → 已解决 → 新建，复发应为 2。
        """
        ids = [self._add('101', '内存条松动') for _ in range(3)]
        repair_log.update_status(ids[0], repair_log.STATUS_RESOLVED)
        repair_log.update_status(ids[1], repair_log.STATUS_RESOLVED)

        out = repair_log.repeated_faults()
        assert out[0]['recur'] == 2
        assert out[0]['recurring'] is False   # 门槛是 4，还不够

    def test_recurring_requires_four(self, tmp_data):
        """复发门槛 4 次 —— 累计至少 5 条才可能达标"""
        ids = [self._add('101', '内存条松动') for _ in range(5)]
        for i in range(4):
            repair_log.update_status(ids[i], repair_log.STATUS_RESOLVED)

        out = repair_log.repeated_faults()
        assert out[0]['count'] == 5
        assert out[0]['recur'] == 4
        assert out[0]['recurring'] is True

    def test_sorted_by_count_desc(self, tmp_data):
        for _ in range(5):
            self._add('101', '内存条松动')
        for _ in range(3):
            self._add('102', '硬盘故障')

        out = repair_log.repeated_faults()
        assert [x['count'] for x in out] == [5, 3]

    def test_skips_unfilled_room(self, tmp_data):
        """教室号未填写的记录不参与统计"""
        for _ in range(3):
            self._add('未填写', '内存条松动')
        assert repair_log.repeated_faults() == []

    def test_span_days(self, tmp_data):
        """时间跨度按首末记录算"""
        for _ in range(3):
            self._add('101', '内存条松动')
        out = repair_log.repeated_faults()
        # 测试里三分钟就建完了，跨度应为 0 天
        assert out[0]['span_days'] == 0
        assert out[0]['first_time']
        assert out[0]['last_time']
