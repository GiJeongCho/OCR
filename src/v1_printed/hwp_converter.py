"""
HWP(한글 바이너리 포맷) → PDF 변환 후 pdf_extractor로 처리
변환 전략:
  1차) LibreOffice 직접 변환 (HWP → PDF)
  2차) pyhwp로 HWP → ODT → LibreOffice → PDF
  3차) olefile로 HWP 바이너리 직접 파싱 (텍스트+표 추출)
"""
import os
import struct
import subprocess
import tempfile
import shutil
import zlib
import logging

from ..common.config import LIBREOFFICE_TIMEOUT
from ..common.table_formatter import table_to_markdown
from ..common.pdf_utils import detect_footer_page_number

logger = logging.getLogger(__name__)


def check_libreoffice() -> bool:
    """LibreOffice 설치 여부 확인"""
    return shutil.which("libreoffice") is not None


# ============================================================
# LibreOffice 헬퍼
# ============================================================
def _run_libreoffice(input_path: str, output_dir: str, convert_to: str = "pdf") -> str | None:
    """LibreOffice headless 변환. 성공 시 파일 경로, 실패 시 None."""
    user_install_dir = tempfile.mkdtemp(prefix="lo_profile_")
    cmd = [
        "libreoffice", "--headless", "--norestore", "--nofirststartwizard",
        f"-env:UserInstallation=file://{user_install_dir}",
        "--convert-to", convert_to, "--outdir", output_dir,
        os.path.abspath(input_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=LIBREOFFICE_TIMEOUT)
        if result.stdout:
            logger.debug("LibreOffice stdout: %s", result.stdout.strip())
        if result.stderr:
            logger.debug("LibreOffice stderr: %s", result.stderr.strip())
        if result.returncode != 0:
            return None
    except subprocess.TimeoutExpired:
        logger.warning("LibreOffice 변환 타임아웃 (%d초)", LIBREOFFICE_TIMEOUT)
        return None
    finally:
        shutil.rmtree(user_install_dir, ignore_errors=True)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    expected = os.path.join(output_dir, f"{base_name}.{convert_to}")
    if os.path.exists(expected):
        return expected
    found = [f for f in os.listdir(output_dir) if f.endswith(f".{convert_to}")]
    return os.path.join(output_dir, found[0]) if found else None


# ============================================================
# 2차 폴백: pyhwp (HWP → ODT → PDF)
# ============================================================
def _convert_hwp_via_pyhwp(hwp_path: str, output_dir: str) -> str | None:
    """pyhwp(hwp5odt)로 HWP → ODT → LibreOffice → PDF. 실패 시 None."""
    try:
        import hwp5  # noqa: F401
    except ImportError:
        logger.debug("pyhwp 미설치, 건너뜀")
        return None

    odt_dir = tempfile.mkdtemp(prefix="hwp_odt_")
    base_name = os.path.splitext(os.path.basename(hwp_path))[0]
    odt_path = os.path.join(odt_dir, f"{base_name}.odt")
    logger.info("pyhwp: HWP → ODT 변환 중...")
    try:
        result = subprocess.run(
            ["hwp5odt", os.path.abspath(hwp_path), "--output", odt_path],
            capture_output=True, text=True, timeout=LIBREOFFICE_TIMEOUT,
        )
        if result.returncode != 0 or not os.path.exists(odt_path):
            stderr = result.stderr.strip() if result.stderr else "(없음)"
            logger.warning("hwp5odt 실패: %s", stderr[:200])
            return None
        logger.info("ODT 변환 완료, LibreOffice로 PDF 생성 중...")
        return _run_libreoffice(odt_path, output_dir, "pdf")
    except Exception as e:
        logger.warning("pyhwp 폴백 실패: %s", e)
        return None
    finally:
        shutil.rmtree(odt_dir, ignore_errors=True)


# ============================================================
# 3차 폴백: olefile 직접 HWP 바이너리 파싱
# ============================================================
HWPTAG_BEGIN = 0x010
HWPTAG_PARA_TEXT = HWPTAG_BEGIN + 51
HWPTAG_CTRL_HEADER = HWPTAG_BEGIN + 55
HWPTAG_LIST_HEADER = HWPTAG_BEGIN + 56
HWPTAG_TABLE = HWPTAG_BEGIN + 61

_EXTENDED_CONTROLS = frozenset(range(1, 24)) - {9, 10, 13}
GSO_CTRL_ID = b' osg'


def _parse_para_text(data: bytes) -> str:
    """HWPTAG_PARA_TEXT 레코드에서 텍스트 추출"""
    chars: list[str] = []
    i = 0
    length = len(data)
    while i + 1 < length:
        code = struct.unpack_from("<H", data, i)[0]
        i += 2
        if code == 0:
            continue
        if code in (10, 13):
            chars.append("\n")
            continue
        if code in _EXTENDED_CONTROLS:
            i += 14
            continue
        if code < 0x0020:
            continue
        if 0xD800 <= code <= 0xDFFF:
            continue
        chars.append(chr(code))
    return "".join(chars)


def _parse_records(data: bytes) -> list[tuple[int, int, bytes]]:
    """레코드 스트림을 (tag_id, level, data) 리스트로 파싱"""
    records = []
    pos = 0
    length = len(data)
    while pos + 4 <= length:
        header = struct.unpack_from("<I", data, pos)[0]
        tag_id = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            if pos + 8 > length:
                break
            size = struct.unpack_from("<I", data, pos + 4)[0]
            pos += 8
        else:
            pos += 4
        if pos + size > length:
            break
        records.append((tag_id, level, data[pos:pos + size]))
        pos += size
    return records


def _extract_native_table_at(records: list, start_idx: int) -> tuple[str, int]:
    """HWPTAG_TABLE 레코드부터 네이티브 테이블 파싱."""
    _, table_level, table_data = records[start_idx]
    nrows, ncols = 0, 0
    if len(table_data) >= 8:
        nrows = struct.unpack_from("<H", table_data, 4)[0]
        ncols = struct.unpack_from("<H", table_data, 6)[0]

    cells: list[str] = []
    cell_buf: list[str] | None = None
    j = start_idx + 1
    while j < len(records):
        tid, lv, rd = records[j]
        if lv < table_level:
            break
        if tid == HWPTAG_LIST_HEADER and lv == table_level:
            if cell_buf is not None:
                cells.append(" ".join(cell_buf))
            cell_buf = []
        elif tid == HWPTAG_PARA_TEXT and cell_buf is not None:
            text = _parse_para_text(rd).strip()
            if text:
                cell_buf.append(text)
        j += 1
    if cell_buf is not None:
        cells.append(" ".join(cell_buf))
    if not cells:
        return "", j

    n = len(cells)
    if nrows * ncols != n:
        if len(table_data) >= 6:
            alt_r = struct.unpack_from("<H", table_data, 2)[0]
            alt_c = struct.unpack_from("<H", table_data, 4)[0]
            if alt_r > 0 and alt_c > 0 and alt_r * alt_c == n:
                nrows, ncols = alt_r, alt_c
    if nrows * ncols != n:
        if ncols > 0 and ncols <= n:
            nrows = -(-n // ncols)
        elif nrows > 0 and nrows <= n:
            ncols = -(-n // nrows)
        else:
            ncols = min(n, 5)
            nrows = -(-n // ncols)

    table_2d = []
    for r in range(nrows):
        row = [cells[r * ncols + c] if r * ncols + c < n else "" for c in range(ncols)]
        table_2d.append(row)
    return table_to_markdown(table_2d), j


def _collect_shape_cells(records: list) -> list[tuple[int, int, int, str, int]]:
    """
    gso(그리기 객체) CTRL_HEADER에서 텍스트가 있는 셀을 수집.
    Returns: [(record_idx, vert_pos, horiz_pos, text, end_idx), ...]
    """
    cells = []
    i = 0
    while i < len(records):
        tid, lv, rd = records[i]
        if tid == HWPTAG_CTRL_HEADER and len(rd) >= 24 and rd[:4] == GSO_CTRL_ID:
            vert = struct.unpack_from("<i", rd, 8)[0]
            horiz = struct.unpack_from("<i", rd, 12)[0]
            texts = []
            j = i + 1
            while j < len(records):
                ct, cl, cd = records[j]
                if cl <= lv:
                    break
                if ct == HWPTAG_PARA_TEXT:
                    t = _parse_para_text(cd).strip()
                    if t:
                        texts.append(t)
                j += 1
            if texts:
                cells.append((i, vert, horiz, " ".join(texts), j))
        i += 1
    return cells


def _cluster_rows(cells: list, tolerance: int = 1500) -> list[list]:
    """세로 위치(vert)가 비슷한 셀들을 같은 행으로 클러스터링."""
    if not cells:
        return []
    sorted_cells = sorted(cells, key=lambda c: c[1])
    rows: list[list] = [[sorted_cells[0]]]
    for c in sorted_cells[1:]:
        if abs(c[1] - rows[-1][0][1]) <= tolerance:
            rows[-1].append(c)
        else:
            rows.append([c])
    for row in rows:
        row.sort(key=lambda c: c[2])
    return rows


def _cluster_columns(horiz_values: list[int], tolerance: int = 3000) -> list[int]:
    """수평 위치들을 컬럼으로 클러스터링하여 대표값(중앙값) 리스트 반환."""
    if not horiz_values:
        return []
    sorted_h = sorted(set(horiz_values))
    clusters: list[list[int]] = [[sorted_h[0]]]
    for h in sorted_h[1:]:
        if h - clusters[-1][-1] < tolerance:
            clusters[-1].append(h)
        else:
            clusters.append([h])
    return [cl[len(cl) // 2] for cl in clusters]


def _shapes_to_table(cells: list) -> str | None:
    """위치 기반으로 셀을 행/열 그리드로 배열하여 마크다운 테이블 생성."""
    rows = _cluster_rows(cells)
    if len(rows) < 1:
        return None
    max_cols = max(len(r) for r in rows)
    if max_cols < 2 and len(rows) < 2:
        return None

    col_centers = _cluster_columns([c[2] for c in cells])
    ncols = len(col_centers) if len(col_centers) >= max_cols else max_cols

    def _find_col(horiz: int) -> int:
        best, best_dist = 0, abs(horiz - col_centers[0])
        for ci, center in enumerate(col_centers[1:], 1):
            d = abs(horiz - center)
            if d < best_dist:
                best, best_dist = ci, d
        return best

    table_2d = []
    for row in rows:
        row_cells = [""] * ncols
        for c in row:
            ci = _find_col(c[2])
            if row_cells[ci]:
                row_cells[ci] += " " + c[3]
            else:
                row_cells[ci] = c[3]
        table_2d.append(row_cells)
    return table_to_markdown(table_2d)


def _count_horiz_clusters(cells: list, tolerance: int = 3000) -> int:
    """셀들의 수평 위치가 몇 개의 컬럼으로 나뉘는지 계산."""
    return len(_cluster_columns([c[2] for c in cells], tolerance))


def _group_shapes_spatially(cells: list) -> tuple[list[list], list]:
    """
    GSO 셀들을 공간 분석 기반으로 테이블 그룹과 본문 텍스트로 분리.

    전략:
      1. 셀들을 행(row)으로 클러스터링
      2. 멀티 컬럼(>=2) 행을 기준점으로 삼고, 그 사이의 싱글 컬럼 행도 표에 포함
      3. 마지막 멀티 컬럼 행 이후 싱글 컬럼 행은 간격이 작으면 표, 크면 본문
      4. 멀티 컬럼 행이 없는 구간은 본문 텍스트

    Returns: (table_groups, body_text_cells)
    """
    if not cells:
        return [], []

    rows = _cluster_rows(cells)
    if not rows:
        return [], []

    multi_col_indices = [
        i for i, row in enumerate(rows) if _count_horiz_clusters(row) >= 2
    ]

    if not multi_col_indices:
        return [], cells

    first_mc = multi_col_indices[0]
    last_mc = multi_col_indices[-1]

    row_verts = [min(c[1] for c in row) for row in rows]
    table_range_gaps = []
    for i in range(first_mc, last_mc):
        gap = abs(row_verts[i + 1] - row_verts[i])
        if gap > 0:
            table_range_gaps.append(gap)
    typical_gap = (
        sorted(table_range_gaps)[len(table_range_gaps) // 2]
        if table_range_gaps
        else 2500
    )

    table_rows_idx: set[int] = set()

    for i in range(first_mc, last_mc + 1):
        table_rows_idx.add(i)

    proximity_threshold = typical_gap * 1.5
    for i in range(last_mc + 1, len(rows)):
        gap = abs(row_verts[i] - row_verts[i - 1])
        if gap <= proximity_threshold:
            table_rows_idx.add(i)
        else:
            break

    for i in range(first_mc - 1, -1, -1):
        gap = abs(row_verts[i + 1] - row_verts[i])
        if gap <= proximity_threshold:
            table_rows_idx.add(i)
        else:
            break

    table_groups = []
    body_cells = []
    sorted_table_idx = sorted(table_rows_idx)

    if sorted_table_idx:
        current_group_rows = [rows[sorted_table_idx[0]]]
        for k in range(1, len(sorted_table_idx)):
            if sorted_table_idx[k] == sorted_table_idx[k - 1] + 1:
                current_group_rows.append(rows[sorted_table_idx[k]])
            else:
                flat = [c for row in current_group_rows for c in row]
                if _count_horiz_clusters(flat) >= 2 and len(flat) >= 4:
                    table_groups.append(flat)
                else:
                    body_cells.extend(flat)
                current_group_rows = [rows[sorted_table_idx[k]]]
        flat = [c for row in current_group_rows for c in row]
        if _count_horiz_clusters(flat) >= 2 and len(flat) >= 4:
            table_groups.append(flat)
        else:
            body_cells.extend(flat)

    for i, row in enumerate(rows):
        if i not in table_rows_idx:
            body_cells.extend(row)

    return table_groups, body_cells


def _parse_hwp_section(data: bytes) -> str:
    """하나의 BodyText/Section 스트림에서 텍스트+표를 추출."""
    records = _parse_records(data)

    native_table_starts: dict[int, tuple[int, str]] = {}
    native_table_indices: set[int] = set()
    i = 0
    while i < len(records):
        tid, lv, rd = records[i]
        if tid == HWPTAG_TABLE:
            md, end_i = _extract_native_table_at(records, i)
            native_table_starts[i] = (end_i, md)
            for k in range(i, end_i):
                native_table_indices.add(k)
            i = end_i
            continue
        i += 1

    shape_cells = _collect_shape_cells(records)
    table_groups, body_text_cells = _group_shapes_spatially(shape_cells)

    gso_table_anchors: dict[int, str] = {}
    gso_table_indices: set[int] = set()

    for group in table_groups:
        md = _shapes_to_table(group)
        if md:
            anchor = min(c[0] for c in group)
            gso_table_anchors[anchor] = md
            for c in group:
                for k in range(c[0], c[4]):
                    gso_table_indices.add(k)

    body_text_anchors: dict[int, str] = {}
    body_text_indices: set[int] = set()
    for c in body_text_cells:
        body_text_anchors[c[0]] = c[3]
        for k in range(c[0], c[4]):
            body_text_indices.add(k)

    skip_indices = native_table_indices | gso_table_indices | body_text_indices
    parts: list[str] = []
    i = 0
    while i < len(records):
        if i in native_table_starts:
            end_i, md = native_table_starts[i]
            if md:
                parts.append(f"\n{md}\n")
            i = end_i
            continue

        if i in gso_table_anchors:
            parts.append(f"\n{gso_table_anchors[i]}\n")

        if i in body_text_anchors:
            parts.append(body_text_anchors[i])

        if i not in skip_indices:
            tid, lv, rd = records[i]
            if tid == HWPTAG_PARA_TEXT:
                text = _parse_para_text(rd).strip()
                if text:
                    parts.append(text)
        i += 1

    return "\n".join(parts)


def _extract_hwp_direct(hwp_path: str) -> list:
    """olefile로 HWP 바이너리 직접 파싱하여 텍스트+표 추출."""
    try:
        import olefile
    except ImportError:
        raise RuntimeError("olefile이 설치되어 있지 않습니다.\n설치: pip install olefile")

    if not olefile.isOleFile(hwp_path):
        raise RuntimeError(f"유효한 HWP(OLE) 파일이 아닙니다: {hwp_path}")

    ole = olefile.OleFileIO(hwp_path)
    try:
        header_data = ole.openstream("FileHeader").read()
        is_compressed = bool(header_data[36] & 0x01)
        pages: list[dict] = []
        front_matter_idx = 0
        section_idx = 0
        while True:
            stream_name = f"BodyText/Section{section_idx}"
            if not ole.exists(stream_name):
                break
            raw = ole.openstream(stream_name).read()
            if is_compressed:
                try:
                    raw = zlib.decompress(raw, -15)
                except zlib.error:
                    raw = zlib.decompress(raw)
            text = _parse_hwp_section(raw)

            doc_page_num, cleaned_text = detect_footer_page_number(text)
            if doc_page_num is not None:
                page_num = doc_page_num
            else:
                front_matter_idx += 1
                page_num = f"전문-{front_matter_idx}"

            pages.append({
                "page_num": page_num,
                "text": cleaned_text,
                "tables": [],
                "images": [],
            })
            section_idx += 1
        if not pages:
            raise RuntimeError("BodyText 섹션을 찾을 수 없습니다.")
        return pages
    finally:
        ole.close()


# ============================================================
# 메인 진입점
# ============================================================
def convert_hwp_to_pdf(hwp_path: str, output_dir: str = None) -> str:
    """HWP → PDF 변환 (LibreOffice 직접 → pyhwp 폴백)"""
    if not check_libreoffice():
        raise RuntimeError("LibreOffice가 설치되어 있지 않습니다.\n설치: sudo apt install libreoffice")
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="hwp_convert_")
    else:
        os.makedirs(output_dir, exist_ok=True)

    logger.info("HWP → PDF 변환 중: %s", os.path.basename(hwp_path))

    pdf_path = _run_libreoffice(hwp_path, output_dir, "pdf")
    if pdf_path:
        logger.info("변환 완료 (LibreOffice 직접): %s", pdf_path)
        return pdf_path

    logger.info("LibreOffice 직접 변환 실패, pyhwp 폴백 시도...")
    pdf_path = _convert_hwp_via_pyhwp(hwp_path, output_dir)
    if pdf_path:
        logger.info("변환 완료 (pyhwp 폴백): %s", pdf_path)
        return pdf_path

    raise RuntimeError(f"HWP → PDF 변환 실패: {hwp_path}")


def extract_hwp(hwp_path: str) -> list:
    """HWP에서 페이지별 데이터 추출."""
    from .pdf_extractor import extract_pdf

    try:
        pdf_path = convert_hwp_to_pdf(hwp_path)
        try:
            return extract_pdf(pdf_path)
        finally:
            tmp_dir = os.path.dirname(pdf_path)
            if tmp_dir.startswith(tempfile.gettempdir()):
                shutil.rmtree(tmp_dir, ignore_errors=True)
    except RuntimeError:
        pass

    logger.info("olefile 직접 파싱으로 텍스트/표 추출 중...")
    pages = _extract_hwp_direct(hwp_path)
    logger.info("HWP 직접 파싱 완료: %d개 섹션", len(pages))
    return pages


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.v1_printed.hwp_converter <file.hwp>")
        exit()
    result = extract_hwp(sys.argv[1])
    for p in result:
        print(f"\n--- Page {p['page_num']} ---")
        print(p["text"][:500])
