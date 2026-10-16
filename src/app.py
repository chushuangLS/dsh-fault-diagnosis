"""
机房故障智能诊断助手 - Web 版后端

基于 Flask 提供 HTTP 接口，前端通过 AJAX 调用。
核心诊断逻辑复用 ai_diagnosis 和 repair_log 模块。

启动方式：
    python src/app.py
然后浏览器访问 http://127.0.0.1:5000

作者：liyishuo1
"""

import json
import os
import sys
import time
import uuid

from flask import Flask, request, jsonify, render_template, session

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_diagnosis
from ai_diagnosis import DiagnosisSession
import repair_log
import classroom
import daily_task
import version

# Flask 应用配置
# templates 和 static 目录放在项目根下
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'web', 'templates'),
    static_folder=os.path.join(BASE_DIR, 'web', 'static'),
)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-change-me')

# 默认密钥只适合本机自用。若部署到能被他人访问的环境，
# 任何人都能伪造 session。这里在启动时明确警告，避免被忽略。
if app.secret_key == 'dev-secret-change-me':
    print('[警告] 正在使用默认 FLASK_SECRET_KEY，仅适合本机演示。')
    print('       部署到内网或公网前，请先设置环境变量 FLASK_SECRET_KEY。')

# 会话存储：session_id -> DiagnosisSession
# 说明：内存存储，重启服务后丢失。对于机房现场使用足够。
#       后续如需持久化可改为文件或数据库。
SESSIONS = {}

# 单个会话的空闲存活时间（秒）与最大会话数
#
# 为什么需要限制：
#   会话原先只在「诊断结束」或「重置」时被移除。
#   但用户提出故障后直接关闭浏览器（很常见）不会触发任何清理，
#   该会话就会永久驻留 —— 每个都持有完整对话历史和 OpenAI 客户端对象，
#   长期运行会导致内存持续增长。
SESSION_TTL = 2 * 60 * 60      # 2 小时无活动即回收
MAX_SESSIONS = 200             # 上限，超出后淘汰最旧的


def _purge_sessions():
    """
    清理过期会话与超量会话

    在每次创建新会话前调用，无需后台线程。
    """
    now = time.time()

    # 1) 过期清理
    expired = [
        sid for sid, s in SESSIONS.items()
        if now - getattr(s, 'last_active', now) > SESSION_TTL
    ]
    for sid in expired:
        SESSIONS.pop(sid, None)

    # 2) 超量清理：淘汰最久未活动的
    if len(SESSIONS) > MAX_SESSIONS:
        ordered = sorted(
            SESSIONS.items(),
            key=lambda kv: getattr(kv[1], 'last_active', 0),
        )
        for sid, _ in ordered[:len(SESSIONS) - MAX_SESSIONS]:
            SESSIONS.pop(sid, None)


def get_session():
    """获取或创建当前浏览器的诊断会话"""
    sid = session.get('sid')
    if not sid or sid not in SESSIONS:
        _purge_sessions()
        sid = str(uuid.uuid4())
        session['sid'] = sid
        SESSIONS[sid] = DiagnosisSession()

    # 记录活动时间，供过期清理使用
    SESSIONS[sid].last_active = time.time()
    return SESSIONS[sid]


def _status_for_session(ds):
    """
    根据 AI 的结论决定记录的初始状态

    判定顺序很重要：
      1. 明确要求报修 → 未报修（硬件问题，等维修）
      2. 明确可以自修 → 待自修（非硬件问题，自己能处理）
      3. 两者都没有（AI 没打标记）→ 未报修

    为什么默认落在「未报修」：
      漏报修会让故障被遗忘；而"待自修"若判断错了，
      用户仍可在界面上改状态。保守优先。
    """
    if ds.need_repair:
        return repair_log.STATUS_PENDING
    if ds.self_fix:
        return repair_log.STATUS_SELF_FIX
    return repair_log.STATUS_PENDING


def _asset_version():
    """
    静态资源版本号（用于避免浏览器缓存旧文件）

    为什么需要：
      改完 CSS/JS 后刷新页面，浏览器可能仍用缓存里的旧文件，
      表现为"改了没生效"，排查起来很浪费时间。

      这里用静态文件的最后修改时间做版本号 —— 文件一改，版本就变，
      浏览器会自动重新拉取，不需要手动 Ctrl+F5。
    """
    static_dir = os.path.join(BASE_DIR, 'web', 'static')
    stamps = []
    try:
        for name in ('style.css', 'app.js', 'background.js'):
            path = os.path.join(static_dir, name)
            if os.path.exists(path):
                stamps.append(str(int(os.path.getmtime(path))))
    except OSError:
        pass
    return '-'.join(stamps) if stamps else '1'


# 服务启动时间：渲染到页面上，方便一眼看出跑的是不是最新代码
SERVER_START = time.strftime('%Y-%m-%d %H:%M')


@app.route('/')
def index():
    """主页"""
    return render_template(
        'index.html',
        asset_version=_asset_version(),
        server_start=SERVER_START,
        app_version=version.VERSION,
    )


@app.route('/api/chat', methods=['POST'])
def api_chat():
    """
    对话接口

    请求体：{"message": "用户输入"}
    响应：{"reply": "AI 回复", "finished": bool, "need_repair": bool,
           "record_id": "R001" 或 null, "classroom": "501"}
    """
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 重置会话
    if message == 'reset':
        sid = session.get('sid')
        if sid:
            SESSIONS[sid] = DiagnosisSession()
        return jsonify({'reply': '已重置，请重新描述故障', 'finished': False,
                        'need_repair': False, 'reset': True})

    try:
        ds = get_session()

        # 第一次输入时记录原始故障描述
        if not ds.symptom:
            ds.set_symptom(message)

        reply, finished, need_repair = ds.send(message)

        result = {
            'reply': reply,
            'finished': finished,
            'need_repair': need_repair,
            'self_fix': ds.self_fix,
            'quantity': ds.quantity,
            'classroom': ds.classroom or '',
            'record_id': None,
        }

        # 诊断结束 → 写入台账
        # 需要报修的记为「未报修」，可自修的记为「待自修」
        if finished:
            status = _status_for_session(ds)
            rid = repair_log.add_record(
                classroom=ds.classroom or '未填写',
                symptom=ds.symptom,
                conclusion=reply,
                status=status,
                building=ds.building or '',
                quantity=ds.quantity,
            )
            result['record_id'] = rid
            result['status'] = status

        # 结束的会话从内存里移除，下次重新开始
        if finished:
            sid = session.get('sid')
            if sid:
                SESSIONS.pop(sid, None)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': f'AI 调用失败：{e}'}), 500


@app.route('/api/chat/stream', methods=['POST'])
def api_chat_stream():
    """
    流式对话接口（Server-Sent Events）

    逐段推送 AI 回复，前端逐字显示。
    最后一条消息 type=end，携带 finished / need_repair 等状态。

    注意：生成器在请求上下文之外执行，
          因此所有依赖 request/session 的数据必须在进入生成器前取出。
    """
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    # 前端可通过下拉选择教室，此时直接采用（避免再让 AI 追问）
    picked_building = (data.get('building') or '').strip()
    picked_classroom = (data.get('classroom') or '').strip()

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # ---- 在请求上下文内完成所有 session 操作 ----
    sid = session.get('sid')

    if message == 'reset':
        if sid:
            SESSIONS[sid] = DiagnosisSession()
        else:
            SESSIONS[str(uuid.uuid4())] = DiagnosisSession()
        reset_sid = session.get('sid')

        def gen_reset():
            yield f"data: {json.dumps({'type': 'text', 'content': '已重置，请重新描述故障'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'end', 'finished': False, 'need_repair': False, 'reset': True, 'classroom': ''}, ensure_ascii=False)}\n\n"

        return app.response_class(
            gen_reset(),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    # 建立（或复用）会话，并把对象取出来
    #
    # 注意：这里可能因为「未配置 DEEPSEEK_API_KEY」等原因失败。
    # 如果直接让异常抛出去，Flask 会返回一个 HTML 500 页面，
    # 前端只会显示"请求失败"，用户完全不知道问题出在哪。
    # 所以这里捕获后，用 SSE 格式把具体原因回给前端。
    try:
        ds = get_session()
    except Exception as e:
        reason = str(e)

        def gen_error():
            yield f"data: {json.dumps({'type': 'text', 'content': '⚠ ' + reason}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'end', 'finished': False, 'need_repair': False, 'error': reason}, ensure_ascii=False)}\n\n"

        return app.response_class(
            gen_error(),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    sid = session.get('sid')

    # 前端已选教室 → 注入对话上下文，AI 就不会再问
    if picked_classroom and not ds.classroom:
        ds.set_location(picked_classroom, picked_building)

    if not ds.symptom:
        ds.set_symptom(message)

    def generate():
        try:
            for chunk in ds.send_stream(message):
                if chunk['type'] == 'text':
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                elif chunk['type'] == 'end':
                    payload = dict(chunk)
                    payload['record_id'] = None

                    # 诊断结束 → 写入台账
                    # 需要报修的记为「未报修」，可自修的记为「待自修」
                    if payload.get('finished'):
                        status = _status_for_session(ds)
                        rid = repair_log.add_record(
                            classroom=payload.get('classroom') or '未填写',
                            symptom=ds.symptom,
                            conclusion=payload.get('reply', ''),
                            status=status,
                            building=getattr(ds, 'building', '') or '',
                            quantity=payload.get('quantity', 1),
                        )
                        payload['record_id'] = rid
                        payload['status'] = status
                        payload['building'] = getattr(ds, 'building', '') or ''

                    # 诊断完成 → 沉淀进知识库（越用越聪明）
                    if payload.get('finished'):
                        try:
                            ok, msg = ai_diagnosis.save_diagnosis_case(ds)
                            payload['case_saved'] = ok
                            payload['case_msg'] = msg
                        except Exception as e:
                            payload['case_saved'] = False
                            payload['case_msg'] = str(e)

                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                    # 结束后清理会话
                    if payload.get('finished') and sid:
                        SESSIONS.pop(sid, None)

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@app.route('/api/records', methods=['GET'])
def api_records():
    """
    获取报修记录

    参数：
      status - 按状态筛选（可选）
      sort   - 排序方式：priority（默认，按状态分级）| time（纯按时间）
    """
    status = request.args.get('status') or None
    sort_by = request.args.get('sort') or 'priority'

    try:
        records = repair_log.load_records()

        # 分组计数（用于展示"未报修 3 / 已报修 1 / 已解决 5"）
        counts = {s: 0 for s in repair_log.ALL_STATUS}
        for r in records:
            st = r.get('状态', '')
            if st in counts:
                counts[st] += 1

        if status:
            records = [r for r in records if r['状态'] == status]

        # 按状态分级：未报修 → 已报修 → 已解决
        records = repair_log.sort_records(records, by=sort_by)

        return jsonify({
            'records': records,
            'statuses': repair_log.ALL_STATUS,
            'counts': counts,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/records/<record_id>', methods=['POST'])
def api_update_record(record_id):
    """修改记录状态"""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '')
    note = data.get('note', '')

    ok, msg = repair_log.update_status(record_id, new_status, note)
    if ok:
        return jsonify({'ok': True, 'message': msg})
    return jsonify({'ok': False, 'message': msg}), 400


@app.route('/api/records/<record_id>', methods=['PUT'])
def api_edit_record(record_id):
    """
    修改记录内容（现象 / 结论 / 备注 / 教室）

    请求体：{"symptom": "...", "conclusion": "...", "note": "...",
             "classroom": "...", "building": "..."}
    只传需要修改的字段即可。
    """
    data = request.get_json(silent=True) or {}
    ok, msg = repair_log.update_record(record_id, **data)
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/records/<record_id>', methods=['DELETE'])
def api_delete_record(record_id):
    """删除一条报修记录"""
    ok, msg = repair_log.delete_record(record_id)
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/records/manual', methods=['POST'])
def api_manual_record():
    """
    手动登记故障记录

    支持一次登记多条（表格里填多行：原因 + 数量）。

    请求体：
      {
        "building": "教学楼A",
        "classroom": "A101",
        "faults": [
          {"reason": "电源损坏", "quantity": 3, "status": "未报修", "note": ""},
          ...
        ]
      }

      也兼容单条写法（symptom + conclusion + quantity）。
    """
    d = request.get_json(silent=True) or {}
    classroom_name = (d.get('classroom') or '').strip()
    building = (d.get('building') or '').strip()

    if not classroom_name:
        return jsonify({'ok': False, 'message': '请指定教室'}), 400

    # 组装成统一的 faults 列表
    faults = d.get('faults')
    if not faults:
        symptom = (d.get('symptom') or '').strip()
        if not symptom:
            return jsonify({'ok': False, 'message': '请至少填写一条故障'}), 400
        faults = [{
            'reason': symptom,
            'quantity': d.get('quantity', 1),
            'status': d.get('status') or repair_log.STATUS_PENDING,
            'note': d.get('note', '') or '',
        }]

    # 校验状态合法性
    for f in faults:
        st = f.get('status') or repair_log.STATUS_PENDING
        if st not in repair_log.ALL_STATUS:
            f['status'] = repair_log.STATUS_PENDING

    n, ids, err = repair_log.register_faults(building, classroom_name, faults)
    if err:
        return jsonify({'ok': False, 'message': err}), 400

    return jsonify({
        'ok': True,
        'ids': ids,
        'count': n,
        'message': f'已登记 {n} 条故障（{", ".join(ids)}）',
    })


@app.route('/api/export/repair', methods=['GET'])
def api_export_repair():
    """
    导出报修记录为 Excel

    返回 .xlsx 文件流，浏览器直接下载。
    报表结构见 excel_export 模块的说明。
    """
    try:
        import excel_export
        filename, data = excel_export.export_to_bytes()
    except ImportError:
        return jsonify({'error': '导出功能不可用：缺少 openpyxl，请执行 '
                                 'pip install -r requirements.txt'}), 500
    except Exception as e:
        return jsonify({'error': f'导出失败：{e}'}), 500

    from urllib.parse import quote

    # 文件名含中文，需要按 RFC 5987 编码，否则部分浏览器会乱码
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"

    return app.response_class(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': disposition},
    )


@app.route('/api/statistics', methods=['GET'])
def api_statistics():
    """统计数据（用于数据看板）"""
    try:
        records = repair_log.load_records()
        by_status = {}
        by_classroom = {}
        by_date = {}

        for r in records:
            # 状态统计
            by_status[r['状态']] = by_status.get(r['状态'], 0) + 1

            # 教室统计
            cr = r['教室']
            by_classroom[cr] = by_classroom.get(cr, 0) + 1

            # 日期统计（取时间的前 10 位，即 YYYY-MM-DD）
            d = (r.get('时间') or '')[:10]
            if d:
                by_date[d] = by_date.get(d, 0) + 1

        # 按故障次数排序的教室（前 10）
        top_classrooms = sorted(by_classroom.items(), key=lambda x: -x[1])[:10]

        # 日期升序
        date_sorted = sorted(by_date.items())

        total = len(records)
        resolved = by_status.get(repair_log.STATUS_RESOLVED, 0)
        resolve_rate = round(resolved / total * 100, 1) if total else 0

        return jsonify({
            'total': total,
            'by_status': {
                '未报修': by_status.get(repair_log.STATUS_PENDING, 0),
                '已报修': by_status.get(repair_log.STATUS_REPORTED, 0),
                '已解决': resolved,
            },
            'resolve_rate': resolve_rate,
            'top_classrooms': top_classrooms,
            'dates': [d for d, _ in date_sorted],
            'date_counts': [n for _, n in date_sorted],
            'knowledge': _knowledge_stats(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _knowledge_stats():
    """知识库统计（用于展示"越用越聪明"）"""
    try:
        import knowledge
        return knowledge.stats()
    except Exception:
        return {'total': 0, 'auto': 0, 'manual': 0, 'by_category': {}}


# ============================================================
# 知识库（检索增强）
# ============================================================

@app.route('/api/knowledge', methods=['GET'])
def api_knowledge():
    """
    知识库查询

    无参数：返回统计与全部分类
    ?q=xxx：返回与查询最相似的案例（用于演示检索效果）
    """
    q = request.args.get('q', '').strip()

    try:
        import knowledge
    except ImportError:
        return jsonify({'error': '知识库模块不可用'}), 500

    if q:
        hits = knowledge.search(q, top_n=5, min_score=0)
        return jsonify({
            'query': q,
            'hits': hits,
            'stats': knowledge.stats(),
        })

    return jsonify({
        'stats': knowledge.stats(),
    })


# ============================================================
# 教室与设备管理
# ============================================================

@app.route('/api/classrooms', methods=['GET'])
def api_classrooms():
    """
    获取全部教室数据（两级结构 + 汇总）

    注意：buildings 用的是 buildings_with_stats()，而不是磁盘上的原始数据。
    原始数据里的 broken 是早期手工填写的遗留字段，与报修台账无关；
    直接用会导致列表页显示陈旧数值，与教室详情页对不上。
    """
    return jsonify({
        'buildings': classroom.buildings_with_stats()['buildings'],
        'summary': classroom.summary(),
        'flat': classroom.flat_rooms(),
    })


@app.route('/api/classrooms/summary', methods=['GET'])
def api_classroom_summary():
    """仅返回汇总（状态栏用）"""
    return jsonify(classroom.summary())


@app.route('/api/classrooms/room-detail', methods=['GET'])
def api_room_detail():
    """
    某教室的设备详情

    参数：?building=教学楼A&room=A101
    返回：教室台账信息 + 该教室的全部故障记录（含损坏原因）
    """
    building = request.args.get('building', '').strip()
    room = request.args.get('room', '').strip()

    # 教室台账信息
    info = None
    for r in classroom.flat_rooms():
        if r['building'] == building and r['name'] == room:
            info = r
            break

    # 该教室的故障记录
    records = []
    try:
        for rec in repair_log.load_records():
            if (rec.get('教室') or '').strip() != room:
                continue
            # 教学楼能对上，或旧记录没有教学楼字段
            rec_b = (rec.get('教学楼') or '').strip()
            if rec_b and building and rec_b != building:
                continue
            records.append(rec)
    except Exception:
        pass

    # 倒序，最新在前
    records = list(reversed(records))

    # 按状态统计「台数」——一条记录可能代表多台机器，所以要累加数量
    def machines(status):
        return sum(repair_log.get_quantity(r) for r in records
                   if r['状态'] == status)

    pending = machines(repair_log.STATUS_PENDING)
    self_fix = machines(repair_log.STATUS_SELF_FIX)
    reported = machines(repair_log.STATUS_REPORTED)
    resolved = machines(repair_log.STATUS_RESOLVED)

    return jsonify({
        'info': info,
        'records': records,
        'counts': {
            'pending': pending,
            'self_fix': self_fix,
            'reported': reported,
            'resolved': resolved,
            'unresolved': pending + self_fix + reported,
        },
    })


@app.route('/api/classrooms/building', methods=['POST'])
def api_add_building():
    """新增教学楼"""
    d = request.get_json(silent=True) or {}
    ok, msg = classroom.add_building(d.get('name'))
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/classrooms/building/<name>', methods=['DELETE'])
def api_delete_building(name):
    """删除教学楼"""
    ok, msg = classroom.delete_building(name)
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/classrooms/room', methods=['POST'])
def api_add_room():
    """新增教室（只需电脑总数与备注，损坏台数由报修台账推导）"""
    d = request.get_json(silent=True) or {}
    ok, msg = classroom.add_room(
        d.get('building'),
        d.get('name'),
        d.get('total', 0),
        d.get('note', ''),
    )
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/classrooms/room', methods=['PUT'])
def api_update_room():
    """修改教室（电脑总数 / 备注）"""
    d = request.get_json(silent=True) or {}
    ok, msg = classroom.update_room(
        d.get('building'),
        d.get('name'),
        d.get('total'),
        d.get('note'),
    )
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/classrooms/room', methods=['DELETE'])
def api_delete_room():
    """删除教室"""
    d = request.get_json(silent=True) or {}
    ok, msg = classroom.delete_room(d.get('building'), d.get('name'))
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


# ============================================================
# 日常报备（待办清单）
# ============================================================

@app.route('/api/tasks', methods=['GET'])
def api_tasks():
    """获取报备清单，支持按状态/教室筛选"""
    status = request.args.get('status') or None
    room = request.args.get('room') or None
    return jsonify({
        'tasks': daily_task.list_tasks(status, room),
        'summary': daily_task.summary(),
        'types': daily_task.TASK_TYPES,
        'priorities': daily_task.ALL_PRIORITY,
        'statuses': daily_task.ALL_STATUS,
    })


@app.route('/api/tasks', methods=['POST'])
def api_add_task():
    """新增报备"""
    d = request.get_json(silent=True) or {}
    ok, result = daily_task.add_task(
        building=d.get('building', ''),
        room=d.get('room', ''),
        task_type=d.get('task_type', ''),
        teacher=d.get('teacher', ''),
        major=d.get('major', ''),
        detail=d.get('detail', ''),
        due=d.get('due', ''),
        priority=d.get('priority', daily_task.PRIORITY_MID),
    )
    if ok:
        return jsonify({'ok': True, 'id': result, 'message': f'已添加报备 {result}'})
    return jsonify({'ok': False, 'message': result}), 400


@app.route('/api/tasks/<tid>', methods=['PUT'])
def api_update_task(tid):
    """修改报备"""
    d = request.get_json(silent=True) or {}
    ok, msg = daily_task.update_task(tid, **d)
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/tasks/<tid>/toggle', methods=['POST'])
def api_toggle_task(tid):
    """在待完成 / 已完成之间切换"""
    ok, msg = daily_task.toggle_status(tid)
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/tasks/<tid>', methods=['DELETE'])
def api_delete_task(tid):
    """删除报备"""
    ok, msg = daily_task.delete_task(tid)
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 400)


if __name__ == '__main__':
    print('=' * 55)
    print(f'  机房故障智能诊断助手 · Web 版  v{version.VERSION}')
    print('=' * 55)
    print()

    # 启动时先检查 API Key，避免用户在对话页才发现用不了
    if not os.environ.get('DEEPSEEK_API_KEY'):
        print('  ⚠ 未检测到环境变量 DEEPSEEK_API_KEY')
        print('    诊断功能将无法使用，请先配置后再启动：')
        print()
        print('      临时（仅当前终端）：')
        print('        $env:DEEPSEEK_API_KEY = "你的key"')
        print()
        print('      永久（需重开终端）：')
        print('        [Environment]::SetEnvironmentVariable(')
        print('          "DEEPSEEK_API_KEY", "你的key", "User")')
        print()
        print('    报修台账、教室管理、报表导出等功能不受影响。')
        print()

    print('  访问地址: http://127.0.0.1:5000')
    print('  按 Ctrl+C 停止服务')
    print()

    app.run(host='127.0.0.1', port=5000, debug=False)
