"""
样式表的基本完整性检查

为什么需要：
  改 CSS 时如果用全局正则批量替换（比如删掉所有 backdrop-filter），
  很容易误伤相邻的声明 —— 实际就发生过一次：
  正则把 "-webkit-backdrop-filter" 也当成了 "backdrop-filter"，
  删掉它时把下一行的关键字前缀留了下来：

      -webkit-  display: flex;      ← display 失效，弹窗不再居中
      -webkit-  border: 1px solid …  ← 边框消失

  这类损坏浏览器不会报错，页面也不会崩，只是某个样式**悄悄失效了** ——
  最难发现的那种。所以用测试兜住几条最基本的线索。
"""

import os
import re

import pytest

CSS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'web', 'static', 'style.css')


@pytest.fixture(scope='module')
def css():
    with open(CSS_PATH, encoding='utf-8') as f:
        return f.read()


class TestCssSanity:

    def test_braces_balanced(self, css):
        assert css.count('{') == css.count('}'), '花括号不配对'

    def test_parens_balanced(self, css):
        assert css.count('(') == css.count(')'), '圆括号不配对'

    def test_no_orphan_webkit_prefix(self, css):
        """
        不允许出现 "-webkit-" 后面跟空格的写法

        正常的 -webkit- 属性是紧贴的（-webkit-line-clamp、-webkit-box-orient），
        只有被误删前缀时才会剩下 "-webkit-  border: …" 这种残骸。
        """
        bad = re.findall(r'^\s*-webkit-\s+\S.*$', css, re.M)
        assert not bad, '发现被截断的 -webkit- 行：%r' % bad[:3]

    def test_no_empty_declaration(self, css):
        """不允许出现 ": ;" 这种空声明"""
        bad = re.findall(r':\s*;', css)
        assert not bad, '发现空声明 %d 处' % len(bad)

    def test_no_unclosed_comment(self, css):
        assert css.count('/*') == css.count('*/'), '注释未闭合'

    def test_no_duplicate_backdrop_filter(self, css):
        """
        背景已改成纯色，不应再出现 backdrop-filter

        它和动画背景叠在一起会让整屏区域每帧重新模糊，
        曾经是掉帧的主因，别又加回来。
        """
        assert 'backdrop-filter' not in css
