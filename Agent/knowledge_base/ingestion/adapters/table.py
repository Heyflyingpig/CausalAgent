import csv
import hashlib
import posixpath
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element, fromstring
from zipfile import ZipFile

from ..models import (
    ContentKind,
    KnowledgeFragment,
    KnowledgeSource,
    SourceLocator,
    SourceType,
)


_ROWS_PER_FRAGMENT = 20
_EMPTY_CELL = "<empty>"
_MAX_XLSX_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_XLSX_TOTAL_XML_BYTES = 64 * 1024 * 1024
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOCUMENT_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_BUILTIN_NUMBER_FORMATS = {
    9: "0%",
    10: "0.00%",
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "mmss.0",
}
_DATE_FORMAT_IDS = frozenset({14, 15, 16, 17, 22})
_TIME_FORMAT_IDS = frozenset({18, 19, 20, 21, 45, 46, 47})


def _display_cell(value: str) -> str:
    """把单元格显示值转换为安全、稳定的 Markdown 文字。"""
    normalized = value.strip()
    if not normalized:
        return _EMPTY_CELL
    return (
        normalized.replace("|", r"\|")
        .replace("\r\n", "<br>")
        .replace("\r", "<br>")
        .replace("\n", "<br>")
    )


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """把表头和行组转换为不执行公式的 Markdown 表格。"""
    rendered_headers = [_display_cell(header) for header in headers]
    lines = [
        "| " + " | ".join(rendered_headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_display_cell(value) for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _csv_row_groups(
    text: str,
) -> tuple[list[str], list[tuple[int, int, list[list[str]]]]]:
    """识别 CSV 分隔符和表头，并按连续逻辑行形成有界行组。"""
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    parsed_rows = list(csv.reader(StringIO(text), dialect=dialect, strict=True))
    indexed_rows = [
        (row_number, row)
        for row_number, row in enumerate(parsed_rows, start=1)
        if any(value.strip() for value in row)
    ]
    return _group_rows(indexed_rows)


def _group_rows(
    indexed_rows: list[tuple[int, list[str]]],
) -> tuple[list[str], list[tuple[int, int, list[list[str]]]]]:
    """以首个非空行为表头，将后续连续行切成有界行组。"""
    indexed_rows = [
        (row_number, row)
        for row_number, row in indexed_rows
        if any(value.strip() for value in row)
    ]
    if not indexed_rows:
        return [], []
    header_row_number, raw_headers = indexed_rows[0]
    data_rows = indexed_rows[1:]
    column_count = max(
        [len(raw_headers), *(len(row) for _, row in data_rows)],
        default=len(raw_headers),
    )
    headers = [
        raw_headers[index].strip()
        if index < len(raw_headers) and raw_headers[index].strip()
        else f"column_{index + 1}"
        for index in range(column_count)
    ]
    if not data_rows:
        return headers, [(header_row_number, header_row_number, [])]
    groups = []
    current = []
    group_start = data_rows[0][0]
    previous_row = group_start - 1
    for row_number, row in data_rows:
        if current and (
            row_number != previous_row + 1 or len(current) >= _ROWS_PER_FRAGMENT
        ):
            groups.append((group_start, previous_row, current))
            current = []
            group_start = row_number
        current.append(row + [""] * (column_count - len(row)))
        previous_row = row_number
    groups.append((group_start, previous_row, current))
    return headers, groups


def _column_number(cell_reference: str) -> int:
    """把 XLSX 单元格引用中的列字母转换为一基列号。"""
    match = re.match(r"^([A-Z]+)", cell_reference.upper())
    if match is None:
        raise ValueError("XLSX cell reference is invalid")
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    return column


def _format_xlsx_number(
    value: str,
    style: tuple[int, str],
    *,
    date_1904: bool,
) -> str:
    """按常见 Excel 日期、百分比和货币格式生成稳定显示值。"""
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value
    number_format_id, format_code = style
    lower_format = format_code.lower()
    is_time_only = number_format_id in _TIME_FORMAT_IDS or (
        ("h" in lower_format or "s" in lower_format)
        and "y" not in lower_format
        and "d" not in lower_format
    )
    if is_time_only:
        if number_format_id == 47:
            day_tenths = round(float(number * 24 * 60 * 60 * 10)) % (
                24 * 60 * 60 * 10
            )
            minutes, second_tenths = divmod(day_tenths, 60 * 10)
            seconds, tenths = divmod(second_tenths, 10)
            return f"{minutes % 60:02d}{seconds:02d}.{tenths}"
        total_seconds = round(float(number * 24 * 60 * 60))
        if number_format_id == 46 or "[h]" in lower_format:
            hours, remainder = divmod(total_seconds, 60 * 60)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        day_seconds = total_seconds % (24 * 60 * 60)
        hours, remainder = divmod(day_seconds, 60 * 60)
        minutes, seconds = divmod(remainder, 60)
        if number_format_id == 45:
            return f"{minutes:02d}:{seconds:02d}"
        if "am/pm" in lower_format:
            suffix = "AM" if hours < 12 else "PM"
            display_hour = hours % 12 or 12
            return (
                f"{display_hour}:{minutes:02d}:{seconds:02d} {suffix}"
                if "s" in lower_format
                else f"{display_hour}:{minutes:02d} {suffix}"
            )
        return (
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if "s" in lower_format
            else f"{hours:02d}:{minutes:02d}"
        )
    if number_format_id in _DATE_FORMAT_IDS or (
        "y" in lower_format and ("d" in lower_format or "m" in lower_format)
    ):
        if date_1904:
            displayed = datetime(1904, 1, 1) + timedelta(days=float(number))
        elif int(number) == 60:
            fractional_seconds = round(float(number % 1) * 24 * 60 * 60)
            if not fractional_seconds:
                return "1900-02-29"
            hours, remainder = divmod(fractional_seconds, 60 * 60)
            minutes, seconds = divmod(remainder, 60)
            return f"1900-02-29 {hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            leap_adjustment = 1 if number > 60 else 0
            displayed = datetime(1899, 12, 31) + timedelta(
                days=float(number - leap_adjustment)
            )
        return (
            displayed.date().isoformat()
            if displayed.time() == datetime.min.time()
            else displayed.isoformat(sep=" ", timespec="seconds")
        )
    if "%" in format_code:
        decimal_match = re.search(r"\.(0+)[^%]*%", format_code)
        decimal_places = len(decimal_match.group(1)) if decimal_match else 0
        return f"{number * 100:.{decimal_places}f}%"
    currency = next(
        (symbol for symbol in ("$", "¥", "€", "£") if symbol in format_code),
        None,
    )
    if currency:
        decimal_match = re.search(r"\.(0+)", format_code)
        decimal_places = len(decimal_match.group(1)) if decimal_match else 0
        grouping = "," if "," in format_code else ""
        return f"{currency}{number:{grouping}.{decimal_places}f}"
    return value


def _xlsx_cell_value(
    cell: Element,
    shared_strings: list[str],
    styles: list[tuple[int, str]],
    *,
    date_1904: bool,
) -> str:
    """读取 XLSX 缓存显示值；公式仅以文字呈现，不执行计算。"""
    formula = cell.find(f"{{{_SHEET_NS}}}f")
    value_node = cell.find(f"{{{_SHEET_NS}}}v")
    value = value_node.text if value_node is not None and value_node.text else ""
    style_index = int(cell.get("s") or 0)
    style = styles[style_index] if style_index < len(styles) else (0, "General")
    displayed_value = _format_xlsx_number(value, style, date_1904=date_1904)
    if formula is not None:
        formula_text = (formula.text or "").strip()
        if not formula_text and formula.get("t") == "shared":
            displayed_formula = f"[shared formula si={formula.get('si') or 'unknown'}]"
        else:
            displayed_formula = f"={formula_text}"
        return displayed_formula + (
            f" (cached: {displayed_value})" if displayed_value else ""
        )
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        inline_string = cell.find(f"{{{_SHEET_NS}}}is")
        return _visible_rich_text(inline_string) if inline_string is not None else ""
    if cell_type == "s":
        return shared_strings[int(value)]
    if cell_type == "b":
        return "TRUE" if value == "1" else "FALSE"
    if cell_type in {"s", "inlineStr", "str"}:
        return value
    return displayed_value


def _visible_rich_text(container: Element) -> str:
    """读取直接文字与 rich-text run，排除 rPh 拼音注音。"""
    direct_text = container.find(f"{{{_SHEET_NS}}}t")
    parts = [direct_text.text or ""] if direct_text is not None else []
    parts.extend(
        text_node.text or ""
        for run in container.findall(f"{{{_SHEET_NS}}}r")
        if (text_node := run.find(f"{{{_SHEET_NS}}}t")) is not None
    )
    return "".join(parts)


def _read_xlsx_xml(
    workbook: ZipFile,
    path: str,
    consumed_bytes: list[int],
) -> bytes:
    """在解压前执行单成员与累计 XML 字节预算。"""
    file_size = workbook.getinfo(path).file_size
    if file_size > _MAX_XLSX_MEMBER_BYTES:
        raise ValueError("XLSX XML member exceeds the size limit")
    consumed_bytes[0] += file_size
    if consumed_bytes[0] > _MAX_XLSX_TOTAL_XML_BYTES:
        raise ValueError("XLSX XML members exceed the cumulative size limit")
    return workbook.read(path)


def _xlsx_styles(
    workbook: ZipFile,
    consumed_bytes: list[int],
) -> list[tuple[int, str]]:
    """读取 cellXfs 对应的数字格式 ID 与格式代码。"""
    if "xl/styles.xml" not in workbook.namelist():
        return [(0, "General")]
    root = fromstring(_read_xlsx_xml(workbook, "xl/styles.xml", consumed_bytes))
    custom_formats = {
        int(node.get("numFmtId") or 0): node.get("formatCode") or "General"
        for node in root.findall(f".//{{{_SHEET_NS}}}numFmt")
    }
    cell_formats = root.find(f"{{{_SHEET_NS}}}cellXfs")
    if cell_formats is None:
        return [(0, "General")]
    return [
        (
            number_format_id,
            custom_formats.get(
                number_format_id,
                _BUILTIN_NUMBER_FORMATS.get(number_format_id, "General"),
            ),
        )
        for cell_format in cell_formats.findall(f"{{{_SHEET_NS}}}xf")
        for number_format_id in [int(cell_format.get("numFmtId") or 0)]
    ]


def _xlsx_tables(
    content: bytes,
) -> list[tuple[str, list[str], list[tuple[int, int, list[list[str]]]]]]:
    """按工作簿顺序读取 XLSX sheet，并返回表头与连续行组。"""
    tables = []
    with ZipFile(BytesIO(content)) as workbook:
        consumed_bytes = [0]
        shared_strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = fromstring(
                _read_xlsx_xml(workbook, "xl/sharedStrings.xml", consumed_bytes)
            )
            shared_strings = [
                _visible_rich_text(item)
                for item in shared_root.findall(f"{{{_SHEET_NS}}}si")
            ]
        workbook_root = fromstring(
            _read_xlsx_xml(workbook, "xl/workbook.xml", consumed_bytes)
        )
        workbook_properties = workbook_root.find(f"{{{_SHEET_NS}}}workbookPr")
        date_1904 = (
            workbook_properties is not None
            and workbook_properties.get("date1904") in {"1", "true", "True"}
        )
        styles = _xlsx_styles(workbook, consumed_bytes)
        relationships_root = fromstring(
            _read_xlsx_xml(workbook, "xl/_rels/workbook.xml.rels", consumed_bytes)
        )
        targets = {
            relationship.get("Id"): relationship.get("Target")
            for relationship in relationships_root.findall(f"{{{_REL_NS}}}Relationship")
            if (relationship.get("Type") or "").endswith("/worksheet")
        }
        for sheet in workbook_root.findall(f".//{{{_SHEET_NS}}}sheet"):
            sheet_name = sheet.get("name") or "Sheet"
            relationship_id = sheet.get(f"{{{_DOCUMENT_REL_NS}}}id")
            target = targets.get(relationship_id)
            if not target or ".." in PurePosixPath(target).parts:
                raise ValueError("XLSX worksheet relationship is invalid")
            target_path = target.lstrip("/")
            sheet_path = posixpath.normpath(
                target_path
                if target_path.startswith("xl/")
                else posixpath.join("xl", target_path)
            )
            if not sheet_path.startswith("xl/"):
                raise ValueError("XLSX worksheet relationship leaves the workbook root")
            sheet_root = fromstring(
                _read_xlsx_xml(workbook, sheet_path, consumed_bytes)
            )
            merged_ranges = {
                reference.split(":", 1)[0]: reference
                for node in sheet_root.findall(f".//{{{_SHEET_NS}}}mergeCell")
                if (reference := node.get("ref")) and ":" in reference
            }
            merged_width = max(
                (
                    _column_number(reference.split(":", 1)[1])
                    for reference in merged_ranges.values()
                ),
                default=0,
            )
            indexed_rows = []
            for row in sheet_root.findall(f".//{{{_SHEET_NS}}}row"):
                row_number = int(row.get("r") or len(indexed_rows) + 1)
                values: dict[int, str] = {}
                for cell in row.findall(f"{{{_SHEET_NS}}}c"):
                    reference = cell.get("r") or ""
                    column = _column_number(reference)
                    value = _xlsx_cell_value(
                        cell,
                        shared_strings,
                        styles,
                        date_1904=date_1904,
                    )
                    if reference in merged_ranges:
                        value = f"{value} [merged {merged_ranges[reference]}]"
                    values[column] = value
                width = max(max(values, default=0), merged_width)
                indexed_rows.append(
                    (row_number, [values.get(column, "") for column in range(1, width + 1)])
                )
            headers, groups = _group_rows(indexed_rows)
            if headers:
                tables.append((sheet_name, headers, groups))
    return tables


def _create_fragments(
    source: KnowledgeSource,
    headers: list[str],
    groups: list[tuple[int, int, list[list[str]]]],
    *,
    extractor: str,
    sheet_name: str | None = None,
) -> tuple[KnowledgeFragment, ...]:
    """把一个表格的行组封装为统一知识片段。"""
    return tuple(
        KnowledgeFragment.create(
            source=source,
            locator=SourceLocator(
                sheet_name=sheet_name,
                row_start=row_start,
                row_end=row_end,
                column_start=1,
                column_end=len(headers),
            ),
            content_kind=ContentKind.TABLE,
            text=_markdown_table(headers, rows),
            extractor=extractor,
            extractor_version="1.0",
            title=sheet_name or source.source_name,
            section=sheet_name,
        )
        for row_start, row_end, rows in groups
    )


def extract_table_fragments(
    source: KnowledgeSource,
    content: bytes,
) -> tuple[KnowledgeFragment, ...]:
    """将 CSV/XLSX 表格转换为带 sheet、行列定位的统一知识片段。"""
    if source.source_type is not SourceType.TABLE:
        raise ValueError("table adapter requires a table source")
    if hashlib.sha256(content).hexdigest() != source.content_sha256:
        raise ValueError("table content does not match the source version")
    suffix = PurePosixPath(source.relative_path).suffix.casefold()
    if suffix == ".csv":
        try:
            text = content.decode("utf-8-sig")
            headers, groups = _csv_row_groups(text)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError("CSV source is not valid UTF-8 or has invalid syntax") from exc
        return _create_fragments(source, headers, groups, extractor="csv-adapter")
    if suffix == ".xlsx":
        try:
            tables = _xlsx_tables(content)
        except Exception as exc:
            raise ValueError("XLSX source has invalid workbook structure") from exc
        return tuple(
            fragment
            for sheet_name, headers, groups in tables
            for fragment in _create_fragments(
                source,
                headers,
                groups,
                extractor="xlsx-adapter",
                sheet_name=sheet_name,
            )
        )
    raise ValueError("table adapter requires a CSV or XLSX source")
