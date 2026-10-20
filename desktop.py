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
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'src')

# src 里有 repair_log、classroom 这些模块，app 靠相对导入找它们的
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import paths  # noqa: E402

# 日志放在程序旁边。
#
# 不能用 __file__ 推：打包后入口脚本的 __file__ 在 _internal/ 里面，
# 日志会跑到用户找不到的地方（实际踩过，日志写在 _internal/desktop-error.log）。
LOG = os.path.join(paths.app_dir(), 'desktop-error.log')

WINDOW_TITLE = '机房故障智能诊断助手'


def _screen_size():
    """
    屏幕分辨率

    用 tkinter 问，而不是写死 1280×860 ——
    写死的话在 1080p 和 4K 上体验差很多，笔记本上又会超出屏幕。

    tkinter 是标准库，不会多装东西；问不到就退回一个保守尺寸。
    """
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        size = (root.winfo_screenwidth(), root.winfo_screenheight())
        root.destroy()
        return size
    except Exception:
        return (1280, 860)


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


def _ask_api_key(first_run=True):
    """
    弹一个输入框配 API Key

    两个入口：
      · 首次启动发现没配 Key 时自动弹
      · 菜单「设置 API Key」手动弹（用于 Key 过期、换账号）

    后者是必要的：原来的判断只看"有没有 Key"，
    Key 失效时那条路走不到，用户只能去手改 JSON。

    返回 True 表示保存成功。
    """
    try:
        import tkinter
        from tkinter import simpledialog
    except Exception:
        _log('没有 tkinter，跳过了 Key 引导')
        return False

    import config

    if first_run:
        prompt = ('首次使用需要填 DeepSeek API Key。\n'
                  '申请地址：https://platform.deepseek.com/\n\n'
                  '（留空则跳过，台账和课表照样能用，只是诊断不可用）')
    else:
        current = config.mask_key(config.get_api_key()) or '（当前未配置）'
        prompt = (f'当前：{current}\n\n'
                  '输入新的 DeepSeek API Key。\n'
                  '留空取消，不会清掉已有的。')

    try:
        root = tkinter.Tk()
        root.withdraw()
        key = simpledialog.askstring(
            '配置 API Key', prompt, parent=root, show='*')
        root.destroy()
    except Exception:
        _log('弹窗失败：\n' + traceback.format_exc())
        return False

    if not key or not key.strip():
        _log('用户取消或留空，未改动 Key')
        return False

    path = config.set_api_key(key)
    _log(f'Key 已保存到 {path}')
    return True


def _open_edge_app(url):
    """
    兜底：用 Edge 的「应用模式」开一个无地址栏窗口

    为什么需要这个：
      主方案 pywebview 在 Windows 上要经过 pythonnet 加载 .NET 组件，
      打包后这一步在个别机器/目录下会失败（实测有目录能跑、有目录报
      "Failed to resolve Python.Runtime.Loader.Initialize"）。
      失败时用户看到的是「双击没反应」—— 比没有功能更糟。

      Edge 的 --app 模式不需要任何 .NET 互操作，
      开出来的窗口同样没有地址栏、没有标签页，有自己的任务栏图标。
      看起来比原生窗口差一点，但肯定能用。

    返回 Edge 进程对象；找不到 Edge 时返回 None。
    """
    candidates = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    exe = next((p for p in candidates if os.path.exists(p)), None)
    if not exe:
        _log('找不到 Edge，无法使用兜底窗口')
        return None

    _log(f'使用 Edge 应用模式兜底：{exe}')

    # 必须给一个**独立的用户数据目录**。
    #
    # 否则 Edge 已经开着的时候，新进程会把窗口"交接"给已在运行的浏览器实例，
    # 然后自己立刻退出。我们靠 proc.wait() 判断"窗口什么时候关"，
    # 进程早退就会让程序在窗口还开着的时候就自杀，页面变成"无法连接"。
    # 实测就是这样：启动 6 秒后程序就退出了。
    profile = os.path.join(tempfile.gettempdir(), 'dsh-edge-profile')
    os.makedirs(profile, exist_ok=True)

    return subprocess.Popen([
        exe,
        f'--app={url}',
        f'--user-data-dir={profile}',
        '--window-size=1280,860',
        '--no-first-run',
        '--no-default-browser-check',
    ])


def main():
    import webview

    # 没有 Key 就先问一次 —— 只影响诊断，不影响台账和课表
    import config

    if not config.has_api_key():
        _ask_api_key()

    port = _free_port()
    url = f'http://127.0.0.1:{port}/'

    threading.Thread(target=_serve, args=(port,), daemon=True).start()

    if not _wait_ready(url):
        _log(f'服务在 20 秒内没有就绪：{url}')
        raise RuntimeError('本地服务启动失败，详情见 desktop-error.log')

    _log(f'窗口启动：{url}')

    # 默认铺满屏幕，但"还原尺寸"要给一个小一点的窗口。
    #
    # 之前这里把 width/height 也传成了屏幕尺寸，结果点还原按钮毫无变化 ——
    # 因为还原后的尺寸就等于整屏，看起来像"缩不小"。
    # 现在还原尺寸取屏幕的 85%，并且不超过 1440×900，
    # 这样点还原、拖边框都能正常变小。
    #
    # 用 maximized 而不是 fullscreen：fullscreen 连标题栏都没有，
    # 用户不知道怎么退出；maximized 是"最大化"，还能拖、能还原、能点关闭。
    w, h = _screen_size()
    normal_w = min(int(w * 0.85), 1440)
    normal_h = min(int(h * 0.85), 900)

    try:
        webview.create_window(
            WINDOW_TITLE,
            url,
            width=normal_w,
            height=normal_h,
            min_size=(980, 640),
            maximized=True,
            resizable=True,
            text_select=False,      # 界面是应用而不是网页，别让误拖选中大片文字
        )
        webview.start()
        _log('窗口已关闭，程序退出')
        return
    except Exception:
        _log('pywebview 启动失败，改用 Edge 应用模式：\n'
             + traceback.format_exc())

    # 走到这里说明窗口没起来，用 Edge 兜底。
    # 必须等浏览器进程退出才结束 —— 否则主线程一返回，
    # 后台的 Flask 线程（daemon）跟着被回收，窗口里立刻变成连不上。
    proc = _open_edge_app(url)
    if proc is None:
        raise RuntimeError('窗口和兜底方案都失败了，详情见 desktop-error.log')
    proc.wait()
    _log('兜底窗口已关闭，程序退出')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        _log('启动失败：\n' + traceback.format_exc())
        # 从命令行启动时也把错误打出来，方便当场看到
        traceback.print_exc()
        sys.exit(1)
