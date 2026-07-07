# OCR 서비스 개발 환경 가이드

> 대상: `backend/ocr` (git submodule — [GiJeongCho/OCR](https://github.com/GiJeongCho/OCR))
> 마지막 갱신: 2026-07-07

---

## 1. 서비스 개요

활자체 문서(PDF / HWP / HWPX / DOCX)를 받아 **텍스트 + 표 + 이미지**를 추출하고 Markdown으로 변환하는 독립 FastAPI 마이크로서비스.

| 항목 | 내용 |
|------|------|
| 포트 | `8031` (`OCR_PORT` 환경변수로 변경 가능) |
| 주요 엔드포인트 | `POST /ocr/process` — 문서 업로드·처리 |
| 헬스체크 | `GET /health` |
| 결과물 위치 | `data/3_final_markdown/{파일명}_result.md` |

### 처리 파이프라인

```
업로드 파일
    │
    ├─ PDF ─────── 디지털 PDF? → pdfplumber 직접 추출 (초고속)
    │               스캔 PDF?  → PaddleOCR (OCR 모드)
    │
    ├─ DOCX ──────────────────── python-docx 직접 추출
    │
    ├─ HWPX ──── LibreOffice → PDF 변환 → pdfplumber
    │             (LibreOffice 없으면 XML 직접 파싱으로 폴백)
    │
    └─ HWP ───── LibreOffice → PDF 변환 → pdfplumber
```

---

## 2. 개발 환경 설정

### 2-1. 사전 요구사항

| 항목 | 버전 | 비고 |
|------|------|------|
| Python | 3.12 | conda 환경 권장 |
| conda | 25.x 이상 | — |
| LibreOffice | 최신 | HWP/HWPX 변환용. [다운로드](https://www.libreoffice.org/download/libreoffice-fresh/) |
| CUDA | 11.x 이상 | GPU 사용 시 (paddlepaddle-gpu) |

### 검증된 패키지 버전 조합 (중요)

| 패키지 | 버전 | 비고 |
|--------|------|------|
| `paddleocr` | **2.8.x** (검증: 2.8.1) | **3.x 사용 금지** — 코드가 2.x API(`use_angle_cls`, `show_log`, `use_gpu`) 기반 |
| `paddlepaddle-gpu` | **2.6.2** | paddleocr 2.8.x와 짝. 3.x로 올리면 `set_optimization_level` 에러 발생 |

> ⚠️ **`paddleocr 3.x` + `paddlepaddle 2.6.x` 조합은 동작하지 않는다.**
> paddleocr 3.x는 내부적으로 paddlex를 쓰는데, paddlepaddle 2.6.x에 없는
> `AnalysisConfig.set_optimization_level` API를 호출해 크래시한다.
> 반드시 아래 §2-2의 검증 버전으로 고정 설치할 것.

### 2-2. conda 가상환경 생성

```bash
# 환경 생성
conda create -n ocr python=3.12 -y

# 활성화
conda activate ocr

# 공통 패키지 설치 (backend/ocr 루트에서 실행)
cd backend/ocr
pip install -r requirements.txt
```

> `requirements.txt`의 `paddlepaddle-gpu`는 PyPI에 없어 위 설치에서 실패할 수 있다.
> paddle 계열은 아래처럼 **전용 인덱스 + 검증 버전**으로 별도 설치한다.

```bash
# PaddlePaddle 2.6.2 (GPU, CUDA 11.8 빌드 — 상위 드라이버는 하위 호환)
pip install paddlepaddle-gpu==2.6.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/

# PaddleOCR 2.8.x (3.x 금지)
pip install paddleocr==2.8.1
```

> **GPU 없는 경우**: `paddlepaddle-gpu` 대신 CPU 빌드 설치
>
> ```bash
> pip install paddlepaddle==2.6.2
> pip install paddleocr==2.8.1
> ```

### 2-3. OCR 모델 다운로드 (최초 1회)

```bash
# conda activate ocr 상태에서
cd backend/ocr
python scripts/download_models.py
```

다운로드되는 모델 (`~/.paddleocr/whl/` 캐시):

| 종류 | 모델 | 용도 |
|------|------|------|
| det | `Multilingual_PP-OCRv3_det` | 텍스트 영역 검출 |
| rec | `korean_PP-OCRv4_rec` | 한국어 문자 인식 |
| cls | `ch_ppocr_mobile_v2.0_cls` | 텍스트 방향(각도) 분류 |
| table | `en_ppstructure_mobile_v2.0_SLANet` | 표 구조 인식 |
| layout | `picodet_lcnet_x1_0_fgd_layout_cdla` | 문서 레이아웃 분석 |

특정 경로에 저장하려면:
```bash
python scripts/download_models.py --output-dir backend/ocr/models
```

> **DNS 참고**: 모델은 바이두 CDN(`*.bcebos.com`)에서 받는다. 일부 사내/로컬 DNS는
> 이 도메인을 해석하지 못하는데(`getaddrinfo failed`), `download_models.py`는 이 경우
> 확인된 CDN IP(`103.235.47.176`)로 **자동 폴백**하도록 되어 있어 그대로 실행하면 된다.
> CDN IP가 바뀌어 폴백이 실패하면 §10 트러블슈팅 참고.

### 2-4. LibreOffice 설치 확인

```bash
# 헬스체크 API로 확인 (서버 실행 후)
curl http://localhost:8031/health

# 응답 예시
# {"status":"ok","libreoffice_available":true,"supported_formats":[".pdf",".docx",".hwp",".hwpx"],"mode":"printed","llm_correction":false}
```

`libreoffice_available: false`이면 HWP/HWPX 처리가 불가능하고 HWPX는 XML 파싱 폴백으로만 처리됨.

---

## 3. 환경 변수

`backend/ocr/.env` (또는 시스템 환경변수):

```env
OCR_HOST=0.0.0.0
OCR_PORT=8031
```

설정하지 않으면 위 기본값이 사용됨. 현재 LLM 교정 기능은 비활성화 상태.

---

## 4. 서버 실행

```bash
conda activate ocr
cd backend/ocr

# 개발 모드 (자동 재시작)
uvicorn src.api_server:app --host 0.0.0.0 --port 8031 --reload

# 또는 직접 실행
PYTHONPATH=. python -m src.api_server
```

---

## 5. API 사용

### POST /ocr/process

문서 파일을 업로드하면 페이지별 텍스트·표를 추출해 Markdown으로 저장하고 결과를 반환.

```bash
curl -X POST http://localhost:8031/ocr/process \
  -F "file=@문서.pdf"
```

**응답 예시:**
```json
{
  "filename": "문서.pdf",
  "mode": "printed",
  "processed_time": 1.23,
  "page_count": 5,
  "markdown_url": "/static/3_final_markdown/문서_result.md",
  "results": [
    {
      "page_num": 1,
      "text": "추출된 텍스트...",
      "tables": ["| 열1 | 열2 |\n|-----|-----|"],
      "images": []
    }
  ]
}
```

### GET /health

서버 상태 및 LibreOffice 가용 여부 확인.

---

## 6. 프로젝트 구조

```
backend/ocr/
├── scripts/
│   └── download_models.py      # OCR 모델 사전 다운로드
├── src/
│   ├── api_server.py           # FastAPI 앱 진입점
│   ├── common/
│   │   ├── config.py           # 환경변수 로드 (포트, 경로 등)
│   │   ├── logger.py           # 로깅 설정
│   │   ├── markdown_builder.py # 추출 결과 → Markdown 변환
│   │   ├── pdf_utils.py        # PDF 유틸리티
│   │   ├── storage.py          # SQLite 저장 (ocr_data.db)
│   │   ├── table_formatter.py  # 표 형식 정규화
│   │   └── llm_correction.py   # LLM 교정 (현재 미사용)
│   ├── v1_printed/
│   │   ├── document_loader.py  # 포맷 판별 → 추출기 라우팅
│   │   ├── pdf_extractor.py    # pdfplumber 기반 PDF 추출
│   │   ├── scan_pdf_ocr.py     # PaddleOCR 기반 스캔 PDF 처리
│   │   ├── docx_extractor.py   # python-docx 기반 DOCX 추출
│   │   ├── hwpx_extractor.py   # HWPX XML 직접 파싱
│   │   └── hwp_converter.py    # LibreOffice 변환 (HWP/HWPX → PDF)
│   └── v2_handwritten/         # 필기체 처리 (개발 중)
│       ├── chandra_engine.py
│       └── preprocessing.py
├── data/
│   ├── 0_input/                # 테스트용 입력 문서
│   ├── 3_final_markdown/       # 처리 결과 Markdown 저장
│   └── ocr_data.db             # SQLite DB
├── test_Data/                  # 단위 테스트용 샘플 파일
├── Dockerfile
└── requirements.txt
```

---

## 7. Docker 실행

```bash
cd backend/ocr

docker build -t pps/ocr:v1 .

docker run -d \
  -p 8031:8031 \
  --gpus all \
  -v "$(pwd)/data:/app/data" \
  --name ocr_v1 \
  pps/ocr:v1

docker logs -f ocr_v1
```

> GPU 없으면 `--gpus all` 제거. 단, 스캔 PDF OCR 속도가 크게 느려짐.

---

## 8. Synapse 메인 서비스와의 연동

Synapse `backend`의 전처리 파이프라인에서 OCR 서비스를 HTTP로 호출하는 구조.

```
문서 업로드 (Synapse API)
    → backend/app/preprocessing/pipeline.py
        → OCR 서비스 HTTP 호출 (http://localhost:8031/ocr/process)
            → 추출된 텍스트 → 청킹 → Milvus 임베딩 저장
```

연동 시 환경변수 (`backend/.env`):
```env
OCR_API_URL=http://localhost:8031
```

---

## 9. 개발 표준

### 포맷 추가 시
1. `src/v1_printed/` 아래 `{포맷}_extractor.py` 생성
2. 반환 타입 준수: `[{"page_num": int, "text": str, "tables": [str], "images": [str]}]`
3. `document_loader.py`의 `SUPPORTED_EXTENSIONS` 딕셔너리와 `process_document()` 라우팅에 추가

### 브랜치 전략
- 메인 브랜치: `dydqkem`
- 기능 개발: `feature/{기능명}`
- Synapse 메인 저장소의 submodule은 특정 커밋을 가리키므로, OCR 저장소에 push 후 **Synapse에서 submodule 커밋 업데이트**도 필요:

```bash
# Synapse 루트에서
cd backend/ocr
git pull origin dydqkem
cd ../..
git add backend/ocr
git commit -m "update ocr submodule"
git push origin develop
```

### 코드 스타일
- Python 3.12 타입 힌트 사용
- 로거는 `logging.getLogger(__name__)` 사용 (print 금지)
- 새 추출기는 `common/config.py`의 설정값만 참조 (하드코딩 금지)

---

## 10. 트러블슈팅

### `AttributeError: ... 'AnalysisConfig' object has no attribute 'set_optimization_level'`
- **원인**: `paddleocr 3.x`가 설치됨 (paddlepaddle 2.6.x와 비호환)
- **해결**: 2.x 계열로 재설치

```bash
pip uninstall paddlepaddle-gpu paddleocr paddlex -y
pip install paddlepaddle-gpu==2.6.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
pip install paddleocr==2.8.1
```

### `ValueError: Unknown argument: show_log` (또는 `use_angle_cls`, `use_gpu`)
- **원인**: `paddleocr 3.x`에서 제거된 파라미터를 2.x용 코드가 호출
- **해결**: 위와 동일하게 paddleocr 2.8.x로 다운그레이드

### `getaddrinfo failed` / `Failed to resolve 'paddleocr.bj.bcebos.com'`
- **원인**: 로컬/사내 DNS가 바이두 CDN 도메인(`*.bcebos.com`)을 해석하지 못함
- **확인**: 로컬 DNS는 실패하지만 공용 DNS로는 해석됨

```bash
nslookup paddleocr.bj.bcebos.com          # 실패(timeout)할 수 있음
nslookup paddleocr.bj.bcebos.com 8.8.8.8  # 공용 DNS로는 IP 반환됨
```

- **해결**: `scripts/download_models.py`가 해석 실패 시 확인된 CDN IP(`103.235.47.176`)로
  자동 폴백하므로 그대로 실행하면 된다. IP가 바뀌어 폴백이 실패하면:
  1. 공용 DNS로 최신 IP 조회: `nslookup paddleocr.bj.bcebos.com 8.8.8.8`
  2. `download_models.py`의 `_BAIDU_CDN_FALLBACK_IP` 값을 최신 IP로 교체
  3. 또는 관리자 권한으로 `hosts` 파일(`C:\Windows\System32\drivers\etc\hosts`)에
     `{IP} paddleocr.bj.bcebos.com` 등록

### 모델을 다시 받고 싶을 때
- 캐시 삭제 후 재실행: `~/.paddleocr/whl/` (Windows: `C:\Users\{사용자}\.paddleocr\whl\`) 폴더 삭제
