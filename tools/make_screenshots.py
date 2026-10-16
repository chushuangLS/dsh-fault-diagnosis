"""
README 截图生成工具

为什么要做成脚本而不是手工截图：
  手工截图不可复现 —— 换台机器、界面微调之后就对不上了。
  写成脚本后，任何人改完界面都能一条命令重新生成，
  保证 README 里的图始终和代码一致。

原理：
  应用是单页交互式的，关键界面（教室管理、教室详情）需要点击才出现，
  无头浏览器没法"点击"。所以借助 web/static/screenshot-probe.html：
  它把应用装进一个**同源** iframe，再用脚本调用应用的全局函数
  （enterApp / openRoomDetail …）切到目标界面。
  同源是关键 —— 换成 file:// 打开就会因跨域拿不到 iframe 内部。

用法：
    # 1) 先启动服务
    cd src && python app.py

    # 2) 另开一个终端生成截图
    python tools/make_screenshots.py

依赖：本机装有 Edge 或 Chrome（用无头模式渲染）。
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get('APP_BASE', 'http://127.0.0.1:5000')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'docs', 'screenshots')

# 浏览器可执行文件的常见位置（按顺序找第一个存在的）
BROWSERS = [
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    '/usr/bin/microsoft-edge',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
]

PROBE = '/static/screenshot-probe.html'

# (场景, 输出文件名)
# 文件名用 ASCII：中文文件名在部分 Markdown 渲染器 / 静态站点里容易出编码问题
SCENES = [
    ('landing', '01-landing.png'),
    ('chat', '02-diagnosis.png'),
    ('records', '03-records.png'),
    ('stats', '04-dashboard.png'),
    ('tasks', '05-daily-tasks.png'),
    ('admin', '06-classroom-admin.png'),
    ('room', '07-classroom-detail.png'),
]

WINDOW = '1440,900'
# 给页面留出加载数据、切换界面的时间
BUDGET_MS = 25000


def find_browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    found = shutil.which('msedge') or shutil.which('google-chrome')
    if found:
        return found
    return None


def wait_for_server(timeout=15):
    """等应用起来，避免服务还没就绪就去截图"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + '/', timeout=3):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def shoot(browser, url, dst):
    subprocess.run(
        [browser, '--headless', '--disable-gpu', '--no-sandbox',
         '--hide-scrollbars', f'--window-size={WINDOW}',
         f'--virtual-time-budget={BUDGET_MS}',
         f'--screenshot={dst}', url],
        capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=120)


def main():
    browser = find_browser()
    if not browser:
        print('未找到 Edge / Chrome，无法生成截图')
        return 1

    if not wait_for_server():
        print(f'服务未就绪：{BASE}')
        print('请先在 src/ 下执行：python app.py')
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f'浏览器: {browser}')
    print(f'输出到: {OUT_DIR}')
    print()

    failed = 0
    for scene, filename in SCENES:
        dst = os.path.join(OUT_DIR, filename)
        url = f'{BASE}{PROBE}?scene={scene}'
        shoot(browser, url, dst)

        if os.path.exists(dst):
            size = os.path.getsize(dst) / 1024
            print(f'  OK   {filename:<26} {size:>7.1f} KB')
        else:
            failed += 1
            print(f'  FAIL {filename}')

    print()
    if failed:
        print(f'{failed} 张生成失败')
        return 1
    print(f'全部完成，共 {len(SCENES)} 张')
    return 0


if __name__ == '__main__':
    sys.exit(main())
