"""
DOCX(Word) 파일에서 python-docx를 사용하여 텍스트와 표를 직접 추출
"""
import os
import logging

from docx import Document

from ..common.table_formatter import table_to_markdown

logger = logging.getLogger(__name__)

_WML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def extract_docx(docx_path: str, image_output_dir: str = None) -> list:
    """
    DOCX 파일에서 텍스트, 표, 이미지를 추출

    Args:
        docx_path: DOCX 파일 경로
        image_output_dir: 이미지 저장 디렉토리 (None이면 이미지 추출 안함)

    Returns:
        [{"page_num": 1, "text": "...", "tables": ["md_table", ...], "images": [...]}, ...]
    """
    doc = Document(docx_path)

    full_text_parts = []
    table_md_list = []
    image_paths = _extract_images(doc, image_output_dir)

    body = doc.element.body
    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            line = _extract_paragraph(child)
            if line:
                full_text_parts.append(line)

        elif tag == "tbl":
            md = _extract_table(child)
            if md:
                table_md_list.append(md)
                full_text_parts.append(f"\n{md}\n")

    page_data = {
        "page_num": 1,
        "text": "\n".join(full_text_parts),
        "tables": table_md_list,
        "images": image_paths,
    }

    logger.info(
        "DOCX 추출 완료: text=%d chars, tables=%d, images=%d",
        len(page_data["text"]), len(table_md_list), len(image_paths),
    )
    return [page_data]


def _extract_images(doc: Document, output_dir: str | None) -> list[str]:
    if not output_dir:
        return []

    os.makedirs(output_dir, exist_ok=True)
    paths = []
    img_idx = 0

    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            img_idx += 1
            image_data = rel.target_part.blob
            ext = os.path.splitext(rel.target_part.partname)[1]
            img_filename = f"image_{img_idx:03d}{ext}"
            img_save_path = os.path.join(output_dir, img_filename)
            with open(img_save_path, "wb") as f:
                f.write(image_data)
            paths.append(img_save_path)

    return paths


def _extract_paragraph(para_elem) -> str | None:
    """문단 XML에서 텍스트를 추출하고 헤딩 마크다운 적용"""
    text_parts = []
    for run in para_elem.findall(f".//{{{_WML_NS}}}r"):
        t = run.find(f"{{{_WML_NS}}}t")
        if t is not None and t.text:
            text_parts.append(t.text)

    line = "".join(text_parts).strip()
    if not line:
        return None

    ppr = para_elem.find(f"{{{_WML_NS}}}pPr")
    if ppr is not None:
        pstyle = ppr.find(f"{{{_WML_NS}}}pStyle")
        if pstyle is not None:
            style_val = pstyle.get(f"{{{_WML_NS}}}val", "")
            heading_map = {
                "Heading1": "# ", "heading1": "# ", "1": "# ",
                "Heading2": "## ", "heading2": "## ",
                "Heading3": "### ", "heading3": "### ",
            }
            for key, prefix in heading_map.items():
                if key in style_val or key == style_val:
                    line = f"{prefix}{line}"
                    break

    return line


def _extract_table(tbl_elem) -> str | None:
    """표 XML에서 마크다운 표 문자열을 생성"""
    table_data = []
    for tr in tbl_elem.findall(f".//{{{_WML_NS}}}tr"):
        row = []
        for tc in tr.findall(f"{{{_WML_NS}}}tc"):
            cell_texts = []
            for p in tc.findall(f".//{{{_WML_NS}}}p"):
                for run in p.findall(f".//{{{_WML_NS}}}r"):
                    t = run.find(f"{{{_WML_NS}}}t")
                    if t is not None and t.text:
                        cell_texts.append(t.text)
            row.append(" ".join(cell_texts).strip())
        table_data.append(row)

    md = table_to_markdown(table_data)
    return md if md else None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.v1_printed.docx_extractor <file.docx>")
        exit()
    result = extract_docx(sys.argv[1])
    print(result[0]["text"][:500])
