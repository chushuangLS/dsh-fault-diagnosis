"""
并发安全测试

这一组测试针对的是「读-改-写」竞态：
Flask 默认多线程，多个请求可能同时读同一个文件、各自修改、再写回，
后写的会覆盖先写的，导致数据丢失。

这些测试用小规模线程池重复触发竞态，验证加锁后数据不丢。
"""

import json
import threading

import pytest

import classroom
import daily_task
import knowledge
import repair_log


def _run_threads(fn, n=8):
    """并发跑 n 次 fn(i)，收集异常"""
    errors = []

    def worker(i):
        try:
            fn(i)
        except Exception as e:      # noqa: BLE001 - 测试里需要捕获所有异常
            errors.append(repr(e))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return errors


class TestConcurrentWrites:

    def test_concurrent_records_no_loss(self, tmp_data):
        """并发新增报修记录，不应丢失"""
        errors = _run_threads(
            lambda i: repair_log.add_record(f'50{i}', f'现象{i}', '结论'), n=10
        )
        assert not errors, errors

        records = repair_log.load_records()
        assert len(records) == 10, f'预期 10 条，实际 {len(records)} 条'
        # 编号不能重复
        ids = [r['记录编号'] for r in records]
        assert len(ids) == len(set(ids)), f'编号重复: {ids}'

    def test_concurrent_tasks_no_loss(self, tmp_data):
        """并发新增报备任务，不应丢失"""
        errors = _run_threads(
            lambda i: daily_task.add_task(room=f'A{i:02d}', task_type='安装新软件'),
            n=10,
        )
        assert not errors, errors
        assert len(daily_task.list_tasks()) == 10

        ids = [t['id'] for t in daily_task.list_tasks()]
        assert len(ids) == len(set(ids)), f'编号重复: {ids}'

    def test_concurrent_buildings_no_loss(self, tmp_data):
        """并发新增教学楼，不应丢失"""
        errors = _run_threads(lambda i: classroom.add_building(f'教学楼{i}'), n=8)
        assert not errors, errors
        assert len(classroom.load()['buildings']) == 8

    def test_concurrent_knowledge_sediment(self, tmp_data):
        """
        并发沉淀知识案例，不应丢失

        注意：症状必须足够不同，否则会被去重逻辑拦掉（那是正确行为）。
        """
        def add(i):
            return knowledge.save_case(
                symptom=f'并发测试专用故障描述甲乙丙丁{i}',
                conclusion=f'原因：测试原因{i}。\n处理：忽略。',
            )

        errors = _run_threads(add, n=8)
        assert not errors, errors

        n = len(json.load(open(knowledge.AUTO_FILE, encoding='utf-8'))['cases'])
        assert n == 8, f'预期 8 条，实际 {n} 条'

    def test_concurrent_status_updates_keep_file_valid(self, tmp_data):
        """并发改状态后，CSV 仍应是完整可解析的"""
        rids = [repair_log.add_record(f'50{i}', f'现象{i}', '结论') for i in range(8)]

        def flip(i):
            repair_log.update_status(rids[i], repair_log.STATUS_REPORTED)

        errors = _run_threads(flip, n=8)
        assert not errors, errors

        records = repair_log.load_records()
        assert len(records) == 8, '并发更新后记录数变化，文件可能被写坏'


class TestFileLock:

    def test_lock_is_reentrant_safe_sequentially(self, tmp_data):
        """同一文件反复加锁解锁不应出错"""
        from filelock import file_lock

        for _ in range(5):
            with file_lock(classroom.DATA_FILE):
                pass

    def test_lock_creates_lock_file(self, tmp_data):
        import os
        from filelock import file_lock

        with file_lock(classroom.DATA_FILE):
            assert os.path.exists(classroom.DATA_FILE + '.lock')

    def test_lock_is_reentrant_same_thread(self, tmp_data):
        """
        同一线程嵌套加锁不得死锁

        业务里存在「持锁后调用另一个也会加锁的函数」的写法，
        例如 repair_log 在锁内调用 load_records()，
        而 load_records() 为了确保文件存在又去加锁。
        锁不可重入的话，这种写法会直接把线程卡死。
        """
        import threading
        from filelock import file_lock

        done = threading.Event()

        def nested():
            with file_lock(classroom.DATA_FILE):
                with file_lock(classroom.DATA_FILE):      # 内层重入
                    with file_lock(classroom.DATA_FILE):  # 再深一层
                        pass
            done.set()

        t = threading.Thread(target=nested, daemon=True)
        t.start()
        t.join(timeout=5)

        assert done.is_set(), '嵌套加锁把线程卡死了，说明锁不可重入'

    def test_load_records_inside_lock_does_not_deadlock(self, tmp_data):
        """
        回归：在锁内调用 load_records() 不得死锁

        load_records() 会调 init_file()，而 init_file() 现在也加锁。
        这是实际存在的调用路径（update_status / delete_record 等都在锁内读记录）。
        """
        import threading

        repair_log.add_record('A101', '现象', '结论')

        done = threading.Event()

        def work():
            with repair_log.file_lock(repair_log.RECORD_FILE):
                recs = repair_log.load_records()
                assert len(recs) >= 1
            done.set()

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(timeout=5)
        assert done.is_set(), '锁内调用 load_records() 死锁了'


class TestInitFileRace:
    """
    init_file 的「检查-创建」竞态

    历史缺陷：init_file 未加锁，多线程同时首次调用时都能通过
    os.path.exists() 检查，后到的那个以 'w' 模式打开文件 ——
    而 'w' 是截断写，会把先到者刚写入的表头/记录清掉。
    实测 60 轮并发首次创建中有 47 轮丢数据。
    """

    def test_concurrent_init_then_append_no_loss(self, tmp_data):
        """并发首次初始化 + 追加，一条都不能丢"""
        import csv
        import os

        for round_no in range(15):
            if os.path.exists(repair_log.RECORD_FILE):
                os.remove(repair_log.RECORD_FILE)

            def worker(i):
                repair_log.init_file()
                with open(repair_log.RECORD_FILE, 'a', newline='',
                          encoding='utf-8-sig') as f:
                    csv.writer(f).writerow(
                        [f'R{i:03d}', '', '', '', '', '', '', '1', ''])

            errors = _run_threads(worker, n=8)
            assert not errors, errors

            recs = repair_log.load_records()
            assert len(recs) == 8, (
                f'第 {round_no} 轮：预期 8 条，实际 {len(recs)} 条 '
                f'（init_file 的检查-写入竞态把先写入的内容截断了）'
            )
