"""
机房故障智能诊断助手 - 教室与设备台账模块

数据结构（两级）：
    教学楼
      └── 教室
            ├── 电脑总数
            └── 损坏数

存储文件：data/classrooms.json
格式：
    {
      "buildings": [
        {
          "name": "教学楼A",
          "rooms": [
            {"name": "A101", "total": 60, "broken": 2, "note": ""}
          ]
        }
      ]
    }

作者：liyishuo1
"""

import json
import os

from filelock import file_lock

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'classrooms.json')


def _empty():
    return {'buildings': []}


def load():
    """读取教室数据"""
    if not os.path.exists(DATA_FILE):
        return _empty()
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if 'buildings' not in data:
            return _empty()
        return data
    except Exception:
        return _empty()


def save(data):
    """保存教室数据"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- 教学楼 ----------------

def add_building(name):
    """新增教学楼"""
    name = (name or '').strip()
    if not name:
        return False, '教学楼名称不能为空'

    with file_lock(DATA_FILE):
        return _add_building_locked(name)


def _add_building_locked(name):
    data = load()
    if any(b['name'] == name for b in data['buildings']):
        return False, f'教学楼「{name}」已存在'

    data['buildings'].append({'name': name, 'rooms': []})
    save(data)
    return True, f'已添加教学楼「{name}」'


def delete_building(name):
    """删除教学楼（连同其下教室）"""
    with file_lock(DATA_FILE):
        return _delete_building_locked(name)


def _delete_building_locked(name):
    data = load()
    before = len(data['buildings'])
    data['buildings'] = [b for b in data['buildings'] if b['name'] != name]

    if len(data['buildings']) == before:
        return False, f'未找到教学楼「{name}」'

    save(data)
    return True, f'已删除教学楼「{name}」'


# ---------------- 教室 ----------------

def add_room(building, room_name, total=0, broken=0, note=''):
    """在某教学楼下新增教室"""
    room_name = (room_name or '').strip()
    if not room_name:
        return False, '教室名称不能为空'

    try:
        total = int(total)
        broken = int(broken)
    except (TypeError, ValueError):
        return False, '电脑数量必须是整数'

    if total < 0 or broken < 0:
        return False, '数量不能为负数'
    if broken > total:
        return False, '损坏数不能大于总数'

    with file_lock(DATA_FILE):
        return _add_room_locked(building, room_name, total, broken, note)


def _add_room_locked(building, room_name, total, broken, note):
    data = load()
    for b in data['buildings']:
        if b['name'] == building:
            if any(r['name'] == room_name for r in b['rooms']):
                return False, f'「{building}」下已存在教室「{room_name}」'
            b['rooms'].append({
                'name': room_name,
                'total': total,
                'broken': broken,
                'note': note or '',
            })
            save(data)
            return True, f'已添加教室「{room_name}」'

    return False, f'未找到教学楼「{building}」'


def update_room(building, room_name, total=None, broken=None, note=None):
    """修改教室信息"""
    with file_lock(DATA_FILE):
        return _update_room_locked(building, room_name, total, broken, note)


def _update_room_locked(building, room_name, total=None, broken=None, note=None):
    data = load()
    for b in data['buildings']:
        if b['name'] != building:
            continue
        for r in b['rooms']:
            if r['name'] != room_name:
                continue

            if total is not None:
                try:
                    total = int(total)
                    if total < 0:
                        return False, '总数不能为负数'
                except (TypeError, ValueError):
                    return False, '电脑总数必须是整数'
                r['total'] = total

            if broken is not None:
                try:
                    broken = int(broken)
                    if broken < 0:
                        return False, '损坏数不能为负数'
                except (TypeError, ValueError):
                    return False, '损坏数必须是整数'
                r['broken'] = broken

            if note is not None:
                r['note'] = note

            if r['broken'] > r['total']:
                return False, '损坏数不能大于总数'

            save(data)
            return True, f'已更新教室「{room_name}」'

    return False, f'未找到教室「{room_name}」'


def delete_room(building, room_name):
    """删除教室"""
    with file_lock(DATA_FILE):
        return _delete_room_locked(building, room_name)


def _delete_room_locked(building, room_name):
    data = load()
    for b in data['buildings']:
        if b['name'] != building:
            continue
        before = len(b['rooms'])
        b['rooms'] = [r for r in b['rooms'] if r['name'] != room_name]
        if len(b['rooms']) == before:
            return False, f'未找到教室「{room_name}」'
        save(data)
        return True, f'已删除教室「{room_name}」'

    return False, f'未找到教学楼「{building}」'


# ---------------- 统计 ----------------

def _count_unresolved_by_room():
    """
    从报修台账统计每间教室「未解决」的故障数

    返回：{"教学楼|教室": 数量}
    说明：未解决 = 状态为「未报修」或「已报修」
          这是教室里「损坏电脑数」的真实来源，避免两处数据不一致
    """
    try:
        import repair_log
    except ImportError:
        return {}

    counts = {}
    try:
        records = repair_log.load_records()
    except Exception:
        return counts

    for r in records:
        # 已解决的机器算修好了，不计入损坏
        if r.get('状态') == repair_log.STATUS_RESOLVED:
            continue
        room = (r.get('教室') or '').strip()
        building = (r.get('教学楼') or '').strip()
        if not room or room == '未填写':
            continue
        key = f'{building}|{room}'
        counts[key] = counts.get(key, 0) + 1

    return counts


def _count_auto_broken(building, room):
    """某间教室由报修记录自动统计出的损坏数"""
    key = f'{building}|{room}'
    return _count_unresolved_by_room().get(key, 0)


def summary():
    """
    汇总统计

    损坏数 = 手动登记数 + 报修台账自动统计数

    为什么两者相加：
      手动登记 —— 用于"发现了但还没来得及走诊断流程"的临时记录
      自动统计 —— 从报修台账算出的、有据可查的损坏
      两者是不同来源，相加才是这间教室真实的损坏总数
    """
    data = load()
    buildings = data['buildings']
    broken_map = _count_unresolved_by_room()

    total_rooms = 0
    total_pcs = 0
    total_broken = 0
    total_manual = 0
    total_auto = 0

    for b in buildings:
        for r in b['rooms']:
            total_rooms += 1
            total_pcs += r.get('total', 0)

            manual = r.get('broken', 0)
            auto = broken_map.get(f"{b['name']}|{r['name']}", 0)

            total_manual += manual
            total_auto += auto
            total_broken += manual + auto

    return {
        'buildings': len(buildings),
        'rooms': total_rooms,
        'total_pcs': total_pcs,
        'broken_pcs': total_broken,
        'manual_broken': total_manual,
        'auto_broken': total_auto,
        'healthy_pcs': max(total_pcs - total_broken, 0),
    }


def flat_rooms():
    """
    把两级结构拍平

    损坏数拆成两个来源，便于前端解释"这个数字怎么来的"：
      manual_broken —— 手动登记的
      auto_broken   —— 从报修台账自动统计的
      broken        —— 两者之和
    """
    data = load()
    broken_map = _count_unresolved_by_room()
    out = []

    for b in data['buildings']:
        for r in b['rooms']:
            key = f"{b['name']}|{r['name']}"
            manual = r.get('broken', 0)
            auto = broken_map.get(key, 0)
            broken = manual + auto
            total = r.get('total', 0)

            out.append({
                'building': b['name'],
                'name': r['name'],
                'full_name': f"{b['name']}-{r['name']}",
                'total': total,
                'broken': broken,
                'manual_broken': manual,
                'auto_broken': auto,
                'healthy': max(total - broken, 0),
                'note': r.get('note', ''),
            })
    return out


# 测试
if __name__ == '__main__':
    print('教室台账模块测试')
    print()

    print(add_building('教学楼A'))
    print(add_building('实验楼'))
    print(add_room('教学楼A', 'A101', 60, 2))
    print(add_room('教学楼A', 'A102', 60, 0))
    print(add_room('实验楼', '201', 40, 5))
    print()

    s = summary()
    print(f"教学楼: {s['buildings']}  教室: {s['rooms']}  "
          f"电脑: {s['total_pcs']}  损坏: {s['broken_pcs']}")
    print()
    print(update_room('教学楼A', 'A101', broken=4))

    for r in flat_rooms():
        print(f"  {r['full_name']:<14} 总数 {r['total']:>3}  "
              f"损坏 {r['broken']:>2}  正常 {r['healthy']:>3}")
