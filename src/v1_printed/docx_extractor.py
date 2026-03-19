"""
DOCX(Word) 파일에서 python-docx를 사용하여 텍스트와 표를 직접 추출
"""
import os
import sys
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.table_formatter import table_to_markdown


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
    image_paths = []

    # 이미지 추출
    if image_output_dir:
        os.makedirs(image_output_dir, exist_ok=True)
        img_idx = 0
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                img_idx += 1
                image_data = rel.target_part.blob
                ext = os.path.splitext(rel.target_part.partname)[1]
                img_filename = f"image_{img_idx:03d}{ext}"
                img_save_path = os.path.join(image_output_dir, img_filename)
                with open(img_save_path, "wb") as f:
                    f.write(image_data)
                image_paths.append(img_save_path)

    # 본문의 요소 순서를 유지하며 텍스트/표 추출
    body = doc.element.body
    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            # 문단 (paragraph)
            para = child
            text_parts = []
            for run in para.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r"):
                t = run.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                if t is not None and t.text:
                    text_parts.append(t.text)
            line = "".join(text_parts).strip()
            if line:
                # 스타일 기반 헤딩 감지
                ppr = para.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr")
                if ppr is not None:
                    pstyle = ppr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle")
                    if pstyle is not None:
                        style_val = pstyle.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
                        if "Heading1" in style_val or "heading1" in style_val or "1" == style_val:
                            line = f"# {line}"
                        elif "Heading2" in style_val or "heading2" in style_val or "2" == style_val:
                            line = f"## {line}"
                        elif "Heading3" in style_val or "heading3" in style_val:
                            line = f"### {line}"
                full_text_parts.append(line)

        elif tag == "tbl":
            # 표 (table)
            table_data = []
            for tr in child.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"):
                row = []
                for tc in tr.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"):
                    cell_texts = []
                    for p in tc.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                        for run in p.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r"):
                            t = run.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                            if t is not None and t.text:
                                cell_texts.append(t.text)
                    row.append(" ".join(cell_texts).strip())
                table_data.append(row)

            md = table_to_markdown(table_data)
            if md:
                table_md_list.append(md)
                full_text_parts.append(f"\n{md}\n")

    # DOCX는 페이지 개념이 명확하지 않으므로 단일 페이지로 반환
    page_data = {
        "page_num": 1,
        "text": "\n".join(full_text_parts),
        "tables": table_md_list,
        "images": image_paths,
    }

    print(f"📝 DOCX 추출 완료: text={len(page_data['text'])}chars, tables={len(table_md_list)}, images={len(image_paths)}")
    return [page_data]


if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) < 2:
        print("Usage: python docx_extractor.py <file.docx>")
        exit()
    result = extract_docx(_sys.argv[1])
    print(result[0]["text"][:500])
