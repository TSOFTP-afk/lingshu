# Contributing

感谢关注灵枢。这个仓库以本地桌面写作工作台为核心，优先保证用户数据安全、导入兼容和可回归测试。

## 开发流程

1. 安装开发依赖：`python -m pip install -r requirements-dev.txt`
2. 修改前先运行相关局部测试。
3. 修改数据库、AI 服务、导入导出或 Qt 主窗口时，至少运行 `python -m pytest -q`。
4. 提交前运行编译检查：

```powershell
python -m compileall -q main.py novel_app tests test_core_modules.py test_database_extensions.py test_text_importer.py test_qt_helpers.py
```

## 代码约定

- 保留公开兼容入口：`novel_app.database.Database`、`novel_app.ai_service.SimpleAIService`、`novel_app.structured_templates`。
- 数据层不要依赖 Qt UI 模块。
- 不静默吞掉异常；无法中断主流程的回调错误也要记录日志。
- 不删除或重写用户数据，数据库迁移必须可重复执行。
- 真实 AI API 调用不作为自动化测试前提，测试使用 mock。

## 文档与测试

- 新增公共能力时同步 README 或 `docs/开发指南.md`。
- 新增可被外部调用的模块时，确认 `tools/generate_api_docs.py` 可以生成文档。
- 性能测试使用 `pytest.mark.performance`，避免拖慢默认回归。

## 防复发纪律（长期有效）

依据 `docs/项目抢救方案_2026-09.md` 第六节 4.4，以下规则为硬约束，违反任何一条的 PR 不予合并：

1. **每天 commit，每个 feature 一个分支**。不允许再出现"几天开发只留 2 个 commit"的历史；小步提交、及时 push。
2. **禁止新增平行实现**：
   - 不加第二个管理端（管理界面统一在 cloud-admin）；
   - 不加第二套 DB/Redis 连接（统一走 `novel_app/db` 与 `lingshu_api/dependencies.py`）；
   - 不复制第二份 `ensure_column` / 迁移逻辑（共享逻辑进 `shared/` 或统一 API client）。
3. **私货不入库**。账号、绝对路径、生产 URL、密钥一律走环境变量（`LINGSHU_*` / `REDIS_*` / `.env`）。合并前执行：

   ```bash
   grep -rn "ling-shu.top\|26455\|12345678a\|/home/CODEX" --exclude-dir=node_modules --exclude-dir=_attic .
   ```

   有命中（_attic 留档除外）就修掉再合。
4. **设施必须被消费**。CI 每周至少真实跑一次并看一眼覆盖率报告；连续两周无人引用的文档移入 `_attic/` 留档，不留"看起来有"的假设施。
5. **抢救期不加新功能**。`docs/项目抢救方案_2026-09.md` 路线（阶段 0–4 + E2E 十例）完成之前，所有产能给地基，不接受新功能 PR；修 bug、补测试、还技术债优先。


