"""
페이지별 추출 결과를 최종 마크다운 문서로 조립
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _strip_surrogates(text: str) -> str:
    """UTF-8로 저장할 수 없는 surrogate code point 제거."""
    return "".join(ch for ch in text if not 0xD800 <= ord(ch) <= 0xDFFF)


def build_markdown(pages: list, filename: str = "") -> str:
    """
    페이지별 텍스트/표 결과를 하나의 마크다운 문서로 조립

    V1(pdf_extractor)의 경우 표가 이미 text에 인라인 삽입되어 있으므로
    tables 필드는 text에 포함되지 않은 추가 표만 출력

    Args:
        pages: [{"page_num": 1, "text": "...", "tables": [...], "images": [...]}, ...]
        filename: 원본 파일명

    Returns:
        완성된 마크다운 문자열
    """
    parts = []

    if filename:
        parts.append(f"# {os.path.splitext(filename)[0]}\n")
        parts.append(f"> 처리일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    for page in pages:
        page_num = page.get("page_num", 0)
        text = page.get("text", "").strip()
        tables = page.get("tables", [])
        images = page.get("images", [])

        parts.append(f"\n---\n\n<!-- Page {page_num} -->\n")

        if text:
            parts.append(text)
            parts.append("")

        for table_md in tables:
            if table_md and table_md not in text:
                parts.append(f"\n{table_md}\n")

        for img_path in images:
            parts.append(f"\n![image]({img_path})\n")

    return "\n".join(parts)


def save_markdown(content: str, output_dir: str, filename: str) -> str:
    """
    마크다운 파일로 저장

    Args:
        content: 마크다운 텍스트
        output_dir: 출력 디렉토리
        filename: 파일명 (확장자 제외)

    Returns:
        저장된 파일 경로
    """
    os.makedirs(output_dir, exist_ok=True)
    md_filename = f"{filename}_result.md"
    save_path = os.path.join(output_dir, md_filename)
    sanitized_content = _strip_surrogates(content)

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(sanitized_content)

    logger.info("Markdown saved: %s", save_path)
    return save_path
