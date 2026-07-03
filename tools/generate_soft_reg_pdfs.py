"""生成软著申请 PDF 材料 — 修复版。

修正：
  1. 源代码 PDF 页眉使用中文字体
  2. 源代码精确控制在 60 页（3000 行，每页 50 行）
  3. 文档 PDF 页眉使用中文字体
"""
from __future__ import annotations

import os
from pathlib import Path

from fpdf import FPDF

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs" / "软著申请材料"
SOFTWARE_NAME = "灵枢智能写作工作台软件"
VERSION = "V3.0"

_WIN_FONT_DIR = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
_SIMSUN = _WIN_FONT_DIR / "simsun.ttc"
_MSYH = _WIN_FONT_DIR / "msyh.ttc"
_MSYHBD = _WIN_FONT_DIR / "msyhbd.ttc"
_CONSOLA = _WIN_FONT_DIR / "consola.ttf"

_has_cjk = _MSYH.exists()
_has_mono = _CONSOLA.exists()


def _add_fonts(pdf: FPDF):
    if _MSYH.exists():
        pdf.add_font("CJK", "", str(_MSYH))
    if _MSYHBD.exists():
        pdf.add_font("CJKB", "", str(_MSYHBD))
    if _CONSOLA.exists():
        pdf.add_font("Mono", "", str(_CONSOLA))


class SourcePDF(FPDF):
    def __init__(self, lpp: int = 50):
        super().__init__("P", "mm", "A4")
        self.lpp = lpp
        self.count = 0
        _add_fonts(self)

    def header(self):
        # 页眉用中文字体
        hf = "CJK" if _has_cjk else "Helvetica"
        self.set_font(hf, "", 9)
        self.cell(0, 5, f"{SOFTWARE_NAME} {VERSION}", align="L")
        self.cell(0, 5, str(self.page_no()), align="R", new_x="LMARGIN", new_y="NEXT")
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.count = 0

    def footer(self):
        self.set_y(-10)
        hf = "CJK" if _has_cjk else "Helvetica"
        self.set_font(hf, "", 7)
        self.cell(0, 5, f"- {self.page_no()} -", align="C")

    def _emit(self, text: str, font_size: int = 7, line_h: float = 3.5):
        """写入一行，精确计数。"""
        if self.count >= self.lpp:
            self.add_page()
            self.count = 0
        self.set_font("Mono" if _has_mono else "Courier", "", font_size)
        self.cell(0, line_h, text[:120], new_x="LMARGIN", new_y="NEXT")
        self.count += 1

    def pad_last_page(self):
        while self.count > 0 and self.count < self.lpp:
            self._emit(" ")


class DocPDF(FPDF):
    def __init__(self, lpp: int = 30):
        super().__init__("P", "mm", "A4")
        self.lpp = lpp
        self.count = 0
        _add_fonts(self)

    def header(self):
        hf = "CJK" if _has_cjk else "Helvetica"
        self.set_font(hf, "", 9)
        self.cell(0, 6, f"{SOFTWARE_NAME} {VERSION}", align="L")
        self.cell(0, 6, str(self.page_no()), align="R", new_x="LMARGIN", new_y="NEXT")
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)
        self.count = 0

    def footer(self):
        self.set_y(-12)
        hf = "CJK" if _has_cjk else "Helvetica"
        self.set_font(hf, "", 8)
        self.cell(0, 6, f"- {self.page_no()} -", align="C")

    def _emit(self, text: str):
        if self.count >= self.lpp:
            self.add_page()
            self.count = 0
        hf = "CJK" if _has_cjk else "Helvetica"
        self.set_font(hf, "", 8)
        self.cell(0, 5.5, text[:150], new_x="LMARGIN", new_y="NEXT")
        self.count += 1

    def pad_last_page(self):
        while self.count > 0 and self.count < self.lpp:
            self._emit(" ")


def generate_source_pdf(src_txt: Path, out_pdf: Path):
    """生成源代码 PDF，精确 60 页。"""
    with open(src_txt, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()

    # 精确取 3000 行（60 页 × 50 行/页），去掉首部说明行算入内容行
    LPP = 50
    target = 60 * LPP  # 3000
    contents = all_lines[:target]

    pdf = SourcePDF(LPP)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    for line in contents:
        pdf._emit(line.rstrip("\n\r") or " ")

    pdf.pad_last_page()
    pdf.output(str(out_pdf))
    print(f"  ✓ 源代码 PDF: {out_pdf.name} ({pdf.page_no()} 页, {LPP} 行/页)")


def generate_doc_pdf(md_path: Path, out_pdf: Path):
    """生成文档 PDF。"""
    pdf = DocPDF(30)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    with open(md_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            pdf._emit(line.rstrip("\n\r") or " ")

    pdf.pad_last_page()
    pdf.output(str(out_pdf))
    print(f"  ✓ 文档 PDF: {out_pdf.name} ({pdf.page_no()} 页)")


def main():
    print("=== 生成软著 PDF 材料 ===\n")

    generate_source_pdf(
        DOCS_DIR / "01-源代码（前30页+后30页）.txt",
        DOCS_DIR / "01-源代码（前30页+后30页）.pdf",
    )

    generate_doc_pdf(
        DOCS_DIR / "02-软件设计说明书.md",
        DOCS_DIR / "02-软件设计说明书.pdf",
    )

    generate_doc_pdf(
        DOCS_DIR / "03-核心算法汇编.md",
        DOCS_DIR / "03-核心算法汇编.pdf",
    )

    print(f"\nPDF 输出目录: {DOCS_DIR}")


if __name__ == "__main__":
    main()
