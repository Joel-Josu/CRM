from __future__ import annotations

import base64
import csv
import datetime as dt
import html
import io
import json
import math
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SAMPLE = ROOT / "sample_crm_sales.csv"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 256
MAX_HISTORY = 30
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class Dataset:
    filename: str
    columns: list[str]
    rows: list[dict[str, Any]]
    original: bytes
    content_type: str


DATASET: Dataset | None = None
HISTORY: list[dict[str, Any]] = []
LOCK = threading.RLock()


def load_local_settings() -> None:
    """Load only the optional Gemini settings; never expose them to the browser."""
    if os.environ.get("DATA_DESK_DISABLE_AI") == "1":
        return
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(GEMINI_API_KEY|GEMINI_MODEL)\s*=\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip("\"'")
        if value and key not in os.environ:
            os.environ[key] = value


def unique_headers(headers: list[Any]) -> list[str]:
    if len(headers) > MAX_COLUMNS:
        raise ValueError(f"Files may contain at most {MAX_COLUMNS} columns.")
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(headers):
        label = str(value).strip() if value is not None else ""
        label = label or f"Column {index + 1}"
        count = seen.get(label.casefold(), 0) + 1
        seen[label.casefold()] = count
        result.append(label if count == 1 else f"{label} ({count})")
    return result


def make_dataset(filename: str, content: bytes) -> Dataset:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        rows, columns = parse_csv(content)
        content_type = "text/csv"
    elif suffix == ".json":
        rows, columns = parse_json(content)
        content_type = "application/json"
    elif suffix == ".xlsx":
        rows, columns = parse_xlsx(content)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        raise ValueError("Choose a CSV, XLSX, or JSON file.")
    if not columns:
        raise ValueError("The uploaded file does not contain column headings.")
    if not rows:
        raise ValueError("The uploaded file has headings but no data rows.")
    safe_name = Path(filename.replace("\\", "/")).name
    safe_name = re.sub(r'[\x00-\x1f\x7f"<>|:*?]', "_", safe_name).strip(" .")
    return Dataset(safe_name or "dataset", columns, rows, content, content_type)


def parse_csv(content: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV files must use UTF-8 encoding.") from exc
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, [])
    columns = unique_headers(header)
    rows: list[dict[str, Any]] = []
    for values in reader:
        if not any(str(value).strip() for value in values):
            continue
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"Files may contain at most {MAX_ROWS:,} data rows.")
        values = values[:len(columns)] + [""] * max(0, len(columns) - len(values))
        rows.append(dict(zip(columns, values)))
    return rows, columns


def parse_json(content: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The JSON file could not be parsed.") from exc
    if isinstance(data, dict):
        data = data.get("data", data.get("records", [data]))
    if not isinstance(data, list) or not data:
        raise ValueError("JSON must contain a non-empty array of row objects.")
    if not all(isinstance(row, dict) for row in data):
        raise ValueError("Each item in the JSON array must be an object.")
    if len(data) > MAX_ROWS:
        raise ValueError(f"Files may contain at most {MAX_ROWS:,} data rows.")
    columns = unique_headers(list(dict.fromkeys(key for row in data for key in row)))
    raw_keys = list(dict.fromkeys(key for row in data for key in row))
    mapping = dict(zip(raw_keys, columns))
    rows = [{mapping[key]: value for key, value in row.items()} for row in data]
    return rows, columns


def parse_xlsx(content: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("The XLSX file is not a valid Excel workbook.") from exc
    with archive:
        members = archive.infolist()
        if len(members) > 2_000 or sum(item.file_size for item in members) > 48 * 1024 * 1024:
            raise ValueError("The Excel workbook is too large to safely process.")
        names = {item.filename for item in members}
        if "xl/workbook.xml" not in names:
            raise ValueError("The Excel workbook is missing its workbook metadata.")
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for entry in root:
                shared_strings.append("".join(node.text or "" for node in entry.iter()
                                              if node.tag.endswith("}t")))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next((node for node in workbook.iter() if node.tag.endswith("}sheet")), None)
        if sheet is None:
            raise ValueError("The Excel workbook does not contain a worksheet.")
        relationship_id = next((value for key, value in sheet.attrib.items()
                                 if key.endswith("}id")), None)
        rels_name = "xl/_rels/workbook.xml.rels"
        rels_root = ET.fromstring(archive.read(rels_name))
        target = next((node.attrib.get("Target") for node in rels_root
                       if node.attrib.get("Id") == relationship_id), None)
        if not target:
            raise ValueError("The first worksheet could not be located.")
        sheet_path = (target.lstrip("/") if target.startswith("/")
                      else str(Path("xl") / target)).replace("\\", "/")
        if sheet_path.startswith("xl/../") or "/../" in sheet_path:
            raise ValueError("The workbook contains an invalid worksheet path.")
        root = ET.fromstring(archive.read(sheet_path))
        raw_rows: list[list[Any]] = []
        for row_node in (node for node in root.iter() if node.tag.endswith("}row")):
            cells: list[Any] = []
            for cell in (node for node in row_node if node.tag.endswith("}c")):
                ref = cell.attrib.get("r", "A1")
                column_number = 0
                column_ref = re.match(r"[A-Z]+", ref.upper())
                if column_ref is None:
                    raise ValueError("The Excel workbook contains an invalid cell reference.")
                for char in column_ref.group(0):
                    column_number = column_number * 26 + ord(char) - 64
                if column_number > MAX_COLUMNS:
                    raise ValueError(f"Files may contain at most {MAX_COLUMNS} columns.")
                while len(cells) < column_number:
                    cells.append("")
                cell_type = cell.attrib.get("t")
                value_node = next((node for node in cell if node.tag.endswith("}v")), None)
                value: Any = value_node.text if value_node is not None else ""
                if cell_type == "s" and value != "":
                    try:
                        value = shared_strings[int(value)]
                    except (ValueError, IndexError) as exc:
                        raise ValueError("The Excel workbook contains an invalid shared string reference.") from exc
                elif cell_type == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter()
                                    if node.tag.endswith("}t"))
                elif cell_type == "b":
                    value = value == "1"
                elif value != "" and cell_type not in ("str", "e"):
                    try:
                        number = float(value)
                        value = int(number) if number.is_integer() else number
                    except (ValueError, TypeError):
                        pass
                cells[column_number - 1] = value
            raw_rows.append(cells)
            if len(raw_rows) > MAX_ROWS + 1:
                raise ValueError(f"Files may contain at most {MAX_ROWS:,} data rows.")
    if not raw_rows:
        return [], []
    width = max(map(len, raw_rows))
    columns = unique_headers(raw_rows[0] + [""] * (width - len(raw_rows[0])))
    rows = []
    for values in raw_rows[1:]:
        values = values + [""] * (len(columns) - len(values))
        if any(value != "" for value in values):
            rows.append(dict(zip(columns, values)))
    for row in rows:
        for column, value in row.items():
            date_heading = re.sub(r"[_-]+", " ", column.casefold())
            if isinstance(value, (int, float)) and re.search(
                r"\b(date|datetime|timestamp|time|created|updated|day)\b", date_heading
            ):
                try:
                    row[column] = (dt.datetime(1899, 12, 30) +
                                   dt.timedelta(days=float(value))).date().isoformat()
                except (OverflowError, ValueError):
                    pass
    return rows, columns


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = text.replace(",", "")
    text = re.sub(r"^(?:[$€£₹¥]\s*)+", "", text)
    text = re.sub(r"\s*(?:USD|EUR|GBP|INR|dollars?)$", "", text, flags=re.IGNORECASE)
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    if negative:
        result = -abs(result)
    return result if math.isfinite(result) else None


def date_value(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        pass
    for pattern in ("%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d, %Y",
                    "%B %d, %Y", "%m-%d-%Y", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def column_kind(rows: list[dict[str, Any]], column: str) -> str:
    values = [value for row in rows if (value := row.get(column)) not in (None, "")]
    if not values:
        return "empty"
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    date_matches = sum(date_value(value) is not None for value in values)
    if date_matches / len(values) >= 0.8:
        return "date"
    numeric_matches = sum(number(value) is not None for value in values)
    if numeric_matches / len(values) >= 0.8:
        return "number"
    return "text"


def dataset_info(dataset: Dataset) -> dict[str, Any]:
    kinds = {column: column_kind(dataset.rows, column) for column in dataset.columns}
    missing = {column: sum(row.get(column) in (None, "") for row in dataset.rows)
               for column in dataset.columns}
    serialized = [json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
                  for row in dataset.rows]
    duplicates = len(serialized) - len(set(serialized))
    return {
        "filename": dataset.filename,
        "rowCount": len(dataset.rows),
        "columnCount": len(dataset.columns),
        "columns": [{"name": column, "type": kinds[column], "missing": missing[column]}
                    for column in dataset.columns],
        "duplicateRows": duplicates,
        "preview": dataset.rows[:8],
    }


def choose_dimension(question: str, columns: list[str], kinds: dict[str, str]) -> str | None:
    text = question.casefold()
    aliases = {
        "product": ("product", "item", "sku"),
        "category": ("category", "segment", "type"),
        "region": ("region", "state", "territory", "country", "city", "location"),
        "customer": ("customer", "client", "account", "buyer"),
        "month": ("month", "monthly"),
        "date": ("date", "time", "day", "year"),
        "status": ("status", "stage", "outcome"),
        "source": ("source", "channel", "campaign"),
        "employee": ("employee", "owner", "assigned", "representative", "salesperson"),
    }
    for label, words in aliases.items():
        forms = set()
        for word in words:
            forms.update((word, word + "s"))
            if word.endswith("y"):
                forms.add(word[:-1] + "ies")
        if not any(re.search(rf"\b{re.escape(form)}\b", text) for form in forms):
            continue
        matching = [column for column in columns if any(
            word in column.casefold() for word in words)]
        if label == "month" or label == "date":
            matching = [column for column in columns if kinds[column] == "date"]
        if label == "region" and matching:
            matching.sort(key=lambda col: 0 if any(
                item in col.casefold() for item in ("region", "state", "country")) else 1)
        return matching[0] if matching else None
    for column in columns:
        normalized = re.sub(r"[^a-z0-9]+", " ", column.casefold()).strip()
        forms = {normalized, normalized + "s"}
        if normalized.endswith("y"):
            forms.add(normalized[:-1] + "ies")
        if normalized and re.search(
            rf"\bby\s+(?:the\s+)?(?:{'|'.join(re.escape(form) for form in forms)})\b", text
        ):
            return column
    if "distribution" in text or "breakdown" in text:
        return next((column for column in columns if kinds[column] == "text"), None)
    return None


def choose_metric(question: str, columns: list[str], kinds: dict[str, str]) -> str | None:
    numeric = [column for column in columns if kinds[column] == "number"]
    text = question.casefold()
    preferences = []
    for words in (("profit", "margin"), ("sales", "revenue"), ("amount", "value", "total"),
                  ("quantity", "units"), ("price", "cost"), ("count", "number")):
        if any(word in text for word in words):
            preferences.extend(words)
    for word in preferences:
        found = next((column for column in numeric if word in column.casefold()), None)
        if found:
            return found
    if not preferences:
        for word in ("sales", "revenue", "amount", "profit", "quantity", "price"):
            found = next((column for column in numeric if word in column.casefold()), None)
            if found:
                return found
    elif preferences:
        return None
    usable = [column for column in numeric if not re.search(
        r"(^id$|_id$|id$|^rank$)", column.casefold())]
    return usable[0] if usable else None


def relation_plan(question: str, dataset: Dataset, kinds: dict[str, str]) -> dict[str, Any]:
    candidates = [column for column in dataset.columns
                  if kinds[column] == "number" and not re.search(
                      r"(^id$|_id$|id$|^rank$)", column.casefold())]
    question_text = question.casefold()
    mentioned = []
    for column in candidates:
        words = re.findall(r"[a-z0-9]+", column.casefold())
        pattern = r"\b" + r"[\s_-]+".join(map(re.escape, words)) + r"s?\b"
        match = re.search(pattern, question_text) if words else None
        if match:
            mentioned.append((match.start(), column))
    if len(mentioned) < 2:
        available = ", ".join(candidates) or "none"
        raise ValueError(f"A relationship chart needs two numeric columns. Available numeric columns: {available}.")
    mentioned.sort()
    return {"operation": "scatter", "value_column": None, "group_by": None,
            "x_column": mentioned[0][1], "y_column": mentioned[1][1],
            "sort": "desc", "limit": 200, "filters": [], "chart": "scatter"}


def detect_simple_filters(question: str, dataset: Dataset, kinds: dict[str, str]) -> list[dict[str, Any]]:
    text = question.casefold()
    filters = []
    for column in dataset.columns:
        if kinds[column] != "text":
            continue
        candidates = {str(row[column]).strip() for row in dataset.rows
                      if row.get(column) not in (None, "")}
        matched = []
        for value in candidates:
            if not value or len(value) < 2:
                continue
            pattern = rf"(?<![\w]){re.escape(value.casefold())}(?![\w])"
            if re.search(pattern, text):
                matched.append(value)
        if len(matched) == 1:
            filters.append({"column": column, "operator": "eq", "value": matched[0]})
    return filters


def simple_plan(question: str, dataset: Dataset) -> dict[str, Any]:
    kinds = {column: column_kind(dataset.rows, column) for column in dataset.columns}
    if re.search(r"\b(relationship|correlation|correlate|scatter)\b", question, re.IGNORECASE):
        return relation_plan(question, dataset, kinds)
    dimension = choose_dimension(question, dataset.columns, kinds)
    metric = choose_metric(question, dataset.columns, kinds)
    filters = detect_simple_filters(question, dataset, kinds)
    text = question.casefold()
    top_match = re.search(r"\b(?:top|bottom|lowest|highest|best|worst)\s+(\d+)\b", text)
    limit = min(int(top_match.group(1)), 100) if top_match else 10
    if not top_match and "top" in text:
        limit = 5
    elif not top_match and any(word in text for word in ("highest", "lowest", "largest", "smallest")):
        limit = 1
    if any(word in text for word in ("how many", "number of", "count", "total number")):
        operation = "count"
    elif re.search(r"\b(show|list|display)\b", text) and not top_match and not any(
        word in text for word in ("total", "average", "avg", "mean", "sum", "trend", "revenue", "sales")):
        operation = "list"
    elif any(word in text for word in ("average", "avg", "mean")):
        operation = "average"
    elif any(word in text for word in ("minimum", "lowest", "smallest")):
        operation = "sum" if dimension else "min"
    elif any(word in text for word in ("maximum", "highest", "largest")) and not dimension:
        operation = "max"
    elif any(word in text for word in ("maximum", "highest", "largest", "top ",
                                       "bottom ", "best ", "worst ")):
        operation = "sum"
    else:
        operation = "sum"
    if re.search(r"\b(?:over time|trend|monthly|by month|per month)\b", text):
        dimension = next((column for column in dataset.columns if kinds[column] == "date"), None)
        if dimension is None:
            raise ValueError("This question asks for a time trend, but the dataset has no date column.")
    if dimension is None and operation not in ("count", "list", "min", "max", "sum", "average"):
        raise ValueError("I could not identify a column to group by. Try naming a category, product, region, or date column.")
    if operation not in ("count", "list") and metric is None:
        requested = next((word for word in ("sales", "revenue", "profit", "quantity", "price")
                          if word in text), None)
        if requested:
            raise ValueError(f"The dataset has no numeric column for {requested}. Available columns: {', '.join(dataset.columns)}.")
        raise ValueError("This analysis needs a numeric column, but none was detected in the dataset.")
    if operation == "list" and not top_match:
        limit = 100
    sort_order = "asc" if any(word in text for word in ("lowest", "bottom", "worst")) else "desc"
    chart = "line" if dimension and kinds.get(dimension) == "date" else (
        "bar" if dimension else "kpi")
    if dimension and kinds.get(dimension) == "date":
        chart = "line"
    if dimension and operation == "count" and "distribution" in text:
        chart = "donut"
    return {
        "operation": operation,
        "value_column": metric,
        "group_by": dimension,
        "sort": sort_order,
        "limit": limit,
        "filters": filters,
        "chart": "none" if operation == "list" else chart,
        "methodology": "Interpreted locally from the question and detected column types.",
    }


def gemini_plan(question: str, dataset: Dataset, previous: list[dict[str, Any]]) -> dict[str, Any]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("AI is not configured; using local question interpretation.")
    columns = [{"name": column, "type": column_kind(dataset.rows, column)}
               for column in dataset.columns]
    context = [{"question": item["question"], "method": item["result"]["method"]}
               for item in previous[-3:]]
    prompt = (
        "Turn the user's analytics question into a JSON query plan for the given dataset. "
        "Do not calculate or invent any result. Return JSON only with these keys: "
        "operation (sum, average, count, min, max, list, scatter), value_column (column name or null), "
        "group_by (column name or null), sort (asc or desc), limit (integer 1-200), "
        "x_column and y_column (numeric column names for scatter relationships), "
        "filters (array of {column, operator, value}; operator is eq, neq, contains, gt, gte, lt, lte), "
        "chart (bar, line, area, donut, scatter, kpi, none). Use only supplied columns. "
        "For top/bottom comparisons, set group_by and sort. For a time trend, group by a date column. "
        "If the requested metric or grouping is not in the schema, use null for that field. "
        "Date grouping is performed as month when group_by is a date column.\n"
        f"Columns: {json.dumps(columns, ensure_ascii=False)}\n"
        f"Recent conversation: {json.dumps(context, ensure_ascii=False)}\n"
        f"Question: {question}"
    )
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    request = urllib.request.Request(
        url,
        data=json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                         "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read(256 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"AI interpretation request failed (HTTP {exc.code}); using local question interpretation.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"AI interpretation failed ({type(exc).__name__}); using local question interpretation.") from exc
    try:
        raw = payload["candidates"][0]["content"]["parts"][0]["text"]
        plan = json.loads(raw)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI returned an invalid query plan; using local question interpretation.") from exc
    if not isinstance(plan, dict):
        raise RuntimeError("AI returned an invalid query plan; using local question interpretation.")
    return plan


def validate_plan(plan: dict[str, Any], dataset: Dataset) -> dict[str, Any]:
    operations = {"sum", "average", "count", "min", "max", "list", "scatter"}
    charts = {"bar", "line", "area", "donut", "scatter", "kpi", "none"}
    columns = set(dataset.columns)
    operation = str(plan.get("operation", "sum")).lower()
    if operation not in operations:
        raise ValueError("The question could not be mapped to a supported analysis.")
    value_column = plan.get("value_column")
    group_by = plan.get("group_by")
    x_column, y_column = plan.get("x_column"), plan.get("y_column")
    if value_column not in columns:
        value_column = None
    if group_by not in columns:
        group_by = None
    kinds = {column: column_kind(dataset.rows, column) for column in dataset.columns}
    if operation == "scatter":
        if (x_column not in columns or y_column not in columns or x_column == y_column or
                kinds[x_column] != "number" or kinds[y_column] != "number"):
            raise ValueError("The relationship question needs two different numeric columns.")
    elif operation not in {"count", "list"} and (value_column is None or kinds[value_column] != "number"):
        raise ValueError("The requested numeric measure is not available in this dataset.")
    if operation in ("sum", "average") and value_column is None:
        raise ValueError("Choose a numeric column to calculate a total or average.")
    try:
        maximum_limit = 200 if operation == "scatter" else 100
        limit = max(1, min(maximum_limit, int(plan.get("limit", 10))))
    except (TypeError, ValueError):
        limit = 10
    filters = plan.get("filters", [])
    if not isinstance(filters, list) or len(filters) > 10:
        raise ValueError("The requested filters are not valid.")
    valid_filters = []
    for item in filters:
        if not isinstance(item, dict) or item.get("column") not in columns:
            raise ValueError("The requested filter uses an unknown column.")
        operator = item.get("operator")
        if operator not in {"eq", "neq", "contains", "gt", "gte", "lt", "lte"}:
            raise ValueError("The requested filter uses an unsupported comparison.")
        valid_filters.append({"column": item["column"], "operator": operator,
                              "value": item.get("value")})
    sort = "asc" if str(plan.get("sort", "desc")).lower() == "asc" else "desc"
    chart = str(plan.get("chart", "bar")).lower()
    if chart not in charts:
        chart = "bar" if group_by else "kpi"
    if group_by and kinds[group_by] == "date" and chart not in {"line", "area"}:
        chart = "line"
    if operation == "scatter":
        chart = "scatter"
    return {"operation": operation, "value_column": value_column, "group_by": group_by,
            "x_column": x_column if operation == "scatter" else None,
            "y_column": y_column if operation == "scatter" else None,
            "sort": sort, "limit": limit, "filters": valid_filters, "chart": chart}


def filter_rows(rows: list[dict[str, Any]], filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def matches(row: dict[str, Any], item: dict[str, Any]) -> bool:
        actual = row.get(item["column"])
        expected = item.get("value")
        operator = item["operator"]
        if operator == "contains":
            return str(expected).casefold() in str(actual or "").casefold()
        left_number, right_number = number(actual), number(expected)
        if left_number is not None and right_number is not None:
            left, right = left_number, right_number
        else:
            left, right = str(actual or "").casefold(), str(expected or "").casefold()
        return {
            "eq": lambda: left == right, "neq": lambda: left != right,
            "gt": lambda: left > right, "gte": lambda: left >= right,
            "lt": lambda: left < right, "lte": lambda: left <= right,
        }[operator]()
    return [row for row in rows if all(matches(row, item) for item in filters)]


def group_label(value: Any, date_column: bool) -> str:
    if date_column:
        parsed = date_value(value)
        if parsed:
            return f"{MONTH_NAMES[parsed.month - 1]} {parsed.year}"
    return str(value) if value not in (None, "") else "(Blank)"


def analyze(question: str, dataset: Dataset) -> dict[str, Any]:
    with LOCK:
        previous = list(HISTORY)
    warning = ""
    try:
        plan = validate_plan(simple_plan(question, dataset), dataset)
        interpretation = "Local question interpretation."
    except ValueError as local_error:
        try:
            ai_plan = gemini_plan(question, dataset, previous)
            plan = validate_plan(ai_plan, dataset)
            interpretation = "AI-assisted question interpretation."
        except RuntimeError as exc:
            raise ValueError(f"{local_error} {exc}") from exc
    rows = filter_rows(dataset.rows, plan["filters"])
    operation, metric, group_by = plan["operation"], plan["value_column"], plan["group_by"]
    chart_points: list[dict[str, Any]] = []
    correlation: float | None = None
    method_row_count = len(rows)
    if operation == "scatter":
        x_column, y_column = plan["x_column"], plan["y_column"]
        pairs = [(number(row.get(x_column)), number(row.get(y_column))) for row in rows]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if len(pairs) < 2:
            raise ValueError("At least two records with values in both selected columns are needed for a relationship chart.")
        mean_x = sum(x for x, _ in pairs) / len(pairs)
        mean_y = sum(y for _, y in pairs) / len(pairs)
        variance_x = sum((x - mean_x) ** 2 for x, _ in pairs)
        variance_y = sum((y - mean_y) ** 2 for _, y in pairs)
        if variance_x == 0 or variance_y == 0:
            raise ValueError("A relationship chart needs variation in both numeric columns.")
        correlation = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / math.sqrt(variance_x * variance_y)
        direction = "positive" if correlation > 0 else "negative"
        strength = "weak" if abs(correlation) < 0.3 else "moderate" if abs(correlation) < 0.7 else "strong"
        result_columns = [x_column, y_column]
        output = [{x_column: clean_number(x), y_column: clean_number(y)}
                  for x, y in pairs[:plan["limit"]]]
        chart_points = [{"x": x, "y": y} for x, y in pairs[:plan["limit"]]]
        series = []
        chart_type = "scatter"
        method_row_count = len(pairs)
        statement = (f"{x_column} and {y_column} show a {strength} {direction} linear relationship "
                     f"(Pearson r = {correlation:.3f}) across {len(pairs):,} records.")
    elif operation == "list":
        output = [{column: safe_json_value(row.get(column)) for column in dataset.columns}
                  for row in rows[:plan["limit"]]]
        result_columns = list(dataset.columns)
        series = []
        chart_type = "none"
        statement = (f"No matching records were found in {dataset.filename}."
                     if not rows else f"Showing {len(output):,} of {len(rows):,} matching records.")
    elif group_by:
        groups: dict[str, list[Any]] = {}
        group_dates: dict[str, dt.date] = {}
        is_date = column_kind(dataset.rows, group_by) == "date"
        for row in rows:
            label = group_label(row.get(group_by), is_date)
            groups.setdefault(label, []).append(row.get(metric) if metric else row)
            parsed_date = date_value(row.get(group_by)) if is_date else None
            if parsed_date and (label not in group_dates or parsed_date < group_dates[label]):
                group_dates[label] = parsed_date
        output = []
        for label, values in groups.items():
            valid = [item for value in values if metric and (item := number(value)) is not None]
            result = aggregate(operation, values, valid)
            output.append({group_by if not is_date else "Month": label,
                           metric if metric else "Records": result})
        sort_column = metric if metric else "Records"
        if is_date:
            output.sort(key=lambda item: group_dates.get(
                str(item.get("Month", item.get(group_by))), dt.date.min))
            plan["limit"] = 100
        else:
            output.sort(key=lambda item: sortable(item[sort_column]), reverse=plan["sort"] == "desc")
        output = output[:plan["limit"]]
        result_columns = list(output[0]) if output else [group_by, metric or "Records"]
        series = [{"label": str(row[result_columns[0]]),
                   "value": number(row[result_columns[1]]) or 0} for row in output]
        chart_type = plan["chart"]
        statement = (time_series_statement(operation, metric, output)
                     if is_date else grouped_statement(
                         operation, metric, result_columns[0], output, plan["sort"]))
    else:
        values = [row.get(metric) for row in rows] if metric else rows
        valid = [item for value in values if metric and (item := number(value)) is not None]
        result = aggregate(operation, values, valid)
        result_columns = [metric or "Metric", "Result"]
        output = [{result_columns[0]: metric or "Records", "Result": result}]
        series = [{"label": result_columns[0], "value": number(result) or 0}]
        chart_type = "kpi" if plan["chart"] == "none" else plan["chart"]
        statement = scalar_statement(operation, metric, result, len(rows))
    method = methodology(operation, metric, group_by, plan["filters"], method_row_count,
                         interpretation, plan["sort"], plan["limit"], dataset,
                         plan.get("x_column"), plan.get("y_column"), correlation)
    result_object = {
        "question": question,
        "statement": statement,
        "columns": result_columns,
        "rows": output,
        "chart": {"type": chart_type, "series": series, "points": chart_points,
                  "xLabel": plan.get("x_column"), "yLabel": plan.get("y_column")},
        "method": method,
        "warning": warning,
        "datasetName": dataset.filename,
        "datasetRows": len(dataset.rows),
    }
    with LOCK:
        HISTORY.append({"id": str(uuid.uuid4()), "question": question,
                        "result": result_object, "createdAt": dt.datetime.now().isoformat(timespec="seconds")})
        del HISTORY[:-MAX_HISTORY]
    return result_object


def sortable(value: Any) -> tuple[int, Any]:
    numeric = number(value)
    return (0, numeric) if numeric is not None else (1, str(value).casefold())


def aggregate(operation: str, values: list[Any], valid: list[float]) -> int | float:
    if operation == "count":
        return len(values)
    if not valid:
        return 0
    if operation == "sum":
        return clean_number(sum(valid))
    if operation == "average":
        return clean_number(sum(valid) / len(valid))
    if operation == "min":
        return clean_number(min(valid))
    return clean_number(max(valid))


def clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 4)


def pretty(value: Any) -> str:
    value = number(value)
    if value is None:
        return str(value)
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def scalar_statement(operation: str, metric: str | None, result: Any, rows: int) -> str:
    if operation == "count":
        return f"There are {pretty(result)} records in the dataset."
    if operation == "average":
        return f"The average {metric} is {pretty(result)} across {rows:,} records."
    if operation == "min":
        return f"The lowest {metric} is {pretty(result)}."
    if operation == "max":
        return f"The highest {metric} is {pretty(result)}."
    return f"Total {metric} is {pretty(result)} across {rows:,} records."


def grouped_statement(operation: str, metric: str | None, dimension: str,
                      rows: list[dict[str, Any]], sort: str) -> str:
    if not rows:
        return f"No matching records were found for this {dimension} breakdown."
    first = rows[0]
    measure = next((column for column in first if column != dimension and column != "Month"), "Records")
    label_column = dimension if dimension in first else "Month"
    verb = {"sum": "leads", "average": "has the highest average", "count": "has the most records",
            "min": "has the smallest", "max": "has the largest"}.get(operation, "leads")
    if operation == "sum":
        if sort == "asc":
            return f"{first[label_column]} has the lowest total {metric} at {pretty(first[measure])}."
        statement = f"{first[label_column]} leads {dimension} by {pretty(first[measure])} {metric}"
        if len(rows) > 1:
            statement += f", followed by {rows[1][label_column]} ({pretty(rows[1][measure])})"
        return statement + "."
    if operation == "average":
        return f"{first[label_column]} has the highest average {metric} at {pretty(first[measure])}."
    if operation == "count":
        if sort == "asc":
            return f"{first[label_column]} has the fewest records ({pretty(first[measure])})."
        return f"{first[label_column]} has the most records ({pretty(first[measure])})."
    return f"{first[label_column]} {verb} {metric} at {pretty(first[measure])}."


def time_series_statement(operation: str, metric: str | None,
                          rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No dated records matched this trend."
    label_column = "Month"
    value_column = metric or "Records"
    if len(rows) == 1:
        return (f"The dataset contains one month of data: {value_column} was "
                f"{pretty(rows[0][value_column])} in {rows[0][label_column]}.")
    first, last = rows[0], rows[-1]
    return (f"{value_column} was {pretty(first[value_column])} in {first[label_column]} "
            f"and {pretty(last[value_column])} in {last[label_column]}, "
            f"across {len(rows)} months of data.")


def methodology(operation: str, metric: str | None, group_by: str | None,
                filters: list[dict[str, Any]], row_count: int,
                interpretation: str, sort: str, limit: int, dataset: Dataset,
                x_column: str | None = None, y_column: str | None = None,
                correlation: float | None = None) -> str:
    expression = {"sum": "sum", "average": "arithmetic mean", "count": "record count",
                  "min": "minimum", "max": "maximum", "list": "record listing",
                  "scatter": "Pearson correlation"}[operation]
    details = [interpretation, f"Applied {len(filters)} filter(s) to {row_count:,} matching records.",
               f"Calculated {expression}" +
               (f" of “{metric}”" if metric and operation != "list" else "") + "."]
    if operation == "scatter":
        details.append(f"Compared “{x_column}” with “{y_column}”; Pearson r = {correlation:.3f} "
                       f"across {row_count:,} complete numeric pairs.")
        details.append(f"Chart and table show up to {limit} pairs.")
    if group_by:
        is_date = column_kind(dataset.rows, group_by) == "date"
        details.append(f"Grouped by “{group_by}”" + (" by calendar month" if is_date else "") + ".")
        details.append("Ordered chronologically; displayed up to 100 groups." if is_date
                       else f"Sorted {sort}ending; displayed up to {limit} groups.")
    for item in filters:
        details.append(f"Filter: {item['column']} {item['operator']} {item['value']}.")
    return " ".join(details)


def safe_json_value(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def make_xlsx(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    def cell(ref: str, value: Any) -> str:
        if value is None:
            return f'<c r="{ref}"/>'
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        clean_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))
        text = html.escape(clean_text, quote=False)
        preserve = ' xml:space="preserve"' if str(value).strip() != str(value) else ""
        return f'<c r="{ref}" t="inlineStr"><is><t{preserve}>{text}</t></is></c>'

    def column_name(index: int) -> str:
        out = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            out = chr(65 + remainder) + out
        return out

    sheet_rows = []
    for row_index, values in enumerate([columns] + [[row.get(col) for col in columns] for row in rows], start=1):
        sheet_rows.append(f'<row r="{row_index}">' + "".join(
            cell(f"{column_name(col_index)}{row_index}", value)
            for col_index, value in enumerate(values, start=1)) + "</row>")
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>' + "".join(sheet_rows) + '</sheetData></worksheet>')
    parts = {
        "[Content_Types].xml": ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'),
        "_rels/.rels": ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'),
        "xl/workbook.xml": ('<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Analysis" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'),
        "xl/worksheets/sheet1.xml": sheet,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value.encode("utf-8"))
    return output.getvalue()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=safe_json_value,
                      allow_nan=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "DataDesk/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {format % args}")

    def send_json(self, status: int, value: Any) -> None:
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length.") from exc
        if length < 1 or length > MAX_UPLOAD_BYTES * 2:
            raise ValueError("The request is empty or too large.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("The request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("The request body must be a JSON object.")
        return payload

    def do_GET(self) -> None:
        global DATASET
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            with LOCK:
                dataset = DATASET
                history = list(reversed(HISTORY))
            self.send_json(200, {
                "dataset": dataset_info(dataset) if dataset else None,
                "history": history,
                "aiAvailable": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
            })
            return
        if path == "/api/sample":
            try:
                with LOCK:
                    DATASET = make_dataset(SAMPLE.name, SAMPLE.read_bytes())
                    HISTORY.clear()
                    info = dataset_info(DATASET)
                self.send_json(200, {"dataset": info})
            except (OSError, ValueError) as exc:
                self.send_json(500, {"error": str(exc)})
            return
        if path == "/api/original":
            with LOCK:
                dataset = DATASET
            if not dataset:
                self.send_json(404, {"error": "There is no dataset to download."})
                return
            self.send_response(200)
            self.send_header("Content-Type", dataset.content_type)
            self.send_header("Content-Length", str(len(dataset.original)))
            self.send_header("Content-Disposition",
                             f'attachment; filename="{Path(dataset.filename).name}"')
            self.end_headers()
            self.wfile.write(dataset.original)
            return
        if path == "/":
            self.serve_static("index.html")
            return
        if path.startswith("/static/"):
            self.serve_static(path.removeprefix("/static/"))
            return
        self.send_json(404, {"error": "Not found."})

    def serve_static(self, filename: str) -> None:
        try:
            target = (STATIC / filename).resolve()
            target.relative_to(STATIC.resolve())
            if not target.is_file():
                raise FileNotFoundError
            body = target.read_bytes()
        except (OSError, ValueError):
            self.send_json(404, {"error": "Not found."})
            return
        content_type = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                        ".js": "text/javascript; charset=utf-8"}.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        global DATASET
        path = self.path.split("?", 1)[0]
        try:
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin and origin not in {f"http://{host}", f"https://{host}"}:
                self.send_json(403, {"error": "Cross-origin requests are not allowed."})
                return
            payload = self.read_json()
            if path == "/api/upload":
                filename = str(payload.get("filename", "dataset"))
                encoded = payload.get("contentBase64")
                if not isinstance(encoded, str):
                    raise ValueError("The upload did not include file contents.")
                try:
                    content = base64.b64decode(encoded, validate=True)
                except (ValueError, base64.binascii.Error) as exc:
                    raise ValueError("The uploaded file data is invalid.") from exc
                if not content or len(content) > MAX_UPLOAD_BYTES:
                    raise ValueError("Choose a file smaller than 12 MB.")
                dataset = make_dataset(filename, content)
                with LOCK:
                    DATASET = dataset
                    HISTORY.clear()
                self.send_json(200, {"dataset": dataset_info(dataset)})
                return
            if path == "/api/ask":
                question = payload.get("question")
                if not isinstance(question, str) or not question.strip():
                    raise ValueError("Type a question about your data first.")
                if len(question) > 1_000:
                    raise ValueError("Questions must be 1,000 characters or fewer.")
                with LOCK:
                    dataset = DATASET
                if not dataset:
                    raise ValueError("Upload a dataset or load the sample dataset first.")
                result = analyze(question.strip(), dataset)
                self.send_json(200, {"result": result})
                return
            if path == "/api/export":
                columns, rows = payload.get("columns"), payload.get("rows")
                format_name = payload.get("format")
                if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
                    raise ValueError("The export columns are invalid.")
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                    raise ValueError("The export rows are invalid.")
                if len(rows) > MAX_ROWS:
                    raise ValueError("The result contains too many rows to export.")
                if format_name == "xlsx":
                    body = make_xlsx(columns, rows)
                    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    extension = "xlsx"
                elif format_name == "csv":
                    output = io.StringIO(newline="")
                    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
                    body = output.getvalue().encode("utf-8-sig")
                    content_type, extension = "text/csv; charset=utf-8", "csv"
                else:
                    raise ValueError("Choose CSV or Excel export.")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition",
                                 f'attachment; filename="analysis.{extension}"')
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_json(404, {"error": "Not found."})
        except (ValueError, TypeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
            self.send_json(400, {"error": f"The request could not be processed: {type(exc).__name__}."})
        except Exception as exc:
            self.send_json(500, {"error": f"Analysis failed: {type(exc).__name__}."})


def main() -> None:
    global DATASET
    load_local_settings()
    try:
        DATASET = make_dataset(SAMPLE.name, SAMPLE.read_bytes())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not load the bundled sample dataset: {exc}") from exc
    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8000"))), Handler)
    print(f"Data Desk is ready at http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Data Desk.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
