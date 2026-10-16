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

# DeepSeek API 配置
API_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"

# 结束标记：AI 定位到原因时输出这个标记
DONE_MARKER = "【诊断结束】"

# 报修标记：结论需要报修时输出，程序据此写入记录
REPAIR_MARKER = "【需要报修】"

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

8. **什么时候结束**：当你已经能确定故障原因时，第一行输出 `【诊断结束】`，
   然后给出结论。

## 结论格式（严格遵守）

结束时按以下格式输出（`【诊断结束】`必须单独占第一行）：

```
【诊断结束】
原因：<一句话说明故障原因>
处理：<自己修 / 需要报修，并说明具体怎么做>
```

**如果结论是需要报修**（如硬件损坏、需要专业人员处理），
在结论最后**单独加一行** `【需要报修】`。

判断标准：涉及以下情况必须报修
- 硬件损坏（电源、主板、内存、硬盘、显示器等）
- 需要更换配件
- 网络设备故障（交换机、上联线路）
- 学生无法安全处理的（带电作业、拆机箱等）

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
    """创建 API 客户端，Key 从环境变量读取"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")

    if not api_key:
        raise ValueError(
            "未找到 DEEPSEEK_API_KEY 环境变量。\n"
            "请在系统环境变量中配置，或临时设置：\n"
            "  $env:DEEPSEEK_API_KEY='你的key'"
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

        # 判断是否需要报修（要在剥离标记前判断）
        if REPAIR_MARKER in reply:
            self.need_repair = True

        # 判断是否结束
        if DONE_MARKER in reply:
            self.finished = True

        # 清理标记，得到干净的回复
        clean = reply.replace(DONE_MARKER, '').replace(REPAIR_MARKER, '').strip()

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

        if REPAIR_MARKER in reply:
            self.need_repair = True
        if DONE_MARKER in reply:
            self.finished = True

        clean = reply.replace(DONE_MARKER, '').replace(REPAIR_MARKER, '').strip()
        if self.finished:
            self.conclusion = clean

        yield {
            'type': 'end',
            'reply': clean,
            'finished': self.finished,
            'need_repair': self.need_repair,
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
