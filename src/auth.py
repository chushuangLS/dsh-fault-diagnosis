"""Local accounts and revocable browser sessions."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import unicodedata
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session
from filelock import file_lock
import paths

bp = Blueprint('auth', __name__)
SESSION_SECONDS = 12 * 3600


def _read(path):
    with path.open(encoding='utf-8') as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f'Invalid account data: {path.name}')
    return value


def _write(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _path(name):
    return Path(paths.data_file(name))


def new_invite(excluded=()):
    while True:
        code = '-'.join(secrets.token_hex(2).upper() for _ in range(3))
        if code not in excluded:
            return code


def initialize():
    marker = _path('auth_initialized.json')
    with file_lock(str(marker)):
        admin_code = new_invite()
        defaults = {
            'users.json': {},
            'invites.json': {'admin_code': admin_code, 'member_code': new_invite({admin_code})},
            'auth_sessions.json': {},
            'auth_secret.json': {'key': secrets.token_hex(32)},
        }
        for name, default in defaults.items():
            path = _path(name)
            if not marker.exists() and not path.exists():
                _write(path, default)
            _read(path)
        if not marker.exists():
            _write(marker, {'version': 1})
        _path('audit_log.jsonl').touch(exist_ok=True)
        return os.environ.get('FLASK_SECRET_KEY') or _read(_path('auth_secret.json'))['key']


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200000).hex()


def normalize_name(value):
    return unicodedata.normalize('NFC', value.strip()) if isinstance(value, str) else ''


def current_user(token):
    if not isinstance(token, str):
        return None
    entry = _read(_path('auth_sessions.json')).get(token)
    if not entry or entry['expires'] <= time.time():
        return None
    user = _read(_path('users.json')).get(entry['user_id'])
    if user and user['role'] in ('admin', 'member') and user['salt'] == entry['credential']:
        return {'id': entry['user_id'], 'name': user['name'], 'role': user['role']}
    return None


def revoke(token):
    path = _path('auth_sessions.json')
    with file_lock(str(path)):
        entries = _read(path)
        if entries.pop(token, None) is not None:
            _write(path, entries)


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def error(message, status):
    return jsonify(error=message), status


def _attempt_allowed():
    path = _path('auth_attempts.json')
    with file_lock(str(path)):
        now = time.time()
        attempts = _read(path) if path.exists() else {}
        attempts = {key: [t for t in times if t > now - 60] for key, times in attempts.items()}
        attempts = {key: times for key, times in attempts.items() if times}
        key = (request.remote_addr or 'local') + ':' + request.endpoint
        times = attempts.setdefault(key, [])
        if len(times) >= 10:
            return False
        times.append(now)
        _write(path, attempts)
        return True


@bp.get('/login')
@bp.get('/register')
def page():
    if g.user:
        return redirect('/')
    return render_template('auth.html', register=request.path == '/register', csrf=csrf_token())


@bp.post('/api/auth/register')
def register():
    if not _attempt_allowed():
        return error('尝试次数过多，请稍后再试', 429)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error('无效的注册信息', 400)
    name = normalize_name(data.get('name'))
    password = data.get('password')
    code = data.get('invite_code')
    if not name or len(name) > 50 or any(unicodedata.category(c).startswith('C') for c in name):
        return error('请输入有效用户名', 400)
    if not isinstance(password, str) or not 6 <= len(password) <= 128:
        return error('密码长度须为 6 至 128 个字符', 400)
    if password != data.get('confirm_password'):
        return error('两次密码不一致', 400)
    invites = _read(_path('invites.json'))
    code_bytes = code.strip().upper().encode() if isinstance(code, str) else b''
    role = next((r for r in ('admin', 'member')
                 if hmac.compare_digest(code_bytes, invites[r + '_code'].encode())), None)
    if role is None:
        return error('邀请码无效', 400)
    path = _path('users.json')
    with file_lock(str(path)):
        users = _read(path)
        if any(user['name'] == name for user in users.values()):
            return error('该用户名已注册', 409)
        salt = secrets.token_hex(16)
        users[secrets.token_hex(16)] = {
            'name': name, 'salt': salt, 'hash': password_hash(password, salt),
            'role': role, 'created_at': datetime.now().astimezone().isoformat(),
        }
        _write(path, users)
    return jsonify(ok=True), 201


@bp.post('/api/auth/login')
def login():
    if not _attempt_allowed():
        return error('尝试次数过多，请稍后再试', 429)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error('用户名或密码错误', 401)
    name = normalize_name(data.get('name'))
    password = data.get('password')
    if not isinstance(password, str) or len(password) > 128:
        return error('用户名或密码错误', 401)
    user = authenticate(name, password)
    if not user:
        return error('用户名或密码错误', 401)
    _clear_session()
    token = secrets.token_urlsafe(32)
    path = _path('auth_sessions.json')
    with file_lock(str(path)):
        now = time.time()
        entries = {key: value for key, value in _read(path).items() if value['expires'] > now}
        entries[token] = {'user_id': user['id'], 'expires': now + SESSION_SECONDS,
                          'credential': user['credential']}
        _write(path, entries)
    session['auth_token'] = token
    return jsonify(ok=True, user={key: user[key] for key in ('id', 'name', 'role')})


def authenticate(name, password):
    if not isinstance(password, str) or len(password) > 128:
        return None
    name = normalize_name(name)
    match = next(((uid, user) for uid, user in _read(_path('users.json')).items()
                  if user['name'] == name), None)
    salt = match[1]['salt'] if match else '00' * 16
    hashed = password_hash(password, salt)
    if not match or not hmac.compare_digest(hashed, match[1]['hash']):
        return None
    uid, user = match
    return {'id': uid, 'name': user['name'], 'role': user['role'], 'credential': salt}


def _clear_session():
    revoke(session.get('auth_token'))
    cleanup = current_app.config['CLEAR_DIAGNOSIS_SESSION']
    cleanup(session.get('sid'))
    session.clear()


@bp.post('/api/auth/logout')
def logout():
    _clear_session()
    return jsonify(ok=True)


@bp.get('/api/auth/me')
def me():
    return jsonify(user=g.user, csrf=csrf_token())


def install(app, cleanup, initialize_records):
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('DSH_SECURE_COOKIE') == '1',
                      CLEAR_DIAGNOSIS_SESSION=cleanup)
    app.register_blueprint(bp)

    dispatch = app.wsgi_app

    def initialize_before_session(environ, start_response):
        if not app.secret_key:
            key = initialize()
            initialize_records()
            app.secret_key = key
        return dispatch(environ, start_response)

    app.wsgi_app = initialize_before_session

    @app.before_request
    def authorize():
        if request.endpoint == 'static':
            return
        g.user = current_user(session.get('auth_token'))
        public = request.endpoint in {'auth.page', 'auth.login', 'auth.register'}
        api = request.path.startswith('/api/')
        if not g.user and not public:
            return error('请先登录', 401) if api else redirect('/login')
        write = request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}
        admin = (
            request.path.startswith(('/api/export/', '/api/settings/'))
            or request.path == '/api/audit'
            or (write and request.path.startswith('/api/classrooms/'))
            or (request.method == 'DELETE' and request.path.startswith('/api/records/'))
        )
        if admin and g.user['role'] != 'admin':
            return error('需要管理员权限', 403)
        if write:
            token = request.headers.get('X-CSRF-Token', '').encode()
            if not hmac.compare_digest(token, csrf_token().encode()):
                return error('请求验证失败，请刷新页面', 403)

    @app.after_request
    def prevent_cache(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response
