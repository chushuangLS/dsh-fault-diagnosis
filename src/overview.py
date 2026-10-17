"""
机房故障智能诊断助手 - 运行总览的数据计算

回答的问题分成两类：

  一、现在能不能上课
      「这间教室坏了几台」意义有限 —— 78 人的课坏了 2 台照样能上，
      教师机坏了却一台不缺也上不了。
      所以判定的是**影不影响上课**，不是坏了几台。

  二、今天还有哪几节课要出问题
      从"事后发现"变成"提前准备"：早上打开就知道今天有几节要调。

判定「影响上课」的三个条件（任一命中即可）：

  1. 整体跳闸 —— 未解决的教室设施故障，现象含 总闸/跳闸/没电/停电
  2. 教师机不可用 —— 未解决故障，现象/结论含 教师机/讲台 等
  3. 可用台数 < 上课人数 —— 电脑没坏够，但这节课坐不下

前两条不限定有没有课：整间跳闸或教师机坏了，任何排在那个时段的课都上不了。
第三条只在有课时成立：没课就没有"上课人数"可比。
"""

import re

import classroom
import fault_category
import repair_log
import schedule

# 未解决 = 还需要人处理的状态
UNRESOLVED = [repair_log.STATUS_PENDING,
              repair_log.STATUS_SELF_FIX,
              repair_log.STATUS_REPORTED]

# 整体跳闸的关键词
#
# 「短路」「漏电」也算：出现这些词时总闸必然合不上，
# 结果同样是整间用不了。
_BREAKER_WORDS = ['总闸', '跳闸', '没电', '停电', '断电',
                  '配电箱', '配电柜', '空开', '空气开关', '断路器',
                  '短路', '漏电']

# 教师机关键词
#
# 教师机坏了，学生机全好也上不了课 —— 讲台那台是放课件、控屏幕用的。
_TEACHER_PC_WORDS = ['教师机', '教师电脑', '教师用机', '教师端',
                     '讲台', '教师台']


def _text(record):
    return ((record.get('故障现象') or '') + ' '
            + (record.get('诊断结论') or ''))


def is_breaker_trip(record):
    """这条故障是不是「整间跳闸」级别"""
    t = _text(record)
    return any(w in t for w in _BREAKER_WORDS)


def is_teacher_pc_fault(record):
    """这条故障是不是出在教师机上"""
    t = _text(record)
    return any(w in t for w in _TEACHER_PC_WORDS)


def _unresolved_by_room():
    """
    按教室归类未解决的故障

    返回 {"教学楼|教室": [record, ...]}
    """
    out = {}
    for r in repair_log.load_records():
        if (r.get('状态') or '') not in UNRESOLVED:
            continue
        room = (r.get('教室') or '').strip()
        if not room or room == '未填写':
            continue
        key = schedule.room_key((r.get('教学楼') or '').strip(), room)
        out.setdefault(key, []).append(r)
    return out


def _broken_machines(records):
    """这批记录里坏了几台电脑（设施故障不算台数）"""
    return repair_log.count_machines(
        [r for r in records if not repair_log.is_facility(r)])


def room_impact(records, total, students=None, has_class=False):
    """
    判断一间教室是否「影响上课」

    参数：
      records   - 该教室未解决的故障记录
      total     - 教室设备总数
      students  - 这节课的选课人数（没课时传 None）
      has_class - 这一节有没有课

    返回：
      {'impact': bool, 'reasons': [...], 'broken': n, 'available': n}
    """
    reasons = []
    broken = _broken_machines(records)
    available = max((total or 0) - broken, 0)

    if any(is_breaker_trip(r) for r in records):
        reasons.append('整间跳闸')

    if any(is_teacher_pc_fault(r) for r in records):
        reasons.append('教师机故障')

    # 只有真的在上的课才比人数 —— 没课时"上课人数"没有意义
    if has_class and students:
        if available < students:
            reasons.append(f'可用 {available} 台 < {students} 人')

    return {
        'impact': bool(reasons),
        'reasons': reasons,
        'broken': broken,
        'available': available,
    }


def overview():
    """
    运行总览需要的全部数据

    返回：
      {
        'kpi': {...},
        'rooms': [{'building', 'room', 'total', 'broken', 'facility',
                   'impact', 'reasons', 'class': {...} | None}, ...],
        'warnings': [...],        # 今天受影响的课
        'categories': [...],      # 故障类型分布
        'trend': {'dates': [...], 'new': [...], 'resolved': [...]},
        'term': {...}, 'week': n, 'period': n,
      }
    """
    rooms_flat = classroom.flat_rooms()
    unresolved = _unresolved_by_room()
    sched = schedule.load()
    week = schedule.current_week(sched)
    period = schedule.current_period(sched)

    room_rows = []
    for r in rooms_flat:
        key = schedule.room_key(r['building'], r['name'])
        recs = unresolved.get(key, [])
        total = r.get('total', 0)

        # 这间教室此刻在上什么课
        cls = None
        if week and period and (sched.get('rooms') or {}).get(key):
            c = schedule.room_is_busy(sched['rooms'][key], _today_weekday(),
                                      period, week)
            if c:
                cls = c

        imp = room_impact(recs, total,
                          students=(cls or {}).get('students'),
                          has_class=bool(cls))

        room_rows.append({
            'building': r['building'],
            'room': r['name'],
            'total': total,
            'broken': imp['broken'],
            'facility': sum(1 for x in recs if repair_log.is_facility(x)),
            'impact': imp['impact'],
            'reasons': imp['reasons'],
            'available': imp['available'],
            'class': cls,
            'has_schedule': key in (sched.get('rooms') or {}),
        })

    return {
        'kpi': _kpi(room_rows, unresolved),
        'rooms': room_rows,
        'warnings': today_warnings(sched, unresolved, rooms_flat),
        'categories': category_distribution(),
        'trend': trend(days=14),
        'term': sched.get('term') or {},
        'week': week,
        'period': period,
    }


def _today_weekday():
    """今天是星期几（1-7，周一为 1）"""
    from datetime import date

    return date.today().isoweekday()


def _kpi(room_rows, unresolved):
    """顶部五个数字"""
    total_pcs = sum((r.get('total') or 0) for r in room_rows)
    broken = sum((r.get('broken') or 0) for r in room_rows)

    recs = [x for group in unresolved.values() for x in group]
    reported = repair_log.count_machines(
        recs, statuses=[repair_log.STATUS_REPORTED])
    pending = repair_log.count_machines(
        recs, statuses=[repair_log.STATUS_PENDING])
    selffix = repair_log.count_machines(
        recs, statuses=[repair_log.STATUS_SELF_FIX])

    return {
        'total_pcs': total_pcs,
        'broken_pcs': broken,
        'available_pcs': max(total_pcs - broken, 0),
        'available_rate': round((total_pcs - broken) / total_pcs * 100, 1)
                          if total_pcs else 100.0,
        'pending': pending,
        'reported': reported,
        'selffix': selffix,
        'pending_records': len(recs),
        'repeat_count': len(repair_log.repeated_faults()),
        'room_count': len(room_rows),
        'impact_rooms': sum(1 for r in room_rows if r['impact']),
    }


def today_warnings(sched, unresolved, rooms_flat):
    """
    今天受影响的课

    遍历今天每一节有课的教室，判断是否会受故障影响，命中就生成一条预警。

    同一间教室一天可能有多节命中 —— 每节课的选课人数不同，
    可能第 1 节够用、第 3 节就超了，所以必须逐节判断。
    """
    rooms_data = sched.get('rooms') or {}
    periods = sched.get('periods') or {}
    term = sched.get('term') or {}
    weeks = int(term.get('weeks') or 0)
    week = schedule.current_week(sched)

    if not week or (weeks and week > weeks):
        return []

    day = _today_weekday()
    now_min = _now_minutes()
    total_by_room = {
        schedule.room_key(r['building'], r['name']): r.get('total', 0)
        for r in rooms_flat
    }

    out = []
    for key, rd in rooms_data.items():
        recs = unresolved.get(key)
        if not recs:
            continue

        building, _, room = key.partition('|')
        total = total_by_room.get(key, rd.get('seats') or 0)

        for c in (rd.get('courses') or []):
            if c.get('day') != day:
                continue
            if not (c.get('week_start', 0) <= week <= c.get('week_end', 0)):
                continue

            p = c.get('period_start')
            imp = room_impact(recs, total,
                              students=c.get('students'), has_class=True)
            if not imp['impact']:
                continue

            span = periods.get(str(p)) or {}
            start_min = schedule._hhmm_to_min(span.get('start'))

            if start_min is None:
                state = 'unknown'
            elif now_min < start_min:
                state = 'upcoming'
            elif p == schedule.current_period(sched):
                state = 'ongoing'
            else:
                state = 'past'

            out.append({
                'building': building,
                'room': room,
                'period': p,
                'time': span,
                'state': state,
                'minutes_until': (start_min - now_min)
                                 if (start_min is not None and now_min < start_min)
                                 else None,
                'course': {
                    'name': c.get('name', ''),
                    'teacher': schedule.mask_teacher(c.get('teacher')),
                    'students': c.get('students'),
                },
                'reasons': imp['reasons'],
                'broken': imp['broken'],
                'available': imp['available'],
                'total': total,
                'suggest': suggest_rooms(sched, day, p, week,
                                         c.get('students') or 0,
                                         exclude=key),
            })

    # 进行中排最前，其次按开始时间
    order = {'ongoing': 0, 'upcoming': 1, 'unknown': 2, 'past': 3}
    out.sort(key=lambda x: (order.get(x['state'], 9), x['period']))
    return out


def suggest_rooms(sched, day, period, week, students, exclude=None, limit=3):
    """
    找可以调课去的空闲教室

    只推荐**够坐的最小教室** —— 25 人的课不该推荐 200 座的大教室。
    """
    rooms_data = sched.get('rooms') or {}
    if not rooms_data:
        return []

    out = []
    for r in classroom.flat_rooms():
        key = schedule.room_key(r['building'], r['name'])
        if key == exclude:
            continue
        rd = rooms_data.get(key)
        # 没有课表的教室不能推荐 —— 不知道它是不是也满着
        if not rd:
            continue
        if schedule.room_is_busy(rd, day, period, week):
            continue

        seats = r.get('total') or 0
        if students and seats < students:
            continue

        out.append({
            'building': r['building'],
            'room': r['name'],
            'seats': seats,
        })

    out.sort(key=lambda x: x['seats'])
    return out[:limit]


def category_distribution():
    """故障类型分布（用于看板的柱状图）"""
    counts = {}
    for r in repair_log.load_records():
        cat = fault_category.classify(r)
        counts[cat] = counts.get(cat, 0) + 1

    items = [{'category': k, 'count': v}
             for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return items


def trend(days=14):
    """
    近 N 天的新增 / 解决趋势

    数据不足时前端显示「数据积累中」，不画假线。
    """
    from datetime import date, datetime, timedelta

    records = repair_log.load_records()

    today = date.today()
    dates = [(today - timedelta(days=days - 1 - i)).isoformat()
             for i in range(days)]

    new_count = {d: 0 for d in dates}
    resolved_count = {d: 0 for d in dates}

    for r in records:
        d = (r.get('时间') or '')[:10]
        if d in new_count:
            new_count[d] += 1
        # 已解决的记录：按时间字段统计"当天报的已解决数"
        # （没有单独的解决时间字段，这里用报修时间近似 ——
        #   看板只用来判断大致趋势，不追求精确到小时）
        if d in resolved_count and (r.get('状态') or '') == repair_log.STATUS_RESOLVED:
            resolved_count[d] += 1

    # 有数据的天数
    active_days = len({(r.get('时间') or '')[:10] for r in records})

    return {
        'dates': dates,
        'new': [new_count[d] for d in dates],
        'resolved': [resolved_count[d] for d in dates],
        'active_days': active_days,
    }


def _now_minutes():
    from datetime import datetime

    n = datetime.now()
    return n.hour * 60 + n.minute
