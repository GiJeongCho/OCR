"""
PDF 관련 공통 유틸리티
- 페이지 이미지 변환
- 푸터 페이지 번호 감지
"""
import re
import logging

import cv2
import numpy as np
import pypdfium2 as pdfium

logger = logging.getLogger(__name__)


def pdf_to_images(pdf_path: str, dpi: int = 300) -> list[np.ndarray]:
    """PDF를 페이지별 BGR numpy 이미지 배열로 변환"""
    pdf_doc = pdfium.PdfDocument(pdf_path)
    images = []
    scale = dpi / 72.0

    for i in range(len(pdf_doc)):
        page = pdf_doc[i]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        images.append(cv_image)

    logger.info("PDF → %d페이지 이미지 변환 완료: %s", len(images), pdf_path)
    return images


def detect_footer_page_number(text: str) -> tuple[int | None, str]:
    """
    페이지 하단의 '- N -' 형식 페이지 번호를 감지하고 제거

    Returns:
        (page_number or None, cleaned_text)
    """
    if not text:
        return None, text

    match = re.search(r'^\s*-\s*(\d+)\s*-\s*$', text.strip(), re.MULTILINE)
    if match:
        page_num = int(match.group(1))
        cleaned = text.strip()[:match.start()] + text.strip()[match.end():]
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return page_num, cleaned

    return None, text.strip()
