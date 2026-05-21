# OCR 서비스 - 개발 표준

> 이 문서는 OCR 백엔드(FastAPI + PaddleOCR + LibreOffice) 개발 시 **반드시 지켜야 할 코드/구조/운영 규칙**입니다.
> 신규 추출기/엔진을 추가하거나 새 API 버전을 만들 때 이 문서를 우선 참조하세요.

---

## 1. 디렉토리 & 모듈 규칙

### 1.1 레이어 분리

| 레이어 | 위치 | 책임 |
|--------|------|------|
| API | `src/api_server.py` | FastAPI 라우팅, 요청/응답 모델, 임시파일 관리 |
| 파이프라인 | `src/v{N}_*/` | 입력 포맷별 추출 로직 (활자체: `v1_printed`) |
| 공용 유틸 | `src/common/` | 설정, 로깅, Markdown 빌더, 표 포매터 |
| 자원 | `data/`, `scripts/` | 입출력 데이터 / 모델 다운로드 스크립트 |

> **금지**: API 핸들러 안에서 직접 OCR 추론을 호출하지 않는다. 항상 `v1_printed/document_loader.process_document()` 처럼 파이프라인을 거친다.

### 1.2 API 버저닝
- 활자체 v1: `src/v1_printed/`
- 손글씨 v2: `src/v2_handwritten/`
- 새로운 알고리즘은 `src/vN_<purpose>/` 로 분리해 신설. **기존 폴더는 깨지 않는다.**

### 1.3 네이밍
- 파일/모듈: `snake_case`
- 클래스: `PascalCase`
- 상수: `UPPER_SNAKE`
- FastAPI 응답 모델: `<Domain>Response` (예: `OCRResponse`, `PageResult`)

---

## 2. 의존성 / 패키지 관리

- **패키지 매니저**: `pip` + `requirements.txt` (Docker 빌드 캐시 최적화를 위해 그대로 유지).
- 신규 라이브러리 추가 시:
  1. 최소 버전 명시 (`pkg>=1.2.3`).
  2. **GPU 종속 패키지는 별도 그룹 주석**으로 구분 (`# === 스캔 PDF OCR 폴백 ===`).
  3. CPU/GPU 양쪽 모두에서 import 가능해야 한다(런타임 분기).
- **로컬 캐시 절대 커밋 금지**: `__pycache__`, `*.db` (단, 운영용 `ocr_data.db`는 예외 — 변경 시 PR 설명 필수).

---

## 3. 코드 스타일

### 3.1 일반
- Python 표준: **PEP8**, 4-space, 한 줄 100자.
- import 순서: 표준 → 서드파티 → 로컬 (`from .common ...`).
- 모듈 docstring은 1~3줄로 **무엇을 하는지** 명시(예: `api_server.py` 의 첫 줄).

### 3.2 타입 힌트
- **public 함수/엔드포인트는 타입 힌트 필수**.
- 응답은 Pydantic 모델로 정의 (절대 `dict` 그대로 반환하지 않음).

### 3.3 로깅
- `from src.common.logger import setup_logging` → `setup_logging()` 후 `logging.getLogger(__name__)` 사용.
- `print` 금지. (디버그도 `logger.debug`).
- 예외는 `logger.exception("...")` 으로 traceback 포함.

### 3.4 예외 처리
- API 레이어 예외 = `HTTPException(status_code=..., detail=str(e))` 로 변환.
- 임시 파일은 **반드시 `finally` 절에서 삭제**(현재 `api_server.py` 패턴 준수).
- 라이브러리 예외(`paddleocr`, `pdfplumber`)는 파이프라인 내부에서 잡고, 의미있는 메시지로 재던지기.

---

## 4. API 표준

### 4.1 엔드포인트
- `POST /ocr/process` — 동기 처리. 결과를 `OCRResponse` 로 반환.
- `GET /health` — 항상 다음 필드 포함:
  - `status`, `libreoffice_available`, `supported_formats`, `mode`, `llm_correction`
- 신규 엔드포인트는 `/ocr/<verb>` 패턴.

### 4.2 응답 모델
- 페이지 단위 결과는 `PageResult { page_num, text, tables[], images[] }`.
- 표는 **Markdown 문자열** 형태로 보관 (`table_formatter.py` 사용).
- 이미지 경로는 `/static/...` URL.

### 4.3 파일 업로드
- 업로드는 항상 `tempfile.NamedTemporaryFile` 로 임시 저장 후 처리.
- 원본 확장자(`suffix`)를 보존해야 추출기가 포맷을 판별한다.

---

## 5. 추출기(Extractor) 추가 규칙

신규 입력 포맷을 추가할 때:

1. `src/v1_printed/<format>_extractor.py` 생성.
2. 진입함수 시그니처:
   ```python
   def extract(file_path: str, image_output_dir: str | None = None) -> list[dict]:
       """반환: [{"page_num": int|str, "text": str, "tables": list[str], "images": list[str]}]"""
   ```
3. `document_loader.process_document()` 의 분기에 등록.
4. `/health` 의 `supported_formats` 갱신.
5. 단위 테스트 샘플은 `test_Data/` 에 추가.

---

## 6. GPU / 모델 운영 규칙

- PaddleOCR 모델은 **컨테이너 빌드 시 함께 패키징**하거나, 외부 볼륨으로 마운트.
- 모델 다운로드는 `scripts/download_models.py` 만 사용. 다른 곳에서 임의 다운로드 금지.
- 오프라인 운영을 위해 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` 는 `common/config.py` 에서 강제로 설정 — **삭제 금지**.
- GPU 미가용 시 자동으로 CPU fallback 가능해야 함(향후 개선 대상).

---

## 7. LibreOffice (HWP/HWPX) 규칙

- LibreOffice CLI 호출은 반드시 `src/v1_printed/hwp_converter.py` 를 통해서만.
- 타임아웃은 `common/config.LIBREOFFICE_TIMEOUT` 기준. **직접 하드코딩 금지.**
- 변환 산출물(임시 파일)은 함수 종료 전 모두 정리.

---

## 8. Docker / 배포 표준

- Base image: `python:3.11-slim` (변경 시 보안 패치 정책 합의).
- `EXPOSE ${APP_PORT}` 와 `CMD ["sh","-c","uvicorn ... --port ${APP_PORT}"]` 패턴 유지.
- 코드 변경은 `COPY src/` 만 캐시 무효화하도록 `requirements.txt` 를 먼저 복사한다.
- `.dockerignore` 에 `data/`, `test_Data/`, `__pycache__/`, `.git/`, `.venv/` 포함.

### 8.1 Jenkins 연동
- 이미지 태그: `IMG_OCR_API=<registry>/ocr-api:<env>` (`docker.sh` 의 `.env.<env>` 참조).
- 환경 분리:
  - dev → 포트 6000번대
  - stg → 9000번대
  - prd → 8000번대

---

## 9. 로깅 / 모니터링

| 항목 | 표준 |
|------|------|
| 로그 포맷 | `setup_logging()` 이 제공하는 포맷만 사용 |
| 요청 로그 | 최소 `파일명`, `모드`, `처리시간` 기록 |
| 에러 로그 | `logger.exception` (스택 포함) |
| 헬스체크 주기 | 10s (Jenkins/Compose `healthcheck` 권장) |

---

## 10. Git / 브랜치 / PR

- 브랜치: `feat/ocr-<topic>`, `fix/ocr-<topic>`, `chore/ocr-<topic>`.
- 커밋: `[ocr] <동사> <내용>` (예: `[ocr] add hwpx extractor`).
- PR 본문: **재현 가능한 입력 파일 + 변경 전/후 응답 JSON 첨부**.
- 모델/대용량 파일은 절대 커밋 금지(`*.pdmodel`, `*.safetensors`, `*.wav` 등).

---

## 11. 보안 / 데이터

- 업로드 파일은 처리 직후 삭제(현재 `finally` 패턴 준수).
- 외부에서 접근 가능한 정적 경로(`/static/...`)에는 **개인정보 포함 문서를 노출하지 않는다.** 운영 시에는 백엔드가 별도 권한검사를 거친 후 프록시.
- 로그에 파일 내용 본문을 그대로 적지 않는다.

---

## 12. 백엔드 연동 시 주의

- OCR 서비스는 **인증/권한 검사를 수행하지 않는다.** 호출자(백엔드) 측에서 처리.
- 동기 호출 — 큰 PDF는 수십 초까지 걸릴 수 있으므로 백엔드는 **별도 워커/큐 + Job 패턴** 권장.
- 백엔드는 `markdown_url` 을 받아 다운로드/저장하는 책임을 진다 (OCR 서비스는 보관 기간을 보장하지 않음).
