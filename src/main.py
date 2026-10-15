"""
机房故障智能诊断助手 - 主程序

交互方式：对话式逐层排查
  用户描述故障 → AI 问一个关键问题 → 用户回答 → AI 继续追问
  → 直到 AI 定位到原因，输出结论

作者：liyishuo1
"""

import json
import os

from ai_diagnosis import DiagnosisSession

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'fault_cases.json')


def load_cases():
    """读取故障知识库"""
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)['cases']


def search_cases(cases, keyword):
    """本地关键词匹配（AI 不可用时的降级方案）"""
    return [c for c in cases if keyword in c['symptom'] + c['category']]


def show_case(case):
    """打印案例详情"""
    print(f"\n【{case['id']}】{case['category']}")
    print(f"现象：{case['symptom']}")
    print("排查步骤：")
    for i, step in enumerate(case['steps'], 1):
        print(f"  {i}. {step}")


def main():
    """主程序入口"""
    print("=" * 55)
    print("  机房故障智能诊断助手  v0.4.0")
    print("=" * 55)
    print()

    try:
        cases = load_cases()
        print(f"已加载 {len(cases)} 条故障案例")
    except Exception as e:
        print(f"[警告] 知识库加载失败：{e}")
        cases = []

    print()
    print("请描述遇到的故障，我会一步步引导你排查")
    print("（随时输入 q 退出，输入 r 重新开始一次诊断）")
    print()

    # 当前诊断会话，None 表示还没开始
    session = None

    while True:
        # 根据是否在诊断中，显示不同的提示符
        if session is None:
            prompt = "故障描述："
        else:
            prompt = "你的回答："

        user_input = input(prompt).strip()

        # 全局命令
        if user_input == 'q':
            print("再见！")
            break

        if user_input == 'r':
            session = None
            print("\n--- 已重置，请重新描述故障 ---\n")
            continue

        if not user_input:
            print("请输入内容")
            continue

        # 首次输入：创建新会话
        if session is None:
            print()
            print("正在分析，请稍候...")
            print()
            try:
                session = DiagnosisSession()
            except Exception as e:
                print(f"[提示] AI 不可用：{e}")
                print("已切换到本地知识库匹配\n")
                results = search_cases(cases, user_input)
                if results:
                    for case in results:
                        show_case(case)
                else:
                    print("本地知识库未找到匹配案例。\n")
                continue

        # 发送给 AI
        try:
            reply, finished = session.send(user_input)

            print()
            if finished:
                print("=" * 55)
                print("【诊断结论】")
                print("=" * 55)
                print(reply)
                print("=" * 55)
                print()
                print("--- 本次诊断结束，可继续描述下一个故障 ---")
                print()
                session = None          # 结束会话
            else:
                print(f"→ {reply}")
                print()

        except Exception as e:
            print(f"\n[错误] AI 调用失败：{e}")
            print("已结束本次诊断\n")
            session = None


if __name__ == '__main__':
    main()
