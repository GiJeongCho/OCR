"""
스캔 PDF(이미지 PDF)를 PaddleOCR + PPStructure로 처리하는 폴백 모듈
디지털 텍스트가 없는 PDF에서만 사용
"""
import os
import logging

import cv2
import numpy as np

from ..common.config import *  # noqa: F401 — PADDLE env 설정 보장
from ..common.table_formatter import table_to_markdown
from ..common.pdf_utils import pdf_to_images

logger = logging.getLogger(__name__)

_paddle_ocr = None
_table_engine = None


def _get_paddle_ocr():
    global _paddle_ocr
    if _paddle_ocr is None:
        from paddleocr import PaddleOCR
        logger.info("PaddleOCR 모델 로딩 (Lazy)...")
        _paddle_ocr = PaddleOCR(
            use_angle_cls=True,
            lang="korean",
            use_gpu=True,
            show_log=False,
        )
    return _paddle_ocr


def _get_table_engine():
    global _table_engine
    if _table_engine is None:
        try:
            from paddleocr import PPStructure
            from paddleocr.paddleocr import MODEL_URLS
            ch_layout = MODEL_URLS["STRUCTURE"]["PP-StructureV2"]["layout"]["ch"]
            MODEL_URLS["STRUCTURE"]["PP-StructureV2"]["layout"]["korean"] = ch_layout
            logger.info("PPStructure 표 인식 모델 로딩 (Lazy)...")
            _table_engine = PPStructure(
                table=True,
                ocr=True,
                lang="korean",
                use_gpu=False,
                show_log=False,
            )
        except (Exception, SystemExit) as e:
            logger.warning("표 인식 엔진을 사용할 수 없습니다: %s: %s", type(e).__name__, e)
            _table_engine = False
    return _table_engine


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    """스캔 PDF 이미지 최소 전처리 (해상도 보정)"""
    h, w = image.shape[:2]
    if w < 1000:
        image = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return image


def ocr_image(image: np.ndarray) -> str:
    """PaddleOCR로 이미지에서 텍스트 추출"""
    ocr = _get_paddle_ocr()
    result = ocr.ocr(image, cls=True)

    if not result or result[0] is None:
        return ""

    lines = []
    for line in result[0]:
        text = line[1][0]
        confidence = line[1][1]
        if confidence > 0.5:
            lines.append(text)

    return "\n".join(lines)


def recognize_tables(image: np.ndarray) -> list:
    """PPStructure로 이미지에서 표 구조 인식"""
    engine = _get_table_engine()
    if engine is False:
        return []

    try:
        result = engine(image)
        tables = []
        for item in result:
            if item.get("type") == "table":
                html = item.get("res", {}).get("html", "")
                if html:
                    table_data = _html_table_to_list(html)
                    if table_data:
                        tables.append(table_data)
        return tables
    except Exception as e:
        logger.warning("표 인식 오류: %s", e)
        return []


def _html_table_to_list(html: str) -> list:
    """간단한 HTML 표를 2D 리스트로 변환 (colspan, rowspan 처리)"""
    try:
        from lxml import etree
        parser = etree.HTMLParser()
        tree = etree.fromstring(html, parser)

        rows = list(tree.iter("tr"))
        if not rows:
            return []

        table_data = []
        occupied = {}

        for r_idx, tr in enumerate(rows):
            row_data = []
            c_idx = 0

            for td in tr.iter("td", "th"):
                while occupied.get((r_idx, c_idx), False):
                    c_idx += 1

                text = td.text_content().strip() if hasattr(td, "text_content") else (td.text or "").strip()

                rowspan = int(td.get("rowspan", 1))
                colspan = int(td.get("colspan", 1))

                row_data.append(text)

                for r in range(rowspan):
                    for c in range(colspan):
                        occupied[(r_idx + r, c_idx + c)] = True

                for _ in range(colspan - 1):
                    row_data.append("")
                c_idx += colspan

            max_c_idx = max([c for (r, c) in occupied.keys() if r == r_idx] + [-1]) + 1
            while len(row_data) < max_c_idx:
                row_data.append("")

            if row_data:
                table_data.append(row_data)

        return table_data
    except Exception as e:
        logger.warning("HTML 표 변환 중 오류: %s", e)
        return []


def extract_scanned_pdf(pdf_path: str) -> list:
    """
    스캔 PDF를 PaddleOCR로 처리

    Returns:
        [{"page_num": 1, "text": "...", "tables": [...], "images": []}, ...]
    """
    logger.info("스캔 PDF OCR 처리: %s", os.path.basename(pdf_path))
    images = pdf_to_images(pdf_path)
    pages_result = []

    for i, image in enumerate(images):
        page_num = i + 1
        logger.info("  Page %d/%d OCR 처리 중...", page_num, len(images))

        processed = preprocess_for_ocr(image)
        text = ocr_image(processed)

        tables_data = recognize_tables(processed)
        table_md_list = [table_to_markdown(td) for td in tables_data if table_to_markdown(td)]

        pages_result.append({
            "page_num": page_num,
            "text": text,
            "tables": table_md_list,
            "images": [],
        })

        logger.info("  Page %d: text=%d chars, tables=%d", page_num, len(text), len(table_md_list))

    return pages_result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.v1_printed.scan_pdf_ocr <scanned.pdf>")
        exit()
    result = extract_scanned_pdf(sys.argv[1])
    for p in result:
        print(f"\n--- Page {p['page_num']} ---")
        print(p["text"][:300])
