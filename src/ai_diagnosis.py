"""
机房故障智能诊断助手 - AI 诊断模块

功能：调用大模型 API，根据用户描述的故障现象生成排查建议。

安全说明：
  API Key 从环境变量 DEEPSEEK_API_KEY 读取，不写入代码，
  避免提交到公开仓库时泄露。

作者：liyishuo1
"""

import os
import json

from openai import OpenAI

# DeepSeek API 配置
API_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"

# 系统提示词：约束 AI 的角色和输出格式
# 这段提示词是本模块的核心，决定了 AI 的回答质量
SYSTEM_PROMPT = """你是一名高校机房的资深运维工程师，负责管理机房设备和排查故障。

你的任务：根据用户描述的故障现象，给出专业、可操作的排查建议。

要求：
1. 先用一句话判断故障的大致类别
2. 列出可能的原因（按可能性从高到低排序）
3. 给出具体的排查步骤，每步都要说明"做什么"和"看什么现象"
4. 如果排查到某一步能确定原因，要说明如何判断
5. 最后给出处理建议（自己修 / 报修）

注意事项：
- 面向的是学生管理员，不是专业工程师，语言要通俗易懂
- 不要输出无关的客套话
- 如果故障描述太模糊，先提出 1-2 个澄清问题"""


def get_client():
    """
    创建 API 客户端

    API Key 从环境变量读取，代码里不出现明文
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")

    if not api_key:
        raise ValueError(
            "未找到 DEEPSEEK_API_KEY 环境变量。\n"
            "请先设置：\n"
            "  Windows PowerShell: $env:DEEPSEEK_API_KEY='你的key'\n"
            "  或在系统环境变量中配置"
        )

    return OpenAI(api_key=api_key, base_url=API_BASE)


def build_context():
    """
    构建知识库上下文

    把本地知识库里的案例作为参考资料喂给 AI，
    这样 AI 的回答会更贴合本校机房的实际情况。
    """
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

    # 把案例整理成简洁的文本
    lines = ["【本校机房历史故障案例参考】"]
    for case in cases:
        lines.append(f"\n{case['id']} - {case['category']}")
        lines.append(f"  现象：{case['symptom']}")
        lines.append(f"  常见原因：{'；'.join(case['causes'])}")
        lines.append(f"  处理：{' → '.join(case['steps'][:3])}")

    return "\n".join(lines)


def diagnose_with_ai(symptom, use_context=True):
    """
    调用 AI 进行诊断

    参数：
      symptom     - 用户描述的故障现象
      use_context - 是否携带本地知识库作为参考

    返回：AI 的回答文本
    """
    client = get_client()

    # 构建消息
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 可选：把知识库塞进上下文
    if use_context:
        context = build_context()
        if context:
            messages.append({
                "role": "system",
                "content": context
            })

    # 用户的问题
    messages.append({"role": "user", "content": symptom})

    # 调用 API
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.3,      # 温度低一点，回答更稳定专业
        stream=False,
    )

    return response.choices[0].message.content


# 单独运行本文件时测试
if __name__ == '__main__':
    print("AI 诊断模块测试")
    print()

    try:
        client = get_client()
        print("✅ API 客户端创建成功")
        print(f"   API 地址: {API_BASE}")
        print(f"   模型: {MODEL}")
    except ValueError as e:
        print(f"❌ {e}")
        raise SystemExit(1)

    print()
    print("正在测试诊断功能...")
    print()

    result = diagnose_with_ai("教室里有台电脑开机没反应，按电源键没动静")
    print(result)
