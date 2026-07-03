"""
灵枢 qt_app.py — Qt 桌面应用入口文件

该文件在 v2.0 迁移中已被替换。Qt/PyQt6 桌面应用已迁移至 Vue3 + FastAPI + Electron。

原 Qt 入口逻辑位于:
- main.py → 现在启动 FastAPI 后端
- lingshu-app/  → Vue3 前端（创作工作台）
- web/          → Vue3 前端（书城读者端）
- admin-web/    → Vue3 前端（管理后台）
- electron/     → Electron 桌面壳

请使用以下命令启动:
    后端:     python main.py
    前端:     npm run dev (在项目根目录)
    桌面壳:   cd electron && npx electron .
"""
