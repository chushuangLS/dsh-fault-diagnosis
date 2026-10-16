"""
知识库模块测试

覆盖三类容易出错、且历史上真的出过错的地方：
  1. 分类推断（曾把"风扇声音大"判成音频故障）
  2. 检索匹配（曾因切分粒度不一致，新案例搜不到）
  3. 自动沉淀与手工数据分离（曾写脏受 git 跟踪的手工文件）
"""

import json
import os

import pytest

import knowledge


# ---------------- 分类推断 ----------------

class TestInferCategory:
    """分类推断：规则顺序与关键词覆盖"""

    @pytest.mark.parametrize('text,expect', [
        # 开机 / 电源类
        ('电脑开不了机', '开机故障'),
        ('按电源没反应', '开机故障'),
        ('电脑频繁自动关机', '开机故障'),
        ('电脑自动断电重启', '开机故障'),
        ('主板烧了', '开机故障'),
        ('内存条松动', '开机故障'),
        # 历史 bug：'声音' 关键词过宽，把风扇噪音吸到音频类
        ('风扇声音特别大', '开机故障'),
        ('主机声音很响', '开机故障'),
        ('机箱风扇噪音大', '开机故障'),
        # 音频类（不能被外设抢走）
        ('音箱没有声音', '音频故障'),
        ('耳机没声音', '音频故障'),
        ('话筒有杂音', '音频故障'),
        # 其他常见类
        ('整间教室断网', '网络故障'),
        ('投影仪没信号', '投影故障'),
        ('显示器黑屏', '显示故障'),
        ('电脑蓝屏', '系统故障'),
        ('键盘打不出字', '外设故障'),
        ('打印机卡纸', '打印故障'),
    ])
    def test_category(self, text, expect):
        assert knowledge._infer_category(text) == expect

    def test_case_insensitive(self):
        """英文词应大小写不敏感（USB / usb / CPU）"""
        assert knowledge._infer_category('usb设备识别不到') == '外设故障'
        assert knowledge._infer_category('USB设备识别不到') == '外设故障'

    def test_unknown_falls_back(self):
        """完全无法判断时归入「其他故障」，而不是抛异常"""
        assert knowledge._infer_category('今天天气不错') == '其他故障'


# ---------------- 检索 ----------------

class TestSearch:
    """检索：同义表达、粒度差异、假阳性"""

    def test_direct_hit(self, seeded_knowledge):
        hits = knowledge.search('电脑开不了机')
        assert hits and hits[0]['id'] == 'PC-001'

    @pytest.mark.parametrize('query', [
        '整间教室断网',
        '教室上不了网',
        '整个教室无法上网',
        '教室里电脑连不上网',
    ])
    def test_synonym_queries(self, seeded_knowledge, query):
        """不同意说法应都能命中网络类案例（同义词归一）"""
        hits = knowledge.search(query)
        assert hits, f'{query!r} 应有匹配'
        assert hits[0]['id'] == 'NET-001', f'{query!r} 命中了 {hits[0]["id"]}'

    def test_no_match_returns_empty(self, seeded_knowledge):
        """完全无关的描述不应硬凑结果"""
        assert knowledge.search('食堂的饭不好吃') == []

    def test_false_positive_guarded(self, seeded_knowledge):
        """
        不应只因「原因」里偶然撞上一个泛词就判定相关

        历史 bug：NET-001 的原因含"交换机断电或故障"，
        查"电脑自动关机"时因共享"断电/关机"而误命中网络类。
        """
        hits = knowledge.search('电脑自动关机')
        ids = [h['id'] for h in hits]
        assert not any(i.startswith('NET') for i in ids), f'误命中网络类: {ids}'

    def test_empty_query(self, seeded_knowledge):
        assert knowledge.search('') == []


# ---------------- 自动沉淀 ----------------

class TestSediment:
    """自动沉淀：写入位置、去重、编号"""

    SYM = '机房空调漏水导致地板大面积湿滑'
    CONC = '原因：空调排水管堵塞。\n处理：联系后勤疏通排水管。'

    def test_writes_to_auto_file_only(self, seeded_knowledge):
        """沉淀必须写 auto 文件，绝不能改动手工文件"""
        import knowledge as k
        before = open(k.MANUAL_FILE, encoding='utf-8').read()

        ok, cid = k.save_case(symptom=self.SYM, conclusion=self.CONC)
        assert ok, cid

        after = open(k.MANUAL_FILE, encoding='utf-8').read()
        assert before == after, '手工知识库被程序改写了！'
        assert os.path.exists(k.AUTO_FILE)

    def test_new_case_is_searchable(self, seeded_knowledge):
        """刚沉淀的案例应当能立刻被检索到（历史 bug：搜不到）"""
        ok, cid = knowledge.save_case(symptom=self.SYM, conclusion=self.CONC)
        assert ok

        for q in ['空调漏水', '机房空调漏水', '漏水']:
            ids = [h['id'] for h in knowledge.search(q)]
            assert cid in ids, f'{q!r} 未检索到新沉淀的 {cid}'

    def test_dedup(self, seeded_knowledge):
        """高度相似的现象不应重复沉淀"""
        ok1, _ = knowledge.save_case(symptom=self.SYM, conclusion=self.CONC)
        ok2, msg2 = knowledge.save_case(symptom=self.SYM, conclusion=self.CONC)
        assert ok1
        assert not ok2, '重复沉淀未被拦截'

    def test_id_no_collision_with_manual(self, seeded_knowledge):
        """自动编号要避让手工案例，不能重号"""
        knowledge.save_case(symptom='按开机键毫无反应完全没有电', conclusion='原因：电源坏。\n处理：换电源。')
        ids = [c['id'] for c in knowledge._load_raw()['cases']]
        assert len(ids) == len(set(ids)), f'出现重号: {ids}'

    def test_manual_takes_precedence_on_id_conflict(self, seeded_knowledge):
        """id 冲突时以手工版本为准"""
        with open(knowledge.AUTO_FILE, 'w', encoding='utf-8') as f:
            json.dump({'version': '0.1.0', 'cases': [
                {'id': 'PC-001', 'category': '伪造', 'symptom': '应被忽略',
                 'causes': [], 'steps': [], 'source': 'auto'}
            ]}, f, ensure_ascii=False)

        merged = knowledge._load_raw()['cases']
        pc001 = [c for c in merged if c['id'] == 'PC-001']
        assert len(pc001) == 1
        assert pc001[0]['category'] == '开机故障'

    def test_empty_input_rejected(self, seeded_knowledge):
        ok, _ = knowledge.save_case(symptom='', conclusion='原因：x')
        assert not ok
        ok, _ = knowledge.save_case(symptom='有现象', conclusion='')
        assert not ok


# ---------------- 统计与容错 ----------------

class TestStatsAndRobustness:

    def test_stats_counts(self, seeded_knowledge):
        s = knowledge.stats()
        assert s['total'] == 3
        assert s['manual_file'] == 3
        assert s['auto_file'] == 0

        knowledge.save_case(symptom='机房空调漏水导致地板湿滑', conclusion='原因：堵。\n处理：通。')
        s2 = knowledge.stats()
        assert s2['total'] == 4
        assert s2['auto'] == 1

    def test_corrupt_manual_file_does_not_crash(self, tmp_data):
        """手工文件损坏时不应让整个模块崩溃"""
        with open(knowledge.MANUAL_FILE, 'w', encoding='utf-8') as f:
            f.write('{ 这不是合法 JSON')

        # 读取应返回空结构而不是抛异常
        data = knowledge._load_raw()
        assert data['cases'] == []

    def test_missing_files(self, tmp_data):
        """文件都不存在时应返回空知识库"""
        s = knowledge.stats()
        assert s['total'] == 0
