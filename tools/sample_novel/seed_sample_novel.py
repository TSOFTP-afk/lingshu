#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢范例小说种子脚本。

将《镜中蝉》范例小说及其完整分析数据导入云端数据库（bookstore_demo.db），
归属系统范例用户（__sample__）。新用户注册时由 store.clone_sample_novel_to_user
复制到其个人空间。

预生成数据完美对齐灵枢 V3 九阶段分析引擎与 V1 书籍级 payload 产物：
- characters + character_state_machines（三轴：欲望/MBTI/命理 + 价值观 + 运行态）
- character_cycles / character_snapshots（循环日志与快照）
- chapter_events（每章关键事件，供 M5 卡片生成）
- world_entries（世界观条目，供 world 写回）
- character_relationships（人物关系网，供 M3 共指/实体图谱）
- cloud_analysis_runs + cloud_analysis_cards（V3 卡片，含身份消解卡）

幂等：重复运行会先清除 __sample__ 用户的旧范例再重建。

用法：
    python tools/sample_novel/seed_sample_novel.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# 让脚本能直接从项目根目录运行
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from novel_app.bookstore.models import DEFAULT_DB_PATH, _connect, initialize_database  # noqa: E402

SAMPLE_USERNAME = "__sample__"
SAMPLE_NOVEL_TITLE = "镜中蝉（灵枢范例小说）"
NOVEL_TXT_PATH = Path(__file__).resolve().parent / "镜中蝉.txt"

# ---------------------------------------------------------------------------
# 1. 章节解析
# ---------------------------------------------------------------------------

CHAPTER_PATTERN = re.compile(r"^第([一二三四五六七八九十百零]+)章\s+(.+)$")


def parse_novel(text: str) -> list[dict]:
    """将小说原文按『第X章 标题』拆分为章节列表。"""
    lines = text.splitlines()
    chapters: list[dict] = []
    current_title = "序·世界观与人物"
    current_lines: list[str] = []
    # 开头的世界观/人物设定块作为第 0 章（设定），不计入正文章节
    intro_lines: list[str] = []
    intro_done = False
    for line in lines:
        m = CHAPTER_PATTERN.match(line.strip())
        if m:
            if not intro_done and not chapters:
                intro_lines.extend(current_lines)
            else:
                chapters.append({
                    "title": current_title,
                    "content": "\n".join(current_lines).strip(),
                })
            current_title = f"第{m.group(1)}章 {m.group(2).strip()}"
            current_lines = []
            intro_done = True
            continue
        current_lines.append(line)
    if current_lines:
        chapters.append({"title": current_title, "content": "\n".join(current_lines).strip()})

    # 把开头设定块作为单独一章（设定），放到最前
    intro_text = "\n".join(intro_lines).strip()
    if intro_text:
        chapters.insert(0, {"title": "设定·世界观与人物", "content": intro_text})
    return chapters


# ---------------------------------------------------------------------------
# 2. 人物定义（含完整状态机三轴 + 价值观 + 运行态）
#    字段对齐 character_state_machines 表
# ---------------------------------------------------------------------------

CHARACTERS: list[dict] = [
    {
        "name": "沈砚",
        "role": "主角",
        "profile_text": "上海《新声报》记者，沈鹤年之子。为查父亲十年前失踪真相回到青砚镇，理性缜密却执着，最终在破案后放下执念转向写作。",
        "state_machine": {
            "desire_text": "追寻父亲失踪的真相",
            "desire_origin": "父亲沈鹤年十年前在青砚镇人间蒸发，活不见人死不见尸",
            "desire_anchor": "停在申时三刻的怀表",
            "desire_extreme": "不惜以身犯险，孤身推开蝉镜下地下室",
            "desire_fear_mirror": "怕遗忘——怕忘记父亲的样子，也怕执念本身吞没自己",
            "mbti_type": "INTJ",
            "mbti_i_e": "I", "mbti_n_s": "N", "mbti_t_f": "T", "mbti_j_p": "J",
            "mbti_strategy": "抽丝剥茧，以证据链与线索拼图逼近真相",
            "mbti_advantage": "洞察细节，能从金粉、桂花香、镜中影子察觉异常",
            "mbti_blindspot": "过度理性，初时忽视人情的复杂",
            "fate_type": "命理悖论",
            "fate_content": "越接近真相越被真相吞噬——执念是把刀，能杀人也能割自己",
            "fate_trigger": "申时三刻停摆的怀表",
            "fate_target": "父亲",
            "fate_limit": "真相高于一切，但人心高于真相",
            "belief_core": "真相高于一切",
            "belief_origin": "记者的家训与父亲以身殉真的传承",
            "belief_alignment": "为真相可以冒生命危险",
            "belief_sacrifice": "愿以自身安危换取真相与公道",
            "belief_taboo": "不为追寻真相而牺牲无辜",
            "current_desire_state": "awakened",
            "current_mbti_state": "INTJ",
            "current_fate_state": "active",
            "current_belief_state": "shifting",
            "current_friction": "internal",
            "current_dilemma": "执念与释然之间——父亲遗言让他放下刀",
            "total_change_score": 18,
            "last_update_source": "范例种子",
        },
    },
    {
        "name": "陆婉清",
        "role": "女主角",
        "profile_text": "如烟社当家花旦，身世成谜。登台时镜中倒影常与现实不符。实为十年前失踪的少女小蝉，隐姓埋名十年归来讨公道。与沈砚共破旧案后，去江南小镇教孤儿唱戏。",
        "aliases": ["小蝉", "婉清", "那姑娘", "戏中人", "镜中人"],
        "state_machine": {
            "desire_text": "讨十年血债，救出地下室被囚的孩子",
            "desire_origin": "十年前撞破柳月亭窝藏被拐孩子的罪恶，被秦先生追杀逃亡",
            "desire_anchor": "小铜镜（师父遗物，背面刻『镜中藏真，蝉蜕留壳』）",
            "desire_extreme": "在台上当众唱破真相，置自身于险地",
            "desire_fear_mirror": "被认出真实身份而再度招祸",
            "mbti_type": "INFP",
            "mbti_i_e": "I", "mbti_n_s": "N", "mbti_t_f": "F", "mbti_j_p": "P",
            "mbti_strategy": "以情动人，隐忍十年伺机而发，借戏文传真相",
            "mbti_advantage": "坚韧隐忍，能十年磨一剑",
            "mbti_blindspot": "自我感动，独自承担不愿连累他人",
            "fate_type": "戏命",
            "fate_content": "人生如戏，戏如人生，蝉蜕尘泥留空壳，镜里容颜镜外身",
            "fate_trigger": "镜中不一致的影子——镜中蝉影即她自己",
            "fate_target": "自由",
            "fate_limit": "不能以小蝉身份归来，归来即是死局",
            "belief_core": "不害无辜",
            "belief_origin": "孤儿出身，深知弱者之苦",
            "belief_alignment": "宁可独自涉险不连累沈砚",
            "belief_sacrifice": "愿以自身性命换孩子与公道",
            "belief_taboo": "宁可牺牲自己，不连累无辜",
            "current_desire_state": "awakened",
            "current_mbti_state": "INFP",
            "current_fate_state": "active",
            "current_belief_state": "stable",
            "current_friction": "external",
            "current_dilemma": "复仇与新生之间——最终选择把善意传给孤儿",
            "total_change_score": 21,
            "last_update_source": "范例种子",
        },
    },
    {
        "name": "周慎之",
        "role": "重要配角",
        "profile_text": "青砚镇警察所长，国字脸，处事拘泥程序，忌惮权贵。十年前因怯懦瞒下血字证据，十年来背负愧疚。沈砚归来后终开口坦白，协助翻案。",
        "state_machine": {
            "desire_text": "维持秩序、保全自身与家小",
            "desire_origin": "小镇警察所长，上有县里大人物压顶",
            "desire_anchor": "那枚泛黄的旧照片（与小蝉、沈鹤年合影）",
            "desire_extreme": "为求自保擦掉镜面血字，瞒了十年",
            "desire_fear_mirror": "得罪县里张参议而全家遭殃",
            "mbti_type": "ISTJ",
            "mbti_i_e": "I", "mbti_n_s": "S", "mbti_t_f": "T", "mbti_j_p": "J",
            "mbti_strategy": "按程序办事，明哲保身，伺机而动",
            "mbti_advantage": "熟悉镇上人事，能请来县督察",
            "mbti_blindspot": "拘泥条文，怯懦延宕十年",
            "fate_type": "迟来之赎",
            "fate_content": "怯懦者的迟来赎罪——瞒了十年终须开口",
            "fate_trigger": "沈砚归来与那张旧照片",
            "fate_target": "公道",
            "fate_limit": "一怕十年，开口即赌上前途与性命",
            "belief_core": "服从上级以求自保",
            "belief_origin": "体制内小人物的生存哲学",
            "belief_alignment": "前期服从，后期转变",
            "belief_sacrifice": "最终赌上前途请督察翻案",
            "belief_taboo": "（后期转变）不可再让无辜枉死",
            "current_desire_state": "shifted",
            "current_mbti_state": "ISTJ",
            "current_fate_state": "awakened",
            "current_belief_state": "shifting",
            "current_friction": "internal",
            "current_dilemma": "自保与公道之间——终选公道",
            "total_change_score": 12,
            "last_update_source": "范例种子",
        },
    },
    {
        "name": "柳如烟",
        "role": "反派/灰色人物",
        "profile_text": "如烟社班主，三十上下，墨绿旗袍，水粉折扇。柳月亭侄女，被迫接手叔叔的人贩子生意，又暗地记账十年，等一个翻案时机。镜碎时格刀救沈砚还债。",
        "state_machine": {
            "desire_text": "扳倒张参议，为自己赎罪脱身",
            "desire_origin": "叔叔柳月亭死后留下烂摊子与被要挟的把柄",
            "desire_anchor": "攒了十年的张参议罪证账册",
            "desire_extreme": "一边作恶一边记账，以恶止恶",
            "desire_fear_mirror": "把柄暴露而身败名裂、性命不保",
            "mbti_type": "ENTJ",
            "mbti_i_e": "E", "mbti_n_s": "N", "mbti_t_f": "T", "mbti_j_p": "J",
            "mbti_strategy": "隐忍十年记账，借力打力，等外人翻案",
            "mbti_advantage": "城府深，能同时周旋于黑白两道",
            "mbti_blindspot": "自负，以恶止恶难以自辩",
            "fate_type": "还债",
            "fate_content": "作恶十年终还一债——镜碎时人亦碎，救沈砚是还沈鹤年的命",
            "fate_trigger": "小蝉登台唱破真相的那一刻",
            "fate_target": "救赎",
            "fate_limit": "罪与赎同体，救一人难赎十年恶",
            "belief_core": "目的至上",
            "belief_origin": "被要挟下的生存逻辑",
            "belief_alignment": "为扳倒张参议可忍受一切",
            "belief_sacrifice": "愿以入狱换账册上交",
            "belief_taboo": "（暗线）不可害沈鹤年之子——欠沈家一条命",
            "current_desire_state": "extreme",
            "current_mbti_state": "ENTJ",
            "current_fate_state": "active",
            "current_belief_state": "fractured",
            "current_friction": "internal",
            "current_dilemma": "作恶与赎罪同体——账册是唯一的出路",
            "total_change_score": 15,
            "last_update_source": "范例种子",
        },
    },
    {
        "name": "秦先生",
        "role": "反派",
        "profile_text": "县政务厅调查科亲信，戴礼帽穿长衫，瘦削阴鸷。十年前受张参议指使杀沈鹤年、追杀小蝉。十年后回镇灭口，被周慎之请来的督察擒获。",
        "state_machine": {
            "desire_text": "替张参议灭口，保全自身",
            "desire_origin": "拿人钱财替人消灾，依附权贵",
            "desire_anchor": "那枚刻『秦』字的政务厅调查科徽章",
            "desire_extreme": "十年后再度回镇杀人灭口",
            "desire_fear_mirror": "主子倒台则自己陪葬",
            "mbti_type": "ESTP",
            "mbti_i_e": "E", "mbti_n_s": "S", "mbti_t_f": "T", "mbti_j_p": "P",
            "mbti_strategy": "干净利落灭口，不留活口",
            "mbti_advantage": "果决狠辣",
            "mbti_blindspot": "只认强权不识大势，终被大势碾过",
            "fate_type": "刀客反噬",
            "fate_content": "刀客终被刀所噬——十年前一刀，十年后成囚",
            "fate_trigger": "镜子碎裂、督察到场",
            "fate_target": "权势",
            "fate_limit": "依附权势者，权势倒则命绝",
            "belief_core": "强权即真理",
            "belief_origin": "调查科鹰犬的信仰",
            "belief_alignment": "为权势可杀人越货",
            "belief_sacrifice": "为主子顶罪至最后一刻",
            "belief_taboo": "不留活口",
            "current_desire_state": "frustrated",
            "current_mbti_state": "ESTP",
            "current_fate_state": "collapsed",
            "current_belief_state": "broken",
            "current_friction": "external",
            "current_dilemma": "灭口不成反成囚",
            "total_change_score": 5,
            "last_update_source": "范例种子",
        },
    },
    {
        "name": "沈鹤年",
        "role": "回忆人物",
        "profile_text": "沈砚之父，《新声报》前身记者。十年前为救小蝉、揭露柳月亭罪恶，在鸣蝉阁戏台后被秦先生所害，尸骨埋于地下室。遗言『真相高于一切，但人心高于真相』。",
        "state_machine": {
            "desire_text": "揭露柳月亭罪恶，救小蝉",
            "desire_origin": "记者的良知与对小蝉如父女之情",
            "desire_anchor": "蝉纹怀表与鸣蝉阁调查录",
            "desire_extreme": "孤身赴鸣蝉阁对质，以身殉真",
            "desire_fear_mirror": "（已亡）遗言中怕儿子被执念吞没",
            "mbti_type": "INFJ",
            "mbti_i_e": "I", "mbti_n_s": "N", "mbti_t_f": "F", "mbti_j_p": "J",
            "mbti_strategy": "调查取证，孤身对质",
            "mbti_advantage": "理想主义的光芒与笔的力度",
            "mbti_blindspot": "低估对手的狠辣",
            "fate_type": "殉真",
            "fate_content": "为真相殉身，遗言『人心高于真相』",
            "fate_trigger": "戏台后的大铜镜——他多看了一眼那面镜子",
            "fate_target": "真相",
            "fate_limit": "真相与性命不可兼得",
            "belief_core": "真相高于一切，但人心高于真相",
            "belief_origin": "记者毕生的信念与临终顿悟",
            "belief_alignment": "为真相可殉命",
            "belief_sacrifice": "以命换小蝉逃生与真相存世",
            "belief_taboo": "勿让执念吞了自己——遗训告诫沈砚",
            "current_desire_state": "fulfilled",
            "current_mbti_state": "INFJ",
            "current_fate_state": "sealed",
            "current_belief_state": "transcended",
            "current_friction": "none",
            "current_dilemma": "（已了）真相已由儿子昭雪",
            "total_change_score": 0,
            "last_update_source": "范例种子",
        },
    },
]


# ---------------------------------------------------------------------------
# 3. 人物关系（character_relationships）
# ---------------------------------------------------------------------------

RELATIONSHIPS: list[dict] = [
    {"source": "沈砚", "target": "沈鹤年", "type": "父子", "description": "沈砚为寻父真相归来，父亲遗言成其执念与释然之钥"},
    {"source": "沈砚", "target": "陆婉清", "type": "同盟", "description": "共破十年旧案，互为真相伙伴"},
    {"source": "陆婉清", "target": "沈鹤年", "type": "如父女", "description": "小蝉当年受沈鹤年如父般照拂，沈鹤年因救她而死"},
    {"source": "周慎之", "target": "沈鹤年", "type": "故人", "description": "十年前同在青砚镇，周慎之因怯懦瞒下沈鹤年之死的血字证据"},
    {"source": "柳如烟", "target": "柳月亭", "type": "侄女/继承", "description": "柳月亭死后柳如烟被迫接手如烟社与其罪恶生意"},
    {"source": "秦先生", "target": "柳如烟", "type": "受雇/反制", "description": "秦先生受柳如烟所请来办沈砚，却在台上被柳如烟反制格刀"},
    {"source": "秦先生", "target": "沈鹤年", "type": "凶手/被害", "description": "十年前秦先生奉张参议之命在鸣蝉阁戏台后杀害沈鹤年"},
    {"source": "秦先生", "target": "陆婉清", "type": "追杀", "description": "十年前追杀小蝉未果，十年后回镇欲补杀"},
]


# ---------------------------------------------------------------------------
# 4. 世界观条目（world_entries）
# ---------------------------------------------------------------------------

WORLD_ENTRIES: list[dict] = [
    {"name": "青砚镇", "category": "地点", "content_text": "江南水乡，故事发生地。镇口石桥跨青砚河，老街尽头是鸣蝉阁。流传古训：镜中可见未亡人之影，蝉鸣起时旧案必翻。"},
    {"name": "鸣蝉阁", "category": "建筑", "content_text": "青砚镇百年戏楼，三层木楼，飞檐翘角，前清状元题匾。戏台后有大铜镜（蝉镜），实为通往地下室的暗门。"},
    {"name": "蝉镜", "category": "器物", "content_text": "鸣蝉阁戏台后的大铜镜，传为前明镜匠以陨铁铸成。实为地下室暗门。所谓镜中蝉影，是地下室被囚者透过镜缝漏出的目光。另有小铜镜一枚，背面刻『镜中藏真，蝉蜕留壳』，为小蝉师父遗物。"},
    {"name": "如烟社", "category": "组织", "content_text": "驻鸣蝉阁的戏班。先班主柳月亭借戏班掩护窝藏被拐孩子，死后由侄女柳如烟接手。表面唱戏，暗地仍干人贩子勾当。"},
    {"name": "镜花缘", "category": "戏目", "content_text": "如烟社重排之戏，演唐敖游历海外诸国。小蝉在『女儿国』一折加词『蝉蜕尘泥留空壳，镜里容颜镜外身』，暗指自身身份与十年旧案。"},
    {"name": "地下室", "category": "秘所", "content_text": "鸣蝉阁戏台大铜镜后的暗室，石阶通往铁门。当年柳月亭在此窝藏被拐孩子，沈鹤年尸骨亦埋于此。柳如烟接手后继续关押新拐来的孩子。"},
]


# ---------------------------------------------------------------------------
# 5. 章节事件（chapter_events，按章节标题匹配）
# ---------------------------------------------------------------------------

CHAPTER_EVENTS: dict[str, list[str]] = {
    "设定·世界观与人物": ["故事发生在民国十七年青砚镇", "十年前小蝉与沈鹤年同年失踪", "鸣蝉阁蝉镜传说"],
    "第一章 归乡": ["沈砚归乡初见陆婉清", "镜中影子与台上人动作不一致", "周慎之警告水深", "深秋蝉鸣反常响起"],
    "第二章 旧宅": ["发现停在申时三刻的怀表", "找到四人合影：沈鹤年/小蝉/周慎之/班主", "父亲遗书『勿追镜中蝉』", "镜匠之女传说与蝉镜"],
    "第三章 戏中": ["周慎之讲述十年前镜中多出白衣影子", "看戏时镜中陆婉清朝沈砚笑如小蝉", "戏文『蝉蜕尘泥留空壳』", "捡到蝉纹折扇约九月廿九槐树下"],
    "第四章 失踪": ["打杂小顺子于鸣蝉阁失踪", "纸扎铺瞎眼老头转交小蝉留下的小铜镜", "镜中见梳辫子少女小蝉", "周慎之约子时旧宅细谈"],
    "第五章 线索": ["周慎之坦白小蝉是被吓跑非失踪", "柳月亭借戏班窝藏被拐孩子", "秦先生受张参议之命杀沈鹤年", "镜面血字『镜中蝉勿追』被周慎之擦去"],
    "第六章 共指": ["槐树下陆婉清承认自己就是小蝉", "小蝉流亡十年学戏归来", "大铜镜是地下室暗门", "父亲遗言『人心高于真相』"],
    "第七章 暗涌": ["柳如烟下帖邀沈砚看戏并警告", "桃花折扇暗指小蝉", "沈砚推开蝉镜发现地下石阶", "秦先生现身『令尊十年前也是在这被我拦下』"],
    "第八章 镜碎": ["小蝉台上当众唱破十年真相", "沈砚与秦先生厮打撞碎百年大铜镜", "柳如烟水粉折扇格开秦先生短刀", "地下室救出被拐孩子并取出沈鹤年尸骨"],
    "第九章 身份": ["秦先生供认一刀杀沈鹤年", "柳如烟早认出陆婉清即小蝉却未揭穿", "柳如烟十年记账等翻案时机", "柳如烟格刀是为还沈家一条命"],
    "第十章 对峙": ["柳如烟交出攒了十年的张参议罪证账册", "柳如烟自述被要挟接手罪恶生意", "救沈砚是为还沈鹤年无辜之死的债"],
    "第十一章 揭幕": ["省里派员查办张参议人贩子网络", "沈砚带父亲骨殖回上海与母亲合葬", "小蝉去江南小镇教孤儿唱戏", "执念放下，人心高于真相"],
    "第十二章 蝉鸣": ["沈砚辞去报社写《镜中蝉》小说", "收到小蝉来信：种槐树教孤儿", "镜碎蝉鸣，人心不灭真相不死", "记忆里的蝉鸣陪他一辈子"],
}


# ---------------------------------------------------------------------------
# 6. V3 分析 run + cards（展示九阶段产物）
# ---------------------------------------------------------------------------

ANALYSIS_RUN_META = {
    "pipeline_version": "analysis_v3_m8_probes_v1",
    "scope_type": "book",
    "status": "completed",
    "summary": "《镜中蝉》全书 V3 分析：6 实体、12 章节事件、1 起跨章节身份消解（陆婉清=小蝉）、3 条核心伏笔（怀表/蝉镜/蝉鸣）、4 轴状态机已填充。",
    "stages": {
        "l1_semantic_blocks": "12 章按戏台幕次切分，含 1 设定块",
        "entity_mentions": "提取 6 主要实体 + 多个称呼变体",
        "entity_coreference": "陆婉清/小蝉/婉清/那姑娘/戏中人/镜中人 共指同一实体",
        "identity_resolve": "陆婉清 === 小蝉（十年前后身份消解，confidence=trusted）",
        "atomic_facts": "怀表停申时三刻、镜中影子不一致、地下室救孩子等核心事实",
        "memory_layer": "沈鹤年之死压缩为长记忆，蝉鸣意象迁移为短记忆触发",
        "card_events": "生成 6 实体卡 + 12 章节事件卡 + 1 身份消解卡",
        "probe_plans": "镜中影子一致性探针：trusted；怀表时刻与失踪时间探针：trusted",
    },
}


def build_analysis_cards() -> list[dict]:
    """构造 V3 分析卡片列表，符合 cloud_analysis_cards.payload_json 结构。"""
    cards: list[dict] = []
    # 实体卡（6 个人物）
    for ch in CHARACTERS:
        cards.append({
            "card_uid": f"entity_{ch['name']}",
            "card_type": "entity",
            "entity_uid": ch["name"],
            "ars_score": 0.92,
            "status": "applied",
            "payload_json": {
                "name": ch["name"],
                "role": ch["role"],
                "profile_text": ch["profile_text"],
                "writeback_target": "character",
                "writeback_fields": {
                    "name": ch["name"],
                    "role": ch["role"],
                    "profile_text": ch["profile_text"],
                    "facts": [
                        {"fact_type": "motivation", "content": ch["state_machine"]["desire_text"]},
                        {"fact_type": "fear", "content": ch["state_machine"]["desire_fear_mirror"]},
                        {"fact_type": "cognition strategy", "content": ch["state_machine"]["mbti_strategy"]},
                        {"fact_type": "blindspot", "content": ch["state_machine"]["mbti_blindspot"]},
                        {"fact_type": "fate limitation", "content": ch["state_machine"]["fate_content"]},
                        {"fact_type": "belief", "content": ch["state_machine"]["belief_core"]},
                    ],
                },
            },
        })
    # 身份消解卡（陆婉清 = 小蝉）
    cards.append({
        "card_uid": "identity_resolve_wanqing_xiaochan",
        "card_type": "identity_resolve",
        "entity_uid": "陆婉清",
        "ars_score": 0.98,
        "status": "applied",
        "payload_json": {
            "canonical": "陆婉清",
            "aliases": ["小蝉", "婉清", "那姑娘", "戏中人", "镜中人"],
            "evidence": [
                "第六章陆婉清在槐树下亲口承认『你就是小蝉，对不对』『嗯』",
                "周慎之证实『小蝉以陆婉清的身份回到青砚镇』",
                "年龄吻合：十年前十二三岁，今二十出头",
                "镜中影子与照片上小蝉笑容一致",
            ],
            "confidence": "trusted",
            "note": "跨章节身份消解，V3 M3+ 阶段产出",
        },
    })
    # 关键事件卡
    for title, events in CHAPTER_EVENTS.items():
        cards.append({
            "card_uid": f"events_{title[:8]}",
            "card_type": "event",
            "entity_uid": "",
            "ars_score": 0.85,
            "status": "applied",
            "payload_json": {
                "chapter": title,
                "events": events,
                "writeback_target": "chapter",
            },
        })
    return cards


# ---------------------------------------------------------------------------
# 7. 数据库写入逻辑
# ---------------------------------------------------------------------------

def ensure_sample_user(connection: sqlite3.Connection) -> int:
    """确保 __sample__ 系统用户存在，返回 user_id。"""
    row = connection.execute(
        "SELECT id FROM users WHERE username = ?", (SAMPLE_USERNAME,)
    ).fetchone()
    if row:
        return int(row["id"])
    cursor = connection.execute(
        "INSERT INTO users (username, password_hash, is_author, is_admin, status) "
        "VALUES (?, '', 0, 0, 'sample')",
        (SAMPLE_USERNAME,),
    )
    return int(cursor.lastrowid)


def clear_sample_data(connection: sqlite3.Connection, user_id: int) -> None:
    """清除该用户的旧范例数据（cloud_books 级联删除大部分关联表）。"""
    connection.execute(
        "DELETE FROM cloud_books WHERE user_id = ?", (user_id,)
    )


def insert_sample(connection: sqlite3.Connection, user_id: int) -> dict:
    """插入完整范例数据，返回统计信息。"""
    novel_text = NOVEL_TXT_PATH.read_text(encoding="utf-8")
    chapters = parse_novel(novel_text)

    # book
    cursor = connection.execute(
        "INSERT INTO cloud_books (user_id, title, outline_text, world_text, source_type) "
        "VALUES (?, ?, ?, ?, 'sample')",
        (
            user_id,
            SAMPLE_NOVEL_TITLE,
            "民国十七年，记者沈砚归乡查父失踪案，牵出十年前小蝉失踪、柳月亭人贩子、秦先生灭口等连环旧案。镜碎蝉鸣，真相昭雪。",
            "青砚镇·鸣蝉阁·蝉镜·如烟社·镜花缘·地下室",
        ),
    )
    cloud_book_id = int(cursor.lastrowid)

    # chapters
    chapter_id_map: dict[str, int] = {}
    for idx, ch in enumerate(chapters):
        c = connection.execute(
            "INSERT INTO cloud_chapters (cloud_book_id, title, content, summary_text, sort_order, chapter_type) "
            "VALUES (?, ?, ?, '', ?, '正文')",
            (cloud_book_id, ch["title"], ch["content"], idx),
        )
        chapter_id_map[ch["title"]] = int(c.lastrowid)

    # characters + state machines
    char_id_map: dict[str, int] = {}
    for ch in CHARACTERS:
        c = connection.execute(
            "INSERT INTO cloud_characters (cloud_book_id, name, role, profile_text) VALUES (?, ?, ?, ?)",
            (cloud_book_id, ch["name"], ch["role"], ch["profile_text"]),
        )
        cid = int(c.lastrowid)
        char_id_map[ch["name"]] = cid
        sm = ch["state_machine"]
        connection.execute(
            "INSERT INTO cloud_character_state_machines (cloud_character_id, "
            "desire_text, desire_origin, desire_anchor, desire_extreme, desire_fear_mirror, "
            "mbti_type, mbti_i_e, mbti_n_s, mbti_t_f, mbti_j_p, mbti_strategy, mbti_advantage, mbti_blindspot, "
            "fate_type, fate_content, fate_trigger, fate_target, fate_limit, "
            "belief_core, belief_origin, belief_alignment, belief_sacrifice, belief_taboo, "
            "current_desire_state, current_mbti_state, current_fate_state, current_belief_state, "
            "current_friction, current_dilemma, total_change_score, last_update_source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                sm["desire_text"], sm["desire_origin"], sm["desire_anchor"], sm["desire_extreme"], sm["desire_fear_mirror"],
                sm["mbti_type"], sm["mbti_i_e"], sm["mbti_n_s"], sm["mbti_t_f"], sm["mbti_j_p"],
                sm["mbti_strategy"], sm["mbti_advantage"], sm["mbti_blindspot"],
                sm["fate_type"], sm["fate_content"], sm["fate_trigger"], sm["fate_target"], sm["fate_limit"],
                sm["belief_core"], sm["belief_origin"], sm["belief_alignment"], sm["belief_sacrifice"], sm["belief_taboo"],
                sm["current_desire_state"], sm["current_mbti_state"], sm["current_fate_state"], sm["current_belief_state"],
                sm["current_friction"], sm["current_dilemma"], sm["total_change_score"], sm["last_update_source"],
            ),
        )
        # 每人一条主循环日志（范例种子写入）
        connection.execute(
            "INSERT INTO cloud_character_cycles (cloud_character_id, cycle_type, cycle_code, "
            "triggered_desire, belief_filtered_strategy, action_taken, world_feedback, feedback_intensity, "
            "mbti_change, star_state, fate_state, internal_friction, change_score, cumulative_score, "
            "batch_summary, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid, "main", "M#1", sm["desire_text"], sm["mbti_strategy"],
                "范例种子写入", sm["fate_content"], "light",
                sm["mbti_strategy"], sm["current_desire_state"], sm["current_fate_state"],
                sm["current_friction"], 3, sm["total_change_score"],
                f"{ch['name']} 初始状态机建档", 1,
            ),
        )

    # relationships
    for rel in RELATIONSHIPS:
        src = char_id_map.get(rel["source"])
        tgt = char_id_map.get(rel["target"])
        if src and tgt:
            connection.execute(
                "INSERT INTO cloud_character_relationships (cloud_book_id, source_character_id, target_character_id, relationship_type, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (cloud_book_id, src, tgt, rel["type"], rel["description"]),
            )

    # world entries
    for we in WORLD_ENTRIES:
        connection.execute(
            "INSERT INTO cloud_world_entries (cloud_book_id, name, category, content_text) VALUES (?, ?, ?, ?)",
            (cloud_book_id, we["name"], we["category"], we["content_text"]),
        )

    # chapter events
    for title, events in CHAPTER_EVENTS.items():
        cid = chapter_id_map.get(title)
        if not cid:
            continue
        for idx, label in enumerate(events):
            connection.execute(
                "INSERT INTO cloud_chapter_events (cloud_book_id, cloud_chapter_id, label, sort_order) VALUES (?, ?, ?, ?)",
                (cloud_book_id, cid, label, idx),
            )

    # analysis run
    run_cursor = connection.execute(
        "INSERT INTO cloud_analysis_runs (cloud_book_id, scope_type, status, pipeline_version, summary, meta_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            cloud_book_id,
            ANALYSIS_RUN_META["scope_type"],
            ANALYSIS_RUN_META["status"],
            ANALYSIS_RUN_META["pipeline_version"],
            ANALYSIS_RUN_META["summary"],
            json.dumps(ANALYSIS_RUN_META["stages"], ensure_ascii=False),
        ),
    )
    run_id = int(run_cursor.lastrowid)

    # analysis cards
    for card in build_analysis_cards():
        connection.execute(
            "INSERT INTO cloud_analysis_cards (cloud_book_id, cloud_run_id, card_uid, card_type, entity_uid, "
            "ars_score, status, payload_json, applied_table) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cloud_book_id, run_id, card["card_uid"], card["card_type"], card["entity_uid"],
                card["ars_score"], card["status"],
                json.dumps(card["payload_json"], ensure_ascii=False),
                "character" if card["card_type"] in ("entity", "identity_resolve") else "chapter",
            ),
        )

    return {
        "book_id": cloud_book_id,
        "chapters": len(chapters),
        "characters": len(CHARACTERS),
        "relationships": len(RELATIONSHIPS),
        "world_entries": len(WORLD_ENTRIES),
        "chapter_events": sum(len(v) for v in CHAPTER_EVENTS.values()),
        "analysis_cards": len(build_analysis_cards()),
    }


def main() -> None:
    # 尊重 BOOKSTORE_DB_PATH 环境变量，与线上服务保持同一数据库
    env_db = os.environ.get("BOOKSTORE_DB_PATH", "").strip()
    db_path = Path(env_db) if env_db else DEFAULT_DB_PATH
    initialize_database(db_path)
    with _connect(db_path) as connection:
        user_id = ensure_sample_user(connection)
        clear_sample_data(connection, user_id)
        stats = insert_sample(connection, user_id)
        connection.commit()
    print(f"[seed_sample_novel] 范例小说已导入 user_id={user_id}")
    print(f"  book_id={stats['book_id']}")
    print(f"  chapters={stats['chapters']}, characters={stats['characters']}")
    print(f"  relationships={stats['relationships']}, world_entries={stats['world_entries']}")
    print(f"  chapter_events={stats['chapter_events']}, analysis_cards={stats['analysis_cards']}")
    print(f"  db={db_path}")


if __name__ == "__main__":
    main()
