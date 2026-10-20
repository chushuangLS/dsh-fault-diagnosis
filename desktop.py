"""
机房故障智能诊断助手 - 桌面窗口版

和 Web 版的区别只有一个：不用先起服务再开浏览器。
双击之后直接弹出一个窗口，没有地址栏、没有标签页、没有黑窗口。

为什么不改写成桌面应用（Electron 之类）：
  现有的 Flask + 原生 HTML/CSS/JS 已经跑得很好，
  换壳解决的是"启动方式"，不是"功能"。
  这里用 pywebview 起一个内嵌 WebView2 的原生窗口，
  页面代码一行都不用改。

启动流程：
  1. 找一个空闲端口（避免和已经开着的 Web 版抢 5000）
  2. 后台线程里跑 Flask
  3. 轮询等到服务真的能响应
  4. 开窗口

出错怎么办：
  用 pythonw 启动时没有控制台，看不到报错。
  所以异常统一写进 desktop-error.log，就在这个文件旁边。
"""

import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'src')
LOG = os.path.join(ROOT, 'desktop-error.log')

# src 里有 repair_log、classroom 这些模块，app 靠相对导入找它们的
if SRC not in sys.path:
    sys.path.insert(0, SRC)

WINDOW_TITLE = '机房故障智能诊断助手'
WINDOW_SIZE = (1280, 860)


def _log(msg):
    """把信息写进日志文件（窗口版没有控制台）"""
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n')
    except Exception:
        pass


def _free_port():
    """
    找一个空闲端口

    不写死 5000：Web 版可能正开着，两个抢同一个端口会起不来。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _wait_ready(url, timeout=20.0):
    """轮询等到服务真的能响应，而不是"线程起来了"就开窗口"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def _serve(port):
    """后台线程：跑 Flask"""
    import app
    app.app.run(host='127.0.0.1', port=port,
                debug=False, use_reloader=False, threaded=True)


def main():
    import webview

    port = _free_port()
    url = f'http://127.0.0.1:{port}/'

    threading.Thread(target=_serve, args=(port,), daemon=True).start()

    if not _wait_ready(url):
        _log(f'服务在 20 秒内没有就绪：{url}')
        raise RuntimeError('本地服务启动失败，详情见 desktop-error.log')

    _log(f'窗口启动：{url}')

    webview.create_window(
        WINDOW_TITLE,
        url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=(980, 640),
        text_select=False,      # 界面是应用而不是网页，别让误拖选中大片文字
    )
    webview.start()

    _log('窗口已关闭，程序退出')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        _log('启动失败：\n' + traceback.format_exc())
        # 从命令行启动时也把错误打出来，方便当场看到
        traceback.print_exc()
        sys.exit(1)
