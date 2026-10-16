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
