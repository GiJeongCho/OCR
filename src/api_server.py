"""
OCR Pipeline v2 — FastAPI 통합 서버
mode=printed  → V1 (활자체 PDF/HWP/HWPX/DOCX, 고속)
mode=handwritten → V2 (손글씨, Chandra 기반)
"""
import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
import sys
import shutil
import time
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 모듈 경로 설정
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC_DIR)

from common import storage, markdown_builder, llm_correction

app = FastAPI(
    title="OCR Pipeline v2 API",
    description="V1(활자체: PDF/HWP/HWPX/DOCX) + V2(손글씨: Chandra) 통합 API",
    version="2.0.0",
)

BASE_DIR = os.path.dirname(SRC_DIR)
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "0_input")
OUTPUT_DIR = os.path.join(BASE_DIR, "data")
MD_OUTPUT_DIR = os.path.join(BASE_DIR, "data", "3_final_markdown")

app.mount("/static", StaticFiles(directory=OUTPUT_DIR), name="static")


# ==========================================
# 데이터 모델
# ==========================================
class PageResult(BaseModel):
    page_num: str | int
    text: str
    tables: List[str] = []
    images: List[str] = []


class OCRResponse(BaseModel):
    doc_id: Optional[int] = None
    filename: str
    mode: str
    processed_time: float
    page_count: int
    markdown_url: str
    results: List[PageResult]


# ==========================================
# 시작 이벤트
# ==========================================
@app.on_event("startup")
async def startup_event():
    print("🚀 OCR Pipeline v2 서버 시작")
    storage.init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(MD_OUTPUT_DIR, exist_ok=True)
    print("✅ 서버 준비 완료")
    print("   V1 (활자체): PDF, DOCX, HWP, HWPX 지원")
    print("   V2 (손글씨): Chandra CLI 기반")


# ==========================================
# V1 — 활자체 문서 처리
# ==========================================
def _process_v1_printed(file_path: str, filename: str) -> dict:
    """V1 파이프라인: 포맷 판별 → 직접 추출 또는 OCR 폴백"""
    from v1_printed.document_loader import process_document

    image_output_dir = os.path.join(OUTPUT_DIR, "extracted_images", os.path.splitext(filename)[0])
    pages = process_document(file_path, image_output_dir)
    return {"pages": pages, "used_ocr": False}


# ==========================================
# V2 — 손글씨 문서 처리
# ==========================================
def _process_v2_handwritten(file_path: str, filename: str, use_llm: bool = True) -> dict:
    """V2 파이프라인: 전처리 → Chandra CLI → LLM 교정"""
    from v2_handwritten.preprocessing import load_image, preprocess_handwritten, save_preprocessed
    from v2_handwritten.chandra_engine import check_chandra, process_handwritten

    if not check_chandra():
        raise RuntimeError("Chandra CLI가 설치되어 있지 않습니다.")

    # Step 1: 전처리 (해상도 보정, 색상 유지)
    print("📐 Step 1: 전처리")
    images = load_image(file_path)
    processed_images = [preprocess_handwritten(img) for img in images]

    preprocess_dir = os.path.join(OUTPUT_DIR, "1_preprocessed")
    saved_paths = save_preprocessed(processed_images, preprocess_dir)

    # Step 2+3: Chandra CLI 통합 실행
    print("🔍 Step 2+3: Chandra 처리")
    chandra_output = os.path.join(OUTPUT_DIR, "chandra_output")
    os.makedirs(chandra_output, exist_ok=True)

    # Chandra에 전달할 입력 결정
    # PDF는 원본 사용, 문서 파일(HWP 등)은 전처리 과정에서 이미 이미지화됨
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        chandra_input = file_path
    elif ext in (".hwp", ".hwpx", ".docx", ".doc"):
        chandra_input = saved_paths[0] if saved_paths else file_path
    else:
        chandra_input = saved_paths[0] if saved_paths else file_path

    pages = process_handwritten(chandra_input, chandra_output)

    # Step 3.5: LLM 교정 (선택)
    if use_llm:
        print("✨ Step 3.5: LLM 교정")
        for page in pages:
            if page.get("text"):
                page["text"] = llm_correction.correct_text_with_llm(page["text"])

    return {"pages": pages, "used_ocr": True}


# ==========================================
# API 엔드포인트
# ==========================================
@app.post("/ocr/process", response_model=OCRResponse)
async def process_document(
    file: UploadFile = File(...),
    mode: str = Query("printed", description="처리 모드: printed(활자체) 또는 handwritten(손글씨)"),
    use_llm: bool = Query(False, description="LLM 교정 사용 여부 (V2 기본 True, V1 기본 False)"),
):
    """
    문서를 업로드하고 OCR/추출 처리

    - **mode=printed**: V1 활자체 (PDF/DOCX/HWP/HWPX, 고속)
    - **mode=handwritten**: V2 손글씨 (Chandra 기반)
    """
    if mode not in ("printed", "handwritten"):
        raise HTTPException(status_code=400, detail="mode는 'printed' 또는 'handwritten'이어야 합니다.")

    start_time = time.time()

    # 파일 저장
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    print(f"\n{'='*50}")
    print(f"📂 파일: {file.filename} | 모드: {mode}")
    print(f"{'='*50}")

    try:
        if mode == "printed":
            result = _process_v1_printed(file_path, file.filename)
        else:
            llm_flag = use_llm if use_llm else True
            result = _process_v2_handwritten(file_path, file.filename, use_llm=llm_flag)

        pages = result["pages"]

        # 마크다운 생성 및 저장
        md_content = markdown_builder.build_markdown(pages, file.filename)
        base_name = os.path.splitext(file.filename)[0]
        md_save_path = markdown_builder.save_markdown(md_content, MD_OUTPUT_DIR, base_name)

        processed_time = time.time() - start_time

        # DB 저장
        pages_for_db = []
        for p in pages:
            pages_for_db.append({
                "page_num": p["page_num"],
                "text": p.get("text", ""),
                "images": p.get("images", []),
            })

        doc_id = storage.save_document(
            filename=file.filename,
            page_count=len(pages),
            processed_time=processed_time,
            markdown_path=md_save_path,
            pages_data=pages_for_db,
            mode=mode,
        )

        md_filename = f"{base_name}_result.md"

        print(f"\n✅ 처리 완료: {processed_time:.2f}초")

        return OCRResponse(
            doc_id=doc_id,
            filename=file.filename,
            mode=mode,
            processed_time=processed_time,
            page_count=len(pages),
            markdown_url=f"/static/3_final_markdown/{md_filename}",
            results=[
                PageResult(
                    page_num=p["page_num"],
                    text=p.get("text", ""),
                    tables=p.get("tables", []),
                    images=p.get("images", []),
                )
                for p in pages
            ],
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ocr/history")
def get_history():
    """처리된 문서 목록 조회"""
    return storage.get_all_documents()


@app.get("/ocr/document/{doc_id}")
def get_document(doc_id: int):
    """특정 문서 상세 조회"""
    result = storage.get_document_detail(doc_id)
    if result is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return result


@app.get("/health")
def health_check():
    """서버 상태 확인"""
    from v2_handwritten.chandra_engine import check_chandra
    from v1_printed.hwp_converter import check_libreoffice

    return {
        "status": "ok",
        "chandra_available": check_chandra(),
        "libreoffice_available": check_libreoffice(),
        "supported_formats": {
            "v1_printed": [".pdf", ".docx", ".hwp", ".hwpx"],
            "v2_handwritten": [".pdf", ".hwp", ".hwpx", ".docx", ".doc", ".jpg", ".png", ".bmp", ".tiff"],
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8031)
