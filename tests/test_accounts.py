from pathlib import Path

import audit
import auth
import repair_log


def test_permissions_and_record_audit(login_as):
    from app import app

    anonymous = app.test_client()
    assert anonymous.get('/').location.endswith('/login')
    for path in ('/api/records', '/api/audit', '/api/export/repair'):
        assert anonymous.get(path).status_code == 401
    assert anonymous.post('/api/chat/stream').status_code == 401

    member, headers = login_as()
    admin, admin_headers = login_as('admin')
    assert b'id="audit-btn"' not in member.get('/').data
    assert b'id="audit-btn"' in admin.get('/').data
    assert member.get('/api/audit').status_code == 403
    assert member.get('/api/export/repair').status_code == 403
    assert member.post('/api/export/repair/save', headers=headers).status_code == 403
    assert member.post('/api/settings/open-data-dir', headers=headers).status_code == 403
    assert member.post('/api/classrooms/building', headers=headers).status_code == 403
    path = '/api/records/manual'
    body = {'building': '测试楼', 'classroom': '101', 'symptom': '无法开机'}
    assert member.post(path, json=body).status_code == 403
    actor = member.get('/api/auth/me').get_json()['user']
    assert member.post(path, headers=headers, json={**body, '上报人': '冒名'}).status_code == 400
    response = member.post(path, headers=headers, json=body)
    assert response.status_code == 200
    record_id = repair_log.load_records()[0]['记录编号']
    record_path = '/api/records/' + record_id
    assert member.delete(record_path, headers=headers).status_code == 403
    assert member.post(record_path, headers=headers, json={'status': '已报修'}).status_code == 200
    assert repair_log.load_records()[0]['最后修改人'] == actor['name']

    assert admin.delete(record_path, headers=admin_headers).status_code == 200
    assert admin.delete(record_path, headers=admin_headers).status_code == 200
    assert member.post(record_path, headers=headers, json={'status': '已解决'}).status_code == 404
    assert member.get('/api/records').get_json()['records'] == []
    assert repair_log.load_records(include_deleted=True)[0]['上报人'] == actor['name']
    assert repair_log.next_id() == 'R002'
    page = admin.get('/api/audit?limit=1').get_json()
    assert [event['action'] for event in page['events']] == ['delete']
    page = admin.get('/api/audit', query_string={'cursor': page['next_cursor']}).get_json()
    assert [event['action'] for event in page['events']] == ['status', 'create']

    with member.session_transaction() as browser:
        token = browser['auth_token']
    assert member.post('/api/auth/logout', headers=headers).status_code == 200
    assert auth.current_user(token) is None
    assert member.get('/api/records').status_code == 401


def test_migration_and_audit_recovery(tmp_data, monkeypatch):
    path = Path(repair_log.RECORD_FILE)
    path.write_text('记录编号,教室,状态,自定义列\nR033,101,未报修,保留\n', encoding='utf-8-sig')
    repair_log.init_file()
    before = path.read_bytes()
    repair_log.init_file()
    assert path.read_bytes() == before
    assert repair_log.load_records()[0]['自定义列'] == '保留'
    actor = {'id': 'a1', 'name': '管理员'}
    original = audit.append

    def unavailable(*args):
        raise OSError('模拟日志写入失败')

    import pytest
    with monkeypatch.context() as patch:
        patch.setattr(audit, 'append', unavailable)
        with pytest.raises(OSError):
            repair_log.backfill_reporters('李一硕', {'R033'}, actor)

    assert audit.append is original
    assert repair_log.load_records()[0]['上报人'] == '李一硕'
    assert repair_log.backfill_reporters('李一硕', {'R033'}, actor) == 0
    events, _ = audit.read_page(str(path), None, 10)
    assert len(events) == 1
    assert events[0]['action'] == 'migrate_reporters'



def test_registration_and_revocation(login_as, monkeypatch):
    from app import app

    member, _ = login_as(name='同名值班员')
    anonymous = app.test_client()
    anonymous.get('/register')
    with anonymous.session_transaction() as browser:
        headers = {'X-CSRF-Token': browser['csrf']}
    payload = {'name': ' 同名值班员 ', 'password': 'new-password',
               'confirm_password': 'new-password', 'invite_code': 'wrong'}
    assert anonymous.post('/api/auth/register', headers=headers, json=payload).status_code == 400
    payload['invite_code'] = auth._read(auth._path('invites.json'))['admin_code']
    assert anonymous.post('/api/auth/register', headers=headers, json=payload).status_code == 409
    assert member.get('/api/auth/me').get_json()['user']['role'] == 'member'

    with member.session_transaction() as browser:
        token = browser['auth_token']
    session_entry = auth._read(auth._path('auth_sessions.json'))[token]
    with monkeypatch.context() as patch:
        patch.setattr(auth.time, 'time', lambda: session_entry['expires'])
        assert auth.current_user(token) is None

    from account_admin import main
    monkeypatch.setattr('sys.argv', ['account_admin', 'reset-password', '同名值班员'])
    monkeypatch.setattr('getpass.getpass', lambda prompt: 'new-password')
    main()
    assert auth.current_user(token) is None
    assert auth.authenticate('同名值班员', 'test-password') is None
    assert auth.authenticate('同名值班员', 'new-password')['role'] == 'member'


def test_audit_query_filters_sort_and_pagination(login_as):
    import repair_log
    admin, _ = login_as(role='admin', name='日志管理员')
    path = audit.log_path(repair_log.RECORD_FILE)
    events = [
        dict(event_id='query-a', t='2026-11-01T10:00:00+08:00', user='张三',
             action='create', record_id='R100', room='一号楼-101'),
        dict(event_id='query-b', t='2026-11-02T10:00:00+08:00', user='李四',
             action='delete', record_id='R101', room='一号楼-102'),
        dict(event_id='query-c', t='2026-11-03T10:00:00+08:00', user='张三',
             action='create', record_id='R102', room='一号楼-103'),
    ]
    for event in events:
        audit.append(path, event)
    query = dict(q='张三', action='create', start='2026-11-01',
                 end='2026-11-03', order='asc', limit=1)
    page = admin.get('/api/audit', query_string=query).get_json()
    assert [event['event_id'] for event in page['events']] == ['query-a']
    query['cursor'] = page['next_cursor']
    page = admin.get('/api/audit', query_string=query).get_json()
    assert [event['event_id'] for event in page['events']] == ['query-c']
    assert page['next_cursor'] is None
    page = admin.get('/api/audit?q=R101').get_json()
    assert [event['event_id'] for event in page['events']] == ['query-b']
    page = admin.get('/api/audit?start=2026-11-02&end=2026-11-02').get_json()
    assert [event['event_id'] for event in page['events']] == ['query-b']
    page = admin.get('/api/audit?order=desc').get_json()
    assert [event['event_id'] for event in page['events']] == ['query-c', 'query-b', 'query-a']
    assert admin.get('/api/audit?q=不存在').get_json()['events'] == []
    for args in ('order=invalid', 'start=bad', 'start=2026-11-03&end=2026-11-01'):
        assert admin.get('/api/audit?' + args).status_code == 400
