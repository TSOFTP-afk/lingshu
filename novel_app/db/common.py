from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from novel_app.star_graph_defaults import PRESET_NODE_STYLES, PRESET_RELATIONSHIP_TYPES
from novel_app.structured_templates.base import (
    BOOK_OUTLINE_FORM_MIGRATION_ID,
    CHARACTER_PROFILE_FORM_MIGRATION_ID,
    STRUCTURED_TEMPLATE_MIGRATION_ID,
    WORLD_FORM_MIGRATION_ID,
    book_outline_form_defaults,
    book_outline_form_to_markdown,
    book_outline_markdown_to_form,
    character_profile_form_defaults,
    character_profile_form_to_markdown,
    character_profile_markdown_to_form,
    merge_world_supplement,
    normalize_book_outline_form,
    normalize_character_profile_form,
    normalize_world_form,
    world_entry_template,
    world_form_defaults,
    world_form_to_markdown,
    world_markdown_to_form,
)

ALL_VOLUMES = "__all__"
UNASSIGNED_VOLUMES = "__unassigned__"
DATABASE_RESET_EPOCH_ID = "full_db_reset_book_outline_v2_20260608"
ANALYSIS_V3_FOUNDATION_MIGRATION_ID = "analysis_v3_foundation"
logger = logging.getLogger("novel_app.database")

__all__ = [
    "ANALYSIS_V3_FOUNDATION_MIGRATION_ID",
    "ALL_VOLUMES",
    "Any",
    "BOOK_OUTLINE_FORM_MIGRATION_ID",
    "CHARACTER_PROFILE_FORM_MIGRATION_ID",
    "DATABASE_RESET_EPOCH_ID",
    "PRESET_NODE_STYLES",
    "PRESET_RELATIONSHIP_TYPES",
    "Path",
    "STRUCTURED_TEMPLATE_MIGRATION_ID",
    "UNASSIGNED_VOLUMES",
    "WORLD_FORM_MIGRATION_ID",
    "book_outline_form_defaults",
    "book_outline_form_to_markdown",
    "book_outline_markdown_to_form",
    "character_profile_form_defaults",
    "character_profile_form_to_markdown",
    "character_profile_markdown_to_form",
    "hashlib",
    "json",
    "logger",
    "merge_world_supplement",
    "normalize_book_outline_form",
    "normalize_character_profile_form",
    "normalize_world_form",
    "os",
    "shutil",
    "sqlite3",
    "world_entry_template",
    "world_form_defaults",
    "world_form_to_markdown",
    "world_markdown_to_form",
]
