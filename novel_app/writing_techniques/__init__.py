"""网文写作技巧集加载器与索引服务。

从 docs/功能/网文小说写作技巧集 目录加载：
- 24 个可执行 SKILL（skills/SKILL-*.md，结构化格式）
- 48 篇参考知识库（按 12 个分类目录组织）

为长篇生成提供可检索、可注入 prompt 的技能索引。
"""
from novel_app.writing_techniques.loader import WritingTechniqueLoader
from novel_app.writing_techniques.indexer import TechniqueIndexer

__all__ = ["WritingTechniqueLoader", "TechniqueIndexer"]
