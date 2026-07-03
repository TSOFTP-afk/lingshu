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

