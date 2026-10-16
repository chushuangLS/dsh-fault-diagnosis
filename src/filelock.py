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

关于可重入：
  同一个线程对同一个文件重复加锁是允许的（重入），
  只有最外层那次真正去拿系统锁，内层只累加计数。

  为什么必须支持重入：
    业务代码里存在「持锁后调用另一个也会加锁的函数」的写法，
    例如 repair_log 在锁内调用 load_records()，
    而 load_records() 为了保证文件存在又去加锁。
    如果锁不可重入，这种写法会直接把线程卡死。
    操作系统级的 flock / msvcrt 对同一进程的重复加锁
    并不保证安全（不同平台行为不一致），所以在这一层自己处理。

注意：锁是文件级的，同一个进程内的多个线程、以及多个进程之间都有效。
"""

import contextlib
import os
import threading

# 每个文件一把可重入锁。
# 用 threading.RLock 而不是普通 Lock：同一线程重入时不会自锁。
# 之所以不只靠 flock，是因为 flock 在同一进程内对同一文件
# 用两个不同 fd 加锁时，行为依平台而异（Linux 上会阻塞，部分实现则不然）。
_local_locks = {}
_local_locks_guard = threading.Lock()

# 记录「当前线程已经持有系统锁」的文件集合，
# 用来判断这次进入是外层还是内层重入。
_held = threading.local()


def _held_paths():
    """当前线程持有的系统锁集合"""
    s = getattr(_held, 'paths', None)
    if s is None:
        s = set()
        _held.paths = s
    return s


def _get_local_lock(path):
    """取（或创建）某个文件对应的进程内可重入锁"""
    key = os.path.abspath(path)
    with _local_locks_guard:
        lock = _local_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _local_locks[key] = lock
        return lock


@contextlib.contextmanager
def file_lock(target_path):
    """
    对 target_path 加排他锁（对 .lock 附属文件加锁）

    参数：
      target_path - 需要保护的数据文件路径，锁文件为 target_path + '.lock'

    说明：
      · 先拿进程内的 RLock（保证同进程多线程互斥、且可重入），
        再拿文件锁（保证跨进程互斥）
      · Linux/macOS 用 fcntl.flock
      · Windows 用 msvcrt.locking（fcntl 不存在）
      · 加锁失败不应让业务崩溃 —— 退化为「无锁执行」并继续，
        因为丢锁只是并发风险，中断业务是确定的故障
    """
    # ---- 第一层：进程内可重入锁 ----
    # 同一线程重复进入同一文件时 RLock 允许直接通过，
    # 内层不会再去碰系统锁，因此既不会自锁也不会死锁。
    key = os.path.abspath(target_path)
    local = _get_local_lock(target_path)

    with local:
        # 本线程是否已经持有这个文件的系统锁 → 本次是内层重入
        nested = key in _held_paths()
        if nested:
            yield
            return

        # ---- 第二层：跨进程文件锁 ----
        lock_path = target_path + '.lock'
        try:
            os.makedirs(os.path.dirname(lock_path), exist_ok=True)
            fh = open(lock_path, 'w')
        except OSError:
            # 锁文件都建不出来（如目录只读），只能放弃跨进程加锁
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

            _held_paths().add(key)
            yield

        finally:
            _held_paths().discard(key)
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
