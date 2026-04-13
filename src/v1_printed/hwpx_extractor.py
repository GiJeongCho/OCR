"""
HWPX 파일에서 텍스트와 표를 추출
HWPX는 ZIP 포맷으로, 내부에 XML(OWPML) 파일을 포함

표 처리 전략:
  - XML 트리를 문서 순서대로 재귀 순회
  - <tbl> 발견 시 마크다운 표로 변환하여 text에 인라인 삽입
  - <tbl> 내부의 <p>는 본문 텍스트로 추출하지 않음 (셀 텍스트 중복 방지)
"""
import zipfile
import logging

from lxml import etree

from ..common.table_formatter import table_to_markdown

logger = logging.getLogger(__name__)


def _tag_name(elem) -> str:
    """XML 요소의 로컬 태그 이름 추출 (네임스페이스 제거)"""
    tag = elem.tag
    return tag.split("}")[-1] if "}" in tag else tag


def _extract_text_from_element(elem):
    """XML 요소에서 텍스트를 재귀적으로 추출 (표 요소는 건너뜀)"""
    texts = []
    if elem.text:
        texts.append(elem.text)
    for child in elem:
        tag = _tag_name(child)
        if tag == "t":
            if child.text:
                texts.append(child.text)
        elif tag in ("run", "r"):
            texts.extend(_extract_text_from_element(child))
        elif tag in ("lineseg", "tbl"):
            continue
        else:
            texts.extend(_extract_text_from_element(child))
        if child.tail:
            texts.append(child.tail)
    return texts


def _find_section_files(zf: zipfile.ZipFile) -> list:
    """HWPX ZIP 내의 section XML 파일들을 찾기"""
    section_files = [
        name for name in zf.namelist()
        if "section" in name.lower() and name.lower().endswith(".xml")
    ]
    section_files.sort()
    return section_files


def _extract_table(tbl_elem) -> list:
    """표 XML 요소에서 2D 리스트 추출"""
    table_data = []
    tr_elems = [c for c in tbl_elem if _tag_name(c) == "tr"]
    if not tr_elems:
        tr_elems = [
            e for e in tbl_elem.iter()
            if e is not tbl_elem and _tag_name(e) == "tr"
        ]

    for tr in tr_elems:
        row = []
        for cell_elem in tr:
            if _tag_name(cell_elem) == "tc":
                cell_texts = _extract_text_from_element(cell_elem)
                row.append(" ".join(cell_texts).strip())
        if row:
            table_data.append(row)
    return table_data


def _walk_body(elem, text_parts, table_md_list):
    """
    XML 트리를 문서 순서대로 순회하며 텍스트와 표를 text_parts에 인라인 삽입.
    <tbl> 내부의 <p>는 _extract_table에서 별도로 처리하므로 중복 방지.
    """
    tag = _tag_name(elem)

    if tag == "tbl":
        table_data = _extract_table(elem)
        if table_data:
            md = table_to_markdown(table_data)
            if md:
                table_md_list.append(md)
                text_parts.append(f"\n{md}\n")
        return

    if tag == "p":
        has_tbl = any(_tag_name(d) == "tbl" for d in elem.iter() if d is not elem)
        if has_tbl:
            for child in elem:
                _walk_body(child, text_parts, table_md_list)
        else:
            para_texts = _extract_text_from_element(elem)
            line = "".join(para_texts).strip()
            if line:
                text_parts.append(line)
        return

    for child in elem:
        _walk_body(child, text_parts, table_md_list)


def extract_hwpx(hwpx_path: str) -> list:
    """
    HWPX 파일에서 텍스트와 표를 추출 (pageBreak 속성으로 페이지 분리)

    Returns:
        [{"page_num": 1, "text": "...(표 인라인 포함)", "tables": [...], "images": []}, ...]
    """
    if not zipfile.is_zipfile(hwpx_path):
        raise ValueError(f"유효한 HWPX(ZIP) 파일이 아닙니다: {hwpx_path}")

    pages_result = []
    total_page_num = 0

    with zipfile.ZipFile(hwpx_path, "r") as zf:
        section_files = _find_section_files(zf)

        if not section_files:
            logger.warning("section XML을 찾을 수 없습니다. 파일 목록: %s", zf.namelist()[:10])
            return pages_result

        for sec_file in section_files:
            try:
                with zf.open(sec_file) as f:
                    tree = etree.parse(f)
                    root = tree.getroot()

                cur_text = []
                cur_tables = []

                for child in root:
                    pb = child.get("pageBreak", "0")
                    if pb == "1" and (cur_text or cur_tables):
                        total_page_num += 1
                        pages_result.append({
                            "page_num": total_page_num,
                            "text": "\n".join(cur_text),
                            "tables": cur_tables,
                            "images": [],
                        })
                        cur_text = []
                        cur_tables = []

                    _walk_body(child, cur_text, cur_tables)

                if cur_text or cur_tables:
                    total_page_num += 1
                    pages_result.append({
                        "page_num": total_page_num,
                        "text": "\n".join(cur_text),
                        "tables": cur_tables,
                        "images": [],
                    })

            except Exception as e:
                logger.warning("Section %s 파싱 오류: %s", sec_file, e)

    logger.info(
        "HWPX 추출: %d페이지, tables=%d",
        total_page_num, sum(len(p["tables"]) for p in pages_result),
    )
    return pages_result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.v1_printed.hwpx_extractor <file.hwpx>")
        exit()
    result = extract_hwpx(sys.argv[1])
    for p in result:
        print(f"\n--- Section {p['page_num']} ---")
        print(p["text"][:500])
