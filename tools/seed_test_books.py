import json
import random
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "data" / "bookstore_demo.db"
TAGS_MAP_PATH = ROOT_DIR / "data" / "tags_map.json"

with open(TAGS_MAP_PATH, "r", encoding="utf-8") as f:
    TAGS_MAP: dict[str, list[str]] = json.load(f)

CATEGORIES = list(TAGS_MAP.keys())

CHAPTER_TITLES = [
    "风云再起", "暗流涌动", "破晓之光", "命运之轮", "决战前夕",
    "新的开始", "巅峰对决", "迷雾重重", "星辰大海", "归途",
    "初入江湖", "潜龙在渊", "雷霆一击", "山雨欲来", "月色如血",
    "绝处逢生", "一剑惊鸿", "王者归来", "四方云动", "天地同寿",
]

SENTENCE_POOL = [
    "他抬起头，望向远方的天际。",
    "风吹过树林，带来一阵清冷的寒意。",
    "就在那一瞬间，天地仿佛凝固了。",
    "没有人知道下一刻会发生什么。",
    "夜色渐深，星辰点缀着无垠的苍穹。",
    "一道剑光划破长空，带着凌厉的杀意。",
    "她的眼眸中闪烁着坚定的光芒。",
    "古老的传说在这一刻被重新唤醒。",
    "万籁俱寂，唯有心跳声清晰可闻。",
    "命运的齿轮开始缓缓转动。",
    "一道身影悄然出现在黑暗之中。",
    "山峰之巅，云雾缭绕，恍如仙境。",
    "他握紧了手中的剑，深吸一口气。",
    "时光如流水般悄然流逝，不留痕迹。",
    "城中的百姓纷纷走上街头，议论纷纷。",
    "那一战，惊天动地，山河变色。",
    "平静的表面下，暗流汹涌不息。",
    "一缕阳光穿透云层，洒落在大地之上。",
    "他微微皱眉，似乎察觉到了什么。",
    "千年之前的神话，在此刻重演。",
]


def ensure_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    columns = [row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()]
    if "is_test" not in columns:
        conn.execute("ALTER TABLE books ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0")
    if "sub_tags" not in columns:
        conn.execute("ALTER TABLE books ADD COLUMN sub_tags TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


def generate_content(min_paragraphs: int = 8, max_paragraphs: int = 18) -> str:
    paragraphs = []
    count = random.randint(min_paragraphs, max_paragraphs)
    for _ in range(count):
        sentences = []
        sentence_count = random.randint(3, 8)
        for _ in range(sentence_count):
            sentences.append(random.choice(SENTENCE_POOL))
        paragraphs.append("".join(sentences))
    return "\n\n".join(paragraphs)


def pick_sub_tags(category: str, count: int = 5) -> str:
    pool = TAGS_MAP.get(category, [])
    if not pool:
        return ""
    selected = random.sample(pool, min(count, len(pool)))
    return ",".join(selected)


def seed(db_path: Path, book_count: int = 500) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("DELETE FROM chapters WHERE book_id IN (SELECT id FROM books WHERE is_test = 1)")
    conn.execute("DELETE FROM books WHERE is_test = 1")
    conn.commit()

    books = []
    for i in range(1, book_count + 1):
        num = f"{i:03d}"
        category = random.choice(CATEGORIES)
        sub_tags = pick_sub_tags(category)
        summary = f"这是 test{num} 的简介描述。一部{category}类作品，讲述了主角在宏大世界中的冒险旅程与成长故事。"
        books.append(("test", f"test{num}", f"test{num}", summary, category, sub_tags))

    conn.executemany(
        "INSERT INTO books (source_app, source_book_id, title, summary, category, sub_tags, is_test) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        books,
    )
    conn.commit()

    book_ids = [row[0] for row in conn.execute(
        "SELECT id FROM books WHERE is_test = 1 AND source_app = 'test' ORDER BY id"
    ).fetchall()]

    total_chapters = 0
    chapter_batch = []
    for idx, book_id in enumerate(book_ids):
        num = f"{idx + 1:03d}"
        chapter_count = random.randint(8, 14)
        for ch_idx in range(chapter_count):
            source_id = f"test{num}_ch{ch_idx + 1}"
            title = f"第{ch_idx + 1}章 {random.choice(CHAPTER_TITLES)}"
            content = generate_content()
            chapter_batch.append((
                book_id, source_id, "", title, "", "", content, ch_idx,
                0, "none", ""
            ))
            total_chapters += 1

        if len(chapter_batch) >= 500:
            conn.executemany(
                """INSERT INTO chapters (
                    book_id, source_chapter_id, source_volume_id,
                    title, outline, summary_text, content, sort_order,
                    ai_probability, ai_probability_level, source_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                chapter_batch,
            )
            conn.commit()
            chapter_batch = []

    if chapter_batch:
        conn.executemany(
            """INSERT INTO chapters (
                book_id, source_chapter_id, source_volume_id,
                title, outline, summary_text, content, sort_order,
                ai_probability, ai_probability_level, source_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            chapter_batch,
        )
        conn.commit()

    conn.close()
    print(f"已插入 {book_count} 本测试书籍，共 {total_chapters} 章节")


if __name__ == "__main__":
    seed(DB_PATH)
