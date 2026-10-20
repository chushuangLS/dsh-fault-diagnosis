"""
本地配置（目前只有 API Key）

为什么需要它：
  Web 版靠环境变量 DEEPSEEK_API_KEY，这对开发机没问题 ——
  但打包成 exe 发给别人，对方电脑上没有这个变量，
  程序能打开、能看台账，一用诊断就报「未配置」。

  所以加一个配置文件，放在数据目录里（和报修记录放一起）：
        <程序目录>/data/config.json
        { "api_key": "sk-..." }

读取优先级：
  1. 进程环境变量 DEEPSEEK_API_KEY —— 开发时方便，且不落盘更安全
  2. config.json —— 桌面窗口版首次启动引导用户填在这里
  3. Windows「用户环境变量」—— 用户按文档设过以后，双击 exe 也能读到

  为什么需要第 3 条：
    Windows 的用户环境变量存在注册表里，新进程通常能继承，
    **但如果用户是在设置之后才打开的资源管理器，或者用 pythonw 启动，
    进程里可能根本没有这个变量**。实际就踩到了：
    用户明明设过 Key，双击 desktop.bat 却报「未配置」。
    所以这里直接读一次注册表兜底。

  第 2 条排在注册表前面，是因为用户后来在弹窗里填的 key 更"新"、
  更明确 —— 不应该被一个更早设过的系统变量悄悄盖掉。

安全说明：
  这个文件是明文保存的。它只适合本机自用 ——
  如果需要多人共用或放到公网，应该改用服务端统一的 key，
  不要让每个客户端各存一份。
"""

import json
import os

import paths

API_KEY_FIELD = 'api_key'
DISABLED_FIELD = 'disabled'
ENV_NAME = 'DEEPSEEK_API_KEY'


def config_file():
    """配置文件路径（和数据放一起，用户备份数据时一起带走）"""
    return paths.data_file('config.json')


def load():
    """读配置；文件不存在或损坏时返回空字典，不抛异常"""
    path = config_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        # 配置坏了不该让整个程序起不来，当没有配置处理
        return {}


def save(data):
    """写配置（自动建目录）"""
    path = config_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _windows_user_env(name):
    """
    读 Windows「用户环境变量」（存在注册表里，不是当前进程的）

    非 Windows 或读取失败都返回空字符串 —— 这只是兜底，不该影响主流程。
    """
    if os.name != 'nt':
        return ''
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value if isinstance(value, str) else ''
    except Exception:
        return ''


def get_api_key():
    """
    取 API Key，三个来源按优先级找

    返回空字符串表示没有可用的 Key。

    关于 disabled 标记：
      用户在设置里点「清除」时，光删掉 config.json 里的 key 是不够的 ——
      后面还有"Windows 用户环境变量"这层兜底，会把它又找回来，
      用户会觉得"点了清除怎么还有"。
      所以清除会写一个显式的 disabled 标记，直接短路掉所有来源。
      重新填一个 Key 就自动解除。
    """
    data = load()
    if data.get(DISABLED_FIELD):
        return ''

    # 1. 当前进程的环境变量
    env = os.environ.get(ENV_NAME)
    if env and env.strip():
        return env.strip()

    # 2. 配置文件（桌面版弹窗 / 设置界面填的就是这里）
    value = data.get(API_KEY_FIELD)
    if isinstance(value, str) and value.strip():
        return value.strip()

    # 3. Windows 用户环境变量
    win = _windows_user_env(ENV_NAME)
    return win.strip() if win and win.strip() else ''


def key_source():
    """
    Key 是从哪来的：env / file / windows / disabled / none

    界面要显示"来源"，光有打码值不够 ——
    用户得知道为什么改了 config.json 却还是老 Key。
    """
    data = load()
    if data.get(DISABLED_FIELD):
        return 'disabled'

    env = os.environ.get(ENV_NAME)
    if env and env.strip():
        return 'env'

    value = data.get(API_KEY_FIELD)
    if isinstance(value, str) and value.strip():
        return 'file'

    if (_windows_user_env(ENV_NAME) or '').strip():
        return 'windows'

    return 'none'


def set_api_key(key):
    """
    把 Key 写进配置文件

    传空字符串表示**清除**：写一个 disabled 标记，
    把环境变量和注册表这几层兜底也一起屏蔽掉。
    重新填 Key 时会自动去掉这个标记。
    """
    data = load()
    key = (key or '').strip()

    if key:
        data[API_KEY_FIELD] = key
        data.pop(DISABLED_FIELD, None)
    else:
        data.pop(API_KEY_FIELD, None)
        data[DISABLED_FIELD] = True

    save(data)
    return config_file()


def has_api_key():
    return bool(get_api_key())


def is_disabled():
    """用户是否在设置里显式清除过 Key"""
    return bool(load().get(DISABLED_FIELD))


def mask_key(key):
    """
    打码显示，用于界面回显

    只露出前 6 位和后 4 位，中间用星号 ——
    既能让人确认"填的是哪把钥匙"，又不至于整串暴露在屏幕上。
    """
    if not key:
        return ''
    if len(key) <= 12:
        return '*' * len(key)
    return key[:6] + '*' * 8 + key[-4:]
