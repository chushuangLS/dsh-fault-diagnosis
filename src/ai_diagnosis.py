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

2. **第一句必须先问教室号**：用户描述故障后，你的第一句回复是：
   「请问是哪间教室？」
   拿到教室号后，再进入故障排查。如果用户已经主动说了教室号，就跳过这一步。

3. **第二步问清具体表现**：拿到教室号后，如果用户描述很模糊（如"电脑打不开"），
   先问清楚具体现象，不要跳到排查。
   - 用户说"电脑打不开" → 问："按开机键后，机箱指示灯亮吗？风扇转吗？"
   - 用户说"上不了网" → 问："其他电脑能上网吗？是一台还是整个教室都不行？"

4. **问什么**：问一个能区分故障原因的关键问题。问题要具体、可操作。
   - 好："换根电源线试试，能开机吗？"
   - 差："请检查电源、主板、开关等多个地方"

5. **怎么问**：用一句话说清「做什么」，然后直接问结果。不要解释原理，不要列可能性。

6. **根据回答推进**：用户说"不行"就排除这个原因，进入下一个**新的**可能。
   绝不重复问同一个问题，也绝不把上一个问题换个说法再问一遍。

7. **用户答非所问时**：如果用户的回答不是针对你的问题，先简短确认他的信息，
   再把原来的问题问一遍（用更简单的方式）。

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


def build_knowledge_context():
    """把本地知识库整理成文本，作为 AI 的参考"""
    data_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'fault_cases.json')

    if not os.path.exists(data_file):
        return ""

    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            cases = json.load(f)['cases']
    except Exception:
        return ""

    if not cases:
        return ""

    lines = ["【本校机房历史故障参考】"]
    for case in cases:
        lines.append(f"{case['category']}：{case['symptom']}")
        lines.append(f"  常见原因：{'；'.join(case['causes'][:3])}")

    return "\n".join(lines)


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
        self.symptom = ''          # 原始故障描述
        self.need_repair = False   # 结论是否需要报修
        self.conclusion = ''       # 诊断结论
        self._last_asked_classroom = False   # AI 上一句是否在问教室号

        # 初始化：系统提示词
        self.history.append({"role": "system", "content": SYSTEM_PROMPT})

        # 可选：加入知识库
        if use_knowledge:
            ctx = build_knowledge_context()
            if ctx:
                self.history.append({"role": "system", "content": ctx})

    def set_symptom(self, text):
        """记录用户最初描述的故障现象"""
        self.symptom = text

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
