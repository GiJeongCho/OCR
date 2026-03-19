"""
Version 2 (손글씨) 전처리 모듈
색상 정보를 유지하면서 해상도 보정만 수행
(형광펜, 컬러 손글씨 등의 정보 보존이 중요)
"""
import os
import cv2
import numpy as np
import pypdfium2 as pdfium

DOCUMENT_EXTENSIONS = {".hwp", ".hwpx", ".docx", ".doc"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def load_image(file_path: str) -> list:
    """
    이미지, PDF, 또는 문서(HWP/HWPX/DOCX/DOC)를 로드하여 numpy 이미지 리스트로 반환
    문서 파일은 LibreOffice로 PDF 변환 후 이미지화
    색상(BGR) 유지

    Args:
        file_path: 입력 파일 경로

    Returns:
        numpy 이미지 리스트 (BGR)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _pdf_to_images(file_path)
    elif ext in IMAGE_EXTENSIONS:
        return _load_single_image(file_path)
    elif ext in DOCUMENT_EXTENSIONS:
        return _document_to_images(file_path)
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {ext}")


def _pdf_to_images(pdf_path: str, dpi: int = 300) -> list:
    """PDF를 컬러 이미지로 변환"""
    print(f"📂 PDF 로딩: {pdf_path}")
    pdf = pdfium.PdfDocument(pdf_path)
    images = []
    scale = dpi / 72.0

    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        images.append(cv_image)

    print(f"   {len(images)} 페이지 로드 완료")
    return images


def _document_to_images(file_path: str, dpi: int = 300) -> list:
    """HWP/HWPX/DOCX/DOC → LibreOffice로 PDF 변환 → 이미지로 변환"""
    from v1_printed.hwp_converter import convert_hwp_to_pdf

    ext = os.path.splitext(file_path)[1].lower()
    print(f"📂 {ext.upper()} → PDF 변환 후 이미지화: {os.path.basename(file_path)}")

    pdf_path = convert_hwp_to_pdf(file_path)
    try:
        return _pdf_to_images(pdf_path, dpi)
    finally:
        import tempfile, shutil
        tmp_dir = os.path.dirname(pdf_path)
        if tmp_dir.startswith(tempfile.gettempdir()):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _load_single_image(file_path: str) -> list:
    """단일 이미지 로드"""
    print(f"📂 이미지 로딩: {file_path}")
    img = cv2.imread(file_path)

    if img is None:
        img_array = np.fromfile(file_path, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {file_path}")

    return [img]


def preprocess_handwritten(image: np.ndarray) -> np.ndarray:
    """
    손글씨 문서 전처리
    - 해상도 보정 (저해상도 업스케일)
    - 색상 유지 (그레이스케일 변환하지 않음)
    - 약간의 선명화만 적용

    Args:
        image: BGR numpy 이미지

    Returns:
        전처리된 BGR numpy 이미지
    """
    h, w = image.shape[:2]

    # 저해상도 업스케일
    if w < 1500:
        scale = 2.0 if w < 800 else 1.5
        print(f"   → 저해상도 ({w}x{h}), {scale}x 업스케일")
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # 선명화 (Unsharp mask) — 손글씨 경계를 또렷하게
    gaussian = cv2.GaussianBlur(image, (0, 0), 3)
    sharpened = cv2.addWeighted(image, 1.5, gaussian, -0.5, 0)

    return sharpened


def save_preprocessed(images: list, output_dir: str, prefix: str = "page") -> list:
    """전처리된 이미지를 저장"""
    os.makedirs(output_dir, exist_ok=True)
    saved = []

    for idx, img in enumerate(images):
        filename = f"{prefix}_{idx + 1:03d}.jpg"
        path = os.path.join(output_dir, filename)
        cv2.imwrite(path, img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        saved.append(path)

    print(f"✅ {len(images)}개 이미지 저장: {output_dir}")
    return saved


if __name__ == "__main__":
    import sys

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    test_img = os.path.join(BASE_DIR, "test_Data", "test.png")

    if len(sys.argv) > 1:
        test_img = sys.argv[1]

    images = load_image(test_img)
    processed = [preprocess_handwritten(img) for img in images]
    save_preprocessed(processed, os.path.join(BASE_DIR, "data", "1_preprocessed"))
