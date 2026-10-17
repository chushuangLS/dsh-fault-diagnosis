"""
机房故障智能诊断助手 - 故障分类

用途：给报修记录打一个**细粒度**分类，供统计分析使用
（尤其是「反复故障」—— 同一间教室同一种问题反复出现，指向的是根因而不是配件）。

为什么不用 knowledge.py 里那个分类器：
  knowledge._infer_category() 是给**知识库检索**用的粗分类，
  它的「开机故障」把电源、主板、内存、硬盘、风扇全包在一起。
  对检索来说够用（都是开机类问题），但用来分析「哪个部件在反复坏」
  就完全看不出差别了。

  两者的目标不同，所以分开：
    · knowledge 的分类 → 影响检索打分，改动要谨慎
    · 本模块的分类   → 只影响统计展示，可以调整

分类维度：
  先看「故障对象」—— 已经是「教室设施」的，一律归到教室设施。
  否则按故障部件细分。

  这样与 repair_log.TARGET_FACILITY 保持一致：
  教室总闸、空调、教室网络都由后勤/网络中心处理，和电脑故障不是一类事。
"""

# 分类名（顺序即展示顺序，大致按常见程度）
CATEGORY_FACILITY = '教室设施'
CATEGORY_POWER = '电源故障'
CATEGORY_MEMORY = '内存故障'
CATEGORY_STORAGE = '存储故障'
CATEGORY_BOARD = '主板故障'
CATEGORY_COOLING = '散热故障'
CATEGORY_DISPLAY = '显示故障'
CATEGORY_NETWORK = '网络故障'
CATEGORY_PERIPHERAL = '外设故障'
CATEGORY_SYSTEM = '系统故障'
CATEGORY_PROJECTOR = '投影故障'
CATEGORY_AUDIO = '音频故障'
CATEGORY_PRINT = '打印故障'
CATEGORY_OTHER = '其他'

ALL_CATEGORIES = [
    CATEGORY_POWER, CATEGORY_MEMORY, CATEGORY_STORAGE, CATEGORY_BOARD,
    CATEGORY_COOLING, CATEGORY_DISPLAY, CATEGORY_NETWORK, CATEGORY_PERIPHERAL,
    CATEGORY_SYSTEM, CATEGORY_PROJECTOR, CATEGORY_AUDIO, CATEGORY_PRINT,
    CATEGORY_FACILITY, CATEGORY_OTHER,
]

# 教室级设施的关键词
#
# 仅在记录还没被标记故障对象时用于兜底 ——
# 正常流程下 repair_log.is_facility() 已经给出答案。
_FACILITY_WORDS = [
    '总闸', '配电箱', '配电柜', '空开', '空气开关', '断路器', '跳闸',
    '教室没电', '教室停电', '教室断电', '整间', '全教室',
    '教室网络', '交换机', '路由器', '光猫', '上联',
    '空调', '照明', '日光灯',
]

# 按部件细分的关键词表
#
# 顺序即优先级：越具体的越靠前。
# 例如「风扇异响」要落到散热故障，不能因为含「响」被音频类抢走。
_RULES = [
    (CATEGORY_STORAGE, [
        '硬盘', 'ssd', '固态', '磁盘', '系统盘', '存储',
    ]),
    (CATEGORY_MEMORY, [
        '内存', '内存条', '金手指',
    ]),
    (CATEGORY_BOARD, [
        '主板', 'cmos', 'bios', '南桥', '北桥',
    ]),
    (CATEGORY_COOLING, [
        '风扇', '散热', '积灰', '过热', '温度高', '发烫',
        '噪音大', '很响', '异响',
    ]),
    # 投影要排在显示之前：「投影仪无信号」里的「无信号」是通用词，
    # 放后面的话会被显示故障抢走
    (CATEGORY_PROJECTOR, [
        '投影',
    ]),
    (CATEGORY_DISPLAY, [
        '黑屏', '花屏', '无信号', '没画面', '显示器', '偏色', '分辨率', '闪屏',
    ]),
    (CATEGORY_POWER, [
        '电源', '供电', '插座', '插排', '不通电', '指示灯不亮',
        '开不了机', '打不开', '开机没反应', '按电源没反应',
    ]),
    (CATEGORY_PRINT, [
        '打印', '卡纸', '墨盒', '脱机',
    ]),
    (CATEGORY_AUDIO, [
        '音响', '音箱', '耳机', '话筒', '麦克风', '没声音', '杂音', '电流声',
    ]),
    (CATEGORY_PERIPHERAL, [
        '键盘', '鼠标', 'usb', 'u盘', '摄像头', '耳麦', '外设',
    ]),
    (CATEGORY_NETWORK, [
        '网络', '断网', '网线', '网口', '掉线', '上网', 'ip地址',
    ]),
    (CATEGORY_SYSTEM, [
        '系统', '重装', '驱动', '病毒', '蓝屏', '卡顿', '死机', '弹窗', '还原',
    ]),
]


def classify_text(text):
    """
    从一段文字里推断故障分类（不看故障对象字段）

    先判教室级设施，再按部件细分，都命中不了归「其他」。
    """
    low = (text or '').lower()

    for kw in _FACILITY_WORDS:
        if kw in low:
            return CATEGORY_FACILITY

    for name, keywords in _RULES:
        for kw in keywords:
            if kw in low:
                return name

    return CATEGORY_OTHER


def classify(record):
    """
    给一条报修记录分类

    优先看「故障对象」：已经标记为教室设施的，直接归教室设施。
    这样和 repair_log.TARGET_FACILITY 保持一致，
    不会出现"故障对象是设施、分类却是网络故障"这种矛盾。

    其次看**故障现象**，而不是诊断结论。

    为什么不用结论：
      结论里会写一串鉴别诊断过程，例如「换线后显示器正常，问题出在主机端」
      或者「电源线已重插仍无效，判断为电源或主板供电故障」——
      这些句子里会出现显示器、主板、内存等一大堆部件名，
      拿去做关键词匹配会把分类带偏（实测 3 条记录被误判）。

      故障现象是运维人员自己的简短描述，稳定、没有干扰，
      也更贴近"这间教室又报同样的问题了"这个实际观察。
    """
    if not record:
        return CATEGORY_OTHER

    # 延迟导入：本模块可能被 repair_log 之外的场景单独使用
    try:
        import repair_log
        if repair_log.is_facility(record):
            return CATEGORY_FACILITY
    except Exception:
        pass

    # 先按现象判；现象太模糊（落到其他）时，再退一步看结论
    cat = classify_text(record.get('故障现象'))
    if cat != CATEGORY_OTHER:
        return cat

    return classify_text(record.get('诊断结论'))


def label_order():
    """分类的展示顺序：常见在前，其他垫底"""
    return list(ALL_CATEGORIES)
