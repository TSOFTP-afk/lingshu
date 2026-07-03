"""
工作台 Pydantic 模型 — 书籍/分卷/章节的数据模型。
"""
from typing import Any

from pydantic import BaseModel, Field


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(default="", max_length=4000)
    tags: str = Field(default="", max_length=500)


class BookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    summary: str | None = Field(default=None, max_length=4000)
    tags: str | None = Field(default=None, max_length=500)


class VolumeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class VolumeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    sort_order: int | None = Field(default=None)


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ChapterUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = Field(default=None, max_length=1_000_000)
    outline: str | None = Field(default=None, max_length=100_000)
    sort_order: int | None = Field(default=None)


class ChapterMove(BaseModel):
    target_volume_id: int | None = Field(default=None)
    sort_order: int


class SnapshotCreate(BaseModel):
    label: str = Field(default="")


class SnapshotRestore(BaseModel):
    snapshot_id: str


class CharacterCreate(BaseModel):
    """创建人物请求体。"""
    name: str = Field(..., min_length=1, max_length=100, description="人物名称")
    profile_text: str = Field(default="", description="人物描述文本")
    profile_data: dict[str, Any] | None = Field(default=None, description="人物表单数据")


class CharacterUpdate(BaseModel):
    """更新人物请求体。"""
    name: str | None = Field(default=None, max_length=100, description="人物名称")
    role: str | None = Field(default=None, max_length=50, description="人物角色")
    profile_text: str | None = Field(default=None, description="人物描述文本")
    profile_data: dict[str, Any] | None = Field(default=None, description="人物表单数据")
    image_path: str | None = Field(default=None, description="人物图片路径")


class CharacterLinkBook(BaseModel):
    """人物关联书籍请求体。"""
    book_id: int = Field(..., gt=0, description="书籍 ID")


class StateMachineUpdate(BaseModel):
    """状态机三轴/价值观/运行态快照字段更新。

    所有字段可选，仅更新提供的字段。字段名必须在 STATE_MACHINE_FIELD_IDS 白名单内。
    """
    model_config = {"extra": "forbid"}
    desire_text: str | None = None
    desire_origin: str | None = None
    desire_anchor: str | None = None
    desire_extreme: str | None = None
    desire_fear_mirror: str | None = None
    mbti_type: str | None = None
    mbti_i_e: str | None = None
    mbti_n_s: str | None = None
    mbti_t_f: str | None = None
    mbti_j_p: str | None = None
    mbti_strategy: str | None = None
    mbti_advantage: str | None = None
    mbti_blindspot: str | None = None
    fate_type: str | None = None
    fate_content: str | None = None
    fate_trigger: str | None = None
    fate_target: str | None = None
    fate_limit: str | None = None
    belief_core: str | None = None
    belief_origin: str | None = None
    belief_alignment: str | None = None
    belief_sacrifice: str | None = None
    belief_taboo: str | None = None
    current_desire_state: str | None = None
    current_mbti_state: str | None = None
    current_fate_state: str | None = None
    current_belief_state: str | None = None
    current_friction: str | None = None
    current_dilemma: str | None = None
    last_update_source: str | None = None


class CycleCreate(BaseModel):
    """创建循环日志。"""
    cycle_type: str = Field(..., pattern="^(micro|main|heavy)$")
    intensity: str = Field(default="", pattern="^(|light|medium|heavy|existential)$")
    triggered_desire: str = ""
    belief_filtered_strategy: str = ""
    action_taken: str = ""
    world_feedback: str = ""
    feedback_intensity: str = ""
    mbti_change: str = ""
    star_state: str = ""
    fate_state: str = ""
    internal_friction: str = ""
    cycle_code: str = ""


class CharacterSnapshotCreate(BaseModel):
    """手动触发快照存档。"""
    trigger_detail: str = ""
    phase_change_summary: str = ""
    micro_cycle_summary: str = ""


class GenerationSnapshotCreate(BaseModel):
    """创建生成快照。"""
    mode: str = Field(default="draft", pattern="^(draft|continue|polish)$")
    outline: str = ""
    generated_text: str = ""
    selected_skills: list[dict[str, Any]] = Field(default_factory=list)
    status: str = Field(default="success", pattern="^(success|failed|cancelled)$")
    task_id: str = ""


class WorldSave(BaseModel):
    """保存世界观请求体。"""
    world_text: str = Field(default="", description="世界观 Markdown 文本")
    world_data: dict[str, Any] | None = Field(default=None, description="世界观表单数据")
    text: str | None = Field(default=None, description="兼容旧客户端的世界观文本字段")
    content: str | None = Field(default=None, description="兼容旧客户端的世界观文本字段")

    @property
    def resolved_world_text(self) -> str:
        if self.world_text:
            return self.world_text
        return self.text or self.content or ""


class BookOutlineSave(BaseModel):
    """保存书籍大纲请求体。"""
    outline_text: str = Field(default="", description="大纲 Markdown 文本")
    outline_data: dict[str, Any] | None = Field(default=None, description="大纲表单数据")
    text: str | None = Field(default=None, description="兼容旧客户端的大纲文本字段")
    content: str | None = Field(default=None, description="兼容旧客户端的大纲文本字段")

    @property
    def resolved_outline_text(self) -> str:
        if self.outline_text:
            return self.outline_text
        return self.text or self.content or ""


# ================================================================
#  响应 Schema
# ================================================================


class OkResponse(BaseModel):
    """通用成功响应。"""
    ok: bool = Field(default=True, description="操作是否成功")


class BookListResponse(BaseModel):
    """书籍列表响应。"""
    # TODO: 细化 items 为 BookItem schema
    items: list[dict[str, Any]] = Field(default_factory=list, description="书籍列表")


class BookItemResponse(BaseModel):
    """单本书籍操作响应（创建/更新）。"""
    ok: bool = Field(default=True, description="操作是否成功")
    # TODO: 细化 item 为 BookDetail schema
    item: dict[str, Any] = Field(default_factory=dict, description="书籍详情")


class VolumeItemResponse(BaseModel):
    """单分卷操作响应（创建/更新）。"""
    ok: bool = Field(default=True, description="操作是否成功")
    item: dict[str, Any] = Field(default_factory=dict, description="分卷详情")


class ChapterListResponse(BaseModel):
    """章节列表响应。"""
    # TODO: 细化 items 为 ChapterItem schema
    items: list[dict[str, Any]] = Field(default_factory=list, description="章节列表")


class ChapterItemResponse(BaseModel):
    """单章节操作响应（创建/更新/恢复）。"""
    ok: bool = Field(default=True, description="操作是否成功")
    # TODO: 细化 item 为 ChapterDetail schema
    item: dict[str, Any] = Field(default_factory=dict, description="章节详情")


class SnapshotListResponse(BaseModel):
    """快照列表响应。"""
    # TODO: 细化 items 为 SnapshotItem schema
    items: list[dict[str, Any]] = Field(default_factory=list, description="快照列表")
