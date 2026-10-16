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

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'fault_cases.json')

# 检索时最多返回几条案例
TOP_N = 3

# 得分阈值：低于这个分数认为"不相关"，不注入提示词
MIN_SCORE = 1.0


def _load_raw():
    """读取原始知识库文件"""
    if not os.path.exists(DATA_FILE):
        return {'version': '0.1.0', 'description': '机房故障知识库', 'cases': []}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('cases', [])
        return data
    except Exception:
        return {'version': '0.1.0', 'description': '机房故障知识库', 'cases': []}


def _save_raw(data):
    """写回知识库文件"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
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
        # 中文：整段如果是短词就收；长句则只收其中的关键片段
        for seg in re.findall(r'[\u4e00-\u9fa5]+', chunk):
            if 2 <= len(seg) <= 4 and seg not in STOP_WORDS:
                terms.add(seg)
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
    return sorted(_normalize_terms(_drop_noise(terms)))


def _drop_noise(terms):
    """
    过滤掉切分产生的「跨词碎片」

    问题背景：
        "交换机断电或故障" 这一串做 3-gram 滑窗，会切出 "机断电"、"电或故" 等碎片。
        其中某些碎片恰好是别的领域的正常词 —— 例如 "关机" 可能是
        "交[换机][断]电" 这类跨词边界拼出来的假词。
        结果：查"电脑自动关机"时，NET-001 因为正文里含"机断电"而被误判命中，
        得分 1.0 刚好越过阈值，产生**假阳性**（比不匹配更糟）。

    过滤规则：
        只有当碎片「能对应到已知词汇」时才保留 —— 即它本身是
        KEY_TERMS、SYNONYMS 的标准词或变体之一。
        切分产生的无意义碎片（如 "机断电"）不在任何词表里，直接丢弃。
    """
    known = set(KEY_TERMS) | set(_SYNONYM_LOOKUP)

    kept = set()
    for t in terms:
        # 命中已知词汇 → 保留
        if t in known:
            kept.add(t)
            continue
        # 长度 >= 2 的中文词，且不是纯粹的碎片：
        # 若它是某个已知词的子串，或某个已知词是它的子串，保留
        if any(t in k or k in t for k in known if len(k) >= 2):
            kept.add(t)

    # 保底：如果过滤后什么都不剩，就不要过度过滤（避免完全匹配不上）
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
        if t in case_terms['category']:
            score += 3.0
        if t in case_terms['symptom']:
            score += 2.0
        if t in case_terms['causes']:
            score += 1.0

    # 关键特征词加成
    for term, weight in KEY_TERMS.items():
        if term in query_terms:
            all_case = set(case_terms['category'] + case_terms['symptom'] + case_terms['causes'])
            if term in all_case:
                score += weight

    return score


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

    scored = []
    for case in cases:
        s = _score(q_terms, _case_terms(case))
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

    data = _load_raw()
    cases = data['cases']

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

    nums = []
    for c in cases:
        cid = c.get('id', '')
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

    cases.append({
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
    })

    data['cases'] = cases
    _save_raw(data)

    return True, new_id


def stats():
    """知识库统计（用于演示"越用越聪明"）"""
    data = _load_raw()
    cases = data['cases']
    auto = [c for c in cases if c.get('source') == 'auto']

    by_category = {}
    for c in cases:
        cat = c.get('category', '未分类')
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        'total': len(cases),
        'auto': len(auto),
        'manual': len(cases) - len(auto),
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
