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

def add_room(building, room_name, total=0, note=''):
    """
    在某教学楼下新增教室

    说明：不再接受"损坏数"参数 —— 设备的损坏台数完全由报修台账推导，
    在这里手填会和台账冲突（两处记录同一件事，必然对不上）。
    """
    room_name = (room_name or '').strip()
    if not room_name:
        return False, '教室名称不能为空'

    try:
        total = int(total)
    except (TypeError, ValueError):
        return False, '电脑数量必须是整数'

    if total < 0:
        return False, '数量不能为负数'

    with file_lock(DATA_FILE):
        return _add_room_locked(building, room_name, total, note)


def _add_room_locked(building, room_name, total, note):
    data = load()
    for b in data['buildings']:
        if b['name'] == building:
            if any(r['name'] == room_name for r in b['rooms']):
                return False, f'「{building}」下已存在教室「{room_name}」'
            b['rooms'].append({
                'name': room_name,
                'total': total,
                'note': note or '',
            })
            save(data)
            return True, f'已添加教室「{room_name}」'

    return False, f'未找到教学楼「{building}」'


def update_room(building, room_name, total=None, note=None):
    """修改教室信息（电脑总数 / 备注）"""
    with file_lock(DATA_FILE):
        return _update_room_locked(building, room_name, total, note)


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

            if note is not None:
                r['note'] = note

            # 兼容：清掉旧数据里遗留的手动损坏数字段
            # （损坏台数现在完全由报修台账推导）
            r.pop('broken', None)

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

def _room_status_counts():
    """
    从报修台账统计每间教室各状态的机器台数

    返回：{"教学楼|教室": {'未报修': n, '待自修': n, '已报修': n, '已解决': n}}

    说明：
      · 按「数量」字段累加台数，而不是数记录条数
        （一条记录可能代表多台同因损坏的机器）
      · 台数的唯一来源是报修台账，教室台账不再单独存"损坏数"，
        避免两处数据不一致
    """
    try:
        import repair_log
    except ImportError:
        return {}

    result = {}
    try:
        records = repair_log.load_records()
    except Exception:
        return result

    for r in records:
        room = (r.get('教室') or '').strip()
        building = (r.get('教学楼') or '').strip()
        if not room or room == '未填写':
            continue

        status = r.get('状态') or repair_log.STATUS_PENDING
        qty = repair_log.get_quantity(r)

        key = f'{building}|{room}'
        d = result.setdefault(key, {})
        d[status] = d.get(status, 0) + qty

    return result


def _count_unresolved_by_room():
    """
    每间教室「不能用」的机器台数

    「不能用」= 未报修 + 待自修 + 已报修（即尚未解决的）
    已解决的机器算修好了，不计入。
    """
    counts = {}
    for key, by_status in _room_status_counts().items():
        n = sum(
            v for s, v in by_status.items()
            if s != '已解决'
        )
        if n:
            counts[key] = n
    return counts


def _count_auto_broken(building, room):
    """某间教室由报修记录统计出的未解决台数"""
    key = f'{building}|{room}'
    return _count_unresolved_by_room().get(key, 0)


def summary():
    """
    汇总统计

    设备分三种状态：
      正常    —— 台账总数 - 不能用台数
      待自修  —— 非硬件问题，可自行修复（黄色）
      不能用  —— 需要报修 / 等待维修（硬件故障）

    台数的唯一来源是报修台账，教室台账不再单独存"损坏数"，
    避免同一件事记在两个地方、两边对不上。
    """
    data = load()
    buildings = data['buildings']
    status_map = _room_status_counts()

    total_rooms = 0
    total_pcs = 0
    total_broken = 0
    total_self_fix = 0

    for b in buildings:
        for r in b['rooms']:
            total_rooms += 1
            total_pcs += r.get('total', 0)

            by_status = status_map.get(f"{b['name']}|{r['name']}", {})
            self_fix = by_status.get('待自修', 0)
            broken = sum(v for s, v in by_status.items() if s != '已解决')

            total_self_fix += self_fix
            total_broken += broken

    return {
        'buildings': len(buildings),
        'rooms': total_rooms,
        'total_pcs': total_pcs,
        'broken_pcs': total_broken,
        'self_fix_pcs': total_self_fix,
        'healthy_pcs': max(total_pcs - total_broken, 0),
    }


def flat_rooms():
    """
    把两级结构拍平

    每间教室给出三种状态的台数：
      self_fix_pcs —— 待自修（黄色）
      broken_pcs   —— 不能用（含待自修，因为自修前也用不了）
      healthy_pcs  —— 正常
    """
    data = load()
    status_map = _room_status_counts()
    out = []

    for b in data['buildings']:
        for r in b['rooms']:
            key = f"{b['name']}|{r['name']}"
            by_status = status_map.get(key, {})

            total = r.get('total', 0)
            pending = by_status.get('未报修', 0)
            self_fix = by_status.get('待自修', 0)
            reported = by_status.get('已报修', 0)
            resolved = by_status.get('已解决', 0)

            broken = pending + self_fix + reported

            out.append({
                'building': b['name'],
                'name': r['name'],
                'full_name': f"{b['name']}-{r['name']}",
                'total': total,
                'broken': broken,
                'broken_pcs': broken,
                'self_fix_pcs': self_fix,
                'pending_pcs': pending,
                'reported_pcs': reported,
                'resolved_pcs': resolved,
                'healthy': max(total - broken, 0),
                'healthy_pcs': max(total - broken, 0),
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
