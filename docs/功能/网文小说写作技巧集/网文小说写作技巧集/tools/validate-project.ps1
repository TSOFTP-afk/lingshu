$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$readmePath = Join-Path $root 'README.md'

if (-not (Test-Path -LiteralPath $readmePath)) {
    throw "README.md not found: $readmePath"
}

$readme = Get-Content -Raw -Encoding UTF8 -LiteralPath $readmePath
$issues = New-Object System.Collections.Generic.List[string]

# Check README relative links.
$linkMatches = [regex]::Matches($readme, '\[[^\]]+\]\((?!https?://)(?!#)([^)]+)\)')
foreach ($match in $linkMatches) {
    $rawLink = $match.Groups[1].Value
    $pathPart = ($rawLink -split '#')[0]
    if ([string]::IsNullOrWhiteSpace($pathPart)) {
        continue
    }

    $normalized = $pathPart -replace '/', [IO.Path]::DirectorySeparatorChar
    if ($normalized.StartsWith('.' + [IO.Path]::DirectorySeparatorChar)) {
        $normalized = $normalized.Substring(2)
    }

    $target = Join-Path $root $normalized
    if (-not (Test-Path -LiteralPath $target)) {
        $issues.Add("Missing README link target: $rawLink")
    }
}

# Count executable skill docs.
$skillsDir = Join-Path $root 'skills'
$skillCount = 0
if (Test-Path -LiteralPath $skillsDir) {
    $skillCount = @(Get-ChildItem -LiteralPath $skillsDir -Filter 'SKILL-*.md' -File).Count
}

# Count reference docs only under numbered category directories.
$categoryDirs = @(Get-ChildItem -LiteralPath $root -Directory | Where-Object { $_.Name -match '^\d{2}-' })
$referenceCount = @(
    foreach ($dir in $categoryDirs) {
        Get-ChildItem -LiteralPath $dir.FullName -Recurse -Filter '*.md' -File
    }
).Count

# Check indexed skill links point to existing skill docs and count matches.
$indexedSkillLinks = [regex]::Matches($readme, '\]\(\./skills/(SKILL-\d{3}[^)]*\.md)\)')
if ($indexedSkillLinks.Count -ne $skillCount) {
    $issues.Add("README indexed skill count mismatch: indexed=$($indexedSkillLinks.Count), actual=$skillCount")
}

foreach ($match in $indexedSkillLinks) {
    $skillPath = Join-Path $skillsDir $match.Groups[1].Value
    if (-not (Test-Path -LiteralPath $skillPath)) {
        $issues.Add("README references missing skill file: $($match.Groups[1].Value)")
    }
}

# Check indexed reference document count matches numbered category dirs.
$indexedReferenceLinks = [regex]::Matches($readme, '\]\(\./\d{2}-[^)]*\.md\)')
if ($indexedReferenceLinks.Count -ne $referenceCount) {
    $issues.Add("README indexed reference count mismatch: indexed=$($indexedReferenceLinks.Count), actual=$referenceCount")
}

if ($issues.Count -gt 0) {
    Write-Host "Project validation failed:" -ForegroundColor Red
    foreach ($issue in $issues) {
        Write-Host " - $issue"
    }
    exit 1
}

Write-Host "Project validation passed." -ForegroundColor Green
Write-Host "Skills: $skillCount"
Write-Host "Reference docs: $referenceCount"
Write-Host "README relative links: $($linkMatches.Count)"
