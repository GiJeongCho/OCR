"""
Version 1 (활자체) 문서 로더
파일 포맷을 판별하고 적절한 추출기로 라우팅
지원 포맷: PDF, DOCX, HWP, HWPX
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".hwp": "hwp",
    ".hwpx": "hwpx",
}


def detect_format(file_path: str) -> str:
    """파일 확장자로 포맷 판별"""
    ext = os.path.splitext(file_path)[1].lower()
    fmt = SUPPORTED_EXTENSIONS.get(ext)
    if fmt is None:
        raise ValueError(f"지원하지 않는 파일 형식: {ext}\n지원 형식: {list(SUPPORTED_EXTENSIONS.keys())}")
    return fmt


def process_document(file_path: str, image_output_dir: str = None) -> list:
    """
    파일 포맷을 자동 판별하고 적절한 추출기로 처리

    Args:
        file_path: 입력 파일 경로
        image_output_dir: 이미지 저장 디렉토리 (DOCX용)

    Returns:
        [{"page_num": int, "text": str, "tables": [str], "images": [str]}, ...]
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    fmt = detect_format(file_path)
    print(f"📂 파일 포맷: {fmt.upper()} | {os.path.basename(file_path)}")

    if fmt == "pdf":
        return _process_pdf(file_path)
    elif fmt == "docx":
        return _process_docx(file_path, image_output_dir)
    elif fmt == "hwpx":
        return _process_hwpx(file_path)
    elif fmt in ("hwp", "doc"):
        return _process_hwp(file_path)
    else:
        raise ValueError(f"처리할 수 없는 포맷: {fmt}")


def _process_pdf(file_path: str) -> list:
    """PDF 처리: 디지털 PDF → pdfplumber, 스캔 PDF → PaddleOCR"""
    from v1_printed.pdf_extractor import is_scanned_pdf, extract_pdf
    from v1_printed.scan_pdf_ocr import extract_scanned_pdf

    if is_scanned_pdf(file_path):
        print("   → 스캔 PDF 감지: OCR 모드로 처리")
        return extract_scanned_pdf(file_path)
    else:
        print("   → 디지털 PDF 감지: 직접 추출 모드 (초고속)")
        return extract_pdf(file_path)


def _process_docx(file_path: str, image_output_dir: str = None) -> list:
    """DOCX 처리"""
    from v1_printed.docx_extractor import extract_docx
    return extract_docx(file_path, image_output_dir)


def _process_hwpx(file_path: str) -> list:
    """HWPX 처리: LibreOffice → PDF(페이지 단위) 우선, 실패 시 직접 XML 파싱"""
    import tempfile
    import shutil
    from v1_printed.hwp_converter import check_libreoffice, _run_libreoffice

    if check_libreoffice():
        output_dir = tempfile.mkdtemp(prefix="hwpx_convert_")
        try:
            print("   🔄 HWPX → PDF 변환 중 (LibreOffice)...")
            pdf_path = _run_libreoffice(file_path, output_dir, "pdf")
            if pdf_path:
                print(f"   ✅ PDF 변환 완료, 페이지별 추출 진행")
                from v1_printed.pdf_extractor import extract_pdf
                return extract_pdf(pdf_path)
            else:
                print("   ⚠️ LibreOffice 변환 실패, 직접 XML 파싱으로 폴백")
        except Exception as e:
            print(f"   ⚠️ HWPX → PDF 변환 오류: {e}, 직접 XML 파싱으로 폴백")
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    from v1_printed.hwpx_extractor import extract_hwpx
    return extract_hwpx(file_path)


def _process_hwp(file_path: str) -> list:
    """HWP 처리: LibreOffice → PDF → pdfplumber"""
    from v1_printed.hwp_converter import extract_hwp
    return extract_hwp(file_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        test_pdf = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "test_Data",
            "water_result01_74.pdf",
        )
    else:
        test_pdf = sys.argv[1]

    result = process_document(test_pdf)
    print(f"\n✅ 총 {len(result)} 페이지 처리 완료")
    for p in result[:3]:
        print(f"\n--- Page {p['page_num']} ---")
        print(f"Text: {p['text'][:200]}...")
        print(f"Tables: {len(p['tables'])}개")
