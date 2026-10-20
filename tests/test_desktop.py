"""
桌面窗口版启动器的测试

窗口本身没法规在测试里打开，但启动器里有两段纯逻辑值得测：
  · 端口挑选（不能写死，否则和 Web 版抢同一个端口）
  · 服务就绪等待（不能"线程起来了"就开窗口）

模块级只导入标准库，pywebview 是在 main() 里才导入的 ——
所以这里不装 GUI 依赖也能测。
"""

import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import desktop  # noqa: E402


class TestFreePort:

    def test_returns_usable_port(self):
        port = desktop._free_port()
        assert isinstance(port, int)
        assert 1024 <= port <= 65535

        # 说空闲就必须真的能绑上
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', port))
        finally:
            s.close()

    def test_port_not_hardcoded(self):
        """
        不能写死 5000

        Web 版可能正开着，两个抢同一个端口会起不来。
        """
        ports = {desktop._free_port() for _ in range(5)}
        assert 5000 not in ports


class TestWaitReady:

    def test_returns_false_for_dead_url(self):
        """连不上的地址要在超时后返回 False，而不是抛异常"""
        # 一个几乎不可能有服务的端口
        ok = desktop._wait_ready('http://127.0.0.1:1/', timeout=0.6)
        assert ok is False

    def test_returns_true_for_live_url(self):
        """能响应的地址要立刻返回 True"""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        import threading

        def reply():
            try:
                conn, _ = srv.accept()
                conn.recv(1024)
                conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok')
                conn.close()
            except Exception:
                pass

        threading.Thread(target=reply, daemon=True).start()
        try:
            assert desktop._wait_ready(f'http://127.0.0.1:{port}/',
                                       timeout=3.0) is True
        finally:
            srv.close()


class TestModule:

    def test_log_file_constant(self):
        assert desktop.LOG.endswith('desktop-error.log')

    def test_window_title(self):
        assert desktop.WINDOW_TITLE == '机房故障智能诊断助手'

    def test_src_on_path(self):
        """src 必须在 sys.path 上，否则 app 会找不到 repair_log 这些模块"""
        assert desktop.SRC in sys.path
