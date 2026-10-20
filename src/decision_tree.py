"""
机房故障智能诊断助手 - 决策树诊断模块

功能：加载决策树，通过逐步问答引导用户定位故障原因。

作者：liyishuo1
"""

import json
import os

import paths

# 决策树数据文件路径
TREE_FILE = paths.data_file('decision_trees.json')


def load_trees():
    """读取所有决策树"""
    with open(TREE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['trees']


def match_tree(trees, keyword):
    """
    根据关键词找到匹配的决策树

    匹配规则：关键词出现在树的 trigger 列表里，
             或者出现在树的 name 里
    """
    for tree in trees:
        # 检查 trigger 列表
        for trigger in tree['trigger']:
            if trigger in keyword or keyword in trigger:
                return tree
        # 检查树名
        if keyword in tree['name']:
            return tree
    return None


def run_tree(tree):
    """
    执行一棵决策树的问答流程

    流程：
    1. 从 start 节点开始
    2. 显示问题，让用户选择
    3. 根据选择跳到 next 节点
    4. next 为 null 时结束，显示 conclusion
    """
    print()
    print('=' * 55)
    print(f"  开始诊断：{tree['name']}")
    print('=' * 55)

    # 当前节点ID，从 start 开始
    current_id = tree['start']
    step = 0

    # 循环：只要 current_id 不为空就继续
    while current_id is not None:
        step += 1
        node = tree['nodes'].get(current_id)

        # 防御：节点不存在
        if node is None:
            print(f"[错误] 找不到节点 {current_id}，诊断中断")
            return

        # 显示问题
        print()
        print(f"【第 {step} 步】{node['question']}")
        print()

        # 显示选项
        options = node['options']
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt['answer']}")

        # 让用户选择
        choice = input("\n请选择（输入序号，或 q 退出诊断）：").strip()

        if choice == 'q':
            print("已退出诊断。")
            return

        # 校验输入
        if not choice.isdigit() or not (1 <= int(choice) <= len(options)):
            print(f"[提示] 请输入 1 到 {len(options)} 之间的数字")
            step -= 1          # 这一步不算，重来
            continue

        # 取出用户选的选项
        selected = options[int(choice) - 1]

        # 判断是否结束
        if selected['next'] is None:
            # 结束，显示结论
            print()
            print('-' * 55)
            print("【诊断结论】")
            print(selected['conclusion'])
            print('-' * 55)
            return
        else:
            # 继续下一个节点
            current_id = selected['next']


def diagnose(keyword):
    """
    对外接口：根据用户描述进行诊断
    返回 True 表示走了决策树，False 表示没有匹配的树
    """
    trees = load_trees()
    tree = match_tree(trees, keyword)

    if tree is None:
        return False

    run_tree(tree)
    return True


# 单独运行本文件时，做个简单测试
if __name__ == '__main__':
    print("决策树模块测试")
    print()
    trees = load_trees()
    print(f"已加载 {len(trees)} 棵决策树：")
    for t in trees:
        print(f"  - {t['name']}  (触发词: {', '.join(t['trigger'])})")
