"""
OCR Pipeline 중앙 설정
환경변수 > 기본값 순서로 로드
"""
import os

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
MD_OUTPUT_DIR = os.path.join(DATA_DIR, "3_final_markdown")

SERVER_HOST = os.getenv("OCR_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("OCR_PORT", "8031"))

LIBREOFFICE_TIMEOUT = 120
