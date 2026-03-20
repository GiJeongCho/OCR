"""
디지털 PDF에서 pdfplumber를 사용하여 텍스트와 표를 직접 추출
- 표 영역 텍스트 중복 제거
- 표를 본문 위치에 삽입
- 불완전한 표(세로 텍스트, 병합 셀 등)는 PPStructure로 폴백
"""
import logging

import cv2
import numpy as np
import pdfplumber
import pypdfium2 as pdfium

from ..common.config import *  # noqa: F401
from ..common.table_formatter import table_to_markdown
from ..common.pdf_utils import detect_footer_page_number

logger = logging.getLogger(__name__)

_ppstructure_cache = {}


def is_scanned_pdf(pdf_path: str, sample_pages: int = 3, min_chars: int = 50) -> bool:
    """PDF가 스캔 이미지인지 판별"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_to_check = min(sample_pages, len(pdf.pages))
            for i in range(pages_to_check):
                text = pdf.pages[i].extract_text()
                if text and len(text.strip()) > min_chars:
                    return False
        return True
    except Exception as e:
        logger.warning("PDF 판별 실패: %s", e)
        return True


def _clean_table_data(table_data: list) -> list:
    """표 데이터 정리: 완전히 비어있는 행 제거, None 정리"""
    if not table_data:
        return []

    cleaned = []
    for row in table_data:
        if not row:
            continue
        if any(cell and str(cell).strip() for cell in row):
            cleaned.append(row)

    return cleaned


def _has_usable_table_data(table_data: list) -> bool:
    """
    표 데이터가 마크다운으로 변환 가능한 최소 조건을 충족하는지 확인
    (최소 2행, 3개 이상의 비어있지 않은 셀)
    """
    if not table_data or len(table_data) < 2:
        return False

    non_empty = 0
    for row in table_data:
        for cell in row:
            if cell and str(cell).strip():
                non_empty += 1

    return non_empty >= 3


def _get_page_image(pdf_path, page_index, dpi=200):
    """PDF 페이지를 numpy 이미지로 변환 (PPStructure 폴백용)"""
    pdf_doc = pdfium.PdfDocument(pdf_path)
    pg = pdf_doc[page_index]
    bitmap = pg.render(scale=dpi / 72.0)
    pil_image = bitmap.to_pil()
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def _ppstructure_for_region(pdf_path, page_index, page_height, y_top, y_bottom, dpi=200):
    """
    PPStructure로 특정 세로 영역의 표를 인식
    페이지 전체 너비를 사용하여 세로 텍스트 헤더도 포착
    """
    cache_key = f"{pdf_path}:{page_index}:{y_top:.0f}:{y_bottom:.0f}"
    if cache_key in _ppstructure_cache:
        return _ppstructure_cache[cache_key]

    try:
        from .scan_pdf_ocr import _get_table_engine, _html_table_to_list

        image = _get_page_image(pdf_path, page_index, dpi)
        h, w = image.shape[:2]
        scale = h / page_height

        crop_y1 = max(0, int((y_top - 20) * scale))
        crop_y2 = min(h, int((y_bottom + 20) * scale))
        cropped = image[crop_y1:crop_y2, :, :]

        engine = _get_table_engine()
        if engine is False:
            _ppstructure_cache[cache_key] = None
            return None

        logger.info("  PPStructure 폴백 (y: %.0f~%.0f)...", y_top, y_bottom)
        result = engine(cropped)
        for item in result:
            if item.get("type") == "table":
                html = item.get("res", {}).get("html", "")
                if html:
                    table_data = _html_table_to_list(html)
                    if table_data:
                        md = table_to_markdown(table_data)
                        if md:
                            _ppstructure_cache[cache_key] = md
                            return md

        _ppstructure_cache[cache_key] = None
        return None
    except Exception as e:
        logger.warning("  PPStructure 폴백 실패: %s", e)
        _ppstructure_cache[cache_key] = None
        return None


def _extract_text_for_bbox(page, bbox) -> str:
    """특정 영역(bbox)의 텍스트를 레이아웃 유지하며 추출"""
    x0, y0, x1, y1 = bbox
    cropped = page.crop((x0, y0, x1, y1))
    try:
        text = cropped.extract_text(layout=True)
    except TypeError:
        text = cropped.extract_text()
    return text or ""


def _extract_page_with_tables(page, pdf_path=None, page_index=None) -> str:
    """
    한 페이지에서 표 영역을 제외한 텍스트를 추출하고,
    표를 원래 위치에 마크다운으로 삽입
    불완전한 표(열 부족, 좁은 bbox)는 PPStructure로 폴백
    """
    page_height = page.height
    page_width = page.width

    tables = page.find_tables()
    table_bboxes = []
    table_entries = []

    for table in tables:
        bbox = table.bbox
        table_data = table.extract()

        if not table_data:
            continue

        y_center = (bbox[1] + bbox[3]) / 2
        cleaned_data = _clean_table_data(table_data)

        if _has_usable_table_data(cleaned_data):
            table_width_ratio = (bbox[2] - bbox[0]) / page_width

            md = table_to_markdown(cleaned_data)
            if md:
                use_bbox = bbox
                if table_width_ratio < 0.75:
                    use_bbox = (0, bbox[1] - 5, page_width, bbox[3] + 5)
                table_bboxes.append(use_bbox)
                table_entries.append({"y": y_center, "content": f"\n{md}\n", "bbox": use_bbox})
                continue

        fallback_text = _extract_text_for_bbox(page, bbox)
        if fallback_text.strip():
            table_bboxes.append(bbox)
            table_entries.append({"y": y_center, "content": fallback_text.strip(), "bbox": bbox})

    if table_bboxes:
        def not_in_table(obj):
            obj_y = obj.get("top", 0)
            obj_x = obj.get("x0", 0)
            for bbox in table_bboxes:
                x0, y0, x1, y1 = bbox
                if y0 - 2 <= obj_y <= y1 + 2 and x0 - 2 <= obj_x <= x1 + 2:
                    return False
            return True

        filtered_page = page.filter(not_in_table)
        text_only = filtered_page.extract_text() or ""
    else:
        text_only = page.extract_text() or ""

    if not table_entries:
        return text_only.strip()

    text_lines = text_only.strip().split("\n") if text_only.strip() else []

    if not text_lines:
        return "\n\n".join(t["content"] for t in sorted(table_entries, key=lambda x: x["y"]))

    words = page.extract_words()
    filtered_words = []
    for w in words:
        in_table = False
        for bbox in table_bboxes:
            if bbox[1] - 2 <= w["top"] <= bbox[3] + 2:
                in_table = True
                break
        if not in_table:
            filtered_words.append(w)

    line_y_positions = []
    word_idx = 0
    for line in text_lines:
        if word_idx < len(filtered_words):
            line_y_positions.append(filtered_words[word_idx]["top"])
            line_words = line.split()
            word_idx += max(len(line_words), 1)
        else:
            last_y = line_y_positions[-1] if line_y_positions else page_height
            line_y_positions.append(last_y + 15)

    result_parts = []
    table_inserted = [False] * len(table_entries)

    for i, line in enumerate(text_lines):
        line_y = line_y_positions[i] if i < len(line_y_positions) else page_height

        for j, tbl in enumerate(table_entries):
            if not table_inserted[j] and tbl["y"] <= line_y:
                result_parts.append(f"\n{tbl['content']}\n")
                table_inserted[j] = True

        result_parts.append(line)

    for j, tbl in enumerate(table_entries):
        if not table_inserted[j]:
            result_parts.append(f"\n{tbl['content']}\n")

    return "\n".join(result_parts).strip()


def extract_pdf(pdf_path: str) -> list:
    """
    디지털 PDF에서 텍스트와 표를 페이지별로 추출
    페이지 번호는 문서 하단의 '- N -' 푸터를 기준으로 결정

    Returns:
        [{"page_num": 1, "text": "...(표 포함)", "tables": [], "images": []}, ...]
    """
    pages_result = []
    front_matter_idx = 0

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        logger.info("PDF 페이지 수: %d", total_pages)

        for i, page in enumerate(pdf.pages):
            combined_text = _extract_page_with_tables(page, pdf_path=pdf_path, page_index=i)

            doc_page_num, cleaned_text = detect_footer_page_number(combined_text)

            if doc_page_num is not None:
                page_num = doc_page_num
            else:
                front_matter_idx += 1
                page_num = f"전문-{front_matter_idx}"

            page_data = {
                "page_num": page_num,
                "text": cleaned_text,
                "tables": [],
                "images": [],
            }

            logger.info("  Page %s (PDF %d/%d): %d chars", page_num, i + 1, total_pages, len(cleaned_text))
            pages_result.append(page_data)

    return pages_result


if __name__ == "__main__":
    import os
    import sys

    test_pdf = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "test_Data",
        "water_result01_74.pdf",
    )

    if not os.path.exists(test_pdf):
        print(f"테스트 파일 없음: {test_pdf}")
        exit()

    scanned = is_scanned_pdf(test_pdf)
    print(f"스캔 PDF 여부: {scanned}")

    if not scanned:
        result = extract_pdf(test_pdf)
        print(f"\n총 {len(result)} 페이지 추출 완료")
        for p in result:
            print(f"\n{'=' * 60}")
            print(f"--- Page {p['page_num']} ---")
            print(f"{'=' * 60}")
            print(p["text"])
