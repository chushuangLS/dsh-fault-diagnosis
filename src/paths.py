"""
统一的路径解析

为什么要有这个文件：
  所有模块原先都写 `os.path.join(os.path.dirname(__file__), '..', 'data', ...)`，
  开发时没问题，但打包成 exe 之后会出事 ——

    打成单文件 exe 时，程序会被解压到一个临时目录里运行，
    `__file__` 指向的就是那个临时目录。数据写到那儿，
    程序一退出就被清空 —— 用户记了一天的报修记录全没了。

  所以"代码在哪"和"数据该写哪"必须分开：
    · 只读资源（模板、静态文件）：跟着程序走，打包后在解包目录里
    · 可写数据（报修记录、课表）：放在程序外面，用户能看见、能备份

目录优先级（data_dir）：
  1. 环境变量 DSH_DATA_DIR —— 测试和特殊部署用
  2. exe 同目录的 data/ —— 绿色版，U 盘拷走数据跟着走
  3. %APPDATA%\\机房故障智能诊断助手\\data —— 装在 Program Files 里时兜底
"""

import os
import sys

APP_NAME = '机房故障智能诊断助手'

# 只读资源文件（模板、静态资源）都在这个子目录下
WEB_DIR = 'web'

_cached_data_dir = None


def is_frozen():
    """是否运行在打包后的可执行文件里（PyInstaller 会设 sys.frozen）"""
    return bool(getattr(sys, 'frozen', False))


def app_dir():
    """
    程序所在目录

    开发时 = 项目根目录；打包后 = exe 所在目录
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def res_dir():
    """
    只读资源（web/templates、web/static）所在目录

    打包后 PyInstaller 把资源解到 sys._MEIPASS，程序退出就删 ——
    只读资源放这儿没问题，正好也不用管清理。

    注意要判断"空值"而不只是"有没有这个属性"：
    某些打包配置下 _MEIPASS 会被设成空字符串，
    这时 getattr 拿到的不是默认值，会返回一个空路径，
    结果就是模板永远找不到。
    """
    if is_frozen():
        base = getattr(sys, '_MEIPASS', '')
        return base if base else app_dir()
    return app_dir()


def _writable(path):
    """目录可写性探测（不能只看 os.access，Windows 上偶尔不准）"""
    probe = os.path.join(path, '.write_test')
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, 'w', encoding='utf-8') as f:
            f.write('ok')
        os.remove(probe)
        return True
    except Exception:
        return False


def data_dir():
    """
    可写数据目录（带缓存）
    """
    global _cached_data_dir
    if _cached_data_dir:
        return _cached_data_dir

    env = os.environ.get('DSH_DATA_DIR')
    if env:
        _cached_data_dir = os.path.abspath(env)
        os.makedirs(_cached_data_dir, exist_ok=True)
        return _cached_data_dir

    # 绿色版：数据放在 exe 旁边
    beside = os.path.join(app_dir(), 'data')
    if _writable(beside):
        _cached_data_dir = beside
        return _cached_data_dir

    # 兜底：装在只读位置（如 Program Files）时放用户目录
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    fallback = os.path.join(appdata, APP_NAME, 'data')
    os.makedirs(fallback, exist_ok=True)
    _cached_data_dir = fallback
    return _cached_data_dir


def data_file(name):
    """数据文件的完整路径，如 data_file('repair_records.csv')"""
    return os.path.join(data_dir(), name)


def reset_cache():
    """
    清掉缓存的数据目录

    测试要切换 DSH_DATA_DIR 时用；正常运行不需要调用。
    """
    global _cached_data_dir
    _cached_data_dir = None


# 首次运行时需要准备的文件：(目标文件名, 来源文件名)
#
# 知识库和决策树属于程序内容，要随程序走；
# 台账和日常报备用示例文件铺个空架子，用户自己往里填。
# 真实的使用数据（报修记录、课表）**不在这里** —— 它们属于用户，
# 不能被打进 exe，也不能被示例覆盖。
SEED_FILES = [
    ('fault_cases.json', 'fault_cases.json'),
    ('decision_trees.json', 'decision_trees.json'),
    ('classrooms.json', 'classrooms.example.json'),
    ('daily_tasks.json', 'daily_tasks.example.json'),
]


def ensure_seed_files():
    """
    首次运行时把随程序带的初始文件铺到数据目录

    只补**不存在**的文件 —— 绝不覆盖用户已有的数据。
    打包成 exe 后，如果数据目录是空的，知识库就是空的，
    一点诊断就什么都检索不到，看上去像功能坏了。

    返回实际补了哪些文件（便于日志）。
    """
    seed_dir = os.path.join(res_dir(), 'data')
    target_dir = data_dir()
    os.makedirs(target_dir, exist_ok=True)

    copied = []
    for name, source_name in SEED_FILES:
        target = os.path.join(target_dir, name)
        if os.path.exists(target):
            continue
        source = os.path.join(seed_dir, source_name)
        if not os.path.exists(source):
            continue
        try:
            with open(source, 'rb') as f:
                payload = f.read()
            with open(target, 'wb') as f:
                f.write(payload)
            copied.append(name)
        except Exception:
            # 补文件失败不该阻止程序启动，缺了顶多某个功能没内容
            pass
    return copied
