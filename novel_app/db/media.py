from __future__ import annotations

from novel_app.db.common import *


class MediaMixin:
    def normalize_media_path(self, path: str | Path) -> str:
        value = str(path).strip()
        if not value:
            return ""
        candidate = Path(value)
        try:
            resolved = candidate.resolve()
        except OSError:
            return value
        try:
            return resolved.relative_to(self.data_dir.resolve()).as_posix()
        except ValueError:
            return str(resolved)

    def resolve_media_path(self, stored_path: str | Path) -> Path:
        value = str(stored_path).strip()
        if not value:
            return Path()
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
        data_root = self.data_dir.resolve()
        try:
            resolved = (data_root / candidate).resolve()
            resolved.relative_to(data_root)
            return resolved
        except (OSError, ValueError):
            logger.warning("Rejected media path outside data_dir: %s", stored_path)
            return Path()
