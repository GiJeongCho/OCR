# OCR 서비스 - 개발 환경 가이드

> 백엔드 개발자 대상 문서.
> 본 서비스는 **활자체 문서(PDF / DOCX / HWP / HWPX)** 를 받아 텍스트·표·이미지를 추출하고 Markdown으로 변환해주는 **AI/OCR 백엔드**입니다.

---

## 1. 서비스 개요

| 항목 | 내용 |
|------|------|
| 서비스 이름 | OCR Pipeline API |
| 목적 | 활자체 문서 → 텍스트/표/이미지 추출 → Markdown 산출 |
| 입력 포맷 | `.pdf`, `.docx`, `.hwp`, `.hwpx` |
| 출력 | JSON 응답 + `data/3_final_markdown/*.md` 파일 + `/static/*` URL |
| 처리 모드 | `printed` (활자체 전용). 손글씨/`v2_handwritten`은 별도 모듈로 분리되어 있으나 현재 API는 활자체만 사용 |

---

## 2. 기술 스택 (AI / Framework)

### 2.1 런타임
- **Python**: `3.11` (Docker 이미지 기준: `python:3.11-slim`)
- **OS 의존성 (Debian/Ubuntu)**:
  - `libgl1`, `libglib2.0-0`, `libsm6`, `libxrender1`, `libxext6` — OpenCV/PaddleOCR 런타임
  - `libreoffice` — **HWP / HWPX / DOCX 변환용 (CLI 헤드리스 모드)**

### 2.2 웹 / API
- **FastAPI** ≥ 0.115 — REST API 프레임워크 (lifespan 기반 부트스트랩 사용)
- **Uvicorn** ≥ 0.30 — ASGI 서버
- **python-multipart** ≥ 0.0.9 — `multipart/form-data` 업로드 지원
- **Pydantic** — 응답/요청 모델 (`OCRResponse`, `PageResult`)

### 2.3 활자체 직접 추출
- **pdfplumber** ≥ 0.11 — PDF 텍스트/표 추출
- **pypdfium2** ≥ 4.0 — PDF 페이지 렌더링 (OCR 폴백용 이미지 변환)
- **python-docx** ≥ 1.1 — DOCX 본문/표 파싱
- **lxml** ≥ 5.0 — HWPX XML 파싱
- **olefile** == 0.47 — 구형 HWP(OLE) 시그니처 확인

### 2.4 스캔 PDF OCR 폴백 (GPU)
- **paddleocr** ≥ 2.8 — 텍스트 검출(`PP-OCRv*`) + 인식
- **paddlepaddle-gpu** ≥ 2.6 — PaddlePaddle GPU 런타임
- **opencv-python-headless** ≥ 4.9 — 이미지 전처리
- **numpy** ≥ 1.26, **Pillow** ≥ 10.0
- **tqdm** ≥ 4.66

### 2.5 (옵션) 손글씨 모듈 (`src/v2_handwritten/`)
- `chandra_engine.py` 기반. API에서는 호출 안 함. **백엔드에서 무시 가능**.

---

## 3. 디렉토리 구조

```
ocr/
├── Dockerfile
├── requirements.txt
├── data/
│   ├── 0_input/                 # 업로드 임시 영역 (사용 시)
│   ├── 3_final_markdown/        # 최종 Markdown 출력 (/static/3_final_markdown 로 노출)
│   └── ocr_data.db              # 선택적 메타 저장소(SQLite)
├── scripts/
│   └── download_models.py       # Paddle/HWP 변환 자원 다운로드 (오프라인 환경 대비)
└── src/
    ├── api_server.py            # FastAPI 엔트리포인트 (uvicorn src.api_server:app)
    ├── common/
    │   ├── config.py            # 서버 포트/경로/타임아웃
    │   ├── logger.py            # logging 설정
    │   ├── markdown_builder.py  # 페이지 → Markdown 변환
    │   ├── table_formatter.py   # 표 정규화
    │   ├── pdf_utils.py
    │   ├── storage.py
    │   └── llm_correction.py    # (현재 사용 안 함 / 비활성)
    ├── v1_printed/              # ★ 운영 파이프라인
    │   ├── document_loader.py   # 포맷 판별 → 적절한 추출기 호출
    │   ├── pdf_extractor.py     # 일반 PDF (텍스트 PDF)
    │   ├── scan_pdf_ocr.py      # 스캔 PDF → PaddleOCR 폴백
    │   ├── docx_extractor.py
    │   ├── hwpx_extractor.py
    │   └── hwp_converter.py     # LibreOffice CLI 호출
    └── v2_handwritten/          # 손글씨용. API 미연결.
```

> 백엔드 호출 흐름: `POST /ocr/process` → `document_loader.process_document()`
> → 포맷 분기(`pdf_extractor` / `docx_extractor` / `hwpx_extractor` / `hwp_converter`)
> → 텍스트 PDF가 아니면 `scan_pdf_ocr` 로 폴백 → `markdown_builder.build_markdown()`.

---

## 4. 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OCR_HOST` | `0.0.0.0` | 바인딩 호스트 |
| `OCR_PORT` | `8031` | 로컬 실행 시 포트 (Docker에서는 `APP_PORT`) |
| `APP_PORT` | (없음) | **Dockerfile의 CMD가 사용** — compose에서 주입 |
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | `True` | PaddleOCR 오프라인 모델 검증 비활성화 (코드에서 자동 설정) |

> **포트 규칙 (Jenkins 배포 기준, `dev/docker.sh`)**
> - dev: 6000번대 / stg: 9000번대 / prd: 8000번대
> - 컨테이너 내부 포트는 compose에서 `APP_PORT`로 주입

---

## 5. 로컬 개발 환경 구축

### 5.1 사전 요구사항
- Python 3.11
- CUDA 11.8+ (Paddle GPU 사용 시. CPU만 쓰려면 `paddlepaddle` 로 교체)
- LibreOffice (HWP/HWPX/DOCX 변환에 필수)
- Git

```bash
# 1) 시스템 패키지 (Ubuntu 기준)
sudo apt-get update
sudo apt-get install -y libreoffice libgl1 libglib2.0-0 libsm6 libxrender1 libxext6

# 2) 가상환경
cd /home/pps-nipa/jenkins/dev/ocr
python3.11 -m venv .venv
source .venv/bin/activate

# 3) 의존성
pip install -U pip
pip install -r requirements.txt

# 4) (선택) 모델 사전 다운로드 — 오프라인 환경 배포 대비
python scripts/download_models.py
```

### 5.2 실행

```bash
# 개발 모드
export OCR_PORT=8031
uvicorn src.api_server:app --host 0.0.0.0 --port "${OCR_PORT}" --reload

# 또는 모듈 실행
python -m src.api_server
```

### 5.3 헬스 체크

```bash
curl http://localhost:8031/health
```

응답 예시:
```json
{
  "status": "ok",
  "libreoffice_available": true,
  "supported_formats": [".pdf", ".docx", ".hwp", ".hwpx"],
  "mode": "printed",
  "llm_correction": false
}
```

---

## 6. Docker / Compose 실행

### 6.1 단독 Docker 빌드
```bash
cd /home/pps-nipa/jenkins/dev/ocr
docker build -t pps/ocr-api:dev .
docker run --rm -p 6031:6031 \
  -e APP_PORT=6031 \
  --gpus all \
  pps/ocr-api:dev
```

### 6.2 Jenkins 통합 배포 (권장)
- 전체 스택은 `/home/pps-nipa/jenkins/dev/docker.sh` 가 관리합니다.
- 이미지 태그는 `.env.dev` 의 `IMG_OCR_API` 로 지정됩니다.

```bash
sudo /home/pps-nipa/jenkins/dev/docker.sh dev up ocr_api
```

---

## 7. API 사용법

### 7.1 문서 처리: `POST /ocr/process`

| 파라미터 | 위치 | 타입 | 설명 |
|----------|------|------|------|
| `file` | multipart | File | 업로드 문서 (`.pdf`/`.docx`/`.hwp`/`.hwpx`) |

```bash
curl -X POST "http://localhost:8031/ocr/process" \
  -H "accept: application/json" \
  -F "file=@./sample.pdf"
```

응답 (`OCRResponse`):
```json
{
  "doc_id": null,
  "filename": "sample.pdf",
  "mode": "printed",
  "processed_time": 1.42,
  "page_count": 3,
  "markdown_url": "/static/3_final_markdown/sample_result.md",
  "results": [
    { "page_num": 1, "text": "...", "tables": ["| A | B |\n|---|---|"], "images": [] }
  ]
}
```

### 7.2 정적 파일
- `/static/3_final_markdown/<base>_result.md` 로 변환 결과 다운로드 가능.

### 7.3 Swagger / ReDoc
- `http://localhost:8031/docs`
- `http://localhost:8031/redoc`

---

## 8. 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| `/health` 의 `libreoffice_available: false` | HWP/HWPX 변환 불가 | `apt-get install libreoffice` 재확인 |
| `paddleocr` import 시 GPU 오류 | CUDA/cuDNN 미설치 | `paddlepaddle` (CPU 버전)으로 교체하거나 `--gpus all` 옵션 사용 |
| 한글 폰트 깨짐 | 컨테이너 한글 폰트 부재 | `apt-get install fonts-nanum` 추가 |
| 500 에러 (HWP) | LibreOffice 타임아웃 | `common/config.py` 의 `LIBREOFFICE_TIMEOUT` 상향 |

---

## 9. 관련 문서
- 개발 표준 → [`./development-standards.md`](./development-standards.md)
- Jenkins 통합 배포 → [`/home/pps-nipa/jenkins/docs/development-environment.md`](../../../docs/development-environment.md)
