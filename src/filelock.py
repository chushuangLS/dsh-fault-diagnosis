"""
机房故障智能诊断助手 - 跨平台文件锁

为什么需要单独一个模块：
  Flask 默认多线程，多个请求可能同时「读-改-写」同一个数据文件。
  没有锁时，后写的会覆盖先写的，导致数据丢失
  （例如两条报修记录同时提交，只留下一条）。

  knowledge / classroom / daily_task / repair_log 都需要这个能力，
  集中放在这里，避免每个模块各写一份、行为不一致。

用法：

    from filelock import file_lock

    with file_lock(path):          # 自动加锁 / 解锁
        data = load()
        data['x'].append(...)
        save(data)

注意：锁是文件级的，同一个进程内的多个线程、以及多个进程之间都有效。
"""

import contextlib
import os


@contextlib.contextmanager
def file_lock(target_path):
    """
    对 target_path 加排他锁（对 .lock 附属文件加锁）

    参数：
      target_path - 需要保护的数据文件路径，锁文件为 target_path + '.lock'

    说明：
      · Linux/macOS 用 fcntl.flock
      · Windows 用 msvcrt.locking（fcntl 不存在）
      · 加锁失败不应让业务崩溃 —— 退化为「无锁执行」并继续，
        因为丢锁只是并发风险，中断业务是确定的故障
    """
    lock_path = target_path + '.lock'
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        fh = open(lock_path, 'w')
    except OSError:
        # 锁文件都建不出来（如目录只读），只能放弃加锁
        yield
        return

    locked = False
    try:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            locked = True
        except ImportError:
            # Windows
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            locked = True
        except OSError:
            # 拿不到锁：不阻塞业务，继续执行
            locked = False

        yield

    finally:
        if locked:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except ImportError:
                try:
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            except OSError:
                pass
        fh.close()
