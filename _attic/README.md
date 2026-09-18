# _attic — 废旧文件归档区

> **归档执行日期**：2026-09-18（由 `tools/archive_cleanup.ps1` 一次性生成本目录结构）
>
> **归档原则**：本仓库 git 历史不可靠——本地仓库仅 2 个提交（2026-09 初始化），三代技术栈
> （PyQt6 → PyInstaller → Electron/云端）更迭期间的大量文件从未纳入版本控制。
> 因此本次清理执行「**只移不删**」：除 0 字节空文件与确认为空的残留目录外，
> 任何有内容的文件一律移动至本目录对应类别下保存，随时可手工找回；
> 不做任何 `git rm` 或不可恢复删除。

## 执行方式

```powershell
# 预演（不改动任何文件）
powershell -ExecutionPolicy Bypass -File tools\archive_cleanup.ps1 -WhatIf
# 实际执行（幂等，可重复运行）
powershell -ExecutionPolicy Bypass -File tools\archive_cleanup.ps1
```

执行后如提示有被 git 跟踪的文件被移动，运行 `git add -A` 让 git 记录为重命名。
注意：`tools/archive_cleanup.ps1` 必须以 **UTF-8 with BOM** 编码保存（Windows PowerShell 5.1 依赖 BOM 解析中文路径字面量）。

## 归档清单（18 项迁移 + 4 项硬删）

| 原路径 | 归档路径 | 类别 | 一句话理由 + 证据 |
|---|---|---|---|
| `_cancel.py` | `_attic/oneoff-scripts/_cancel.py` | oneoff-scripts | 一次性修数脚本：把 `analysis_runs` 置为 cancelled（内嵌写死备注文字）；全仓无任何引用 |
| `index.html` | `_attic/junk/index.html` | junk | 误留仓库根的 Vite 构建产物：引用 `/assets/index-9hiSTpI2.js` 等哈希文件而根目录无 `assets/`；lingshu-app/electron 均使用各自目录的 index.html |
| `build_pc_v2_preview.ps1` | `_attic/legacy-packaging/build_pc_v2_preview.ps1` | legacy-packaging | v2.0-preview 时代打包入口，仅转发 `build_electron.ps1`；全仓仅旧文档 `docs/打包流程.md` 提及 |
| `build_v2_preview.ps1` | `_attic/legacy-packaging/build_v2_preview.ps1` | legacy-packaging | v2.0-preview 时代「Web 书城 + 桌面端」打包入口；全仓仅旧文档 `docs/打包流程.md` 提及 |
| `count_source_lines.py` | `_attic/oneoff-scripts/count_source_lines.py` | oneoff-scripts | 统计源码行数的一次性脚本；全仓无引用 |
| `generate_copyright_pdf.py` | `_attic/oneoff-scripts/generate_copyright_pdf.py` | oneoff-scripts | 旧版软著 PDF 生成器（扫描源码拼 60 页文本）；软著材料已由 `docs/软著申请材料/generate_pdf.py` 接管 |
| `verify_pdf.py` | `_attic/oneoff-scripts/verify_pdf.py` | oneoff-scripts | 上述旧软著 PDF 的配套校验脚本；全仓无引用 |
| `技能-全项目总索引.md` | `_attic/legacy-docs/技能-全项目总索引.md` | legacy-docs | 2026-05-30 的本机外部路径索引（`C:\Users\...\Desktop\skill库\`），与仓库代码无关；全仓无引用 |
| `DATABASE_CHANGES.md` | `_attic/legacy-docs/DATABASE_CHANGES.md` | legacy-docs | hybrid-database-architecture spec（07-02~07-03）的一次性实施记录，任务闭环后不再更新；全仓无引用 |
| `TRAE参赛提交文档.md` | `_attic/competition/TRAE参赛提交文档.md` | competition | TRAE 比赛提交文档（06-29）；无现役引用 |
| `报名文档_灵枢.txt` | `_attic/competition/报名文档_灵枢.txt` | competition | 比赛报名文本（06-20）；无现役引用 |
| `灵枢-灵爻发展规划.docx` | `_attic/competition/灵枢-灵爻发展规划.docx` | competition | 灵爻-灵枢发展企划（06-24）；同主题文本版 `docs/规划/灵爻-灵枢发展企划书.txt` 已留存 |
| `同类型项目对比报告.docx` | `_attic/reports/同类型项目对比报告.docx` | reports | 行业对比报告（06-02）；无现役引用 |
| `网络小说行业分析报告.docx` | `_attic/reports/网络小说行业分析报告.docx` | reports | 行业分析报告（06-02）；`docs/规划/` 存有同名副本，归档后以 docs 份为唯一副本 |
| `社区反馈报告.docx` | `_attic/reports/社区反馈报告.docx` | reports | 反馈报告（06-02）；`docs/规划/` 存有同名副本，归档后以 docs 份为唯一副本 |
| `security_best_practices_report.md` | `_attic/reports/security_best_practices_report.md` | reports | 生成报告：`.gitignore` 第 32 行明确将其列为「生成报告」忽略项 |
| `灵枢形象.jpg` | `_attic/media/灵枢形象.jpg` | media | 形象图（06-08）；全仓代码/文档/配置均无引用 |
| `.build_tools/` | `_attic/legacy-packaging/.build_tools/` | legacy-packaging | PyInstaller 6.20 时代本地依赖库（pefile/altgraph/hooks_contrib，04-26~06-08）；现役脚本零引用（`pytest.ini` norecursedirs 仅为排除规则；正式 PyInstaller 依赖来自 requirements-dev.txt） |

**硬删 4 项（无内容，符合红线）**：

| 原路径 | 类别 | 理由 |
|---|---|---|
| `novels.db`（0 字节） | junk | 空文件；全部现役代码一律使用 `data/novels.db`（如 `novel_app/database.py:173`），根目录这份系某次 cwd 不对时 `sqlite3.connect` 误建 |
| `_MEI129842/` | junk | PyInstaller onefile 运行残留目录（04-26，`.gitignore` 有 `_MEI*/` 规则）；目录 ACL 受限无法列内容，脚本仅在确能删除时删除，否则告警保留 |
| `tmp_focus_test_x_86qp3w/` | junk | pytest 残留临时目录（04-26，`.gitignore` 有 `tmp_focus_test*/` 规则）；同上处理 |
| `codex_key/` | junk | 清单外发现：完全空目录（06-16）；仅当确认为空时删除 |

## 核实后判定「保留」的项目（有现役引用或活跃维护）

| 路径 | 保留原因（引用位置） |
|---|---|
| `灵枢.spec` | 被 `test_core_modules.py:687`（`TestPackagingScripts`）无条件读取并断言内容；该文件在 `pytest.ini` testpaths，CI 经 `tests/test_runner.py`（= `python -m pytest`）运行。虽是 PyInstaller 时代产物且 hiddenimports 含已弃用的 qdrant_client，但移动即打破现役回归测试 |
| `packaging/Launcher.cs` | 被 `test_core_modules.py:676` 读取断言（`test_launcher_reuses_extracted_runtime_until_payload_changes`）；同上测试链路。系上一代（SimpleAINovelAppLauncher）自解压启动器，待测试重构后方可归档 |
| `packaging/build_first_exe_fast.ps1` | 被 `test_core_modules.py:667` 读取断言（`test_build_script_uses_base_python_and_source_pip`）；同上测试链路 |
| `image_1777455545955.png` | 现役构建输入：`electron/package.json:56` extraResources 将其打包为 `branding/startup.png`；`electron/main.js:44-45` 作为 splash 图片 fallback 路径 |
| `CHANGELOG.md` | 被 `docs/软著申请材料/generate_pdf.py:186` 读取作为软著 PDF 素材；README 未引用但软著流程可能重跑 |
| `ARCHITECTURE.md` | 2026-07-03 仍在维护的全局架构总档（89KB），第 1667 行描述的正是现役 Electron 自解压打包链（csc + payload.zip + app_icon.ico）；非上代文档，建议后续拆分过时章节而非整体归档 |
| `项目描述.txt` | 2026-07-14 编辑（仓库收尾期最后一次编辑的物料），内容为当代技术栈介绍（在线 Demo ling-shu.top）；活跃使用中的介绍文本 |
| `test_core_modules.py`、`test_database_extensions.py`、`test_text_importer.py` | `pytest.ini` testpaths 现役收集；`CONTRIBUTING.md:13` compileall 命令点名 |
| `test_qt_helpers.py` | `conftest.py` QT_TESTS 集合按名管理（`novel_app/qt` 缺失时自动跳过收集）；`CONTRIBUTING.md:13` 点名；属代码文件本轮不动 |
| `CONTRIBUTING.md` | 现役开发流程文档（引用 requirements-dev.txt、pytest、tools/generate_api_docs.py） |
| `packaging/ElectronSelfExtractLauncher.cs`、`packaging/app_icon.ico` | 现役打包链：`build_electron.ps1:26-27` 编译/嵌入；`electron/package.json:61` win.icon |
| `main.py`、`README.md`、`package.json`、`requirements*.txt`、`pytest.ini`、`conftest.py` 等 | 红线文件 / 现役配置，未列入清理 |

## 清单外发现（本轮核实、暂不处理）

- `showcase/index.html`（54KB，06-17）：无任何引用的静态产品展示单页；内容完整精美，建议后续移入 `docs/` 或 `_attic/competition/showcase/`，因不确定是否仍在对外使用，本轮不动。
- 根目录 `__pycache__/`、`.pytest_cache/`：可再生缓存目录（已被 .gitignore 忽略），可在确认无进程占用后直接删除；因「有内容不硬删」原则本轮未处理。
- `.codex-runtime/`、`.trae/`：AI 工具运行时与 spec 配置，保留。
- `docs/规划/` 下存有 `社区反馈报告.docx`、`网络小说行业分析报告.docx`，与本次归档的根目录同名文件互为副本；根目录份归档后，docs 份为唯一副本，无需重复处理。
- `docs/` 内部的遗留文档（Qt迁移Vue技术栈方案.md、打包流程.md、安全检查报告V5、源代码.txt 等）本轮一律不动，处理建议见 `docs/_archive_plan_2026-09.md`。
