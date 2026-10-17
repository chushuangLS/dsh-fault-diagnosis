"""
测试公共配置（pytest fixture）

要点：
  1. 把 src 加入 sys.path，让测试能 import 各个模块
  2. 每个测试用「临时数据文件」，绝不碰仓库里的真实数据
  3. 不依赖真实 API Key（不调用大模型）
"""

import json
import os
import shutil
import sys
import tempfile

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# 避免导入时因缺少 Key 而报错（本测试套件不会真的调用 API）
os.environ.setdefault('DEEPSEEK_API_KEY', 'sk-test-not-used')


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """
    把各模块的数据文件重定向到临时目录

    这样可以放心地测增删改，不会污染 data/ 下的真实数据。
    """
    import knowledge
    import classroom
    import daily_task
    import repair_log
    import schedule

    d = tmp_path / 'data'
    d.mkdir()

    monkeypatch.setattr(knowledge, 'MANUAL_FILE', str(d / 'fault_cases.json'))
    monkeypatch.setattr(knowledge, 'AUTO_FILE', str(d / 'fault_cases_auto.json'))
    monkeypatch.setattr(classroom, 'DATA_FILE', str(d / 'classrooms.json'))
    monkeypatch.setattr(daily_task, 'DATA_FILE', str(d / 'daily_tasks.json'))
    monkeypatch.setattr(repair_log, 'RECORD_FILE', str(d / 'repair_records.csv'))
    monkeypatch.setattr(schedule, 'DATA_FILE', str(d / 'schedule.json'))

    return d


@pytest.fixture
def seeded_knowledge(tmp_data):
    """写入几条手工案例，供检索测试使用"""
    import knowledge

    cases = [
        {
            'id': 'PC-001', 'category': '开机故障',
            'symptom': '按开机键没有任何反应，指示灯不亮，风扇不转',
            'causes': ['电源线未插紧或插座无电', '电源供应器损坏'],
            'steps': ['检查电源线两端是否插紧'],
        },
        {
            'id': 'NET-001', 'category': '网络故障',
            'symptom': '整个教室的电脑都无法上网',
            'causes': ['交换机断电或故障', '上层网络中断'],
            'steps': ['确认是否整间教室都断网'],
        },
        {
            'id': 'DISPLAY-001', 'category': '显示故障',
            'symptom': '显示器黑屏，显示无信号',
            'causes': ['视频线未插紧', '显示器输入源选错'],
            'steps': ['检查视频线两端是否插紧'],
        },
    ]
    with open(knowledge.MANUAL_FILE, 'w', encoding='utf-8') as f:
        json.dump({'version': '0.1.0', 'description': '测试知识库', 'cases': cases},
                  f, ensure_ascii=False, indent=2)
    return cases


@pytest.fixture
def seeded_rooms(tmp_data):
    """
    预置一个空的教室台账文件

    名称保留为 seeded_rooms 是因为导出测试会在这个基础上继续加教室；
    这里先建好合法结构，避免文件不存在导致读取回退。
    """
    import classroom

    with open(classroom.DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump({'buildings': []}, f, ensure_ascii=False, indent=2)
    return classroom.DATA_FILE
