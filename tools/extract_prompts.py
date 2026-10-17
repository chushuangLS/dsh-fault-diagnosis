"""
从 DSH 会话存档中抽取真实用户输入，用于生成 AI 对话记录

为什么需要这个：
  比赛的「AI 协同过程」要求提交真实的 Prompt 记录。
  凭记忆补写是不诚实的，也会漏掉真正有价值的细节
  （比如当时是怎么否掉 AI 方案的、用了什么措辞）。

  DSH 会把会话写成 zstd 压缩的 JSONL，这里解压后逐条筛出
  **真人打的字** —— 系统注入的运行时上下文、技能清单、压缩摘要都要跳过。

用法：
    python tools/extract_prompts.py --list
    python tools/extract_prompts.py --session session-xxx --from 10-15 --to 10-17

说明：
  · 会话文件在 ~/.dsh/sessions/ 下，不进仓库（含个人对话）
  · 抽取结果也只用于生成 docs/AI对话Prompt快照.md，
    不会自动化提交任何原始会话
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')

SESSIONS_DIR = os.path.join(os.path.expanduser('~'), '.dsh', 'sessions')

TZ = timezone(timedelta(hours=8))

# 需要脱敏的内容：账号密码、邮箱、手机号
REDACT = [
    (re.compile(r'\bsk-[A-Za-z0-9]{10,}'), '[密钥已脱敏]'),
    (re.compile(r'[\w.+-]+@[\w.+-]+\.\w+'), '[邮箱已脱敏]'),
    (re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)'), '[手机号已脱敏]'),
    (re.compile(r'(?i)(密码|password)\s*[:：]?\s*\S+'), '[密码已脱敏]'),
]


def list_sessions():
    """列出所有会话（按最近修改排序）"""
    out = []
    if not os.path.isdir(SESSIONS_DIR):
        return out

    for project in os.listdir(SESSIONS_DIR):
        pdir = os.path.join(SESSIONS_DIR, project)
        if not os.path.isdir(pdir):
            continue
        for sid in os.listdir(pdir):
            sdir = os.path.join(pdir, sid)
            files = [f for f in os.listdir(sdir) if f.startswith('session.v')]
            if not files:
                continue
            # v4 优先，其次取版本号最大的
            files.sort(reverse=True)
            path = os.path.join(sdir, files[0])
            out.append({
                'project': project,
                'session': sid,
                'path': path,
                'size': os.path.getsize(path),
                'mtime': datetime.fromtimestamp(os.path.getmtime(path)),
            })

    out.sort(key=lambda x: x['mtime'], reverse=True)
    return out


def read_messages(path):
    """
    读出会话里的真实用户输入

    只保留 source.kind == 'user' 的 —— 系统注入的上下文、技能清单、
    自动压缩摘要都带别的 kind，混进来会污染记录。
    """
    from compression import zstd

    text = zstd.decompress(open(path, 'rb').read()).decode('utf-8', errors='replace')

    msgs = []
    for line in text.split('\n'):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get('type') != 'user/message':
            continue

        data = o.get('data') or {}
        if (data.get('source') or {}).get('kind') != 'user':
            continue

        parts = [c.get('text') or ''
                 for c in (data.get('content') or [])
                 if c.get('type') == 'text']
        body = '\n'.join(parts).strip()
        if not body:
            continue

        # 系统自动生成的压缩摘要，不是人打的字
        if body.startswith('This is an automatically generated checkpoint'):
            continue

        ts = o.get('time') or 0
        msgs.append({
            'ts': ts,
            'when': (datetime.fromtimestamp(ts / 1000, TZ).strftime('%m-%d %H:%M')
                     if ts else '?'),
            'text': body,
        })

    msgs.sort(key=lambda x: x['ts'])
    return msgs


def redact(text):
    for pat, rep in REDACT:
        text = pat.sub(rep, text)
    return text


def main():
    ap = argparse.ArgumentParser(description='从 DSH 会话存档抽取真实用户输入')
    ap.add_argument('--list', action='store_true', help='列出所有会话')
    ap.add_argument('--session', help='会话 ID 的前缀')
    ap.add_argument('--from', dest='start', help='起始日期，如 10-15')
    ap.add_argument('--to', dest='end', help='结束日期，如 10-17')
    ap.add_argument('--out', help='输出 JSON 路径')
    ap.add_argument('--min-len', type=int, default=0,
                    help='只保留长度超过该值的输入（过滤掉"可以""继续"这类应答）')
    args = ap.parse_args()

    sessions = list_sessions()

    if args.list or not args.session:
        print('会话列表：')
        for s in sessions:
            print(f"  {s['session'][:24]}  {s['mtime']:%m-%d %H:%M}  "
                  f"{s['size']:>10,} B  {s['project']}")
        print()
        if not args.session:
            print('用 --session <ID 前缀> 指定要抽取的会话')
        return 0

    hits = [s for s in sessions if s['session'].startswith(args.session)]
    if not hits:
        print(f'找不到会话：{args.session}')
        return 1

    msgs = read_messages(hits[0]['path'])
    print(f'会话 {hits[0]["session"][:24]}：共 {len(msgs)} 条用户输入')

    if args.start:
        msgs = [m for m in msgs if m['when'] >= args.start]
    if args.end:
        # 结束日期当天也要包含，所以比较时用 "日期 + 空格" 的边界
        msgs = [m for m in msgs if m['when'] <= args.end + ' 99:99']
    if args.min_len:
        msgs = [m for m in msgs if len(m['text']) > args.min_len]

    for m in msgs:
        m['text'] = redact(m['text'])

    print(f'筛选后：{len(msgs)} 条')

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(msgs, f, ensure_ascii=False, indent=1)
        print('已写入', args.out)
    else:
        for m in msgs:
            first = m['text'].split('\n')[0]
            print(f"  [{m['when']}] {first[:90]}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
