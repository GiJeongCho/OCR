"""
스캔 PDF(이미지 PDF)를 PaddleOCR + PPStructure로 처리하는 폴백 모듈
디지털 텍스트가 없는 PDF에서만 사용
"""
import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
import sys
import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.table_formatter import table_to_markdown

_paddle_ocr = None
_table_engine = None


def _get_paddle_ocr():
    global _paddle_ocr
    if _paddle_ocr is None:
        from paddleocr import PaddleOCR
        print("🚀 PaddleOCR 모델 로딩 (Lazy)...")
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
            print("🚀 PPStructure 표 인식 모델 로딩 (Lazy)...")
            _table_engine = PPStructure(
                table=True,
                ocr=True,
                lang="korean",
                use_gpu=False,
                show_log=False,
            )
        except (Exception, SystemExit) as e:
            print(f"⚠️ 표 인식 엔진을 사용할 수 없습니다: {type(e).__name__}: {e}")
            _table_engine = False
    return _table_engine


def pdf_to_images(pdf_path: str, dpi: int = 300) -> list:
    """PDF를 페이지별 numpy 이미지 배열로 변환"""
    pdf = pdfium.PdfDocument(pdf_path)
    images = []
    scale = dpi / 72.0

    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        images.append(cv_image)

    return images


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    """스캔 PDF 이미지 최소 전처리 (deskew + 해상도 보정)"""
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
        print(f"⚠️ 표 인식 오류: {e}")
        return []


def _html_table_to_list(html: str) -> list:
    """간단한 HTML 표를 2D 리스트로 변환 (colspan, rowspan 처리)"""
    try:
        from lxml import etree
        parser = etree.HTMLParser()
        tree = etree.fromstring(html, parser)

        # 행과 열의 최대 크기 계산
        rows = list(tree.iter("tr"))
        if not rows:
            return []
            
        table_data = []
        # 그리드 관리를 위해 각 셀의 점유 상태를 추적
        occupied = {}

        for r_idx, tr in enumerate(rows):
            row_data = []
            c_idx = 0
            
            for td in tr.iter("td", "th"):
                # 이미 rowspan으로 점유된 칸 건너뛰기
                while occupied.get((r_idx, c_idx), False):
                    c_idx += 1
                
                text = td.text_content().strip() if hasattr(td, "text_content") else (td.text or "").strip()
                
                # rowspan, colspan 속성 가져오기
                rowspan = int(td.get("rowspan", 1))
                colspan = int(td.get("colspan", 1))
                
                # 현재 셀 데이터 저장 (병합된 셀의 왼쪽 상단에만 텍스트 배치)
                # 마크다운 표는 병합을 지원하지 않으므로, 나머지 칸은 빈 문자열로 채움
                row_data.append(text)
                
                # 병합된 영역을 occupied로 표시
                for r in range(rowspan):
                    for c in range(colspan):
                        occupied[(r_idx + r, c_idx + c)] = True
                
                # colspan만큼 열 인덱스 증가시키고, 현재 행(row_data)에 빈칸 추가
                for _ in range(colspan - 1):
                    row_data.append("")
                c_idx += colspan
                
            # 위쪽 행의 rowspan으로 인해 현재 행의 끝부분에 들어가야 할 빈 셀 처리
            max_c_idx = max([c for (r, c) in occupied.keys() if r == r_idx] + [-1]) + 1
            while len(row_data) < max_c_idx:
                row_data.append("")
                
            if row_data:
                table_data.append(row_data)
                
        return table_data
    except Exception as e:
        print(f"HTML 표 변환 중 오류: {e}")
        return []


def extract_scanned_pdf(pdf_path: str) -> list:
    """
    스캔 PDF를 PaddleOCR로 처리

    Args:
        pdf_path: 스캔 PDF 파일 경로

    Returns:
        [{"page_num": 1, "text": "...", "tables": [...], "images": []}, ...]
    """
    print(f"🔍 스캔 PDF OCR 처리: {os.path.basename(pdf_path)}")
    images = pdf_to_images(pdf_path)
    pages_result = []

    for i, image in enumerate(images):
        page_num = i + 1
        print(f"   Page {page_num}/{len(images)} OCR 처리 중...")

        processed = preprocess_for_ocr(image)

        text = ocr_image(processed)

        tables_data = recognize_tables(processed)
        table_md_list = []
        for td in tables_data:
            md = table_to_markdown(td)
            if md:
                table_md_list.append(md)

        pages_result.append({
            "page_num": page_num,
            "text": text,
            "tables": table_md_list,
            "images": [],
        })

        print(f"   Page {page_num}: text={len(text)}chars, tables={len(table_md_list)}")

    return pages_result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scan_pdf_ocr.py <scanned.pdf>")
        exit()
    result = extract_scanned_pdf(sys.argv[1])
    for p in result:
        print(f"\n--- Page {p['page_num']} ---")
        print(p["text"][:300])
