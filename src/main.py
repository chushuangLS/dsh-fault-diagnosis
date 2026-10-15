"""
机房故障智能诊断助手 - 主程序

功能：用户描述设备故障现象，程序从知识库中匹配相关案例，
      调用 AI 生成针对性的排查建议。

作者：liyishuo1
"""

import json
import os

# 知识库文件路径
DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'fault_cases.json')


def load_cases():
    """读取故障知识库"""
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['cases']


def search_cases(cases, keyword):
    """
    根据关键词搜索故障案例
    这里先用最简单的字符串匹配，后续可以换成 AI 语义匹配
    """
    results = []
    for case in cases:
        # 在症状和分类里找关键词
        text = case['symptom'] + case['category']
        if keyword in text:
            results.append(case)
    return results


def show_case(case):
    """打印一个案例的详情"""
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
    print("=" * 50)
    print("  机房故障智能诊断助手  v0.1.0")
    print("=" * 50)
    print()

    cases = load_cases()
    print(f"已加载 {len(cases)} 条故障案例")
    print()

    while True:
        keyword = input("请描述故障现象（输入 q 退出）：").strip()

        if keyword == 'q':
            print("再见！")
            break

        if not keyword:
            print("请输入内容\n")
            continue

        # 先本地匹配
        results = search_cases(cases, keyword)

        if results:
            print(f"\n找到 {len(results)} 条相关案例：\n")
            for case in results:
                show_case(case)
        else:
            print("\n本地知识库未找到匹配案例。")
            print("（后续版本将接入 AI 进行智能分析）\n")


if __name__ == '__main__':
    main()
