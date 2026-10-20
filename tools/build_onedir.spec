# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（文件夹版 / onedir）

为什么不用单文件（--onefile）：
  单文件运行时要把自己解压到临时目录再启动。实际测试里这一步被拦了：

      [PYI-2580:ERROR] Could not create temporary directory!

  换一个临时目录也不行 —— 是杀毒软件对"程序自我解包"这个行为的典型拦截。
  单文件还有别的麻烦：启动慢（每次都要解压，30MB）、更容易误报。

  文件夹版没有解包这一步，exe 直接跑，依赖就在旁边。
  交付时整个文件夹打包成 zip 就行，双击里面的 exe 即可。

  唯一要注意的：整个文件夹要一起拷走，不能只拷 exe。
"""

import os

ROOT = os.path.abspath(os.getcwd())
WEB = os.path.join(ROOT, 'web')
DATA = os.path.join(ROOT, 'data')

# 只带走程序内容，不带用户数据（报修记录、课表是用户自己的）
SEED = ['fault_cases.json', 'decision_trees.json',
        'classrooms.example.json', 'daily_tasks.example.json']

datas = [
    (os.path.join(WEB, 'templates'), os.path.join('web', 'templates')),
    (os.path.join(WEB, 'static'), os.path.join('web', 'static')),
]
for name in SEED:
    src = os.path.join(DATA, name)
    if os.path.exists(src):
        datas.append((src, 'data'))

hiddenimports = [
    'openpyxl',
    'openpyxl.styles',
    'openpyxl.utils',
    'xlrd',
    'webview',
    'clr_loader',
    'pythonnet',
]

a = Analysis(
    [os.path.join(ROOT, 'desktop.py')],
    pathex=[ROOT, os.path.join(ROOT, 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter.test', 'test', 'unittest', 'pytest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='机房故障智能诊断助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='机房故障智能诊断助手',
)
