#requires -Version 5.1
# NOTE: 本文件必须以「UTF-8 with BOM」编码保存——Windows PowerShell 5.1 依赖 BOM
#       正确解析脚本内的中文路径字面量（无 BOM 时将按 ANSI 读取导致路径错乱）。
<#
.SYNOPSIS
  灵枢仓库废旧文件归档迁移脚本（只移不删、幂等、支持 -WhatIf 预演）。

.DESCRIPTION
  - 将仓库根目录散落的废弃文件逐一 Move-Item 到 _attic/<类别>/ 下；
  - 0 字节的根目录 novels.db 直接删除（非 0 字节则告警跳过）；
  - 空残留目录（_MEI129842、tmp_focus_test_x_86qp3w、codex_key）仅在确能删除
    （即确为空且无 ACL 阻碍）时 Remove-Item，失败则告警保留；
  - 幂等：源不存在（已归档过）则跳过；_attic 目标已存在同名项则告警跳过；
  - 所有路径相对仓库根，仓库根由 $PSScriptRoot 推导，无硬编码绝对路径；
  - 脚本开头打印完整计划，结尾打印汇总。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\archive_cleanup.ps1 -WhatIf   # 预演
  powershell -ExecutionPolicy Bypass -File tools\archive_cleanup.ps1           # 执行
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'

# ---- 仓库根：由脚本自身位置推导（本脚本位于 <仓库根>/tools/ 下）----
$RepoRoot  = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$AtticRoot = Join-Path $RepoRoot '_attic'

# ---- 迁移计划：原路径（相对仓库根） -> _attic/<Category>/<Name> ----
$MovePlan = @(
    @{ Category = 'oneoff-scripts';   Name = '_cancel.py' },
    @{ Category = 'junk';             Name = 'index.html' },
    @{ Category = 'legacy-packaging'; Name = 'build_pc_v2_preview.ps1' },
    @{ Category = 'legacy-packaging'; Name = 'build_v2_preview.ps1' },
    @{ Category = 'oneoff-scripts';   Name = 'count_source_lines.py' },
    @{ Category = 'oneoff-scripts';   Name = 'generate_copyright_pdf.py' },
    @{ Category = 'oneoff-scripts';   Name = 'verify_pdf.py' },
    @{ Category = 'legacy-docs';      Name = '技能-全项目总索引.md' },
    @{ Category = 'legacy-docs';      Name = 'DATABASE_CHANGES.md' },
    @{ Category = 'competition';      Name = 'TRAE参赛提交文档.md' },
    @{ Category = 'competition';      Name = '报名文档_灵枢.txt' },
    @{ Category = 'competition';      Name = '灵枢-灵爻发展规划.docx' },
    @{ Category = 'reports';          Name = '同类型项目对比报告.docx' },
    @{ Category = 'reports';          Name = '网络小说行业分析报告.docx' },
    @{ Category = 'reports';          Name = '社区反馈报告.docx' },
    @{ Category = 'reports';          Name = 'security_best_practices_report.md' },
    @{ Category = 'media';            Name = '灵枢形象.jpg' },
    @{ Category = 'legacy-packaging'; Name = '.build_tools' }
)

# ---- 仅当 0 字节时才允许删除的文件 ----
$DeleteEmptyFiles = @('novels.db')

# ---- 仅当确能删除（空且无 ACL 阻碍）时才删除的残留目录 ----
$DeleteEmptyDirs = @('_MEI129842', 'tmp_focus_test_x_86qp3w', 'codex_key')

$stats = @{
    Planned      = $MovePlan.Count
    Moved        = 0
    SkipMissing  = 0
    SkipConflict = 0
    DelFiles     = 0
    DelDirs      = 0
    DirKept      = 0
}

$whatIf = [bool]$WhatIfPreference
$tag    = if ($whatIf) { '[WhatIf] ' } else { '' }

Write-Host ''
Write-Host '====================================================' -ForegroundColor Green
Write-Host '  灵枢 · 废旧文件归档清理 (tools/archive_cleanup.ps1)' -ForegroundColor Green
Write-Host "  仓库根 : $RepoRoot"
Write-Host "  归档区 : _attic\<类别>\ （只移不删）"
if ($whatIf) { Write-Host '  模式   : WhatIf 预演——不会真实改动任何文件' -ForegroundColor Yellow }
Write-Host '===================================================='
Write-Host ''

# ---------- 打印计划 ----------
Write-Host ("--- 迁移计划：{0} 项 ---" -f $stats.Planned)
foreach ($item in $MovePlan) {
    Write-Host ("  [{0}] {1}" -f $item.Category, $item.Name)
}
Write-Host '--- 硬删计划（仅限无内容项）---'
foreach ($name in $DeleteEmptyFiles) { Write-Host "  [空文件] $name （仅当 0 字节）" }
foreach ($name in $DeleteEmptyDirs)  { Write-Host "  [空目录] $name （仅当确为空且可删）" }
Write-Host ''

# ---------- 执行迁移 ----------
foreach ($item in $MovePlan) {
    $name    = $item.Name
    $src     = Join-Path $RepoRoot $name
    $destDir = Join-Path $AtticRoot $item.Category
    $dest    = Join-Path $destDir $name

    if (-not (Test-Path -LiteralPath $src)) {
        Write-Host "  SKIP（源不存在，可能已归档）: $name" -ForegroundColor DarkGray
        $stats.SkipMissing++
        continue
    }
    if (Test-Path -LiteralPath $dest) {
        Write-Warning "  SKIP（_attic 目标已存在同名项，请人工核对）: $dest"
        $stats.SkipConflict++
        continue
    }
    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Move-Item -LiteralPath $src -Destination $dest
    Write-Host ("  {0}MOVED: {1} -> _attic/{2}/" -f $tag, $name, $item.Category) -ForegroundColor Green
    $stats.Moved++
}

# ---------- 删除 0 字节空文件 ----------
foreach ($name in $DeleteEmptyFiles) {
    $path = Join-Path $RepoRoot $name
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "  SKIP（文件不存在）: $name" -ForegroundColor DarkGray
        continue
    }
    $length = (Get-Item -LiteralPath $path).Length
    if ($length -ne 0) {
        Write-Warning "  SKIP（非 0 字节，拒绝删除）: $name（$length bytes）"
        continue
    }
    Remove-Item -LiteralPath $path -Force
    Write-Host ("  {0}DELETED 空文件: {1}" -f $tag, $name) -ForegroundColor Green
    $stats.DelFiles++
}

# ---------- 删除空残留目录（尽力而为，失败即保留） ----------
foreach ($name in $DeleteEmptyDirs) {
    $path = Join-Path $RepoRoot $name
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "  SKIP（目录不存在）: $name" -ForegroundColor DarkGray
        continue
    }
    try {
        # 不带 -Recurse：非空目录或 ACL 受限时直接抛错 -> 走告警保留，绝不递归硬删
        Remove-Item -LiteralPath $path -Force -ErrorAction Stop
        Write-Host ("  {0}DELETED 空目录: {1}" -f $tag, $name) -ForegroundColor Green
        $stats.DelDirs++
    } catch {
        Write-Warning "  KEEP（目录非空或权限受限，予以保留）: $name — $($_.Exception.Message)"
        $stats.DirKept++
    }
}

# ---------- 汇总 ----------
$movedLabel = if ($whatIf) { '预演迁移' } else { '已迁移' }
Write-Host ''
Write-Host '==================== 归档汇总 ====================' -ForegroundColor Green
Write-Host ("  计划迁移        : {0}" -f $stats.Planned)
Write-Host ("  {0}          : {1}" -f $movedLabel, $stats.Moved)
Write-Host ("  跳过（源不存在）: {0}" -f $stats.SkipMissing)
Write-Host ("  跳过（目标冲突）: {0}" -f $stats.SkipConflict)
Write-Host ("  删除空文件      : {0}" -f $stats.DelFiles)
Write-Host ("  删除空目录      : {0}" -f $stats.DelDirs)
Write-Host ("  目录保留（异常）: {0}" -f $stats.DirKept)
if ($whatIf) {
    Write-Host '  以上为 WhatIf 预演结果，未实际改动任何文件。' -ForegroundColor Yellow
} else {
    Write-Host '  提示: 被迁移文件若此前已被 git 跟踪，请运行 git add -A 让 git 记录为重命名。' -ForegroundColor Cyan
}
Write-Host '=================================================='
