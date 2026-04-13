"""
Version 2 (손글씨) Chandra CLI 통합 엔진
Chandra가 레이아웃 분석 + OCR + 마크다운 생성을 한번에 수행
"""
import os
import subprocess
import json
import shutil
import time


def check_chandra() -> bool:
    """Chandra CLI 설치 여부 확인"""
    return shutil.which("chandra") is not None


def run_chandra(file_path: str, output_root: str) -> dict:
    """
    Chandra CLI를 실행하여 문서를 분석

    Args:
        file_path: 입력 파일 경로 (이미지 또는 PDF)
        output_root: 결과 저장 루트 디렉토리

    Returns:
        {
            "task_id": str,
            "original_filename": str,
            "output_dir": str,
            "markdown_file": str or None,
            "html_file": str or None,
            "images": [str],
            "full_text": str,
            "pages": [{"page_num": int, "text": str, "tables": [], "images": []}]
        }
    """
    if not check_chandra():
        raise RuntimeError("Chandra CLI가 설치되어 있지 않습니다.")

    file_name = os.path.splitext(os.path.basename(file_path))[0]
    task_id = f"{file_name}_{int(time.time())}"
    output_dir = os.path.join(output_root, task_id)

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    print(f"🚀 [Chandra] Processing: {file_path}")
    print(f"📂 [Chandra] Output: {output_dir}")

    command = ["chandra", file_path, output_dir]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        print("✅ [Chandra] 처리 완료")
    except subprocess.CalledProcessError as e:
        print(f"❌ [Chandra] CLI 오류: {e.stderr}")
        raise RuntimeError(f"Chandra 처리 실패: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Chandra 처리 타임아웃 (300초)")

    # 결과 파싱
    result_data = {
        "task_id": task_id,
        "original_filename": os.path.basename(file_path),
        "output_dir": output_dir,
        "markdown_file": None,
        "html_file": None,
        "images": [],
        "full_text": "",
        "pages": [],
    }

    for root, dirs, files in os.walk(output_dir):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, output_root)

            if file.endswith(".md"):
                result_data["markdown_file"] = rel_path
                with open(full_path, "r", encoding="utf-8") as f:
                    result_data["full_text"] = f.read()

            elif file.endswith(".html"):
                result_data["html_file"] = rel_path

            elif file.lower().endswith((".png", ".jpg", ".jpeg")):
                result_data["images"].append(rel_path)

    # 페이지 데이터 생성 (마크다운 기반)
    if result_data["full_text"]:
        result_data["pages"] = _split_to_pages(result_data["full_text"], result_data["images"])

    # 메타데이터 저장
    meta_path = os.path.join(output_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {k: v for k, v in result_data.items() if k != "pages"},
            f,
            indent=2,
            ensure_ascii=False,
        )

    return result_data


def _split_to_pages(full_text: str, images: list) -> list:
    """
    마크다운 텍스트를 페이지 단위로 분할
    Chandra가 페이지 구분자를 넣지 않으면 전체를 단일 페이지로 취급
    """
    # 페이지 구분자 패턴 (Chandra 출력에 따라 조정 필요)
    import re
    page_splits = re.split(r"(?:---|\n#{1,2}\s*Page\s*\d+)", full_text)

    if len(page_splits) <= 1:
        return [{
            "page_num": 1,
            "text": full_text.strip(),
            "tables": [],
            "images": images,
        }]

    pages = []
    for i, section in enumerate(page_splits):
        section = section.strip()
        if section:
            pages.append({
                "page_num": i + 1,
                "text": section,
                "tables": [],
                "images": [],
            })

    # 이미지를 첫 페이지에 할당 (추후 개선 가능)
    if pages and images:
        pages[0]["images"] = images

    return pages


def process_handwritten(file_path: str, output_root: str) -> list:
    """
    손글씨 문서를 Chandra로 처리하고 페이지 결과 반환

    Args:
        file_path: 입력 파일 경로
        output_root: 출력 루트 디렉토리

    Returns:
        [{"page_num": int, "text": str, "tables": [], "images": []}, ...]
    """
    result = run_chandra(file_path, output_root)
    return result["pages"]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python chandra_engine.py <input_file>")
        exit()

    if not check_chandra():
        print("❌ Chandra CLI가 설치되어 있지 않습니다.")
        exit()

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_root = os.path.join(BASE_DIR, "data", "chandra_output")

    result = run_chandra(sys.argv[1], output_root)
    print(f"\n📄 결과:")
    print(f"   Markdown: {result['markdown_file']}")
    print(f"   텍스트 길이: {len(result['full_text'])} chars")
    print(f"   이미지: {len(result['images'])}개")
    print(f"   페이지: {len(result['pages'])}개")
