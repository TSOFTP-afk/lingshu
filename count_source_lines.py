"""统计项目自有源代码行数（精确排除第三方/打包产物）。"""
from pathlib import Path

# 项目自有源代码目录
include_dirs = {
    'novel_app', 'lingshu_api', 'electron', 'packaging',
    'admin-web', 'cloud-admin', 'lingshu-app', 'lingjing-app',
}

# 排除目录（第三方库、打包产物、运行时、构建工具、缓存）
exclude_dirs = {
    '.git', '.vscode', '__pycache__', 'node_modules', '.venv', 'venv', 'env',
    'dist', 'build', '.idea', 'docs', 'tests', 'test', 'release',
    'vendor', '.codex-runtime', '.pytest_cache', '.ruff_cache', '.build_tools',
    '.github', 'showcase', 'data', 'tools', 'assets', 'public',
}

include_exts = {'.py', '.js', '.ts', '.tsx', '.jsx', '.vue', '.html', '.css', '.scss', '.cs'}

root = Path(r'f:\项目\灵枢')
total_lines = 0
non_blank_total = 0
file_count = 0
file_stats = []

for path in root.rglob('*'):
    if not path.is_file():
        continue
    # 必须在项目自有目录下
    try:
        rel = path.relative_to(root)
        rel_str = str(rel).replace('\\', '/')
    except ValueError:
        continue
    # 取第一级目录
    parts = rel.parts
    if not parts:
        continue
    first_part = parts[0]
    # 排除目录
    if any(part in exclude_dirs for part in parts):
        continue
    # 只统计项目自有源代码目录（或根目录下的源文件）
    if first_part not in include_dirs and first_part not in {'main.py'}:
        # 根目录下的源文件单独判断
        if len(parts) == 1 and path.suffix in include_exts:
            pass
        else:
            continue
    if path.suffix.lower() not in include_exts:
        continue
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        non_blank = sum(1 for l in lines if l.strip())
        total_lines += len(lines)
        non_blank_total += non_blank
        file_count += 1
        file_stats.append((str(rel), len(lines), non_blank))
    except Exception:
        pass

print(f'项目自有源代码文件数: {file_count}')
print(f'总行数（含空行）: {total_lines}')
print(f'总行数（非空）: {non_blank_total}')
print()
print('=== 按行数排序 Top 40 ===')
file_stats.sort(key=lambda x: -x[1])
for i, (name, lines, non_blank) in enumerate(file_stats[:40], 1):
    print(f'{i:2d}. {lines:5d} 行 (非空 {non_blank:4d}) - {name}')

print()
print('=== 按模块统计 ===')
module_stats = {}
for name, lines, non_blank in file_stats:
    module = name.split('/')[0] if '/' in name else '(root)'
    if module not in module_stats:
        module_stats[module] = [0, 0, 0]
    module_stats[module][0] += 1
    module_stats[module][1] += lines
    module_stats[module][2] += non_blank

for module, (fc, tl, nb) in sorted(module_stats.items(), key=lambda x: -x[1][1]):
    print(f'{module:20s}: {fc:4d} 文件, {tl:6d} 行 (非空 {nb:6d})')

print()
print('=== 判定 ===')
if non_blank_total >= 3000:
    print(f'非空总行数 {non_blank_total} >= 3000，需提交前 30 页 + 后 30 页（共 60 页）')
else:
    print(f'非空总行数 {non_blank_total} < 3000，提交全部源代码')
