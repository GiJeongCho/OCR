"""
PaddleOCR / PPStructure 모델 사전 다운로드 스크립트

Docker 빌드 또는 최초 배포 시 실행하면 런타임에 다운로드 대기가 없어집니다.
모델은 ~/.paddleocr/ 하위에 캐시됩니다.

Usage:
    python scripts/download_models.py
    python scripts/download_models.py --output-dir /app/models
"""
import argparse
import os
import socket
import sys

# 일부 사내/로컬 DNS는 모델 서버(바이두 bcebos.com CDN)를 해석하지 못한다.
# 정상 해석이 가능하면 그대로 쓰고, 실패할 때만 확인된 CDN IP로 폴백한다.
# (SNI/Host 헤더는 원래 도메인이 유지되므로 TLS 인증서 검증에는 영향 없음)
_BAIDU_CDN_FALLBACK_IP = "103.235.47.176"
_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_with_fallback(host, *args, **kwargs):
    try:
        return _orig_getaddrinfo(host, *args, **kwargs)
    except socket.gaierror:
        if isinstance(host, str) and host.endswith("bcebos.com"):
            return _orig_getaddrinfo(_BAIDU_CDN_FALLBACK_IP, *args, **kwargs)
        raise


socket.getaddrinfo = _getaddrinfo_with_fallback


def download_paddleocr(output_dir: str | None = None):
    """PaddleOCR 한국어 모델 다운로드 (detection + recognition + angle classifier)"""
    from paddleocr import PaddleOCR

    kwargs = dict(
        use_angle_cls=True,
        lang="korean",
        use_gpu=False,
        show_log=True,
    )
    if output_dir:
        det_dir = os.path.join(output_dir, "det")
        rec_dir = os.path.join(output_dir, "rec")
        cls_dir = os.path.join(output_dir, "cls")
        os.makedirs(det_dir, exist_ok=True)
        os.makedirs(rec_dir, exist_ok=True)
        os.makedirs(cls_dir, exist_ok=True)
        kwargs.update(det_model_dir=det_dir, rec_model_dir=rec_dir, cls_model_dir=cls_dir)

    print("[1/2] PaddleOCR 한국어 모델 다운로드 중...")
    ocr = PaddleOCR(**kwargs)
    print("      PaddleOCR 모델 준비 완료\n")
    return ocr


def download_ppstructure(output_dir: str | None = None):
    """PPStructure 표 인식 모델 다운로드 (layout + table + OCR)"""
    try:
        from paddleocr import PPStructure
        from paddleocr.paddleocr import MODEL_URLS

        ch_layout = MODEL_URLS["STRUCTURE"]["PP-StructureV2"]["layout"]["ch"]
        MODEL_URLS["STRUCTURE"]["PP-StructureV2"]["layout"]["korean"] = ch_layout

        print("[2/2] PPStructure 표 인식 모델 다운로드 중...")
        engine = PPStructure(
            table=True,
            ocr=True,
            lang="korean",
            use_gpu=False,
            show_log=True,
        )
        print("      PPStructure 모델 준비 완료\n")
        return engine
    except (Exception, SystemExit) as e:
        print(f"      PPStructure 다운로드 실패 (선택 사항): {e}\n")
        return None


def main():
    parser = argparse.ArgumentParser(description="OCR 모델 사전 다운로드")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="모델 저장 경로 (미지정 시 ~/.paddleocr/ 기본 캐시 사용)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  OCR 모델 다운로드")
    print("=" * 50 + "\n")

    download_paddleocr(args.output_dir)
    download_ppstructure(args.output_dir)

    print("=" * 50)
    print("  모든 모델 다운로드 완료")
    print("=" * 50)


if __name__ == "__main__":
    main()
