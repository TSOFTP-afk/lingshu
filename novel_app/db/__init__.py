from __future__ import annotations

from novel_app.db.common import ALL_VOLUMES, UNASSIGNED_VOLUMES


def __getattr__(name: str):
    if name == "Database":
        from novel_app.database import Database

        return Database
    raise AttributeError(name)


__all__ = ["ALL_VOLUMES", "UNASSIGNED_VOLUMES"]
