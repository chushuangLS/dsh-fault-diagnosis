"""
CI 测试执行与失败上报

为什么需要这个脚本：
  GitHub Actions 的原始日志需要仓库管理员权限才能下载，
  其他人（包括贡献者）看不到具体是哪个用例失败，只能看到一个笼统的红叉。

  这个脚本跑一遍 pytest，把失败用例逐个转成 GitHub 的
  annotation（`::error::` 工作流命令）——
  annotation 是公开可读的，任何人在网页上就能看到失败详情。

用法（CI 中）：
    python tools/ci_report.py

退出码与 pytest 保持一致：全通过 0，有失败 1。
"""

import os
import re
import subprocess
import sys

# 单个用例最多抓多少字符的报错上下文
_WINDOW = 6000


def _failure_message(output, test_name):
    """从 pytest 输出里截取某个失败用例的断言行"""
    # 用例名在输出里会出现三次：
    #   1. -v 的进度行
    #   2. FAILURES 段的标题（形如 ____ test_y ____）
    #   3. 结尾的 short test summary（FAILED tests/xxx.py::test_y）
    # 只有第 2 处后面跟着报错详情，所以要按标题去找，
    # 不能简单用 find / rfind。
    leaf = test_name.split('::')[-1]

    # pytest 的失败标题：两侧用下划线包起来
    m = re.search(r'^_{5,}\s+' + re.escape(leaf) + r'\s+_{5,}\s*$',
                  output, re.M)
    start = m.end() if m else -1

    if start == -1:
        # 没有 tb 时（例如 --tb=no）退化为按用例名找
        start = output.find(test_name)

    window = output[start:start + _WINDOW] if start != -1 else ''

    # pytest 用 E 前缀标记断言/异常行
    lines = [ln.strip() for ln in re.findall(r'^E\s+(.+)$', window, re.M)]
    if lines:
        return ' | '.join(lines[:3])[:220]

    # 退一步：直接找 AssertionError
    m2 = re.search(r'^(AssertionError.*)$', window, re.M)
    if m2:
        return m2.group(1)[:220]

    return '测试失败（未捕获到断言行）'


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    cmd = [sys.executable, '-m', 'pytest', 'tests', '-v', '--tb=short',
           '-p', 'no:cacheprovider']

    proc = subprocess.run(cmd, cwd=root, capture_output=True,
                          text=True, encoding='utf-8', errors='replace')
    output = (proc.stdout or '') + (proc.stderr or '')
    print(output, flush=True)

    in_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    if in_ci and proc.returncode != 0:
        # 把失败用例转成 annotation，让没有仓库权限的人也能看到详情
        for name in re.findall(r'^FAILED\s+(\S+)', output, re.M):
            msg = _failure_message(output, name)
            print(f'::error title=测试失败::{name} — {msg}', flush=True)

        summary = re.search(r'^\d+ failed.*$', output, re.M)
        if summary:
            print(f'::error title=汇总::{summary.group(0).strip()}', flush=True)

    return proc.returncode


if __name__ == '__main__':
    sys.exit(main())
