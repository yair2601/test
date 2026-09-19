"""Profile the sales-order Excel file — offline, read-only, no Priority.

    python inspect_excel.py orders.xlsx
    python inspect_excel.py orders.xlsx --ref-column "אסמכתא"
    python inspect_excel.py orders.xlsx --anonymize     # mask values before sharing

It answers, from the file itself:
  * which sheet, which header row, which columns exist
  * the real type of every column (and the traps: numbers stored as text,
    leading zeros, dates stored as strings, trailing spaces)
  * which column is the reference (grouping key) candidate
  * how many orders that produces, how many lines each has, and whether the
    rows of one order are contiguous
  * which columns are header-level (constant within an order) and which are
    line-level (varying) — i.e. what goes into ORDERS vs ORDERITEMS
  * conflicts that would break the load: one reference with two customers/dates
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

try:
    from openpyxl import load_workbook
except ImportError:
    print("openpyxl is missing. Run:  pip install -r requirements.txt")
    sys.exit(1)

from discovery.util import now_iso, truncate, write_text

MAX_SAMPLES = 5


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def detect_header_row(rows: list[list], scan: int = 15) -> int:
    """Index of the most plausible header row: the first row with several
    distinct non-empty text cells and no numbers."""
    best_index, best_score = 0, -1
    for i, row in enumerate(rows[:scan]):
        values = [c for c in row if c is not None and str(c).strip() != ""]
        if len(values) < 2:
            continue
        texts = sum(1 for v in values if isinstance(v, str))
        numbers = sum(1 for v in values if isinstance(v, (int, float)))
        score = texts * 2 - numbers * 3 + len(set(map(str, values)))
        if score > best_score:
            best_index, best_score = i, score
    return best_index


def read_sheet(path: Path, sheet_name: str | None):
    """Return (sheet, header_row_index, headers, data_rows, formats)."""
    # data_only=True gives computed values instead of formula text.
    workbook = load_workbook(filename=str(path), data_only=True, read_only=True)
    sheet = workbook[sheet_name] if sheet_name else workbook[workbook.sheetnames[0]]

    rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    if not rows:
        return workbook, sheet, 0, [], [], {}

    header_index = detect_header_row(rows)
    raw_headers = rows[header_index]
    headers = []
    for i, cell in enumerate(raw_headers):
        name = str(cell).strip() if cell is not None and str(cell).strip() else f"<col{i + 1}>"
        # Duplicate header names would silently collide.
        if name in headers:
            name = f"{name} ({i + 1})"
        headers.append(name)

    data_rows = [r for r in rows[header_index + 1:]
                 if any(c is not None and str(c).strip() != "" for c in r)]

    # Number formats tell us whether a date column is a real date.
    formats: dict[int, Counter] = defaultdict(Counter)
    fmt_book = load_workbook(filename=str(path), data_only=False, read_only=True)
    fmt_sheet = fmt_book[sheet.title]
    for row_index, row in enumerate(fmt_sheet.iter_rows(min_row=header_index + 2,
                                                        max_row=header_index + 51)):
        for col_index, cell in enumerate(row):
            if cell.value is not None:
                formats[col_index][cell.number_format] += 1
    fmt_book.close()

    return workbook, sheet, header_index, headers, data_rows, formats


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------

def type_name(value) -> str:
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (dt.datetime, dt.date)):
        return "date"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "empty"
        try:
            float(stripped.replace(",", ""))
            return "number-as-text"
        except ValueError:
            return "text"
    return type(value).__name__


def mask(value) -> str:
    """Replace the content of a value but keep its shape, for safe sharing."""
    if value is None:
        return ""
    text = str(value)
    out = []
    for ch in text:
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A" if ch.isascii() else "א")
        else:
            out.append(ch)
    return "".join(out)


def profile_column(header: str, values: list, number_formats: Counter) -> dict:
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    types = Counter(type_name(v) for v in values)
    distinct = OrderedDict()
    for value in non_empty:
        key = str(value)
        if key not in distinct:
            distinct[key] = value

    warnings = []
    text_values = [v for v in non_empty if isinstance(v, str)]
    if any(v != v.strip() for v in text_values):
        warnings.append("leading/trailing whitespace in some cells")
    if types.get("number-as-text") and types.get("int", 0) + types.get("float", 0):
        warnings.append("MIXED: some cells are real numbers, others are numbers stored as text")
    if any(v.strip().startswith("0") and v.strip().isdigit() and len(v.strip()) > 1
           for v in text_values):
        warnings.append("leading zeros present — must be read as text, not as a number")
    if types.get("float"):
        warnings.append("float values — watch for 1.0000000002 style rounding")

    fmt = number_formats.most_common(1)[0][0] if number_formats else ""
    if types.get("date") and fmt:
        warnings.append(f"real date cells, Excel format {fmt!r}")
    looks_like_date = "תאריך" in header or "date" in header.lower()
    if looks_like_date and not types.get("date"):
        warnings.append("looks like a date column but the cells are NOT real dates — "
                        "the exact string format matters")

    return {
        "header": header,
        "total": len(values),
        "non_empty": len(non_empty),
        "empty": len(values) - len(non_empty),
        "distinct": len(distinct),
        "types": dict(types),
        "number_format": fmt,
        "max_len": max((len(str(v)) for v in non_empty), default=0),
        "samples": list(distinct.values())[:MAX_SAMPLES],
        "warnings": warnings,
    }


def guess_reference_column(profiles: list[dict]) -> list[str]:
    """Reference column: many rows, far fewer distinct values, never empty."""
    scored = []
    for profile in profiles:
        distinct, total = profile["distinct"], profile["non_empty"]
        if total == 0 or distinct < 2 or distinct == total:
            continue
        rows_per_group = total / distinct
        if rows_per_group < 1.2:
            continue
        # A reference column is named like one; that beats every shape heuristic.
        name_bonus = 5 if any(
            word in profile["header"].lower()
            for word in ("אסמכת", "אסמכה", "reference", "ref", "order", "הזמנה", "מסמך")
        ) else 0
        # Gaps are allowed but suspicious: a reference is normally mandatory.
        gap_penalty = 2 if profile["empty"] else 0
        scored.append((rows_per_group + name_bonus - gap_penalty, profile["header"]))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [header for _, header in scored[:5]]


def analyse_grouping(headers: list[str], rows: list[list], ref_header: str) -> dict:
    ref_index = headers.index(ref_header)
    groups: OrderedDict[str, list[int]] = OrderedDict()
    for row_index, row in enumerate(rows):
        value = row[ref_index] if ref_index < len(row) else None
        key = "" if value is None else str(value).strip()
        groups.setdefault(key, []).append(row_index)

    contiguous = all(
        indexes == list(range(indexes[0], indexes[0] + len(indexes)))
        for indexes in groups.values()
    )

    # A column constant inside every group belongs to the header (ORDERS);
    # a column that varies belongs to the lines (ORDERITEMS). A column that is
    # constant in nearly every group but varies in one or two is a header
    # column with a data problem, not a line column — classify it as a header
    # column and report the offending groups as conflicts.
    def cell(row_index: int, col_index: int) -> str:
        row = rows[row_index]
        if col_index >= len(row) or row[col_index] is None:
            return ""
        return str(row[col_index]).strip()

    header_level, line_level, conflicts = [], [], []
    group_count = len(groups) or 1
    for col_index, name in enumerate(headers):
        varying_groups = [
            (key, sorted({cell(i, col_index) for i in indexes}))
            for key, indexes in groups.items()
            if len({cell(i, col_index) for i in indexes}) > 1
        ]
        if len(varying_groups) / group_count <= 0.2:
            header_level.append(name)
            for key, values in varying_groups[:20]:
                conflicts.append({"reference": key, "column": name, "values": values[:5]})
        else:
            line_level.append(name)

    sizes = [len(v) for v in groups.values()]
    return {
        "reference_column": ref_header,
        "orders": len(groups),
        "rows": len(rows),
        "min_lines": min(sizes) if sizes else 0,
        "max_lines": max(sizes) if sizes else 0,
        "avg_lines": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        "contiguous": contiguous,
        "empty_reference_rows": len(groups.get("", [])),
        "header_level_columns": header_level,
        "line_level_columns": line_level,
        "conflicts": conflicts,
        "sample_refs": [k for k in list(groups)[:5]],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(path: Path, sheet_names: list[str], sheet_title: str, header_index: int,
           headers: list[str], rows: list[list], profiles: list[dict],
           ref_candidates: list[str], grouping: dict | None, anonymize: bool) -> str:
    show = (lambda v: mask(v)) if anonymize else (lambda v: truncate(v, 40))

    lines = [
        "# Excel profile",
        "",
        f"- File: `{path.name}`",
        f"- Inspected: {now_iso()}",
        f"- Sheets: {', '.join(sheet_names)}  (profiled: **{sheet_title}**)",
        f"- Header row: Excel row {header_index + 1}",
        f"- Data rows: {len(rows)}",
        f"- Columns: {len(headers)}",
    ]
    if anonymize:
        lines.append("- **Anonymized**: digits shown as `9`, letters as `A`/`א`. "
                     "Shapes are real, contents are not.")
    lines += ["", "## Columns", ""]

    for profile in profiles:
        types = ", ".join(f"{k}:{v}" for k, v in sorted(
            profile["types"].items(), key=lambda kv: -kv[1]))
        lines.append(f"### `{profile['header']}`")
        lines.append(
            f"- filled {profile['non_empty']}/{profile['total']}"
            f" | distinct {profile['distinct']} | max length {profile['max_len']}"
        )
        lines.append(f"- types: {types}")
        if profile["number_format"] and profile["number_format"] != "General":
            lines.append(f"- Excel number format: `{profile['number_format']}`")
        samples = ", ".join(f"`{show(s)}`" for s in profile["samples"]) or "_none_"
        lines.append(f"- samples: {samples}")
        for warning in profile["warnings"]:
            lines.append(f"- ⚠ {warning}")
        lines.append("")

    lines += ["## Reference column candidates", ""]
    if ref_candidates:
        for name in ref_candidates:
            lines.append(f"- `{name}`")
        lines.append("")
        lines.append("Re-run with `--ref-column \"<name>\"` to analyse the grouping.")
    else:
        lines.append("_None found: no column groups rows the way a reference would._")
    lines.append("")

    if grouping:
        lines += [
            "## Grouping analysis", "",
            f"- Reference column: `{grouping['reference_column']}`",
            f"- Orders: **{grouping['orders']}** from {grouping['rows']} rows",
            f"- Lines per order: min {grouping['min_lines']}, max {grouping['max_lines']}, "
            f"average {grouping['avg_lines']}",
            f"- Rows of one order are contiguous: **{'yes' if grouping['contiguous'] else 'NO'}**",
        ]
        if grouping["empty_reference_rows"]:
            lines.append(f"- ⚠ {grouping['empty_reference_rows']} row(s) have an EMPTY reference "
                         "— those cannot be loaded and will be reported as failures.")
        lines += [
            "",
            "### Header-level columns (constant within an order -> ORDERS)",
            "",
            *(f"- `{name}`" for name in grouping["header_level_columns"]),
            "",
            "### Line-level columns (vary within an order -> ORDERITEMS)",
            "",
            *(f"- `{name}`" for name in grouping["line_level_columns"]),
            "",
        ]
        if grouping["conflicts"]:
            lines += [
                "### ⚠ Conflicts", "",
                "These columns look like header fields but hold more than one value inside a",
                "single reference. The loader cannot guess which one is right — decide the rule",
                "before loading, or those orders get rejected.", "",
            ]
            for conflict in grouping["conflicts"][:20]:
                values = ", ".join(f"`{show(v)}`" for v in conflict["values"])
                lines.append(
                    f"- reference `{show(conflict['reference'])}` column `{conflict['column']}`: {values}"
                )
            lines.append("")

        lines += ["## Mapping skeleton for config.yaml", "", "```yaml", "excel:",
                  f"  sheet: {sheet_title!r}",
                  f"  header_row: {header_index + 1}",
                  f"  reference_column: {grouping['reference_column']!r}", "",
                  "  # Set each Priority field to the Excel column that feeds it.",
                  "  header_fields:"]
        for name in grouping["header_level_columns"]:
            lines.append(f"    # PRIORITY_FIELD: {name!r}")
        lines += ["  line_fields:"]
        for name in grouping["line_level_columns"]:
            lines.append(f"    # PRIORITY_FIELD: {name!r}")
        lines += ["```", ""]

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile the orders Excel file")
    parser.add_argument("excel", help="Path to the .xlsx file")
    parser.add_argument("--sheet", default=None, help="Sheet name (default: first sheet)")
    parser.add_argument("--ref-column", default=None,
                        help="Column to group orders by; omit to see candidates")
    parser.add_argument("--anonymize", action="store_true",
                        help="Mask values (digits->9, letters->A) so the report is safe to share")
    parser.add_argument("--out", default="excel-profile.md", help="Where to write the report")
    args = parser.parse_args()

    path = Path(args.excel)
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    workbook, sheet, header_index, headers, rows, formats = read_sheet(path, args.sheet)
    if not headers:
        print("The sheet appears to be empty.")
        return 1

    profiles = []
    for col_index, header in enumerate(headers):
        values = [row[col_index] if col_index < len(row) else None for row in rows]
        profiles.append(profile_column(header, values, formats.get(col_index, Counter())))

    ref_candidates = guess_reference_column(profiles)

    grouping = None
    if args.ref_column:
        if args.ref_column not in headers:
            print(f"Column {args.ref_column!r} not found. Available columns:")
            for header in headers:
                print(f"  - {header}")
            return 1
        grouping = analyse_grouping(headers, rows, args.ref_column)

    report = render(path, workbook.sheetnames, sheet.title, header_index, headers, rows,
                    profiles, ref_candidates, grouping, args.anonymize)
    workbook.close()

    out_path = write_text(Path(args.out), report)
    print(report)
    print(f"\n[report written to {out_path.resolve()}]")
    if not args.ref_column and ref_candidates:
        print(f"\nNext: python inspect_excel.py {path.name} --ref-column \"{ref_candidates[0]}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
