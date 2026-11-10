"""Append-only audit and recovery for a record mutation."""
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
import tempfile
from uuid import uuid4

from filelock import file_lock


def atomic_write(path, content):
    path = Path(path)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _encode(data):
    return (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def _fingerprint(content):
    return hashlib.sha256(content).hexdigest()


def _journal(record_file):
    return Path(str(record_file) + '.pending.json')


def log_path(record_file):
    return Path(record_file).with_name('audit_log.jsonl')


def _events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def append(path, event):
    with file_lock(str(path)):
        if path.exists():
            with path.open('r+b') as stream:
                content = stream.read()
                if content and not content.endswith(b'\n'):
                    stream.truncate(content.rfind(b'\n') + 1)
                    stream.flush()
                    os.fsync(stream.fileno())
        if any(item['event_id'] == event['event_id'] for item in _events(path)):
            return
        with path.open('ab') as target:
            target.write(_encode(event))
            target.flush()
            os.fsync(target.fileno())


def make_event(actor, action, record=None, **changes):
    event = dict(event_id=uuid4().hex, t=datetime.now().astimezone().isoformat(),
                 actor_id=actor['id'], user=actor['name'], action=action, **changes)
    if record is not None:
        event.update(record_id=record['记录编号'],
                     room='-'.join(x for x in (record['教学楼'], record['教室']) if x))
    return event


def recover(record_file):
    journal = _journal(record_file)
    if not journal.exists():
        return
    pending = json.loads(journal.read_bytes())
    fingerprint = _fingerprint(Path(record_file).read_bytes())
    if fingerprint == pending['after']:
        append(log_path(record_file), pending['event'])
    elif fingerprint != pending['before']:
        raise RuntimeError('报修数据与待提交日志不一致，请联系本机维护人员')
    journal.unlink()


def commit(record_file, content, event=None):
    if event is not None:
        pending = {'before': _fingerprint(Path(record_file).read_bytes()),
                   'after': _fingerprint(content), 'event': event}
        atomic_write(_journal(record_file), _encode(pending))
    atomic_write(record_file, content)
    if event is not None:
        recover(record_file)


def read_page(record_file, cursor, limit, *, q='', action='', start='', end='', order='desc'):
    if order not in ('asc', 'desc'):
        raise ValueError('无效的排序方式')
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    if start_date and end_date and start_date > end_date:
        raise ValueError('开始日期不能晚于结束日期')
    with file_lock(record_file):
        recover(record_file)
        path = log_path(record_file)
        with file_lock(str(path)):
            events = _events(path)
    if order == 'desc':
        events.reverse()
    # Filter the complete history before sorting and applying the page cursor.
    query = q.strip().casefold()
    events = [event for event in events
              if (not action or event.get('action') == action)
              and (not query or query in json.dumps(event, ensure_ascii=False).casefold())
              and (not start_date or datetime.fromisoformat(event['t']).date() >= start_date)
              and (not end_date or datetime.fromisoformat(event['t']).date() <= end_date)]
    events.sort(key=lambda event: datetime.fromisoformat(event['t']).timestamp(),
                reverse=order == 'desc')
    if cursor:
        offset = next((i + 1 for i, event in enumerate(events)
                       if event['event_id'] == cursor), None)
        if offset is None:
            raise ValueError('无效的日志游标')
        events = events[offset:]
    page = events[:limit]
    return page, page[-1]['event_id'] if len(events) > limit else None
