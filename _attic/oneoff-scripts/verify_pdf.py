"""验证生成的软著 PDF 是否符合规范。

注意：pypdf 的 extract_text() 会丢失空行，无法准确统计实际渲染行数。
实际每页渲染行数（含空行）由 generate_copyright_pdf.py 在生成时统计，
每页稳定 55 行（最少 50 行），满足软著 >=50 行/页 的硬性要求。
"""
from pathlib import Path

try:
    import pypdf
except ImportError:
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pypdf", "-q"])
    import pypdf

pdf_path = Path(r'f:\项目\灵枢\docs\软著申请材料\灵枢源代码-60页.pdf')
reader = pypdf.PdfReader(str(pdf_path))
page_count = len(reader.pages)
print(f'文件: {pdf_path.name}')
print(f'文件大小: {pdf_path.stat().st_size / 1024:.1f} KB')
print(f'总页数: {page_count} (要求: 60)')
print(f'页数验证: {"[OK]" if page_count == 60 else "[FAIL]"}')

# 验证关键内容
print(f'\n=== 内容验证 ===')
full_text = ""
for page in reader.pages:
    full_text += page.extract_text() + "\n"

checks = [
    ('程序入口 main.py', 'main.py' in full_text),
    ('API入口 lingshu_api/main.py', 'lingshu_api/main.py' in full_text),
    ('核心算法 mention_extractor', 'mention_extractor' in full_text),
    ('核心算法 coreference', 'coreference' in full_text),
    ('核心算法 semantic_chunker', 'semantic_chunker' in full_text),
    ('核心算法 memory_window', 'memory_window' in full_text),
    ('中间省略标记', '中间部分源代码已省略' in full_text),
    ('程序结束标志', '（程序结束）' in full_text),
    ('软件名称', '灵枢智能写作工作台软件 V3.0' in full_text),
]

all_ok = True
for name, ok in checks:
    print(f'  {"[OK]" if ok else "[FAIL]"} {name}')
    if not ok:
        all_ok = False

# 验证核心算法在前30页
print(f'\n=== 核心算法位置验证（前30页）===')
front_text = ""
for i in range(min(30, page_count)):
    front_text += reader.pages[i].extract_text() + "\n"

front_checks = [
    ('mention_extractor 在前30页', 'mention_extractor' in front_text),
    ('coreference 在前30页', 'coreference' in front_text),
    ('semantic_chunker 在前30页', 'semantic_chunker' in front_text),
    ('memory_window 在前30页', 'memory_window' in front_text),
]

for name, ok in front_checks:
    print(f'  {"[OK]" if ok else "[FAIL]"} {name}')
    if not ok:
        all_ok = False

print(f'\n=== 总结 ===')
if all_ok and page_count == 60:
    print('[OK] PDF 符合软著申请要求：60页（前30+后30），核心算法在前30页，内容完整')
else:
    print('[FAIL] PDF 存在不达标项，请检查')
