"""
把 DSH 会话记录导出为「AI 对话历史 / Prompt 链」材料

比赛要求（传智杯 2.1）：
  「须包含至少 3 个核心功能迭代时与 AI 交互的完整 Prompt 链，
    包含你的 Prompt 提问、AI 的修改建议、以及你如何引导 AI 修复 Bug 的过程」

本脚本从 DSH 的会话文件（zstd 压缩的 JSONL）中提取：
  · 用户实际输入的每一句 Prompt
  · AI 的关键回复
  · 工具调用摘要（做了什么）
  · 遇到的错误与修复过程

输出：
  docs/AI对话记录-完整版.md     全部轮次，便于检索
  docs/AI对话记录-关键片段.md   自动挑选的「提问 → 方案 → 踩坑 → 修复」片段

用法：
  python tools/export_conversation.py            # 导出本工作目录最近的会话
  python tools/export_conversation.py <会话文件路径>
"""

import json
import os
import sys
from datetime import datetime
from compression import zstd

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(SRC_DIR, 'docs')

# 过滤掉系统自动注入的内容，只保留人真正打的字
SKIP_SOURCES = {'runtime-context', 'system', 'tool'}

# 这些是运行环境自动附加到消息里的块，不是用户写的话，需要剥掉
INJECTED_TAGS = [
    ('<system-reminder>', '</system-reminder>'),
    ('<available_skills>', '</available_skills>'),
    ('<skill_content>', '</skill_content>'),
    ('<attached_files>', '</attached_files>'),
    ('<runtime_context>', '</runtime_context>'),
]


def strip_injected(text):
    """
    剥掉系统注入的块，只留用户自己写的部分

    这些块会混在用户消息里（例如每轮附加的技能目录、运行时上下文），
    但它们不是「我提的 Prompt」，放进材料里会干扰评委阅读。
    """
    import re

    out = text
    for open_tag, close_tag in INJECTED_TAGS:
        # 成对出现的：整块删除（含内容）
        out = re.sub(
            re.escape(open_tag) + r'.*?' + re.escape(close_tag),
            '',
            out,
            flags=re.DOTALL,
        )
        # 只有开标签、没有闭合的：删到结尾
        idx = out.find(open_tag)
        if idx != -1:
            out = out[:idx]

    # 去掉「Current runtime context...」这类以固定句式开头的环境说明段
    out = re.sub(
        r'Current runtime context\..*?(?=\n\n[^\n]|\Z)',
        '',
        out,
        flags=re.DOTALL,
    )

    return out.strip()


def find_latest_session():
    """在本工作目录对应的会话目录里找最近更新的会话文件"""
    home = os.path.expanduser('~')
    base = os.path.join(home, '.dsh', 'sessions')

    # DSH 把工作目录编码成目录名：C:\学习 -> --C-~5B66~4E60--
    cwd = os.getcwd()
    encoded = '--' + ''.join(
        ch if ch.isalnum() else '~%04X' % ord(ch) if ord(ch) > 127 else '-'
        for ch in cwd
    ) + '--'

    candidates = []
    for dirpath, _, files in os.walk(base):
        for fn in files:
            if fn.startswith('session.') and fn.endswith('.jsonl.zstd'):
                full = os.path.join(dirpath, fn)
                candidates.append((os.path.getmtime(full), full))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def load_records(path):
    with open(path, 'rb') as f:
        text = zstd.decompress(f.read()).decode('utf-8')
    out = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def extract_text(content):
    """从 content 结构里取出纯文本"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    parts = []
    for blk in content:
        if isinstance(blk, dict) and blk.get('type') == 'text':
            parts.append(blk.get('text', ''))
    return '\n'.join(parts)


def build_turns(records):
    """把记录整理成「用户提问 + AI 回复 + 工具动作」的轮次列表"""
    turns = []
    current = None

    for r in records:
        t = r.get('type')
        d = r.get('data') or {}

        if t == 'user/message':
            src = (d.get('source') or {}).get('kind')
            if src in SKIP_SOURCES:
                continue
            text = strip_injected(extract_text(d.get('content'))).strip()
            if not text:
                continue
            # 图片附件：记下数量，方便对照
            images = [
                b for b in (d.get('content') or [])
                if isinstance(b, dict) and b.get('type') in ('image', 'image_url')
            ]
            if images:
                text += f'\n\n（另附 {len(images)} 张图片）'
            current = {'user': text, 'assistant': [], 'tools': [], 'errors': []}
            turns.append(current)

        elif t == 'assistant/message' and current is not None:
            msg = d.get('message') or {}
            text = extract_text(msg.get('content')).strip()
            if text:
                current['assistant'].append(text)

        elif t == 'tool/call' and current is not None:
            name = d.get('name', '')
            args = d.get('arguments', '')
            try:
                a = json.loads(args)
                # 不同工具的参数不同：pwsh 有 description，
                # read/glob/grep 只有文件路径，edit/write 只有 file_path
                desc = (
                    a.get('description')
                    or a.get('file_path')
                    or a.get('pattern')
                    or a.get('command')
                    or ''
                )
            except Exception:
                desc = str(args)
            desc = str(desc).replace('\n', ' ').strip()[:100]
            current['tools'].append(f'{name}({desc})' if desc else name)

        elif t == 'tool/result' and current is not None:
            text = extract_text(d.get('content'))
            if not text:
                text = json.dumps(d, ensure_ascii=False)
            # 只记录「失败」的结果（exit code 非 0），这是排查过程的证据
            if 'exit code' in text and 'exit code: 0' not in text:
                current['errors'].append(compact_error(text))

    return turns


def compact_error(text, limit=240):
    """
    把工具报错压缩成一行人话

    原始内容是嵌套 JSON，直接放进材料里评委看不懂，
    这里抽出关键信息（退出码 + stderr 首行）。
    """
    import re

    code = ''
    mc = re.search(r'exit code[:：]\s*(\d+)', text)
    if mc:
        code = f'[exit {mc.group(1)}] '

    # 优先取 [stderr] 之后的内容
    m = re.search(r'\[stderr\]\s*(.{0,400})', text, re.DOTALL)
    if m:
        body = m.group(1)
    else:
        # 退而求其次：取 JSON 里的 text 字段
        m2 = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        body = m2.group(1) if m2 else text

    body = body.replace('\\n', ' ').replace('\\"', '"').replace('\\r', ' ')
    body = re.sub(r'^[\s"\[\]{}]+', '', body)
    body = re.sub(r'\s+', ' ', body).strip()

    out = (code + body).strip()
    return out[:limit] + ('…' if len(out) > limit else '')


def best_reply(tn):
    """
    取该轮最能代表 AI 结论的回复

    一轮里 AI 可能说多段话，其中有些是「现在我来改 xxx」这类过程性叙述。
    这里挑最长的一段，通常就是真正的方案/结论。
    """
    if not tn['assistant']:
        return ''
    return max(tn['assistant'], key=len)


def write_full(turns, path, session_path):
    lines = [
        '# AI 对话记录（完整版）',
        '',
        '> 本文件由 `tools/export_conversation.py` 从 DSH 会话记录自动导出，',
        '> 是开发过程中与 AI 交互的原始材料，未经改写。',
        '',
        f'- 导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'- 会话文件：`{os.path.basename(session_path)}`',
        f'- 用户提问轮次：{len(turns)}',
        '',
        '---',
        '',
    ]

    for i, tn in enumerate(turns, 1):
        lines.append(f'## 第 {i} 轮')
        lines.append('')
        lines.append('### 👤 我的提问（Prompt）')
        lines.append('')
        lines.append('```text')
        lines.append(tn['user'])
        lines.append('```')
        lines.append('')

        if tn['tools']:
            lines.append(f'### 🔧 调用的工具（{len(tn["tools"])} 次）')
            lines.append('')
            for t in tn['tools'][:20]:
                lines.append(f'- `{t}`')
            if len(tn['tools']) > 20:
                lines.append(f'- …（其余 {len(tn["tools"]) - 20} 次略）')
            lines.append('')

        if tn['errors']:
            lines.append('### ⚠️ 报错 / 失败（后续被修复）')
            lines.append('')
            for e in tn['errors'][:5]:
                lines.append(f'- `{e[:200]}`')
            lines.append('')

        if tn['assistant']:
            lines.append('### 🤖 AI 的关键回复')
            lines.append('')
            for a in tn['assistant']:
                lines.append(a)
                lines.append('')

        lines.append('---')
        lines.append('')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def write_highlights(turns, path, top_n=6):
    """
    挑选「提问 → 方案 → 踩坑 → 修复」的片段

    评分依据（分值越高越像「引导 AI 修复问题」的过程）：
      · 该轮出现过报错 / 失败        +3
      · 用户明确要求修复 / 怀疑有问题  +3
      · 用户要求验证 / 测试           +2
      · 该轮工具调用多（工作量大）      +1

    只取前 top_n 轮，保证材料精炼、评委能读完。
    """
    strong = ['修复', 'bug', '报错', '错误', '失败', '漏洞', '不对', '有问题',
              '不对吧', '为什么', '检查', '验证', '测试']
    weak = ['提交', '推送', '看看', '完善', '建议']

    scored = []
    for i, tn in enumerate(turns, 1):
        u = tn['user']
        score = 0
        if tn['errors']:
            score += 3
        if any(k in u for k in strong):
            score += 3
        if any(k in u for k in weak):
            score += 1
        if tn['tools']:
            score += 1
        # 太短的寒暄句降权
        if len(u) < 10:
            score -= 2
        scored.append((score, i, tn))

    scored.sort(key=lambda x: (-x[0], x[1]))
    top = sorted(scored[:top_n], key=lambda x: x[1])

    lines = [
        '# AI 对话关键片段（Prompt 链）',
        '',
        '> 从完整对话中挑选的代表性片段，展示与 AI 协作的完整过程：',
        '> **提出需求 → AI 给出方案 → 实际验证 → 发现问题 → 引导修复**。',
        '',
        f'- 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'- 片段数：{len(top)}（完整对话共 {len(turns)} 轮）',
        '- 完整对话见 [AI对话记录-完整版.md](AI对话记录-完整版.md)',
        '',
        '---',
        '',
    ]

    for score, idx, tn in top:
        lines.append(f'## 片段 {idx}：第 {idx} 轮')
        lines.append('')
        lines.append('**👤 我的 Prompt：**')
        lines.append('')
        lines.append('```text')
        lines.append(tn['user'])
        lines.append('```')
        lines.append('')

        if tn['tools']:
            lines.append(f'**🔧 实际执行的动作（{len(tn["tools"])} 次工具调用）：**')
            lines.append('')
            for t in tn['tools'][:8]:
                lines.append(f'- `{t}`')
            if len(tn['tools']) > 8:
                lines.append(f'- …（其余 {len(tn["tools"]) - 8} 次略）')
            lines.append('')

        if tn['errors']:
            lines.append('**⚠️ 过程中出现的报错（暴露了问题所在）：**')
            lines.append('')
            for e in tn['errors'][:3]:
                lines.append(f'- {e}')
            lines.append('')

        reply = best_reply(tn)
        if reply:
            lines.append('**🤖 AI 的回复（该轮主要内容，节选）：**')
            lines.append('')
            lines.append(reply[:1500] + ('\n\n…（略）' if len(reply) > 1500 else ''))
            lines.append('')

        lines.append('---')
        lines.append('')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = find_latest_session()

    if not path or not os.path.exists(path):
        print('未找到会话文件')
        return 1

    print('会话文件:', path)
    records = load_records(path)
    print('记录条数:', len(records))

    turns = build_turns(records)
    print('用户提问轮次:', len(turns))

    if not turns:
        print('没有提取到用户提问，可能选错了会话文件')
        return 1

    os.makedirs(DOCS, exist_ok=True)
    full = os.path.join(DOCS, 'AI对话记录-完整版.md')
    hi = os.path.join(DOCS, 'AI对话记录-关键片段.md')

    write_full(turns, full, path)
    write_highlights(turns, hi)

    print('已写出:')
    print('  ', full)
    print('  ', hi)
    return 0


if __name__ == '__main__':
    sys.exit(main())
