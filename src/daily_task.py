"""
机房故障智能诊断助手 - 日常报备模块

记录老师提出的日常需求（软件更新、安装软件、缺外设等），
作为待办清单跟踪处理。

与「故障诊断」的区别：
  诊断  = 设备坏了，需要排查原因
  报备  = 日常杂事，知道要做什么，只是需要安排去做

存储：data/daily_tasks.json

作者：liyishuo1
"""

import json
import os
import uuid
from datetime import datetime

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'daily_tasks.json')

# 状态
STATUS_PENDING = '待完成'
STATUS_DONE = '已完成'
ALL_STATUS = [STATUS_PENDING, STATUS_DONE]

# 优先级
PRIORITY_HIGH = '高'
PRIORITY_MID = '中'
PRIORITY_LOW = '低'
ALL_PRIORITY = [PRIORITY_HIGH, PRIORITY_MID, PRIORITY_LOW]

# 常用需求类型（前端下拉用，也允许自定义）
TASK_TYPES = [
    '软件更新',
    '安装新软件',
    '缺少键盘',
    '缺少鼠标',
    '缺少其他外设',
    '系统重装',
    '网络开通',
    '投影调试',
    '其他',
]


def _empty():
    return {'tasks': []}


def load():
    """读取全部报备任务"""
    if not os.path.exists(DATA_FILE):
        return _empty()
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('tasks', [])
        return data
    except Exception:
        return _empty()


def save(data):
    """保存"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _next_id(tasks):
    """生成编号 T001 / T002 ..."""
    if not tasks:
        return 'T001'
    nums = []
    for t in tasks:
        try:
            nums.append(int(t['id'][1:]))
        except (ValueError, KeyError):
            continue
    return f'T{max(nums) + 1:03d}' if nums else f'T{len(tasks) + 1:03d}'


def add_task(building='', room='', task_type='', teacher='', major='',
             detail='', due='', priority=PRIORITY_MID):
    """
    新增一条报备

    参数：
      building  - 教学楼
      room      - 教室名
      task_type - 需求类型（软件更新/安装新软件/…）
      teacher   - 教师姓名
      major     - 专业名称
      detail    - 详细情况
      due       - 预计解决时间（YYYY-MM-DD 或 YYYY-MM-DD HH:MM）
      priority  - 优先级（高/中/低）

    返回：(是否成功, 提示信息或任务编号)
    """
    room = (room or '').strip()
    task_type = (task_type or '').strip()

    if not room:
        return False, '请选择教室'
    if not task_type:
        return False, '请选择需求类型'
    if priority not in ALL_PRIORITY:
        priority = PRIORITY_MID

    data = load()
    tid = _next_id(data['tasks'])

    data['tasks'].append({
        'id': tid,
        'building': (building or '').strip(),
        'room': room,
        'task_type': task_type,
        'teacher': (teacher or '').strip(),
        'major': (major or '').strip(),
        'detail': (detail or '').strip(),
        'due': (due or '').strip(),
        'priority': priority,
        'status': STATUS_PENDING,
        'created': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'finished': '',
        'note': '',
    })

    save(data)
    return True, tid


def update_task(tid, **fields):
    """
    修改任务

    允许修改：building / room / task_type / teacher / major /
             detail / due / priority / status / note
    """
    data = load()

    for t in data['tasks']:
        if t['id'] != tid:
            continue

        # 状态切换时记录完成时间
        if 'status' in fields and fields['status'] != t.get('status'):
            new_status = fields['status']
            if new_status not in ALL_STATUS:
                return False, f'状态必须是：{" / ".join(ALL_STATUS)}'
            t['status'] = new_status
            t['finished'] = (
                datetime.now().strftime('%Y-%m-%d %H:%M')
                if new_status == STATUS_DONE else ''
            )

        for k in ('building', 'room', 'task_type', 'teacher', 'major',
                  'detail', 'due', 'priority', 'note'):
            if k in fields and fields[k] is not None:
                t[k] = str(fields[k]).strip()

        save(data)
        return True, f'已更新 {tid}'

    return False, f'未找到任务 {tid}'


def toggle_status(tid):
    """在「待完成」和「已完成」之间切换"""
    data = load()
    for t in data['tasks']:
        if t['id'] != tid:
            continue
        new_status = (
            STATUS_DONE if t['status'] == STATUS_PENDING else STATUS_PENDING
        )
        return update_task(tid, status=new_status)
    return False, f'未找到任务 {tid}'


def delete_task(tid):
    """删除任务"""
    data = load()
    before = len(data['tasks'])
    data['tasks'] = [t for t in data['tasks'] if t['id'] != tid]

    if len(data['tasks']) == before:
        return False, f'未找到任务 {tid}'

    save(data)
    return True, f'已删除 {tid}'


def list_tasks(status=None, room=None):
    """
    列出任务

    排序规则：
      1. 未完成的排在前面
      2. 同状态内按预计解决时间升序（没填时间的排最后）
      3. 再按创建时间倒序
    """
    data = load()
    tasks = data['tasks']

    if status:
        tasks = [t for t in tasks if t['status'] == status]
    if room:
        tasks = [t for t in tasks if t['room'] == room]

    def sort_key(t):
        done = 1 if t['status'] == STATUS_DONE else 0
        due = t.get('due') or '9999-99-99'
        return (done, due, t.get('created', ''))

    tasks = sorted(tasks, key=sort_key)
    return list(reversed(tasks)) if False else tasks


def summary():
    """汇总统计"""
    tasks = load()['tasks']
    now = datetime.now().strftime('%Y-%m-%d')

    pending = [t for t in tasks if t['status'] == STATUS_PENDING]
    done = [t for t in tasks if t['status'] == STATUS_DONE]

    # 逾期：有预计时间、未完成、且时间已过
    overdue = [
        t for t in pending
        if t.get('due') and t['due'][:10] < now
    ]

    return {
        'total': len(tasks),
        'pending': len(pending),
        'done': len(done),
        'overdue': len(overdue),
        'high': len([t for t in pending if t.get('priority') == PRIORITY_HIGH]),
    }


# 测试
if __name__ == '__main__':
    print('日常报备模块测试')
    print()

    ok, tid = add_task(
        building='教学楼A', room='A101', task_type='安装新软件',
        teacher='张老师', major='计算机科学与技术',
        detail='需要安装 Python 和 VS Code，下周一上课要用',
        due='2026-10-20', priority='高',
    )
    print(ok, tid)

    ok, tid2 = add_task(
        building='实验楼', room='201', task_type='缺少鼠标',
        teacher='李老师', major='物联网工程',
        detail='第 3 排第 5 台鼠标失灵',
        due='2026-10-25', priority='中',
    )
    print(ok, tid2)

    print()
    print('--- 待办清单 ---')
    for t in list_tasks():
        mark = '✅' if t['status'] == STATUS_DONE else '⏳'
        print(f"  {mark} [{t['priority']}] {t['id']}  {t['building']}-{t['room']}  "
              f"{t['task_type']}  预计 {t['due'] or '未定'}  ({t['teacher']})")

    print()
    print(toggle_status(tid)[1])

    print()
    print('--- 完成后 ---')
    for t in list_tasks():
        mark = '✅' if t['status'] == STATUS_DONE else '⏳'
        print(f"  {mark} [{t['priority']}] {t['id']}  {t['room']}  {t['task_type']}")

    s = summary()
    print()
    print(f"汇总: 共{s['total']}条  待完成{s['pending']}  已完成{s['done']}  "
          f"逾期{s['overdue']}  高优先级{s['high']}")
