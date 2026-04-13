"""
표 데이터를 마크다운 표 형식으로 변환하는 유틸리티
"""


def table_to_markdown(table_data: list) -> str:
    """
    2D 리스트(표 데이터)를 마크다운 표 문자열로 변환

    Args:
        table_data: [[cell, cell, ...], [cell, cell, ...], ...]

    Returns:
        마크다운 표 문자열
    """
    if not table_data or not table_data[0]:
        return ""

    max_cols = max(len(row) for row in table_data)

    normalized = []
    for row in table_data:
        cells = []
        for i in range(max_cols):
            if i < len(row) and row[i] is not None:
                cell_text = str(row[i]).replace("\n", " ").replace("|", "\\|").strip()
            else:
                cell_text = ""
            cells.append(cell_text)
        normalized.append(cells)

    col_widths = [3] * max_cols
    for row in normalized:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    def format_row(cells):
        parts = []
        for i, cell in enumerate(cells):
            parts.append(f" {cell.ljust(col_widths[i])} ")
        return "|" + "|".join(parts) + "|"

    lines = []
    lines.append(format_row(normalized[0]))
    separator_parts = [" " + "-" * col_widths[i] + " " for i in range(max_cols)]
    lines.append("|" + "|".join(separator_parts) + "|")

    for row in normalized[1:]:
        lines.append(format_row(row))

    return "\n".join(lines)


def tables_to_markdown_blocks(tables: list) -> list:
    """
    여러 표 데이터를 마크다운 블록 리스트로 변환

    Args:
        tables: [table_data, table_data, ...]

    Returns:
        마크다운 표 문자열 리스트
    """
    blocks = []
    for table in tables:
        md = table_to_markdown(table)
        if md:
            blocks.append(md)
    return blocks
