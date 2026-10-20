"""
把当前 data/ 里的真实数据拷进打包产物

为什么需要这一步：
  PyInstaller 只带了"种子文件"（知识库、决策树、空台账骨架），
  这样别人拿到 exe 是一个干净的起点。但对自用来说是空的 ——
  19 间教室、1170 条课表、历史报修记录都不在里面。

  这一步把仓库 data/ 下的实际数据同步到 dist/<产物>/data/，
  打包出来就是"打开即有内容"的可用版本。

不拷的东西：
  · *.lock        运行时的锁文件，没有意义
  · *.bak         备份
  · config.json   **里面有 API Key，绝对不能打进交付包**
  · desktop-error.log

安全提醒：
  data/schedule.json 里是**真实教师姓名**（接口返回时脱敏，文件本身没有）。
  这个包只适合自己用或校内演示，不要公开分发。
"""

import os
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data')
DIST = os.path.join(ROOT, 'dist')

# 打包产物目录名（和 spec 里的 name 一致）
BUNDLE_NAME = '机房故障智能诊断助手'

SKIP_SUFFIX = ('.lock', '.bak')
SKIP_NAMES = {'config.json', 'desktop-error.log'}


def find_bundle():
    """找到打包产物目录（兼容 onedir 结构）"""
    candidate = os.path.join(DIST, BUNDLE_NAME)
    if os.path.isdir(candidate):
        return candidate
    # 兜底：dist 下第一个目录
    if os.path.isdir(DIST):
        for name in os.listdir(DIST):
            p = os.path.join(DIST, name)
            if os.path.isdir(p):
                return p
    return None


def main():
    bundle = find_bundle()
    if not bundle:
        print('找不到打包产物，先运行 tools\\build_exe.bat')
        return 1

    dst = os.path.join(bundle, 'data')
    os.makedirs(dst, exist_ok=True)

    copied = []
    for name in sorted(os.listdir(SRC)):
        path = os.path.join(SRC, name)
        if not os.path.isfile(path):
            continue
        if name in SKIP_NAMES or name.endswith(SKIP_SUFFIX):
            continue
        shutil.copy2(path, os.path.join(dst, name))
        size = os.path.getsize(path)
        copied.append((name, size))

    print('产物目录:', bundle)
    print('数据目录:', dst)
    print()
    for name, size in copied:
        print('  {:<28} {:>8.1f} KB'.format(name, size / 1024))

    total = sum(s for _, s in copied)
    print()
    print('共 {} 个文件，{:.1f} MB'.format(len(copied), total / 1024 / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
