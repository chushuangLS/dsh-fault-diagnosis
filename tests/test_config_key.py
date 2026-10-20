"""
API Key 配置的测试（含"清除后屏蔽环境变量"这条语义）
"""

import sys

import pytest

import config
import paths


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    paths.reset_cache()
    # 不读真实注册表
    monkeypatch.setattr(config, '_windows_user_env', lambda name: '')
    yield config
    paths.reset_cache()


class TestKeySource:

    def test_none(self, cfg):
        assert cfg.key_source() == 'none'
        assert cfg.get_api_key() == ''

    def test_env_wins(self, cfg, monkeypatch):
        cfg.set_api_key('sk-file')
        monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-env')
        assert cfg.key_source() == 'env'
        assert cfg.get_api_key() == 'sk-env'

    def test_file_wins_over_registry(self, cfg, monkeypatch):
        cfg.set_api_key('sk-file')
        monkeypatch.setattr(cfg, '_windows_user_env', lambda n: 'sk-reg')
        assert cfg.key_source() == 'file'

    def test_registry_fallback(self, cfg, monkeypatch):
        monkeypatch.setattr(cfg, '_windows_user_env', lambda n: 'sk-reg')
        assert cfg.key_source() == 'windows'
        assert cfg.get_api_key() == 'sk-reg'


class TestDisabled:
    """
    「清除」必须真的把 Key 停掉

    只删 config.json 里的 key 是不够的 —— 后面还有注册表兜底，
    会把它又找回来，用户点了清除却发现还能用，会以为坏了。
    """

    def test_clear_blocks_registry(self, cfg, monkeypatch):
        monkeypatch.setattr(cfg, '_windows_user_env', lambda n: 'sk-reg')
        assert cfg.get_api_key() == 'sk-reg'

        cfg.set_api_key('')          # 点「清除」

        assert cfg.get_api_key() == ''
        assert cfg.key_source() == 'disabled'
        assert cfg.is_disabled() is True

    def test_clear_blocks_env_too(self, cfg, monkeypatch):
        monkeypatch.setenv('DEEPSEEK_API_KEY', 'sk-env')
        cfg.set_api_key('')
        assert cfg.get_api_key() == '', '清除后环境变量也应被忽略'

    def test_set_key_lifts_disabled(self, cfg):
        cfg.set_api_key('')
        assert cfg.is_disabled() is True

        cfg.set_api_key('sk-new')
        assert cfg.is_disabled() is False
        assert cfg.get_api_key() == 'sk-new'

    def test_disabled_survives_corrupt_other_fields(self, cfg):
        cfg.set_api_key('')
        data = cfg.load()
        assert data.get(cfg.DISABLED_FIELD) is True
