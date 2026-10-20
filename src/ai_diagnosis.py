"""
机房故障智能诊断助手 - AI 诊断模块（对话式）

设计要点：
  1. 维护对话历史（messages 数组），让 AI 记住之前的排查过程
  2. 一次只问一个问题，根据用户回答逐层推进
  3. AI 判断定位到原因时，输出结论并结束

作者：liyishuo1
"""

import os
import json
import time

from openai import OpenAI

import config

# DeepSeek API 配置
API_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"

# 结束标记：AI 定位到原因时输出这个标记
DONE_MARKER = "【诊断结束】"

# 报修标记：结论需要报修时输出，程序据此写入记录
REPAIR_MARKER = "【需要报修】"

# 自修标记：结论属于非硬件问题、可自行修复
# 这类故障不占用报修资源，在界面上标为「可自修」（黄色）
SELF_FIX_MARKER = "【可自修】"

# 教室设施标记：故障出在教室级设备上（总闸、交换机、投影、空调、教室网络）
#
# 为什么要这个标记：
#   这类故障会让整间教室不能用，但**电脑本身没坏**。
#   如果按"损坏 N 台电脑"记，会得出"损坏 80 台"这种错误数字 ——
#   一台电脑都没坏，坏的是配电箱。
#   有了这个标记，记录会落到 repair_log.TARGET_FACILITY，
#   统计时不计入电脑台数，而是单独标记为「设施故障」。
FACILITY_MARKER = "【教室设施】"

# 教室设施关键词：用于从现象/结论里兜底推断故障对象
# （AI 没输出标记时，也能把总闸这类问题归类正确）
#
# 只收「教室级」的说法。像"插座无电"「一台没网络」这种可能是单台机器的，
# 不往里放 —— 宁可漏判成电脑故障（用户能手动改），
# 也不要把单台故障误判成整间教室出事（会漏统计真实损坏）。
_FACILITY_KEYWORDS = [
    # 供电 / 配电
    #
    # 这里不写「线路故障」「供电线路」这类泛词：
    # 电脑自己的电源线、机箱电源也会被描述成"供电线路故障"，
    # 用它们会把单台电脑的故障误判成教室设施故障。
    '总闸', '配电箱', '配电柜', '空开', '空气开关', '断路器',
    '跳闸', '短路', '漏电', '墙内线路',
    # 教室整体没电 / 整间范围
    '整间', '全教室', '教室没电', '教室停电', '教室断电', '整间教室',
    # 网络设备
    '交换机', '路由器', '光猫', '上联',
    # 教室设备
    '投影仪', '投影机', '投影故障',
    '空调',
]


def infer_target(symptom, conclusion):
    """
    推断故障对象：电脑 / 教室设施

    优先看 AI 是否输出了【教室设施】标记；
    没有的话按关键词兜底（总闸、交换机、投影、空调等）。

    宁可偏向「电脑」：误判成设施故障会把真实损坏漏统计，
    而误判成电脑故障至少数据还在，用户能手动改。
    """
    text = f'{symptom or ""} {conclusion or ""}'

    if FACILITY_MARKER in (conclusion or ''):
        return '教室设施'

    for kw in _FACILITY_KEYWORDS:
        if kw in text:
            return '教室设施'

    return '电脑'

# 系统提示词：约束 AI 的交互方式
# 这是本模块的核心，决定了对话的质量
SYSTEM_PROMPT = """你是一名高校机房的运维工程师，正在通过对话帮学生管理员排查设备故障。

## 核心规则（必须严格遵守）

1. **每次回复只做一件事**：要么问一个问题，要么给出结论。绝不一次列出多个问题或多个步骤。

2. **教室号已知时绝不再问**：如果对话或【已知信息】里已经出现了教室，
   直接进入故障排查，不要问"哪间教室"。只有完全不知道教室时才问。

3. **第一步问清具体表现**：如果用户描述很模糊（如"电脑打不开"），
   先问清楚具体现象，不要跳到排查。

4. **提问要多样化，禁止套模板**：
   不要每次都问"指示灯亮吗？风扇转吗？"——这句话只在真正需要时用。
   根据故障类型选择不同的切入角度：
   - 电源类故障：可以先问插座、电源线、开关、有没有异味或响声
   - 显示类故障：可以先问显示器电源灯、信号线、输入源
   - 网络类故障：可以先问是一台还是整间、其他教室是否正常、网口灯
   - 系统类故障：可以先问卡在哪一步、有没有报错画面、能否进安全模式
   - 外设类故障：可以先问换接口、换设备是否正常
   同一场对话中，**后一个问题绝不能和前面重复或换说法**。

5. **问题要具体可操作**：一句话说清「做什么」，然后直接问结果。
   - 好："把机箱后面那根电源线拔下来重插，再按开机键，有反应吗？"
   - 差："请检查电源、主板、开关等多个地方"

6. **根据回答推进**：用户说"不行"就排除这个原因，进入下一个**全新的**可能。
   绝不重复问同一个问题。

7. **用户答非所问时**：先简短确认他的信息，再把原来的问题换个更简单的说法。

8. **确定原因后先判断故障范围，再决定要不要问数量**：
   · **个别机器**故障（如某几台开不了机、某台黑屏）→
     先问一句「这间教室有**几台**是这个情况？」，拿到数量再出结论。
   · **范围性**故障（整间教室停电、整间断网、总闸跳闸、交换机故障）→
     **不要问「几台」**。整间都不能用了，问"几台电脑"没有意义。
     直接按整间出结论，结论里省略「数量：」这一行。

9. **数量要记住，不要写错**：用户提过的数量要沿用到最后的「数量：」一行。
   用户没提过、你也问过了，就用他回答的数字。
   用户始终没说的，写「数量：1 台」。
   **绝不要写 0 台** —— 至少坏了一台才需要排查。

10. **什么时候结束**：确认了原因、并问清数量之后，
    第一行输出 `【诊断结束】`，然后给出结论。

11. **涉及电气安全时，第一件事是止损，不是继续排查**：

    总闸 / 空气开关跳闸，**只允许让用户推一次**：
    - 推一次就恢复正常 → 可以继续按普通故障处理
    - 推上去立刻又跳、或根本推不上去 → **立即停止**，
      明确告诉用户「不要再反复推闸」，直接给结论并报修

    出现以下任一情况，同样立即停止并报修，**禁止用户自行处理**：
    - 闻到焦糊味、看到冒烟或火花
    - 插头、插座、线路发烫
    - 触碰有麻感（漏电）
    - 怀疑墙内线路、配电箱内部故障

    这类问题需要电工处理。**绝不能让学生反复合闸、拆配电箱、动墙内线路** ——
    短路状态下反复合闸可能产生电弧甚至引起火灾。
    结论里必须写明「不要再反复推闸，等电工处理」。

## 结论格式（严格遵守）

结束时按以下格式输出（`【诊断结束】`必须单独占第一行）：

```
【诊断结束】
原因：<一句话说明故障原因>
数量：<N 台>
处理：<自己修 / 需要报修，并说明具体怎么做>
```

**范围性故障（整间断电、总闸跳闸、交换机故障等）省略「数量：」这一行**，
因为问"几台电脑"没有意义 —— 整间都用不了。

**如果结论是需要报修**（如硬件损坏、需要专业人员处理），
在结论最后**单独加一行** `【需要报修】`。

**如果结论是可以自己修**（非硬件问题，如线松了、信号源选错、系统设置问题），
在结论最后**单独加一行** `【可自修】`。

**如果故障出在教室级设施上**（总闸、配电箱、交换机、投影、空调、教室网络，
电脑本身没坏），在结论最后**单独加一行** `【教室设施】`。
这种情况不要写「数量：」，因为坏的不是某几台电脑。

判断标准：涉及以下情况必须报修
- 硬件损坏（电源、主板、内存、硬盘、显示器等）
- 需要更换配件
- 网络设备故障（交换机、上联线路）
- **总闸 / 空气开关反复跳闸，或推不上去**
- **配电箱、墙内线路、插座线路的问题**
- 有焦糊味、冒烟、火花、发烫、漏电迹象
- 学生无法安全处理的（带电作业、拆机箱等）

反之，以下情况属于「可自修」：
- 线材松动、插口没插好
- 信号源 / 输入源选错
- 显示器电源没开、亮度调到最低
- 系统设置问题（分辨率、显示模式）
- 换个机位、换根线就能解决的
- 总闸跳闸后**推一次就恢复正常**（仅此一次，反复跳闸必须报修）

## 回复格式（严格遵守）

每次回复控制在 3 行以内。

- **追问时**：直接问，例如「先换一根电源线试试，能开机吗？」
- **结束时**：按上面的「结论格式」输出。

## 排查思路参考

按「从简单到复杂、从便宜到贵」的顺序：
1. 外部连接（线材、插座、开关）
2. 简单替换（换线、换插座、换机位）
3. 硬件判断（电源、主板、内存）
4. 需要报修的情况

不要一次性把所有可能都抖出来，走到哪一步说哪一步。

## 严禁

- 严禁一次列出多个排查步骤
- 严禁输出大段解释和原理
- 严禁重复已经排除的检查项
- 严禁使用「首先、其次、最后」这种结构化列点"""


def get_client():
    """
    创建 API 客户端

    Key 的读取交给 config 模块：环境变量优先，其次 data/config.json。
    （打包成 exe 给别人用时，对方多半没有环境变量，靠配置文件。）
    """
    api_key = config.get_api_key()

    if not api_key:
        raise ValueError(
            "未配置 API Key。\n"
            "两种方式任选其一：\n"
            "  1. 设置环境变量 DEEPSEEK_API_KEY\n"
            "     PowerShell:  $env:DEEPSEEK_API_KEY='你的key'\n"
            "  2. 写进配置文件（桌面窗口版首次启动会弹窗引导）：\n"
            "     " + config.config_file()
        )

    return OpenAI(api_key=api_key, base_url=API_BASE)


def build_knowledge_context(query=''):
    """
    构建知识库上下文（检索增强，RAG 的轻量实现）

    与早期版本的区别：
      早期：把全部案例塞进提示词 —— 案例一多就浪费 token，且干扰判断
      现在：先用本地检索找出 Top-3 相似案例，只注入这几条

    参数：
      query - 用户的故障描述；为空时回退到「注入全部」的行为（兼容旧调用）
    """
    try:
        import knowledge
    except ImportError:
        return ""

    # 有查询词 → 只注入相关案例
    if query:
        return knowledge.build_context(query)

    # 没有查询词（兼容旧调用）→ 给出知识库概览而不是全文
    try:
        s = knowledge.stats()
    except Exception:
        return ""

    if not s.get('total'):
        return ""

    cats = '、'.join(f"{k}（{v}条）" for k, v in s['by_category'].items())
    return f"【本校机房故障知识库】共 {s['total']} 条案例，覆盖：{cats}"


def parse_quantity(text):
    """
    从 AI 的结论里解析损坏数量

    AI 按约定输出「数量：3 台」，但实际可能写成
    "3 台" / "三台" / "大概 5 台" 等，这里做容错解析。

    解析不出来时返回 1（保守估计：至少坏了一台）。
    """
    import re

    if not text:
        return 1

    # 优先取「数量：」后面的数字
    m = re.search(r'数量[:：]\s*(\d+)', text)
    if m:
        return max(int(m.group(1)), 1)

    # 中文数字
    cn = {'一': 1, '两': 2, '二': 2, '三': 3, '四': 4, '五': 5,
          '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    m = re.search(r'([一两二三四五六七八九十]+)\s*台', text)
    if m:
        s = m.group(1)
        if s in cn:
            return cn[s]
        if s.startswith('十'):
            return 10 + cn.get(s[1:], 0)
        if '十' in s:
            a, _, b = s.partition('十')
            return cn.get(a, 1) * 10 + cn.get(b, 0)

    # 兜底：任意位置出现 "N 台"
    m = re.search(r'(\d+)\s*台', text)
    if m:
        return max(int(m.group(1)), 1)

    return 1


def apply_markers(session, reply):
    """
    根据 AI 回复里的标记，更新会话状态

    抽成公共函数，避免 send 和 send_stream 两处各写一份、改漏一处
    （历史上这两条路径就曾因为各写一份而行为不一致）。
    """
    if REPAIR_MARKER in reply:
        session.need_repair = True
    if SELF_FIX_MARKER in reply:
        session.self_fix = True

    if DONE_MARKER in reply:
        session.finished = True
        # 数量只在结论文本里才有意义
        session.quantity = parse_quantity(reply)

    return reply


def clean_markers(reply):
    """去掉控制用的标记，留下给用户看的干净文本"""
    return (reply
            .replace(DONE_MARKER, '')
            .replace(REPAIR_MARKER, '')
            .replace(SELF_FIX_MARKER, '')
            .replace(FACILITY_MARKER, '')
            .strip())


def save_diagnosis_case(session):
    """
    把一次完成的诊断沉淀进知识库

    这是"知识库越用越聪明"的入口：
    每次成功诊断后调用，把现象与结论提取成结构化案例。

    参数：session - DiagnosisSession 实例
    返回：(是否新增, 提示信息)
    """
    try:
        import knowledge
    except ImportError:
        return False, '知识库模块不可用'

    if not session.finished or not session.conclusion:
        return False, '诊断未完成，不沉淀'

    # 已报修的故障只记录结论，不作为"已解决案例"沉淀
    # （因为还没验证结论是否正确）
    if session.need_repair:
        return False, '结论为待报修，暂不沉淀（待验证）'

    return knowledge.save_case(
        symptom=session.symptom,
        conclusion=session.conclusion,
        excluded=getattr(session, 'excluded', None),
        classroom=session.classroom,
    )


class DiagnosisSession:
    """
    一次诊断会话

    维护对话历史，实现多轮追问
    记录教室号和故障现象，供报修时使用
    """

    def __init__(self, use_knowledge=True):
        self.client = get_client()
        self.history = []          # 对话历史
        self.finished = False      # 是否已结束
        self.classroom = ''        # 教室号
        self.building = ''         # 教学楼名称（前端选择时写入）
        self.symptom = ''          # 原始故障描述
        self.need_repair = False   # 结论是否需要报修
        self.self_fix = False      # 结论是否属于「可自修」
        self.quantity = 1          # 损坏数量（AI 确认原因后询问得到）
        self.conclusion = ''       # 诊断结论
        self._last_asked_classroom = False   # AI 上一句是否在问教室号
        self.excluded = []         # 已排除的原因（用于沉淀案例）
        self._knowledge_injected = False     # 是否已注入检索结果
        self.use_knowledge = use_knowledge
        self.knowledge_hits = []   # 本次命中的历史案例
        self.last_active = time.time()   # 最后活动时间（供 Web 端会话清理）

        # 初始化：只放系统提示词
        # 知识库不在这里注入 —— 因为此时还不知道用户要问什么，
        # 等拿到故障描述后用检索的方式精准注入（见 _inject_knowledge）
        self.history.append({"role": "system", "content": SYSTEM_PROMPT})

    def _inject_knowledge(self, query):
        """
        根据用户描述检索并注入相关案例（RAG 的轻量实现）

        只在首次拿到故障描述时调用一次。
        """
        if not self.use_knowledge or self._knowledge_injected:
            return

        self._knowledge_injected = True

        try:
            import knowledge
            hits = knowledge.search(query)
        except Exception:
            return

        if not hits:
            return

        self.knowledge_hits = hits

        # 只注入检索到的 Top-N，而不是全部案例
        ctx = knowledge.build_context(query)
        if ctx:
            self.history.append({"role": "system", "content": ctx})

    def set_symptom(self, text):
        """记录用户最初描述的故障现象"""
        self.symptom = text

    def set_location(self, classroom, building=''):
        """
        设定教室位置（前端下拉选择时调用）

        关键：把位置信息作为一条 system 消息写入对话历史，
        否则 AI 不知道用户已经选了教室，还会重复追问。
        """
        self.classroom = classroom or ''
        self.building = building or ''

        if not self.classroom:
            return

        where = f"{self.building} {self.classroom}".strip()
        self.history.append({
            "role": "system",
            "content": (
                f"【已知信息】用户所在的教室是「{where}」。"
                f"教室号已确定，**不要再问哪间教室**，直接进入故障排查。"
            ),
        })

    def _extract_classroom(self, user_input):
        """
        从用户输入中提取教室号

        两种策略：
          1. 上下文优先：如果 AI 上一句在问教室号，那么用户这轮的任何回答
             都当作教室号处理（用户可能只回一个 "501"）
          2. 正则兜底：从文本里查找形如 "305教室" / "教室305" / "A203" 的内容
        """
        import re

        text = user_input.strip()

        # ---- 策略 1：上下文判断 ----
        # 检查 AI 上一条回复是否在问教室号
        if self._last_asked_classroom:
            # 用户可能在回答里带多余的字，提取其中的编号
            m = re.search(r'([A-Za-z]?\d{1,4})', text)
            if m:
                return m.group(1)
            # 实在提不出数字，就把整句当教室号（如"三楼东边那间"）
            if text and len(text) <= 20:
                return text

        # ---- 策略 2：正则匹配 ----
        patterns = [
            r'([A-Za-z]?\d{3,4})\s*(?:教室|机房|室|房间)',   # 305教室 / A203机房
            r'(?:教室|机房|室|房间)\s*([A-Za-z]?\d{3,4})',   # 教室305
            r'([A-Za-z]\d{3,4})',                            # A203
            r'^([A-Za-z]?\d{3,4})$',                         # 纯数字 501（单独一行时）
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1)

        return None

    def send(self, user_input):
        """
        发送用户输入，返回 AI 回复

        返回：(回复文本, 是否已结束, 是否需要报修)
        """
        # 记录用户输入
        self.history.append({"role": "user", "content": user_input})

        # 尝试提取教室号
        if not self.classroom:
            extracted = self._extract_classroom(user_input)
            if extracted:
                self.classroom = extracted

        # 首次拿到故障描述 → 检索并注入相关历史案例
        self._inject_knowledge(self.symptom or user_input)

        # 调用 API（带上完整历史）
        response = self.client.chat.completions.create(
            model=MODEL,
            messages=self.history,
            temperature=0.3,
            max_tokens=300,        # 限制长度，强制精简
        )

        reply = response.choices[0].message.content.strip()

        # 记录 AI 回复
        self.history.append({"role": "assistant", "content": reply})

        # 判断 AI 刚才是不是在问教室号
        # 用于下一轮把用户的回答直接当教室号处理
        self._last_asked_classroom = (
            not self.classroom
            and ('教室' in reply and ('哪' in reply or '几' in reply))
        )

        # 判断是否需要报修 / 可自修 / 是否结束（要在剥离标记前判断）
        apply_markers(self, reply)

        # 清理标记，得到干净的回复
        clean = clean_markers(reply)

        if self.finished:
            self.conclusion = clean

        return clean, self.finished, self.need_repair

    def send_stream(self, user_input):
        """
        流式发送用户输入

        生成器，逐段 yield AI 回复的文本片段。
        最后一段会 yield 一个特殊的结束标记字典，
        包含 finished / need_repair / classroom 等状态。

        用法：
            for chunk in session.send_stream("电脑开不了机"):
                if chunk['type'] == 'text':
                    print(chunk['content'], end='')
                elif chunk['type'] == 'end':
                    print(chunk['finished'], chunk['need_repair'])
        """
        # 记录用户输入
        self.history.append({"role": "user", "content": user_input})

        # 尝试提取教室号
        if not self.classroom:
            extracted = self._extract_classroom(user_input)
            if extracted:
                self.classroom = extracted

        # 首次拿到故障描述 → 检索并注入相关历史案例
        self._inject_knowledge(self.symptom or user_input)

        # 流式调用
        stream = self.client.chat.completions.create(
            model=MODEL,
            messages=self.history,
            temperature=0.3,
            max_tokens=300,
            stream=True,
        )

        full = ''
        for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            piece = getattr(delta, 'content', None)
            if piece:
                full += piece
                yield {'type': 'text', 'content': piece}

        # 流结束，处理标记
        reply = full.strip()
        self.history.append({"role": "assistant", "content": reply})

        self._last_asked_classroom = (
            not self.classroom
            and ('教室' in reply and ('哪' in reply or '几' in reply))
        )

        apply_markers(self, reply)

        clean = clean_markers(reply)
        if self.finished:
            self.conclusion = clean

        yield {
            'type': 'end',
            'reply': clean,
            'finished': self.finished,
            'need_repair': self.need_repair,
            'self_fix': self.self_fix,
            'quantity': self.quantity,
            'classroom': self.classroom or '',
        }


# 单独运行测试
if __name__ == '__main__':
    print("对话式诊断模块测试")
    print("=" * 50)

    session = DiagnosisSession()
    print("模拟对话：\n")

    # 模拟用户输入序列
    test_inputs = [
        "电脑打不开",
        "按电源没反应",
        "换了还是不行",
        "开关是开的，灯也不亮",
    ]

    for user_input in test_inputs:
        print(f"[用户] {user_input}")
        try:
            reply, finished = session.send(user_input)
            print(f"[AI]   {reply}")
            if finished:
                print("\n>>> 诊断已结束")
                break
        except Exception as e:
            print(f"[错误] {e}")
            break
        print()
