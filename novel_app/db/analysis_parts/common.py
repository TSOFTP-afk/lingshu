"""analysis_parts 各分域 mixin 共享的模块级常量与辅助函数。

当前各分域文件没有需要共享的模块级常量/函数，此文件仅转发
``novel_app.db.common`` 的导出（含 ``Any``/``sqlite3``/``json``/``hashlib`` 等），
后续新增共享常量或辅助函数时放在这里。
"""
from __future__ import annotations

from novel_app.db.common import *
