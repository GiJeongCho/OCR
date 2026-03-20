"""
OCR Pipeline 로깅 설정
"""
import logging
import sys


def setup_logging(level: int = logging.INFO):
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger("src")
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)

    return root
