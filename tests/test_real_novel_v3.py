"""全链路测试：用真实小说文本测试 V3 分析管道。

使用《斗破苍穹》第一章内容，测试语义分块、实体提及抽取、共指消解、
原子事实抽取、记忆分层、卡片生成和探针规划的完整流程。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION, AnalysisPipelineV3
from novel_app.database import Database

# ============================================================
# 《斗破苍穹》第一章 正文（节选，用于测试）
# ============================================================
CHAPTER_1_TITLE = "第一章 陨落的天才"
CHAPTER_1_CONTENT = """
斗之力，三段！

望着测验魔石碑上面闪亮得甚至有些刺眼的五个大字，少年面无表情，唇角有着一抹自嘲，紧握的手掌，因为大力，而导致略微尖锐的指甲深深的刺进了掌心之中，带来一阵阵钻心的疼痛……

"萧炎，斗之力，三段！级别：低级！"测验魔石碑之旁，一位中年男子，看了一眼碑上所显示出来的信息，语气漠然的将之公布了出来……

中年男子话刚刚脱口，便是不出意外的在人头汹涌的广场上带起了一阵嘲讽的骚动。

"三段？嘿嘿，果然不出我所料，这个'天才'这一年又是在原地踏步！"

"哎，这废物真是把家族的脸都给丢光了。"

"要不是族长是他的父亲，这种废物，早就被驱赶出家族，任其自生自灭了，哪还有机会待在家族中白吃白喝。"

"唉，昔年那名闻乌坦城的天才少年，如今怎么落魄成这般模样了啊？"

"谁知道呢，或许做了什么亏心事，惹得神灵降怒了吧……"

周围传来的不屑嘲笑以及惋惜轻叹，落在那如木桩待在原地的少年耳中，恍如一根根利刺狠狠的扎在心脏一般，让得少年呼吸微微急促。

少年缓缓抬起头来，露出一张有些清秀的稚嫩脸庞，漆黑的眸子木然的在周围那些嘲讽的同龄人身上扫过，少年嘴角的自嘲，似乎变得更加苦涩了。

"这些人，都如此刻薄势力吗？或许是因为三年前他们曾经在自己面前露出过最谦卑的笑容吧，所以，如今想要讨还回去……"苦笑着摇了摇头，萧炎落寞的转身，安静的回到了队伍的最后一排，孤单的身影，与周围的世界，有些格格不入。

"下一个，萧媚！"

听着测验人的喊声，一名少女快速的人群中跑出，少女刚刚出场，附近的议论声便是小了许多，一双双略微火热的目光，牢牢的锁定着少女的脸颊……

少女年龄不过十四左右，虽然并算不上绝色，不过那张稚气未脱的小脸，却是蕴含着淡淡的妩媚，清纯与妩媚，矛盾的集合，让得她成功的成为了全场瞩目的焦点……

少女快步上前，小手轻车熟路的触摸着漆黑的魔石碑，然后缓缓闭上眼睛……

在少女闭眼片刻之后，漆黑的魔石碑之上再次亮起了光芒……

"斗之气：七段！"

"萧媚，斗之气：七段！级别：高级！"

"耶！"听着测验员所喊出的成绩，少女脸颊扬起了得意的笑容……

"啧啧，七段斗之气，真了不起，按这进度，恐怕顶多只需要三年时间，她就能成为一名真正的斗者了吧……"

"不愧是家族中种子级别的人物啊……"

听着人群中传来的一阵阵羡慕声，少女脸颊上的笑容更是多了几分，虚荣心，这是很多女孩都无法抗拒的诱惑……

与平日里的几个姐妹互相笑谈着，萧媚的视线，忽然的透过周围的人群，停在了人群外的那一道孤单身影上……

皱眉思虑了瞬间，萧媚还是打消了过去的念头，现在的两人，已经不在同一个阶层之上，以萧炎最近几年的表现，成年后，顶多只能作为家族中的下层人员，而天赋优秀的她，则将会成为家族重点培养的强者，前途可以说是不可限量。

"唉…"莫名的轻叹了一口气，萧媚脑中忽然浮现出三年前那意气风发的少年，四岁练气，十岁拥有九段斗之气，十一岁突破十段斗之气，成功凝聚斗之气旋，一跃成为家族百年之内最年轻的斗者！

当初的少年，自信而且潜力无可估量，不知让得多少少女对其春心荡漾，当然，这也包括以前的萧媚。

然而天才的道路，貌似总是曲折的，三年之前，这名声望达到巅峰的天才少年，却是突兀的接受到了有生以来最残酷的打击，不仅辛辛苦苦修炼十数载方才凝聚的斗之气旋，一夜之间，化为乌有，而且体内的斗之气，也是随着时间的流逝，变得诡异的越来越少。

斗之气消失的直接结果，便是导致其实力不断的后退。

从天才的神坛，一夜跌落到了连普通人都不如的地步，这种打击，让得少年从此失魂落魄，天才之名，也是逐渐的被不屑与嘲讽所替代。

站的越高，摔得越狠，这次的跌落，或许就再也没有爬起的机会。

"下一个，萧薰儿！"

喧闹的人群中，测试员的声音，再次响了起来。

随着这有些清雅的名字响起，人群忽然的安静了下来，所有的视线，豁然转移。

在众人视线汇聚之处，一位身着紫色衣裙的少女，正淡雅的站立，平静的稚嫩俏脸，并未因为众人的注目而改变分毫。

少女清冷淡然的气质，犹如清莲初绽，小小年纪，却已初具脱俗气质，难以想象，日后若是长大，少女将会如何的倾国倾城……

这名紫裙少女，论起美貌与气质来，比先前的萧媚，无疑还要更胜上几分，也难怪在场的众人都是这般动作。

莲步微移，名为萧薰儿的少女行到魔石碑之前，小手伸出，镶着黑金丝的紫袖滑落而下，露出一截雪白娇嫩的皓腕，然后轻触着石碑……

微微沉静，石碑之上，刺眼的光芒再次绽放。

"斗之气：九段！级别：高级！"

望着石碑之上的字体，场中陷入了一阵寂静。

"……竟然到九段了，真是恐怖！家族中年轻一辈的第一人，恐怕非薰儿小姐莫属了。"寂静过后，周围的少年，都是不由自主的咽了一口唾沫，眼神充满敬畏……

人群中，萧媚皱浅眉盯着石碑前的紫裙少女，脸颊上闪过一抹嫉妒，无奈的轻叹了一口气。

望着石碑上的信息，一旁的中年测验员漠然的脸庞上竟然也是罕见的露出了一丝笑意，对着少女略微恭声道："薰儿小姐，半年之后，你应该便能凝聚斗气之旋，如果你成功的话，那么以十四岁年龄成为一名真正的斗者，你是萧家百年内的第二人！"

是的，第二人，那位第一人，便是褪去了天才光环的萧炎。

"谢谢。"少女微微点了点头，平淡的小脸并未因为他的夸奖而出现喜悦，安静的回转过身，然后在众人炽热的注目中，缓缓的行到了人群最后面的那颓废少年面前……

"萧炎哥哥。"在经过少年身旁时，少女顿下了脚步，对着萧炎恭敬的弯了弯腰，美丽的俏脸上，居然露出了让周围少女为之嫉妒的清雅笑容。

"我现在还有资格让你怎么叫么？"望着面前这颗已经成长为家族中最璀璨的明珠，萧炎苦涩的道，她是在自己落魄后，唯一一个还对自己依旧保持着尊敬的人。

"萧炎哥哥，以前你曾经和薰儿说过，要能放下，才能拿起，提放自如，是自在人！"萧薰儿微笑着柔声道，略微稚嫩的嗓音，却是暖人心肺。

"呵呵，自在人？我也只会说而已，你看我现在的模样，象自在人吗？而且……这世界，本来就不属于我。"萧炎自嘲道。

面对着萧炎的颓废，萧薰儿纤细的眉头微微皱了皱，认真的道："萧炎哥哥，虽然并不知道你究竟是怎么回事，不过，薰儿相信，你会重新站起来，取回属于你的荣耀与尊严……"话到此处，微顿了顿，少女白皙的俏脸，头一次露出淡淡的绯红："当年的萧炎哥哥，的确很吸引人……"

"呵呵……"面对着少女毫不掩饰的坦率话语，少年尴尬的笑了笑，却是再找不出一句话，人在落魄的时候，再温暖的话语，也只不过是一种怜悯。

房间中狼藉一片，萧炎颓废的坐在床沿，木然的望着窗外。

深吸了一口气，少年闭上了眼眸，意识投进自己的体内。

体内的斗之气旋已经消失得无影无踪，经脉中的斗之气，也是稀薄得几乎不可察觉。

"三年前，到底发生了什么？"萧炎紧握着拳头，低声吼道。

就在这时，少年右手上的黑色戒指忽然闪过一丝诡异的光芒，一个苍老的声音突然在房间中响起："小家伙，想知道为什么吗？"

萧炎猛地一惊，目光死死的盯着手指上的戒指："你是谁？"

"嘿嘿，老夫药尘，人称药尊者。"戒指中传来苍老的笑声。

"药尊者？"萧炎心头一震，"你为何在我的戒指里？"

"这个问题，以后再说。现在，我们来谈谈你的斗之气为何消失吧……"药尘的声音带着一丝玩味和得意。

"你知道原因？"萧炎急切的问道。

"当然，因为这三年，你修炼出来的斗之气，全都被老夫给吸收了！"药尘大笑道。

"什么？！"萧炎惊怒交加，"原来是你！"

"小子别急，老夫吸你的斗之气，自然也会给你补偿。从今天起，老夫教你炼药术，让你成为这斗气大陆上最强的炼药师！"

萧炎心中翻江倒海，炼药师，那可是斗气大陆上最尊贵的职业……

"好，我答应你。"少年眼中闪过一抹决然，"不过，我会用我自己的方式，证明给你看。"

"哈哈哈，好小子，有志气！那现在就开始吧……"
"""

CHAPTER_2_TITLE = "第二章 斗气大陆"
CHAPTER_2_CONTENT = """
翌日清晨，萧炎早早的从修炼中醒来，感受着体内缓缓流淌的斗之气，嘴角露出一丝笑意。

按照药尘的指导，他昨晚尝试了一套新的修炼功法——焚决。

"这焚决不愧是地阶低级功法，仅仅一夜的修炼，就让我的斗之气恢复了不少。"萧炎低声自语道。

推开房门，萧炎朝着家族的演武场走去。

演武场上，早已聚集了不少萧家年轻一辈的族人，他们正在进行日常的晨练。

"快看，那个废物来了。"一个尖嘴猴腮的少年低声对身旁的同伴说道。

"呵，他还有脸来演武场？三段斗之气，连我们萧家八岁的孩童都不如吧。"另一个少年嗤笑道。

萧炎仿若未闻，径直走向演武场的一角，开始按照自己的方式修炼。

"萧炎表哥，今天这么早啊。"一道清脆的声音传来，萧媚不知何时走到了他的身旁。

"嗯。"萧炎淡淡应了一声，继续着自己的动作。

萧媚看着眼前这个曾经让她仰望的少年，心中感慨万千，却也不知道该说些什么，轻叹一声后转身离去。

就在这时，演武场中央传来一阵喧哗。

"萧宁表哥突破到八段斗之气了！"

"天啊，萧宁表哥才十六岁，就已经八段了！"

萧宁站在场中央，享受着众人的恭维，目光却扫向了角落里的萧炎，嘴角勾起一抹嘲讽的弧度。

"萧炎表弟，要不要来切磋一下？"萧宁朗声道。

演武场瞬间安静下来，所有人的目光都汇聚到了萧炎身上。

萧炎停下手中的动作，平静的看着萧宁："你想打，我便陪你。"

"好！"萧宁大笑一声，"不过输了可不许哭鼻子。"

两人走到场中央，周围的族人自动让开一片空地。

萧宁身形一动，拳风呼啸，直取萧炎面门。他的速度极快，显然并未因萧炎实力低微而有丝毫留手。

萧炎眼神微凝，脚步轻移，竟是险之又险的避开了这一拳。

"咦？"萧宁轻咦一声，没想到萧炎居然能避开自己的攻击。

就在他愣神的瞬间，萧炎一掌拍出，正中萧宁的胸口。

"嘭！"

萧宁倒退数步，面色一变。

"这……这怎么可能？"围观的族人一片哗然。

萧炎收回手掌，淡淡道："斗之气的高低，并不能完全决定战斗的胜负。"

远处的一座阁楼上，萧家族长萧战负手而立，望着演武场上发生的一切，眼中闪过一丝欣慰。

"族长，萧炎少爷似乎恢复了。"身后一位老者低声道。

"还早。"萧战摇了摇头，"不过……至少他不再颓废了。"

萧战转身，望向大陆的远方："斗气大陆，强者为尊。乌坦城只是一个小小的起点，我萧家的麒麟儿，终有一天会走出这片天地……"
"""

CHAPTER_3_TITLE = "第三章 炼药初试"
CHAPTER_3_CONTENT = """
夜幕降临，萧炎盘坐在自己房间中，面前摆放着几株从后山采来的药材。

"紫兰草、凝血花、骨灵果……这些都是最低级的药材。"药尘的声音从戒指中传出。

"炼药师的基础，便是从这些低级药材开始。"萧炎平静的说道。

"不错，心性倒是沉稳。"药尘赞许道，"现在，按照我教你的方法，尝试炼制一枚凝血散。"

萧炎点了点头，伸出右手，掌心朝上。

"喝！"

轻喝一声，萧炎的手掌之上，一股淡淡的斗气缓缓涌现。

斗气在掌心中凝聚，化为一团淡黄色的火焰——这是每个炼药师都必须掌握的斗气火焰。

萧炎小心翼翼的将一株紫兰草投入火焰之中。药材在火焰的灼烧下，渐渐化为一滴紫色的液体。

"控制好火候，紫兰草的药性温和，但稍有不慎就会焚毁。"药尘提醒道。

萧炎额头渗出细密的汗珠，操控斗气火焰对现在的他来说，消耗极大。

第二株凝血花，第三株骨灵果……

半个时辰后，萧炎手中的火焰缓缓散去，一枚淡红色的丹药静静躺在掌心。

"成功了！"萧炎眼中闪过一抹喜色。

"还不错，第一次就能炼制成功，天赋确实不差。"药尘的声音中带着几分满意。

"药老，这凝血散的效果如何？"萧炎问道。

"凝血散，一品丹药，可加速伤口愈合，止血生肌。虽然在炼药界算是最低级的丹药，但在乌坦城这种小地方，已经算是稀罕物了。"

萧炎将丹药小心收好，眼中闪过一抹坚定："这只是开始。总有一天，我会炼制出九品丹药，成为这大陆上最强的炼药师！"

"有志气。"药老大笑，"不过在此之前，你还需要提升自己的实力。炼药师虽然尊贵，但没有足够的斗气支撑，一切都是空谈。"

"我明白。"

萧炎再次闭上眼睛，进入了修炼状态。

窗外，月光如水，洒在这个曾经跌落神坛的少年身上。

而这一次，他的眼中，不再有迷茫。
"""


def run_full_pipeline_test():
    """运行完整的 V3 分析管道测试，输出详细结果。"""
    print("=" * 80)
    print("灵枢 V3 分析管道 — 真实小说全链路测试")
    print("=" * 80)
    print(f"管道版本: {PIPELINE_V3_VERSION}")
    print(f"测试用书: 《斗破苍穹》(前3章)")
    print()

    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            # ████████████████████████████████████████████████████████████████
            # Step 1: 创建书籍和章节
            # ████████████████████████████████████████████████████████████████
            print("─" * 80)
            print("【Step 1】创建书籍和章节")
            print("─" * 80)
            book_id = db.create_book("斗破苍穹")
            print(f"  创建书籍: id={book_id}")

            chapters_data = [
                (CHAPTER_1_TITLE, CHAPTER_1_CONTENT),
                (CHAPTER_2_TITLE, CHAPTER_2_CONTENT),
                (CHAPTER_3_TITLE, CHAPTER_3_CONTENT),
            ]

            chapter_ids = []
            total_chars = 0
            for title, content in chapters_data:
                ch_id = db.create_chapter(book_id, title)
                db.update_chapter(ch_id, outline="", content=content)
                chapter_ids.append(ch_id)
                chars = len(content.strip())
                total_chars += chars
                print(f"  第{len(chapter_ids)}章: id={ch_id}, 标题={title}, 字数={chars}")

            print(f"  总计: {len(chapter_ids)} 章, {total_chars} 字")

            # ████████████████████████████████████████████████████████████████
            # Step 2: 添加正式人物卡（作为种子增强实体识别）
            # ████████████████████████████████████████████████████████████████
            print()
            print("─" * 80)
            print("【Step 2】添加正式人物卡 (种子)")
            print("─" * 80)
            characters = [
                ("萧炎", "主角，曾经的修炼天才，后沦为废柴，被药尘收入门下学习炼药术"),
                ("萧薰儿", "萧家天才少女，对萧炎始终如一"),
                ("萧媚", "萧家少女，曾经仰慕萧炎"),
                ("药尘", "药尊者，寄居在萧炎戒指中的灵魂，教导萧炎炼药术"),
                ("萧战", "萧家族长，萧炎的父亲"),
                ("萧宁", "萧家年轻一辈的佼佼者"),
            ]
            for name, desc in characters:
                char_id = db.create_character(book_id, name)
                print(f"  人物: {name} (id={char_id}) — {desc}")

            # ████████████████████████████████████████████████████████████████
            # Step 3: 运行 V3 全链路分析
            # ████████████████████████████████████████████████████████████████
            print()
            print("─" * 80)
            print("【Step 3】运行 V3 全链路分析")
            print("─" * 80)

            pipeline = AnalysisPipelineV3(db)
            result = pipeline.start_run(book_id)

            print()
            print(f"  运行状态: {result.status}")
            print(f"  Run ID: {result.run_id}")
            print(f"  语义块数: {result.block_count}")
            print(f"  实体提及数: {result.mention_count}")
            print(f"  实体候选数: {result.entity_count}")
            print(f"  原子事实数: {result.fact_count}")
            print(f"  卡片数: {result.card_count}")
            print(f"  记忆事实数: {result.memory_fact_count}")
            print(f"  记忆摘要数: {result.memory_summary_fact_count}")
            print(f"  探针计划数: {result.probe_plan_count}")
            print(f"  探针结果数: {result.probe_result_count}")
            print(f"  不一致探针数: {result.probe_inconsistent_count}")
            print()

            # ████████████████████████████████████████████████████████████████
            # Step 4: 详细输出语义块
            # ████████████████████████████████████████████████████████████████
            print("─" * 80)
            print("【Step 4】语义分块详情 (前10个)")
            print("─" * 80)
            blocks = db.list_analysis_blocks(book_id, run_id=result.run_id)
            for block in blocks[:10]:
                text_preview = str(block["text"])[:80].replace("\n", " ")
                print(f"  [{block['chunk_id']}] 章节{block['chapter_id']} | {block['char_start']}-{block['char_end']}")
                print(f"    文本: {text_preview}...")
                print(f"    content_hash: {block['content_hash'][:16]}...")

            # ████████████████████████████████████████████████████████████████
            # Step 5: 详细输出实体提及
            # ████████████████████████████████████████████████████████████████
            print()
            print("─" * 80)
            print("【Step 5】实体提及详情")
            print("─" * 80)
            mentions = db.list_analysis_entity_mentions(book_id, run_id=result.run_id)
            for mention in mentions:
                row = dict(mention)
                print(f"  [{row['mention_uid']}]")
                print(f"    类型: {row['entity_type']}")
                print(f"    名称: {row['normalized_text']}")
                print(f"    原文: {row['quote_text']}")
                print(f"    置信度: {row['confidence']}")
                print(f"    来源规则: {row['source_rule']}")
                print(f"    章节: {row.get('chapter_id')}")
                print()

            # ████████████████████████████████████████████████████████████████
            # Step 6: 详细输出实体候选（共指消解结果）
            # ████████████████████████████████████████████████████████████████
            print("─" * 80)
            print("【Step 6】实体候选（共指消解结果）")
            print("─" * 80)
            entities = db.list_analysis_entities(book_id, run_id=result.run_id)
            for entity in entities:
                row = dict(entity)
                print(f"  [{row['entity_uid'][:20]}...]")
                print(f"    类型: {row['entity_type']}")
                print(f"    规范名称: {row['canonical_name']}")
                print(f"    别名: {row.get('aliases', '')}")
                print(f"    置信度: {row['confidence']}")
                print(f"    提及数: {row.get('mention_count', '?')}")
                print(f"    来源规则: {row['source_rule']}")
                print()

            # ████████████████████████████████████████████████████████████████
            # Step 7: 详细输出原子事实
            # ████████████████████████████████████████████████████████████████
            print("─" * 80)
            print("【Step 7】原子事实详情")
            print("─" * 80)
            facts = db.list_analysis_facts(book_id, run_id=result.run_id)
            for fact in facts:
                row = dict(fact)
                value = dict(row.get('value') or {})
                print(f"  [{row['fact_uid'][:16]}...]")
                print(f"    类型: {row['fact_type']}")
                print(f"    主体: {row['subject_entity_uid'][:20]}...")
                print(f"    内容: {str(value.get('summary', ''))[:100]}")
                print(f"    原文: {str(row['quote_text'])[:120]}")
                print(f"    置信度: {row['confidence']}")
                print(f"    记忆范围: {row['memory_scope']}")
                print(f"    记忆重要性: {row['memory_importance']}")
                print(f"    记忆类型: {row['memory_type']}")
                print(f"    重要性分数: {row['importance_score']}")
                print()

            # ████████████████████████████████████████████████████████████████
            # Step 8: 详细输出卡片
            # ████████████████████████████████████████████████████████████████
            print("─" * 80)
            print("【Step 8】分析卡片详情")
            print("─" * 80)
            cards = db.list_analysis_cards(result.run_id)
            for card in cards:
                row = dict(card)
                print(f"  [{row['card_uid'][:20]}...]")
                print(f"    类型: {row['card_type']}")
                print(f"    状态: {row['status']}")
                print(f"    实体UID: {row.get('entity_uid', 'N/A')}")
                card_payload = str(row.get("payload") or "")
                print(f"    Payload 长度: {len(card_payload)} 字符")
                # 尝试解析 JSON payload
                try:
                    payload_json = json.loads(card_payload)
                    if isinstance(payload_json, dict):
                        for key in list(payload_json.keys())[:5]:
                            val = payload_json[key]
                            if isinstance(val, str):
                                print(f"      {key}: {val[:80]}")
                            elif isinstance(val, list):
                                print(f"      {key}: [{len(val)} 项]")
                            else:
                                print(f"      {key}: {val}")
                except Exception:
                    print(f"    Payload: {card_payload[:150]}")
                print()

            # ████████████████████████████████████████████████████████████████
            # Step 9: 查询审查/门禁状态
            # ████████████████████████████████████████████████████████████████
            print("─" * 80)
            print("【Step 9】审查与门禁状态")
            print("─" * 80)
            audit = db.connection.execute(
                "SELECT action, target_type, reason, created_at FROM analysis_audit_logs WHERE run_id = ? ORDER BY created_at",
                (result.run_id,),
            ).fetchall()
            for row in audit:
                print(f"  [{row['created_at']}] {row['action']}")
                print(f"    原因: {row['reason']}")

            # ████████████████████████████████████████████████████████████████
            # Step 10: 运行增量分析测试
            # ████████████████████████████████████████████████████████████████
            print()
            print("─" * 80)
            print("【Step 10】增量分析测试")
            print("─" * 80)
            # 添加新章节
            ch4_id = db.create_chapter(book_id, "第四章 坊市风波")
            db.update_chapter(ch4_id, outline="", content="""
萧炎带着凝血散走出萧家，前往乌坦城的坊市。

坊市中人声鼎沸，各种摊位琳琅满目。

"凝血散？一品丹药？"一个中年修士盯着萧炎手中的丹药，眼中闪过惊讶。

"这位小哥，这凝血散是你的？"中年修士快步上前。

"不错。"萧炎平静道。

"我愿意出五百金币购买，如何？"

"成交。"

交易完成后，萧炎将金币收入怀中。有了这笔钱，他就可以购买更好的药材，尝试炼制更高级的丹药。

远处，一个黑袍人静静注视着这一幕，嘴角露出一丝玩味的笑容。

"有意思的小家伙……"
""")
            print(f"  新增第4章: id={ch4_id}")

            inc_result = pipeline.start_incremental_run(book_id)
            print(f"  增量分析状态: {inc_result.status}")
            print(f"  是否增量: {inc_result.meta.get('incremental')}")
            print(f"  基础 Run ID: {inc_result.meta.get('base_run_id')}")
            print(f"  新增章节数: {inc_result.meta.get('chapters_added', 0)}")
            print(f"  未变章节数: {inc_result.meta.get('chapters_unchanged', 0)}")
            print(f"  新 Block 数: {inc_result.block_count}")
            print(f"  新 Mention 数: {inc_result.mention_count}")
            print(f"  新 Entity 数: {inc_result.entity_count}")
            print(f"  新 Fact 数: {inc_result.fact_count}")

            # ████████████████████████████████████████████████████████████████
            # 最终汇总
            # ████████████████████████████████████████████████████████████████
            print()
            print("=" * 80)
            print("测试汇总")
            print("=" * 80)
            print(f"  书籍: 斗破苍穹 (id={book_id})")
            print(f"  章节数: {len(chapter_ids) + 1} (含新增)")
            print(f"  总字数: ~{total_chars + 300} 字")
            print(f"  Run ID: {result.run_id}")
            print(f"  最终状态: {result.status}")
            print()
            print("  全量分析结果:")
            print(f"    - 语义分块: {result.block_count} 个")
            print(f"    - 实体提及: {result.mention_count} 个")
            print(f"    - 实体候选: {result.entity_count} 个")
            print(f"    - 原子事实: {result.fact_count} 个")
            print(f"    - 分析卡片: {result.card_count} 张")
            print(f"    - 记忆事实: {result.memory_fact_count} 条")
            print(f"    - 探针计划: {result.probe_plan_count} 个")
            print(f"    - 不一致项: {result.probe_inconsistent_count} 个")
            print()
            print("  增量分析结果:")
            print(f"    - 新增 Block: {inc_result.block_count} 个")
            print(f"    - 新增 Mention: {inc_result.mention_count} 个")
            print(f"    - 新增 Entity: {inc_result.entity_count} 个")
            print(f"    - 新增 Fact: {inc_result.fact_count} 个")
            print()
            print("=" * 80)
            print("全链路测试完成!")
            print("=" * 80)

        finally:
            db.close()


if __name__ == "__main__":
    run_full_pipeline_test()
