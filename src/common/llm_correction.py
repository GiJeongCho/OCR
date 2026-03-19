"""
OCR 결과를 로컬 Ollama LLM으로 교정 (V2 손글씨 전용, V1은 선택적)
"""
import requests

OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3:latest"


def correct_text_with_llm(raw_text: str, timeout: int = 60) -> str:
    """
    OCR 결과 텍스트를 LLM에 보내 오타 수정 및 마크다운 포맷팅 보정

    Args:
        raw_text: OCR 원본 텍스트
        timeout: API 호출 타임아웃 (초)

    Returns:
        교정된 텍스트 (실패 시 원본 반환)
    """
    if not raw_text or len(raw_text.strip()) < 10:
        return raw_text

    prompt = f"""You are a professional editor. Correct the OCR errors in the following text.

Rules:
1. Fix typos and grammatical errors (especially Korean/English mix-ups).
2. Improve Markdown formatting (headers, lists, bold).
3. DO NOT summarize or omit any content. Keep the original meaning 100%.
4. Output ONLY the corrected text. No explanations.

Input Text:
{raw_text}"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 4096,
        },
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=timeout)
        response.raise_for_status()

        result = response.json()
        corrected_text = result.get("response", "").strip()

        if not corrected_text:
            return raw_text

        return corrected_text

    except Exception as e:
        print(f"⚠️ LLM Correction Failed: {e}")
        return raw_text
