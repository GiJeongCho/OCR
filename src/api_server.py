"""
OCR Pipeline FastAPI 서버
활자체 문서(PDF/HWP/HWPX/DOCX)만 처리
"""
import os
import shutil
import tempfile
import time
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .common.config import (
    DATA_DIR, MD_OUTPUT_DIR,
    SERVER_HOST, SERVER_PORT,
)
from .common.logger import setup_logging
from .common import markdown_builder

setup_logging()
logger = logging.getLogger(__name__)


# ==========================================
# Lifespan (startup / shutdown)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("OCR Pipeline 서버 시작")
    os.makedirs(MD_OUTPUT_DIR, exist_ok=True)
    logger.info("서버 준비 완료 — 활자체: PDF/DOCX/HWP/HWPX")
    yield
    logger.info("OCR Pipeline 서버 종료")


app = FastAPI(
    title="OCR Pipeline API",
    description="활자체 문서(PDF/HWP/HWPX/DOCX) 처리 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=DATA_DIR), name="static")


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
# 활자체 문서 처리
# ==========================================
def _process_v1_printed(file_path: str, filename: str) -> dict:
    """활자체 파이프라인: 포맷 판별 → 직접 추출 또는 OCR 폴백"""
    from .v1_printed.document_loader import process_document

    pages = process_document(file_path, image_output_dir=None)
    return {"pages": pages, "used_ocr": False}


# ==========================================
# API 엔드포인트
# ==========================================
@app.post("/ocr/process", response_model=OCRResponse)
async def process_document(
    file: UploadFile = File(...),
):
    """
    문서를 업로드하고 OCR/추출 처리

    - 활자체 PDF/DOCX/HWP/HWPX만 지원
    - LLM 교정은 사용하지 않음
    """
    start_time = time.time()
    mode = "printed"
    original_filename = file.filename or "uploaded"
    suffix = os.path.splitext(original_filename)[1]
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    file_path = temp_file.name

    try:
        with temp_file as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception:
        if os.path.exists(file_path):
            os.unlink(file_path)
        raise

    logger.info("파일: %s | 모드: %s", original_filename, mode)

    try:
        result = _process_v1_printed(file_path, original_filename)
        pages = result["pages"]

        md_content = markdown_builder.build_markdown(pages, original_filename)
        base_name = os.path.splitext(original_filename)[0]
        md_save_path = markdown_builder.save_markdown(md_content, MD_OUTPUT_DIR, base_name)

        processed_time = time.time() - start_time

        md_filename = f"{base_name}_result.md"

        logger.info("처리 완료: %.2f초", processed_time)

        return OCRResponse(
            doc_id=None,
            filename=original_filename,
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
        logger.exception("처리 중 오류 발생")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


@app.get("/health")
def health_check():
    """서버 상태 확인"""
    from .v1_printed.hwp_converter import check_libreoffice

    return {
        "status": "ok",
        "libreoffice_available": check_libreoffice(),
        "supported_formats": [".pdf", ".docx", ".hwp", ".hwpx"],
        "mode": "printed",
        "llm_correction": False,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api_server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
    )
