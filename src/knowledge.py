"""
机房故障智能诊断助手 - 故障知识库（检索增强 + 自动沉淀）

解决的三个问题：
  1. 原来的做法是把全部案例塞进提示词 —— 案例一多就浪费 token
  2. 每次诊断都要 AI 现场推理 —— 常见故障重复推理，成本高
  3. 知识库靠手工维护 —— 实际用起来没人愿意维护

本模块的做法：
  检索：根据用户描述，用关键词权重匹配出最相似的 Top-N 案例
  注入：只把这几个案例放进提示词（而不是全部）
  沉淀：诊断结束后，自动把结论提取成结构化的新案例存回知识库

检索算法说明（不依赖向量库，纯本地、零成本）：
  · 对每个案例提取「特征词」：分类名、现象、原因中的中文词
  · 计算用户输入与案例特征词的重合度
  · 分类命中权重最高，现象次之，原因再次
  · 按得分排序，取 Top-N

作者：liyishuo1
"""

import json
import os
import re
from datetime import datetime

from filelock import file_lock

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# 手工维护的知识库（提交进 git，人工编辑、评审、回滚）
MANUAL_FILE = os.path.join(DATA_DIR, 'fault_cases.json')

# 程序自动沉淀的案例（git 忽略，纯运行时数据）
#
# 为什么要拆成两个文件：
#   原先自动沉淀直接追加到 fault_cases.json，而该文件是 git 跟踪的，
#   导致每跑一次诊断就产生 diff —— 手工积累的知识和机器生成的数据
#   混在一起，既无法单独评审，也会在多人协作时互相冲突。
#   拆分后：人能改的归人能管，机器写的归机器管。
AUTO_FILE = os.path.join(DATA_DIR, 'fault_cases_auto.json')

# 检索时最多返回几条案例
TOP_N = 3

# 得分阈值：低于这个分数认为"不相关"，不注入提示词
MIN_SCORE = 1.0


def _empty():
    return {'version': '0.1.0', 'description': '机房故障知识库', 'cases': []}


def _read_file(path):
    """读取单个知识库文件，失败返回空结构"""
    if not os.path.exists(path):
        return _empty()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('cases', [])
        return data
    except Exception:
        # 读取失败不应让整个知识库不可用 —— 另一个文件仍可能正常
        return _empty()


def _load_raw():
    """
    读取知识库（手工 + 自动沉淀合并）

    合并规则：
      · 两个文件的案例合在一起参与检索
      · 若 id 重复，以「手工文件」为准（人工维护的内容优先级更高）
    """
    manual = _read_file(MANUAL_FILE)
    auto = _read_file(AUTO_FILE)

    manual_cases = manual.get('cases', [])
    auto_cases = auto.get('cases', [])

    seen = {c.get('id') for c in manual_cases}
    merged = list(manual_cases)
    for c in auto_cases:
        if c.get('id') not in seen:
            merged.append(c)

    return {
        'version': manual.get('version', '0.1.0'),
        'description': manual.get('description', '机房故障知识库'),
        'cases': merged,
    }


def _load_auto():
    """只读自动沉淀文件（写入时用，避免把手工数据一起写回去）"""
    return _read_file(AUTO_FILE)


def _write_auto(data):
    """
    写回自动沉淀文件

    注意：只写 AUTO_FILE，绝不写 MANUAL_FILE ——
    手工知识库只应由人修改，程序不得覆盖。
    """
    os.makedirs(os.path.dirname(AUTO_FILE), exist_ok=True)
    with open(AUTO_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- 分词（简易实现） ----------------

# 停用词：这些词太常见，不能作为匹配依据
STOP_WORDS = {
    '的', '了', '是', '在', '有', '和', '就', '都', '而', '及', '与',
    '着', '或', '一个', '没有', '我们', '你们', '他们', '这', '那',
    '电脑', '教室', '机房', '问题', '情况', '一下', '什么', '怎么',
}

# 关键特征词：这些词出现说明故障类型明确，权重更高
KEY_TERMS = {
    # 开机类
    '开机': 3.0, '开机键': 3.0, '打不开': 2.5, '开不了机': 3.0,
    '不通电': 3.0, '没反应': 2.0, '重启': 2.5, '反复重启': 3.5,
    # 显示类
    '蓝屏': 3.0, '黑屏': 3.0, '花屏': 3.5, '条纹': 3.0, '无信号': 3.0,
    '分辨率': 2.5, '模糊': 2.5, '偏色': 3.0, '显示器': 3.0, '屏幕': 2.0,
    # 系统类
    '死机': 3.0, '卡': 1.5, '卡顿': 2.5, '很卡': 2.5, '慢': 1.5,
    '进不去': 2.5, '启动界面': 2.5, '系统': 2.0, '重装': 2.5,
    '病毒': 2.5, '广告': 3.0, '弹窗': 3.0, '主页': 2.5, '劫持': 3.0,
    # 网络类
    '上网': 3.0, '断网': 3.0, '断断续续': 3.5, '掉线': 3.0,
    '网络': 2.5, '网线': 2.5, '网口': 2.5, '连不上': 2.5, '网速': 2.5,
    '交换机': 3.0, '路由器': 2.5,
    # 投影类
    '投影': 3.0, '投影仪': 3.0, '投影机': 3.0, '亮度': 2.5, '灯泡': 2.5,
    # 外设类
    '鼠标': 3.0, '键盘': 3.0, 'U盘': 3.0, 'usb': 2.5, '识别不到': 2.5,
    '音响': 2.5, '音箱': 2.5, '耳机': 2.5, '话筒': 3.0, '麦克风': 3.0,
    '声音': 2.0, '杂音': 3.0, '电流声': 3.0,
    # 打印类
    '打印机': 3.0, '卡纸': 3.5, '脱机': 3.0, '不出纸': 3.0, '墨盒': 2.5,
    # 硬件部件
    '电源': 2.5, '主板': 2.5, '内存': 2.5, '硬盘': 2.5, '显卡': 2.5,
}

# 同义词归一表：把不同说法映射到同一个「标准词」
#
# 为什么需要：
#   用户说"整间教室断网"，知识库里写的是"无法上网"。
#   两边指的是同一件事，但字面完全没有重合 —— 检索得分是 0，等于没匹配上。
#
#   加了这张表后，无论哪种说法都会被归一成标准词（如"上网"），
#   再参与匹配，同义表达就能互相命中了。
#
# 维护方式：key 是标准词，value 是它的各种常见说法（标准词本身会自动包含）。
SYNONYMS = {
    '上网': ['断网', '上不了网', '无法上网', '不能上网', '连不上网', '没有网', '没网', '无网'],
    '开机': ['开不了机', '打不开', '无法开机', '不能开机', '开不起', '点不亮'],
    '黑屏': ['无显示', '没显示', '屏幕黑', '不显示', '没画面', '无画面'],
    '无信号': ['没有信号', '无输入', '没信号', '检测不到信号'],
    '重启': ['自动重启', '反复重启', '不断重启', '重启了'],
    '关机': ['自动关机', '关了机', '关机了', '自己关了'],
    # 注意：不要把「断电」并进「关机」——
    #   "交换机断电"（网络原因）与"电脑自动关机"（主机原因）是两回事，
    #   合并后会让查"自动关机"误命中网络类案例。
    #   断电单独作为电源类标准词，归到「不通电」一组。
    '不通电': ['断电', '自动断电', '掉电', '没电'],
    '死机': ['卡死', '不动了', '没反应了', '假死'],
    '卡顿': ['很卡', '特别卡', '卡慢', '慢'],
    '投影仪': ['投影', '投影机'],
    '音响': ['音箱', '喇叭', '扬声器'],
    '麦克风': ['话筒', '麦'],
    '鼠标': ['鼠标器'],
    '键盘': ['键盘失灵'],
    'U盘': ['优盘', 'u盘', '闪存盘'],
    '打印机': ['打印'],
    '显示器': ['屏幕', '显示屏'],
}

# 反向索引：说法 -> 标准词（在模块加载时构建一次）
_SYNONYM_LOOKUP = {}
for _std, _variants in SYNONYMS.items():
    _SYNONYM_LOOKUP[_std] = _std
    for _v in _variants:
        _SYNONYM_LOOKUP[_v] = _std


def _normalize_terms(terms):
    """
    把特征词里的各种说法归一成标准词

    例如输入含 '断网' → 输出含 '上网'；
    这样"断网"和"无法上网"就能互相匹配上了。
    """
    out = set(terms)
    for t in terms:
        std = _SYNONYM_LOOKUP.get(t)
        if std:
            out.add(std)
    return out


def _extract_terms(text):
    """
    从文本中提取特征词

    做法：优先用「关键特征词表」直接命中（如"开机""蓝屏""断网"），
    这些词准确率最高；再从文本中抽取 2-4 字词做补充。

    注意：早期版本用 2-gram 滑窗切分，会产生大量无意义碎片
    （如"的电""脑频"），导致不同故障之间产生噪音匹配，
    这里改为「关键词优先 + 整段短词」策略。
    """
    if not text:
        return []

    terms = set()

    # 1) 关键特征词直接命中（最可靠）
    for term in KEY_TERMS:
        if term in text:
            terms.add(term)

    # 2) 同义词直接扫描原始文本
    #
    # 为什么必须在切分之前做：
    #   用户说"教室上不了网"，切分只会得到 '教室上'、'室上不' 这类碎片，
    #   '上不了网' 根本不会被提取出来，后面的归一也就无从谈起。
    #   所以这里先用同义词表扫一遍原文，命中就直接加入标准词。
    for variant, std in _SYNONYM_LOOKUP.items():
        if variant in text:
            terms.add(std)

    # 3) 按标点切分，取长度合适的整段词
    cleaned = re.sub(r'[，。、；：！？,.;:!?（）()\[\]【】""\'\'\s]+', ' ', text)

    for chunk in cleaned.split():
        # 中文分段
        for seg in re.findall(r'[\u4e00-\u9fa5]+', chunk):
            if seg in STOP_WORDS:
                continue

            if len(seg) <= 4:
                # 短词：整段保留（如"断网""空调漏水"）
                terms.add(seg)
                # 但要「同时」切出 3-gram。
                #
                # 为什么短词也要切：
                #   查询"空调漏水"（4 字）整段保留，而案例症状是长句、
                #   被切成 '空调漏'/'调漏水' —— 两边粒度不一致，交集为空，
                #   导致刚沉淀的新案例用关键词反而搜不到。
                #   统一都产出 3-gram 后，两边就能对上了。
                if len(seg) > 3:
                    for i in range(len(seg) - 2):
                        piece = seg[i:i + 3]
                        if any(w in piece for w in ('的', '了', '是', '在', '和')):
                            continue
                        terms.add(piece)
            else:
                # 长句：滑动 3-gram，但必须不含停用词且不是常见虚词组合
                for i in range(len(seg) - 2):
                    piece = seg[i:i + 3]
                    if any(w in piece for w in ('的', '了', '是', '在', '和')):
                        continue
                    terms.add(piece)

        # 英文 / 数字
        for w in re.findall(r'[A-Za-z0-9]+', chunk):
            if len(w) >= 2:
                terms.add(w.lower())

    terms = {t for t in terms if t not in STOP_WORDS}

    # 4) 兜底归一：切分出来的词里可能还有变体（如整段就是"断网"）
    return sorted(_normalize_terms(terms))


def _drop_noise(terms):
    """
    过滤掉切分产生的「跨词碎片」（当前默认不启用）

    问题背景：
        "交换机断电或故障" 做 3-gram 滑窗会切出 "机断电" 这类碎片，
        可能与别的领域词产生噪音匹配。

    为什么现在不用它：
        本函数只保留「能对应到已知词表」的碎片，等于要求所有知识
        都必须落在预置词表内。实际使用中会出现词表外的故障
        （如"空调漏水"），一旦被过滤掉，新沉淀的案例就永远搜不到。

    替代方案：
        假阳性改在「打分」环节解决（见 _score 的 MIN_SCORE 与
        3-gram 降权），既保留开放性，又不会被单个碎片带偏。

    保留此函数仅作调试用途。
    """
    known = set(KEY_TERMS) | set(_SYNONYM_LOOKUP)

    kept = set()
    for t in terms:
        if t in known:
            kept.add(t)
            continue
        if any(t in k or k in t for k in known if len(k) >= 2):
            kept.add(t)

    return kept if kept else terms


def _case_terms(case):
    """把一条案例转成特征词集合（带权重标签）"""
    category = case.get('category', '')
    symptom = case.get('symptom', '')
    causes = ' '.join(case.get('causes', [])[:5])

    return {
        'category': _extract_terms(category),
        'symptom': _extract_terms(symptom),
        'causes': _extract_terms(causes),
    }


def _score(query_terms, case_terms):
    """
    计算匹配得分

    权重设计：
      分类命中   × 3.0   （分类对上说明故障大类一致）
      现象命中   × 2.0
      原因命中   × 1.0
      关键特征词 × 额外加成
    """
    q = set(query_terms)
    score = 0.0

    for t in q:
        if _hit(t, case_terms['category']):
            score += 3.0
        if _hit(t, case_terms['symptom']):
            score += 2.0
        if _hit(t, case_terms['causes']):
            # 原因只给很低的权重。
            #
            # 为什么压低：
            #   原因是"排查要点"，用词宽泛（如"交换机断电或故障"里的
            #   "断电"），容易与无关领域的描述偶然重合。
            #   只靠原因重合就判定相关，会产生假阳性 ——
            #   例如查"电脑自动关机"时误命中网络类案例。
            score += 0.5

    # 关键特征词加成
    for term, weight in KEY_TERMS.items():
        if term in query_terms:
            all_case = set(case_terms['category'] + case_terms['symptom'] + case_terms['causes'])
            if _hit(term, all_case):
                score += weight

    return score


def _hit(term, term_set):
    """
    判断一个查询词是否命中案例的词集合

    为什么要做「包含」判断而不只是相等：
      案例正文被切成 3-gram（如 '积湿滑'），而用户可能只输入 2 个字
      （如 '湿滑'）。若只做相等比较，'湿滑' 永远匹配不上 '积湿滑'，
      导致短查询全部失效。

      因此这里放宽为：查询词与案例词互为子串即算命中。
      2 字词对 3 字词的单向包含足以覆盖这类边界差异，
      且 2 字词本身噪音有限，不会明显增加误命中。
    """
    if term in term_set:
        return True
    # 仅对较长的词做包含判断，避免单字造成大面积误命中
    if len(term) >= 2:
        return any(term in c or c in term for c in term_set if len(c) >= 2)
    return False


def _is_relevant(q, case_terms):
    """
    判断是否「真的相关」，用于挡掉假阳性

    满足任一条即算相关：
      1. 查询与案例在「分类」或「现象」上有实质重合
      2. 查询里的关键词（KEY_TERMS）确实出现在案例中

    为什么需要第 2 条：
      "按电源没反应"与案例的"按开机键没有任何反应"表达不同
      （没反应 vs 任何反应），字面交集为空，但语义明显一致。
      靠关键词表能识别出这种情况，不至于漏掉真正的相关案例。

    为什么只和「原因」撞上一个泛词不算相关：
      原因描述用词宽泛（如"交换机断电或故障"里的"断电"），
      偶然重合几乎都是噪音 —— 查"电脑自动关机"会误命中网络类案例。
    """
    cat = set(case_terms['category'])
    sym = set(case_terms['symptom'])

    # 条件 1：分类或现象有实质重合（用包含判断，兼容粒度差异）
    for t in q:
        if _hit(t, cat) or _hit(t, sym):
            return True

    # 条件 2：命中了关键特征词，且该词确实出现在案例里
    all_case = cat | sym | set(case_terms['causes'])
    for term in q:
        if term in KEY_TERMS and _hit(term, all_case):
            return True

    return False


def search(query, top_n=TOP_N, min_score=MIN_SCORE):
    """
    检索相似案例

    参数：
      query     - 用户描述，如"电脑开机没反应，灯不亮"
      top_n     - 最多返回几条
      min_score - 最低得分阈值

    返回：[{**case, '_score': 得分}, ...]，按得分降序
    """
    data = _load_raw()
    cases = data['cases']

    if not cases or not query:
        return []

    q_terms = _extract_terms(query)
    if not q_terms:
        return []

    q_set = set(q_terms)
    scored = []
    for case in cases:
        ct = _case_terms(case)

        # 挡掉假阳性：必须与分类或现象有实质重合
        if not _is_relevant(q_set, ct):
            continue

        s = _score(q_terms, ct)
        if s >= min_score:
            item = dict(case)
            item['_score'] = round(s, 2)
            scored.append(item)

    scored.sort(key=lambda x: -x['_score'])
    return scored[:top_n]


def build_context(query, top_n=TOP_N):
    """
    根据用户描述，构建「只含相关案例」的提示词片段

    与原来的 build_knowledge_context() 的区别：
      原来：把全部案例都塞进去
      现在：只塞检索出的 Top-N，省 token 且更聚焦
    """
    hits = search(query, top_n)

    if not hits:
        return ""

    lines = ["【相似历史案例（供参考，不要照搬结论）】"]
    for c in hits:
        lines.append(f"· {c.get('category', '')}｜{c.get('symptom', '')}")
        causes = c.get('causes', [])[:3]
        if causes:
            lines.append(f"  常见原因：{'；'.join(causes)}")
        steps = c.get('steps', [])[:2]
        if steps:
            lines.append(f"  处理要点：{'；'.join(steps)}")

    return "\n".join(lines)


# ---------------- 自动沉淀 ----------------

# 分类推断规则
#
# 顺序很重要：按「越具体越靠前」排列，第一个命中的生效。
# 特别注意：音频故障放在最后，且不再收录宽泛的「声音」二字 ——
# 否则「风扇声音特别大」会被误判成音频故障（散热问题被当成音响问题）。
_CATEGORY_RULES = [
    # —— 外设类先于音频：'音响''耳机'本身就带"响/机"，
    #    若音频在前，会把"音响没声音"这类描述抢走
    (['鼠标', '键盘', 'U盘', 'usb', '摄像头', '投影笔', '翻页笔'], '外设故障'),
    (['投影', '投影仪', '投影机'], '投影故障'),
    (['打印机', '卡纸', '墨盒', '脱机'], '打印故障'),
    (['上网', '断网', '网络', '网线', '网口', '交换机', '路由器', '掉线'], '网络故障'),
    (['蓝屏', '死机', '卡顿', '系统', '重装', '病毒', '弹窗', '中病毒'], '系统故障'),
    # 显示类：'黑屏' 放到这里，而不是开机类 —— 开机类已由"开不了机"覆盖
    (['显示', '黑屏', '花屏', '无信号', '显示器', '偏色', '分辨率'], '显示故障'),
    # 电源/开机类：补齐 关机 / 断电 / 重启 / 硬件部件
    ([
        '开机', '开不了机', '打不开', '不通电', '没反应',
        '关机', '自动关机', '断电', '重启', '自动重启', '反复重启',
        '电源', '主板', '内存', '硬盘', '显卡', 'cpu', '风扇', '散热', '积灰',
        '主机', '噪音', '很响', '异响',
    ], '开机故障'),
    # 音频类放最后，且用具体词，避免误吸
    (['音响', '音箱', '耳机', '话筒', '麦克风', '没声音', '杂音', '电流声', '音频'], '音频故障'),
]


def _infer_category(text):
    """
    从文本推断故障分类

    按 _CATEGORY_RULES 的顺序做首命中匹配。
    匹配前统一转小写，让 USB / usb / CPU 都能命中。
    """
    low = (text or '').lower()
    for keywords, name in _CATEGORY_RULES:
        if any(k.lower() in low for k in keywords):
            return name
    return '其他故障'


def save_case(symptom, conclusion, excluded=None, classroom=''):
    """
    把一次成功的诊断沉淀成新案例

    参数：
      symptom    - 用户最初描述的现象（如"电脑开不了机"）
      conclusion - AI 给出的结论（含原因和处理）
      excluded   - 排查过程中排除的原因列表（可选）
      classroom  - 教室号（仅作记录，不入库）

    返回：(是否新增, 案例 id 或提示信息)

    去重策略：现象高度相似的案例不重复添加
    """
    symptom = (symptom or '').strip()
    conclusion = (conclusion or '').strip()

    if not symptom or not conclusion:
        return False, '现象或结论为空，不沉淀'

    # 去重：只有现象高度相似时才跳过
    # 阈值设得高一些，避免把不同故障误判为重复
    existing = search(symptom, top_n=1, min_score=8.0)
    if existing:
        return False, f'已有高度相似案例 {existing[0].get("id")}，不重复沉淀'

    # 从结论里抽取「原因」和「处理」
    reason = ''
    action = ''
    m = re.search(r'原因[:：]\s*(.+)', conclusion)
    if m:
        reason = m.group(1).strip().split('\n')[0]
    m = re.search(r'处理[:：]\s*(.+)', conclusion)
    if m:
        action = m.group(1).strip().split('\n')[0]

    # 生成编号
    prefix_map = {
        '开机故障': 'PC', '网络故障': 'NET', '投影故障': 'PRJ',
        '显示故障': 'DISP', '系统故障': 'SYS', '外设故障': 'DEV',
        '打印故障': 'PRT', '音频故障': 'AUD', '其他故障': 'GEN',
    }
    category = _infer_category(symptom + ' ' + conclusion)
    prefix = prefix_map.get(category, 'GEN')

    # 编号要在「手工 + 自动」两份案例里一起避让，
    # 否则自动沉淀可能生成一个与手工案例重号的 id
    all_ids = [c.get('id', '') for c in _load_raw()['cases']]
    nums = []
    for cid in all_ids:
        if cid.startswith(prefix + '-'):
            try:
                nums.append(int(cid.split('-')[1]))
            except (ValueError, IndexError):
                continue
    new_id = f'{prefix}-{max(nums) + 1:03d}' if nums else f'{prefix}-001'

    # 组装新案例
    causes = [reason] if reason else []
    if excluded:
        causes.extend([f'（已排除）{e}' for e in excluded[:3]])

    steps = [action] if action else []
    if excluded:
        steps = [f'先检查：{e}' for e in excluded[:3]] + steps

    new_case = {
        'id': new_id,
        'category': category,
        'symptom': symptom,
        'causes': causes or ['待补充'],
        'steps': steps or ['参考诊断结论'],
        'severity': '中',
        'est_time': '5-10 分钟',
        'source': 'auto',                      # 标注：自动沉淀
        'created': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'from_classroom': classroom or '',
    }

    # 只追加到自动沉淀文件，不碰手工文件
    _append_auto_case(new_case)

    return True, new_id


def _append_auto_case(case):
    """
    把一条案例追加到自动沉淀文件

    用「文件锁 + 读-改-写」保证并发安全：
    Flask 默认多线程，两个诊断同时结束时会并发写同一个文件，
    没有锁的话后写的会覆盖先写的，丢掉案例。

    加锁工具统一由 filelock 模块提供，与其他模块行为一致。
    """
    os.makedirs(os.path.dirname(AUTO_FILE), exist_ok=True)

    with file_lock(AUTO_FILE):
        # 拿到锁之后再读，确保基于最新内容追加
        data = _load_auto()
        data.setdefault('cases', []).append(case)
        _write_auto(data)


def stats():
    """知识库统计（用于演示"越用越聪明"）"""
    manual_cases = _read_file(MANUAL_FILE).get('cases', [])
    auto_cases = _read_file(AUTO_FILE).get('cases', [])
    cases = _load_raw()['cases']

    # 按 source 字段统计（更准确：手工文件里也可能有历史遗留的 auto 条目）
    auto = [c for c in cases if c.get('source') == 'auto']

    by_category = {}
    for c in cases:
        cat = c.get('category', '未分类')
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        'total': len(cases),
        'auto': len(auto),
        'manual': len(cases) - len(auto),
        'manual_file': len(manual_cases),   # 手工文件里的条数
        'auto_file': len(auto_cases),       # 自动沉淀文件里的条数
        'by_category': by_category,
    }


# 测试
if __name__ == '__main__':
    print('知识库模块测试')
    print('=' * 50)

    s = stats()
    print(f"当前知识库：共 {s['total']} 条（手工 {s['manual']}，自动沉淀 {s['auto']}）")
    print()

    # 测试检索
    queries = [
        '电脑开不了机，按电源没反应',
        '整个教室都上不了网',
        '投影仪没有信号',
        '鼠标不动了',
    ]

    for q in queries:
        hits = search(q)
        print(f"查询：{q}")
        if hits:
            for h in hits:
                print(f"   → [{h['_score']:>5}] {h.get('id')} {h.get('category')}：{h.get('symptom')}")
        else:
            print("   → 无匹配")
        print()

    print('=' * 50)
    print('测试自动沉淀')
    ok, msg = save_case(
        symptom='机房空调旁边的电脑频繁自动关机',
        conclusion='原因：散热不良，机箱积灰严重。\n处理：清理机箱灰尘，检查风扇转速。',
        excluded=['电源线松动', '插座无电'],
        classroom='A101',
    )
    print(f"  沉淀结果：{ok}  {msg}")

    s2 = stats()
    print(f"  沉淀后：共 {s2['total']} 条（自动 {s2['auto']}）")
