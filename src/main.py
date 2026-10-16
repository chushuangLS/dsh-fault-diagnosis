"""
机房故障智能诊断助手 - 主程序

功能：
  1. 对话式逐层排查故障（AI 驱动）
  2. 自动记录教室号，需报修的故障写入记录表
  3. 支持查看和修改报修记录

作者：liyishuo1
"""

import json
import os
import sys

# 把本文件所在目录加入模块搜索路径
# 这样无论在哪个目录运行（python src/main.py 或 cd src 后运行），
# 都能正确导入同目录下的 ai_diagnosis 和 repair_log
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_diagnosis import DiagnosisSession
import repair_log
import version

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'fault_cases.json')


def load_cases():
    """
    读取故障知识库（手工 + 自动沉淀）

    直接复用 knowledge 模块的合并逻辑，避免两处各读各的、
    导致命令行降级匹配看不到自动沉淀出来的案例。
    """
    try:
        import knowledge
        return knowledge._load_raw()['cases']
    except Exception:
        # knowledge 不可用时退回只读手工文件
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


def print_help():
    """打印帮助"""
    print()
    print("可用命令：")
    print("  q          退出程序")
    print("  r          重新开始一次诊断")
    print("  log        查看所有报修记录")
    print("  log 未报修  按状态筛选记录")
    print("  done 编号 状态   修改记录状态，如：done R001 已解决")
    print("  help       显示本帮助")
    print()


def main():
    """主程序入口"""
    print("=" * 55)
    print(f"  机房故障智能诊断助手  v{version.VERSION}")
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
    print("输入 help 查看可用命令")
    print()

    session = None

    while True:
        prompt = "故障描述：" if session is None else "你的回答："
        user_input = input(prompt).strip()

        if not user_input:
            print("请输入内容")
            continue

        # ============ 命令处理 ============
        if user_input == 'q':
            print("再见！")
            break

        if user_input == 'help':
            print_help()
            continue

        if user_input == 'r':
            session = None
            print("\n--- 已重置，请重新描述故障 ---\n")
            continue

        # 查看记录：log 或 log 状态
        if user_input.startswith('log'):
            parts = user_input.split()
            status_filter = parts[1] if len(parts) > 1 else None
            show_records_safe(status_filter)
            continue

        # 修改状态：done R001 已解决
        if user_input.startswith('done'):
            parts = user_input.split()
            if len(parts) < 3:
                print("用法：done 记录编号 新状态")
                print(f"状态可选：{' / '.join(repair_log.ALL_STATUS)}")
                continue
            rid, new_status = parts[1], parts[2]
            note = ' '.join(parts[3:]) if len(parts) > 3 else ''
            ok, msg = repair_log.update_status(rid, new_status, note)
            print(('✅ ' if ok else '❌ ') + msg)
            continue

        # ============ 诊断流程 ============
        if session is None:
            print()
            print("正在分析，请稍候...")
            print()
            try:
                session = DiagnosisSession()
                session.set_symptom(user_input)
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

        try:
            reply, finished, need_repair = session.send(user_input)

            print()
            if finished:
                print("=" * 55)
                print("【诊断结论】")
                print("=" * 55)
                print(reply)
                print("=" * 55)

                # 需要报修 → 写入记录
                if need_repair:
                    classroom = session.classroom or '未填写'
                    rid = repair_log.add_record(
                        classroom=classroom,
                        symptom=session.symptom,
                        conclusion=reply,
                        status=repair_log.STATUS_PENDING,
                    )
                    print()
                    print(f"📝 已记录为待报修（编号 {rid}，教室 {classroom}）")
                    print(f"   报修后请执行：done {rid} 已报修")

                print()
                print("--- 本次诊断结束，可继续描述下一个故障 ---")
                print()
                session = None
            else:
                print(f"→ {reply}")
                print()

        except Exception as e:
            print(f"\n[错误] AI 调用失败：{e}")
            print("已结束本次诊断\n")
            session = None


def show_records_safe(status_filter=None):
    """安全地显示记录（处理文件异常）"""
    try:
        repair_log.show_records(status_filter)
    except Exception as e:
        print(f"[错误] 读取记录失败：{e}")


if __name__ == '__main__':
    main()
