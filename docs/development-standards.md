# OCR 서비스 - 개발 표준

문서 버전: 1.0
대상 독자: 백엔드/AI 개발자, DevOps
관련 문서: [`./development-environment.md`](./development-environment.md)

---

## 목차

1. 개요
2. 개발환경
   2.1 개발환경 구성도
   2.2 개발절차
   2.3 개발자 PC 구성 내역
   2.4 IDE (Cursor / VSCode / PyCharm)
   2.5 소스 관리 (사내 Git + GitHub 미러)
   2.6 모델 / 패키지 / 이미지 저장소
   2.7 IDE 설정 및 런타임 설치
       2.7.1 IDE 설정 (Cursor / VSCode)
       2.7.2 Python / uv 설치
       2.7.3 시스템 의존성 (LibreOffice / OpenCV 런타임)
       2.7.4 CUDA / NVIDIA Container Toolkit
       2.7.5 Docker / Compose
       2.7.6 모델 가중치 배치 (PaddleOCR)
3. 디렉토리 & 모듈 표준
4. 의존성 / 패키지 관리 표준
5. 코드 스타일 표준
6. API 표준
7. 추출기(Extractor) 추가 규칙
8. GPU / 모델 운영 규칙
9. LibreOffice (HWP/HWPX) 규칙
10. Docker / 배포 표준
11. 로깅 / 모니터링
12. Git / 브랜치 / PR
13. 보안 / 데이터
14. 백엔드 연동 시 주의

---

## 1. 개요

본 문서는 OCR 서비스(`/home/pps-nipa/jenkins/dev/ocr`)의 **개발 환경 구성 절차 / 소스 관리 / 모델 관리 / 코드 표준 / 배포 표준**을 정의합니다.
서비스는 활자체 문서(PDF/DOCX/HWP/HWPX)를 입력받아 텍스트·표·이미지를 추출하고 Markdown으로 변환하는 **AI/OCR 백엔드**이며, 다음 스택을 사용합니다.

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.11 |
| API | FastAPI + Uvicorn |
| OCR 엔진 | PaddleOCR (GPU) |
| 직접 추출 | pdfplumber / python-docx / lxml / pypdfium2 |
| HWP 변환 | LibreOffice (CLI headless) |
| 컨테이너 | Docker / docker compose |
| CI | Jenkins (`/home/pps-nipa/jenkins/`) |

---

## 2. 개발환경

### 2.1 개발환경 구성도

```
┌──────────────────────────────────────────────────────────────────┐
│                          개발자 PC                                │
│   Cursor IDE / VSCode  ──────────────  Python 3.11 + venv         │
│        │                                       │                  │
│        │ SSH/HTTPS                              │ docker          │
│        ▼                                        ▼                  │
└────────┼────────────────────────────────────────┼──────────────────┘
         │                                        │
         ▼                                        ▼
┌────────────────────┐                  ┌───────────────────────────┐
│  사내 Git (Gitea)   │ ◄── git push ──► │   GitHub 미러             │
│  narea/ocr.git     │                  │   GiJeongCho/OCR          │
└────────┬───────────┘                  └───────────────────────────┘
         │ clone/pull
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Jenkins 서버                                │
│  jenkins.sh / dev/git_clone.sh / dev/model_download.sh           │
│  dev/docker.sh dev up ocr_api                                     │
│                            │                                      │
│                            ▼                                      │
│        ┌───────────────────────────────────────┐                  │
│        │  ocr_api 컨테이너 (FastAPI + Paddle)  │ ◄── /ocr/process │
│        │  /app/src + /app/data                 │                  │
│        └───────────────────────────────────────┘                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 개발절차

1. 개발자 PC에 IDE, Python, uv/pip, Docker, NVIDIA 드라이버를 설치한다.
2. SSH 키를 사내 Git(`git.biz.ppsystem.co.kr`)과 GitHub에 등록한다.
3. `git clone ssh://git@git.biz.ppsystem.co.kr:10022/narea/ocr.git` 또는 `dev/git_clone.sh` 로 일괄 clone.
4. 가상환경 생성 → `pip install -r requirements.txt` 또는 `uv pip install ...`.
5. 로컬에서 시스템 의존성(LibreOffice, OpenCV 런타임) 설치.
6. PaddleOCR 모델 사전 다운로드 (`python scripts/download_models.py`).
7. `uvicorn src.api_server:app --reload` 로 실행 → `/health` 200 확인.
8. 기능 단위 PR → 사내 Git 에 push (자동으로 GitHub 미러에도 push).
9. Jenkins Job 트리거 → 이미지 빌드 → dev/stg/prd 배포.
10. 배포 후 `/health` + 스모크 테스트 수행.

### 2.3 개발자 PC 구성 내역

| 항목 | 최소 | 권장 | 비고 |
|------|------|------|------|
| OS | Ubuntu 20.04 LTS | Ubuntu 22.04 LTS | macOS는 PaddleOCR GPU 미지원 → CPU만 가능 |
| CPU | 4 core | 8 core+ | |
| RAM | 16 GB | 32 GB | LibreOffice 변환 동시 실행 시 메모리 사용 |
| Disk | 50 GB | 200 GB SSD | 모델/샘플 데이터 포함 |
| GPU | 없음 (CPU 가능) | NVIDIA RTX 3060 12GB+ | Paddle GPU 사용 시 CUDA 11.8/12.x |
| Python | 3.11.x | 3.11.x | |
| Docker | 24.x | 26.x | `docker compose` 플러그인 |
| LibreOffice | 7.x | 7.x | HWP/HWPX 변환 |

### 2.4 IDE (Cursor / VSCode / PyCharm)

- **권장**: Cursor (현재 사내 표준) 또는 VSCode.
- 대안: PyCharm Professional (Docker remote interpreter 활용).
- 필수 확장:
  - **Python** (Microsoft) — Pylance, 디버거
  - **Ruff** — 린트/포맷 (PEP8)
  - **Pylance** — 타입 인식
  - **Docker** — 컨테이너 디버깅
  - **Even Better TOML** — `pyproject` 편집
  - **GitLens** — 사내/GitHub 양쪽 히스토리 추적

### 2.5 소스 관리 (사내 Git + GitHub 미러)

- 사내 Git: `ssh://git@git.biz.ppsystem.co.kr:10022/narea/ocr.git`
- GitHub 미러: `https://github.com/GiJeongCho/OCR.git`
- 현재 `origin` 에 **fetch URL 1개 + push URL 2개** 가 설정되어 있어, `git push origin <branch>` 한 번으로 양쪽에 동시 반영됩니다.
- 인증:
  - 사내 Git → `~/.ssh/id_ed25519` 키 등록
  - GitHub → PAT 또는 `~/.git-credentials` 의 GitHub 자격증명
- 검증 명령:
  ```bash
  cd /home/pps-nipa/jenkins/dev/ocr
  git remote -v
  # origin  <사내 git> (fetch)
  # origin  <사내 git> (push)
  # origin  https://github.com/GiJeongCho/OCR.git (push)
  ```

### 2.6 모델 / 패키지 / 이미지 저장소

| 자원 | 저장소 | 비고 |
|------|--------|------|
| PaddleOCR 모델 | (1차) PaddleX 공식 / (2차) 사내 NAS 미러 | 오프라인 운영 시 사내 미러 필수 |
| Python 패키지 | PyPI / 사내 Nexus(PyPI proxy) | 인터넷 차단 망에서는 Nexus 사용 |
| Docker 이미지 | 사내 Registry (`.env.<env>` 의 `IMG_OCR_API`) | dev/stg/prd 태그 분리 |
| Git LFS | 사용 안 함 | 모델은 코드에 포함하지 않음 |

### 2.7 IDE 설정 및 런타임 설치

#### 2.7.1 IDE 설정 (Cursor / VSCode)

`.vscode/settings.json` 권장 값:

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.analysis.typeCheckingMode": "basic",
  "python.analysis.autoImportCompletions": true,
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": { "source.organizeImports": "explicit" },
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.tabSize": 4
  },
  "files.exclude": {
    "**/__pycache__": true,
    "**/.pytest_cache": true,
    "**/*.egg-info": true
  }
}
```

`.vscode/launch.json` (디버그):

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "OCR API (uvicorn)",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["src.api_server:app", "--host", "0.0.0.0", "--port", "8031", "--reload"],
      "env": { "OCR_PORT": "8031", "PYTHONPATH": "${workspaceFolder}" },
      "console": "integratedTerminal",
      "justMyCode": false
    }
  ]
}
```

#### 2.7.2 Python / uv 설치

```bash
# Python 3.11 (Ubuntu)
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

# pip (requirements.txt 사용)
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

# (선택) uv 사용 시
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 2.7.3 시스템 의존성 (LibreOffice / OpenCV 런타임)

```bash
sudo apt-get update
sudo apt-get install -y \
  libreoffice \
  libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
  fonts-nanum
# 검증
libreoffice --headless --version
```

#### 2.7.4 CUDA / NVIDIA Container Toolkit

```bash
# NVIDIA 드라이버 (Ubuntu)
sudo apt-get install -y nvidia-driver-535
nvidia-smi

# Container Toolkit
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

#### 2.7.5 Docker / Compose

```bash
# 공식 저장소
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
docker compose version
```

#### 2.7.6 모델 가중치 배치 (PaddleOCR)

```bash
cd /home/pps-nipa/jenkins/dev/ocr
python scripts/download_models.py
# 다운로드 위치: PaddleX 기본 캐시 (~/.paddlex)
# 오프라인 배포 시 ~/.paddlex 디렉토리를 컨테이너에 마운트
```

---

## 3. 디렉토리 & 모듈 표준

### 3.1 레이어 분리

| 레이어 | 위치 | 책임 |
|--------|------|------|
| API | `src/api_server.py` | FastAPI 라우팅, 요청/응답 모델, 임시파일 관리 |
| 파이프라인 | `src/v{N}_*/` | 입력 포맷별 추출 로직 (활자체: `v1_printed`) |
| 공용 유틸 | `src/common/` | 설정, 로깅, Markdown 빌더, 표 포매터 |
| 자원 | `data/`, `scripts/` | 입출력 데이터 / 모델 다운로드 스크립트 |

> **금지**: API 핸들러 안에서 직접 OCR 추론을 호출하지 않는다. 항상 `v1_printed/document_loader.process_document()` 처럼 파이프라인을 거친다.

### 3.2 API 버저닝
- 활자체 v1: `src/v1_printed/`
- 손글씨 v2: `src/v2_handwritten/`
- 새 알고리즘은 `src/vN_<purpose>/` 로 분리해 신설. **기존 폴더는 깨지 않는다.**

### 3.3 네이밍
- 파일/모듈: `snake_case`
- 클래스: `PascalCase`
- 상수: `UPPER_SNAKE`
- FastAPI 응답 모델: `<Domain>Response` (예: `OCRResponse`, `PageResult`)

---

## 4. 의존성 / 패키지 관리 표준

- **패키지 매니저**: `pip` + `requirements.txt` (Docker 빌드 캐시 최적화 목적). uv 도입 시에는 `pyproject.toml` 동기 갱신 필수.
- 신규 라이브러리:
  1. 최소 버전 명시 (`pkg>=1.2.3`).
  2. GPU 종속 패키지는 별도 그룹 주석 (`# === 스캔 PDF OCR 폴백 ===`).
  3. CPU/GPU 양쪽에서 import 가능해야 한다(런타임 분기).
- 캐시/대용량 파일 커밋 금지: `__pycache__`, `*.db` (단 운영용 `ocr_data.db`는 예외 — 변경 시 PR 설명 필수).
- 사내 Nexus PyPI proxy 사용 시 `pip.conf` 예:
  ```
  [global]
  index-url = https://nexus.biz.ppsystem.co.kr/repository/pypi-proxy/simple/
  trusted-host = nexus.biz.ppsystem.co.kr
  ```

---

## 5. 코드 스타일 표준

### 5.1 일반
- PEP8, 4-space, 한 줄 100자.
- import 순서: 표준 → 서드파티 → 로컬 (`from .common ...`).
- 모듈 docstring은 1~3줄로 **무엇을 하는지** 명시.
- 포맷터: `ruff format` (Black 호환). 린터: `ruff check`.

### 5.2 타입 힌트
- public 함수/엔드포인트는 타입 힌트 필수.
- 응답은 Pydantic 모델로 정의 (절대 `dict` 그대로 반환 금지).

### 5.3 로깅
- `from src.common.logger import setup_logging` → `setup_logging()` 후 `logging.getLogger(__name__)` 사용.
- `print` 금지. 디버그도 `logger.debug`.
- 예외는 `logger.exception("...")` 으로 traceback 포함.

### 5.4 예외 처리
- API 레이어 예외 = `HTTPException(status_code=..., detail=str(e))`.
- 임시 파일은 **반드시 `finally` 절에서 삭제**.
- 라이브러리 예외(`paddleocr`, `pdfplumber`)는 파이프라인 내부에서 잡고, 의미있는 메시지로 재던지기.

---

## 6. API 표준

### 6.1 엔드포인트
- `POST /ocr/process` — 동기 처리. 결과를 `OCRResponse` 로 반환.
- `GET /health` — 항상 다음 필드 포함: `status`, `libreoffice_available`, `supported_formats`, `mode`, `llm_correction`.
- 신규 엔드포인트는 `/ocr/<verb>` 패턴.

### 6.2 응답 모델
- 페이지 단위 결과는 `PageResult { page_num, text, tables[], images[] }`.
- 표는 **Markdown 문자열** 형태 (`table_formatter.py` 사용).
- 이미지 경로는 `/static/...` URL.

### 6.3 파일 업로드
- `tempfile.NamedTemporaryFile` 로 임시 저장 후 처리.
- 원본 확장자(`suffix`)를 보존해야 포맷 판별 가능.

---

## 7. 추출기(Extractor) 추가 규칙

신규 입력 포맷 추가 시:

1. `src/v1_printed/<format>_extractor.py` 생성.
2. 진입 함수 시그니처:
   ```python
   def extract(file_path: str, image_output_dir: str | None = None) -> list[dict]:
       """반환: [{"page_num": int|str, "text": str, "tables": list[str], "images": list[str]}]"""
   ```
3. `document_loader.process_document()` 분기에 등록.
4. `/health` 의 `supported_formats` 갱신.
5. 단위 테스트 샘플은 `test_Data/` 에 추가.

---

## 8. GPU / 모델 운영 규칙

- PaddleOCR 모델은 **컨테이너 빌드 시 함께 패키징**하거나 외부 볼륨 마운트.
- 모델 다운로드는 `scripts/download_models.py` 로만. 다른 곳에서 임의 다운로드 금지.
- 오프라인 운영을 위해 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` 는 `common/config.py` 에서 강제 설정 — **삭제 금지**.
- GPU 미가용 시 자동 CPU fallback (향후 개선 대상).

---

## 9. LibreOffice (HWP/HWPX) 규칙

- LibreOffice CLI 호출은 반드시 `src/v1_printed/hwp_converter.py` 를 통해서만.
- 타임아웃은 `common/config.LIBREOFFICE_TIMEOUT` 기준. **직접 하드코딩 금지.**
- 변환 산출물(임시 파일)은 함수 종료 전 모두 정리.

---

## 10. Docker / 배포 표준

- Base image: `python:3.11-slim`.
- `EXPOSE ${APP_PORT}` 와 `CMD ["sh","-c","uvicorn src.api_server:app --host 0.0.0.0 --port ${APP_PORT}"]` 유지.
- 코드 변경 시 캐시 효율을 위해 `requirements.txt` 를 먼저 복사.
- `.dockerignore`: `data/`, `test_Data/`, `__pycache__/`, `.git/`, `.venv/`.

### 10.1 Jenkins 연동
- 이미지 태그: `IMG_OCR_API=<registry>/ocr-api:<env>` (`.env.<env>` 참조).
- 환경 분리: dev 6031 / stg 9031 / prd 8031.

### 10.2 헬스체크
```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "http://localhost:${APP_PORT}/health"]
  interval: 30s
  timeout: 5s
  retries: 5
```

---

## 11. 로깅 / 모니터링

| 항목 | 표준 |
|------|------|
| 로그 포맷 | `setup_logging()` 이 제공하는 포맷만 사용 |
| 요청 로그 | 최소 `파일명`, `모드`, `처리시간` 기록 |
| 에러 로그 | `logger.exception` |
| 헬스체크 주기 | 10s |
| 로그 보관 | docker 기본 driver (`json-file`) → 외부 수집기로 전달 |

---

## 12. Git / 브랜치 / PR

- 브랜치: `feat/ocr-<topic>`, `fix/ocr-<topic>`, `chore/ocr-<topic>`.
- 커밋 메시지: `[ocr] <동사> <내용>` (예: `[ocr] add hwpx extractor`).
- PR 본문: **재현 가능한 입력 파일 + 변경 전/후 응답 JSON 첨부**.
- 모델/대용량 파일은 절대 커밋 금지(`*.pdmodel`, `*.safetensors`, `*.wav`).
- 사내 Git + GitHub 미러 동시 push 가 기본 동작.

---

## 13. 보안 / 데이터

- 업로드 파일은 처리 직후 삭제 (`finally` 패턴 준수).
- `/static/...` 정적 경로에는 **개인정보 포함 문서 노출 금지**. 운영 시 백엔드 권한 검사 후 프록시.
- 로그에 파일 본문을 그대로 적지 않는다.

---

## 14. 백엔드 연동 시 주의

- OCR 서비스는 **인증/권한 검사를 수행하지 않는다.** 호출자(백엔드) 측에서 처리.
- 동기 호출 — 큰 PDF는 수십 초까지 걸릴 수 있으므로 백엔드는 **별도 워커/큐 + Job 패턴** 권장.
- 백엔드는 `markdown_url` 을 받아 다운로드/저장하는 책임을 진다 (OCR 서비스는 보관 기간을 보장하지 않음).
- 타임아웃: connect 5s, read 120s 이상 권장.
