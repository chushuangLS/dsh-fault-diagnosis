"""
机房故障智能诊断助手 - 主程序

工作流程：
  1. 加载本地故障知识库（作为 AI 的参考资料）
  2. 用户描述故障现象
  3. 调用 AI 进行智能诊断
  4. 若 AI 不可用，回退到本地关键词匹配

作者：liyishuo1
"""

import json
import os

# AI 诊断模块
from ai_diagnosis import diagnose_with_ai

# 知识库文件路径
DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'fault_cases.json')


def load_cases():
    """读取故障知识库"""
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['cases']


def search_cases(cases, keyword):
    """本地关键词匹配（AI 不可用时的降级方案）"""
    results = []
    for case in cases:
        text = case['symptom'] + case['category']
        if keyword in text:
            results.append(case)
    return results


def show_case(case):
    """打印案例详情"""
    print('=' * 50)
    print(f"【{case['id']}】{case['category']}")
    print(f"现象：{case['symptom']}")
    print()
    print("可能原因：")
    for i, cause in enumerate(case['causes'], 1):
        print(f"  {i}. {cause}")
    print()
    print("排查步骤：")
    for i, step in enumerate(case['steps'], 1):
        print(f"  {i}. {step}")
    print()
    print(f"严重程度：{case['severity']}    预计耗时：{case['est_time']}")
    print('=' * 50)


def main():
    """主程序入口"""
    print("=" * 55)
    print("  机房故障智能诊断助手  v0.3.0")
    print("=" * 55)
    print()

    cases = load_cases()
    print(f"已加载 {len(cases)} 条故障案例（作为 AI 参考资料）")
    print("请用自然语言描述故障现象，AI 将给出诊断建议")
    print("输入 q 退出")
    print()

    while True:
        symptom = input("故障描述：").strip()

        if symptom == 'q':
            print("再见！")
            break

        if not symptom:
            print("请输入内容\n")
            continue

        print()
        print("正在分析，请稍候...")
        print()

        # ---- 主路径：AI 诊断 ----
        try:
            answer = diagnose_with_ai(symptom)
            print("=" * 55)
            print("【AI 诊断建议】")
            print("=" * 55)
            print()
            print(answer)
            print()
            print("=" * 55)
            print()

        except Exception as e:
            # ---- 降级：本地匹配 ----
            print(f"[提示] AI 诊断不可用（{e}）")
            print("已切换到本地知识库匹配\n")

            results = search_cases(cases, symptom)
            if results:
                print(f"找到 {len(results)} 条相关案例：\n")
                for case in results:
                    show_case(case)
            else:
                print("本地知识库也未找到匹配案例。\n")


if __name__ == '__main__':
    main()
