"""
路径解析与本地配置的测试

这两块是打包成 exe 的前提，出错的表现都很隐蔽：
  · 路径错了 → 用户记的数据写到临时目录，程序一关就没了
  · Key 读不到 → 程序能开，一诊断就报错

所以宁可多测几条。
"""

import json
import os
import sys

import pytest

import paths


class TestFrozenDetection:

    def test_not_frozen_in_dev(self):
        """测试环境不是打包后的 exe"""
        assert paths.is_frozen() is False

    def test_app_dir_is_project_root_in_dev(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.normcase(paths.app_dir()) == os.path.normcase(root)

    def test_res_dir_equals_app_dir_in_dev(self):
        """开发时只读资源和程序在同一处"""
        assert os.path.normcase(paths.res_dir()) == os.path.normcase(
            paths.app_dir())

    def test_frozen_uses_meipass_for_resources(self, monkeypatch):
        """
        打包后 resource 目录必须用 sys._MEIPASS

        PyInstaller 会把 web/templates 解得那儿；
        如果这里还按 __file__ 推，页面会 404。
        """
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        monkeypatch.setattr(sys, '_MEIPASS', r'C:\Temp\_MEI123', raising=False)
        monkeypatch.setattr(sys, 'executable', r'C:\Apps\助手\助手.exe',
                            raising=False)

        assert paths.is_frozen() is True
        assert paths.res_dir() == r'C:\Temp\_MEI123'
        # 程序目录取 exe 所在目录，不是解包目录
        assert paths.app_dir() == r'C:\Apps\助手'

    def test_frozen_without_meipass_falls_back(self, monkeypatch):
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        monkeypatch.delenv('_MEIPASS', raising=False)
        monkeypatch.setattr(sys, '_MEIPASS', '', raising=False)
        monkeypatch.setattr(sys, 'executable', r'C:\Apps\助手.exe',
                            raising=False)
        # 没有 _MEIPASS 时至少不能崩
        assert paths.res_dir() == r'C:\Apps'


class TestDataDir:

    def test_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DSH_DATA_DIR', str(tmp_path / 'mydata'))
        paths.reset_cache()
        try:
            d = paths.data_dir()
            assert os.path.normcase(d) == os.path.normcase(
                str(tmp_path / 'mydata'))
            assert os.path.isdir(d), '应自动创建目录'
        finally:
            paths.reset_cache()

    def test_data_file_joins(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DSH_DATA_DIR', str(tmp_path))
        paths.reset_cache()
        try:
            p = paths.data_file('x.csv')
            assert os.path.normcase(p) == os.path.normcase(
                str(tmp_path / 'x.csv'))
        finally:
            paths.reset_cache()

    def test_default_dir_is_project_data(self, monkeypatch):
        monkeypatch.delenv('DSH_DATA_DIR', raising=False)
        paths.reset_cache()
        try:
            assert os.path.normcase(paths.data_dir()) == os.path.normcase(
                os.path.join(paths.app_dir(), 'data'))
        finally:
            paths.reset_cache()


class TestConfig:

    @pytest.fixture
    def cfg(self, tmp_path, monkeypatch):
        """配置写到临时目录，不碰真实 data/"""
        monkeypatch.setenv('DSH_DATA_DIR', str(tmp_path))
        monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
        paths.reset_cache()
        import config
        # 避免读到注册表里的真实 Key
        monkeypatch.setattr(config, '_windows_user_env', lambda name: '')
        yield config
        paths.reset_cache()

    def test_missing_returns_empty(self, cfg):
        assert cfg.get_api_key() == ''
        assert cfg.has_api_key() is False

    def test_save_and_read(self, cfg):
        p = cfg.set_api_key('sk-test-1234567890')
        assert os.path.exists(p)
        assert cfg.get_api_key() == 'sk-test-1234567890'
        assert cfg.has_api_key() is True

    def test_env_wins_over_file(self, cfg, monkeypatch):
        cfg.set_api_key('sk-from-file')
        monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-from-env')
        assert cfg.get_api_key() == 'sk-from-env'

    def test_file_wins_over_windows_env(self, cfg, monkeypatch):
        """
        在弹窗里填的 key 应该盖过更早设过的系统环境变量

        否则用户改了 key 却不生效，会以为程序坏了。
        """
        cfg.set_api_key('sk-from-file')
        monkeypatch.setattr(cfg, '_windows_user_env',
                            lambda name: 'sk-from-registry')
        assert cfg.get_api_key() == 'sk-from-file'

    def test_registry_fallback(self, cfg, monkeypatch):
        """文件里没有时读 Windows 用户环境变量"""
        monkeypatch.setattr(cfg, '_windows_user_env',
                            lambda name: 'sk-from-registry')
        assert cfg.get_api_key() == 'sk-from-registry'

    def test_clear(self, cfg):
        cfg.set_api_key('sk-test')
        cfg.set_api_key('')
        assert cfg.get_api_key() == ''

    def test_corrupt_file_does_not_crash(self, cfg):
        """配置文件坏了当没有配置处理，不能让整个程序起不来"""
        p = cfg.config_file()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('{ 这不是合法 JSON')

        assert cfg.load() == {}
        assert cfg.get_api_key() == ''

    def test_mask(self, cfg):
        assert cfg.mask_key('') == ''
        assert cfg.mask_key('short') == '*****'
        masked = cfg.mask_key('sk-1234567890abcdefghij')
        assert masked.startswith('sk-123')
        assert masked.endswith('ghij')
        assert '4567890abcdef' not in masked
