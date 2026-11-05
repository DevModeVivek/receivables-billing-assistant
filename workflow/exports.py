"""Safe file exports and uploads.

Exports: any text cell that starts with =, +, -, @, a tab or a carriage return
is prefixed with an apostrophe, so a spreadsheet opens it as text and never
runs it as a formula (CSV / formula injection). Numbers are left as numbers.

Uploads: size and row limits, and only the expected columns are read.
"""
from __future__ import annotations

import io
from typing import Optional

import pandas as pd

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
MAX_UPLOAD_BYTES = 1_000_000  # 1 MB
MAX_UPLOAD_ROWS = 200


def safe_cell(value):
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(safe_cell)
    out.columns = [safe_cell(str(c)) for c in out.columns]
    return out


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return safe_frame(df).to_csv(index=False).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame, sheet: str = "Sheet1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        safe_frame(df).to_excel(xl, index=False, sheet_name=sheet[:31])
    return buf.getvalue()


class UploadError(ValueError):
    pass


def read_upload(name: str, data: bytes, max_rows: int = MAX_UPLOAD_ROWS) -> pd.DataFrame:
    """Read an uploaded CSV or Excel file as text, within the size and row limits."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"The file is larger than {MAX_UPLOAD_BYTES // 1_000_000} MB.")
    lower = name.lower()
    try:
        if lower.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(data), dtype=str, nrows=max_rows + 1)
        elif lower.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(data), dtype=str, nrows=max_rows + 1)
        else:
            raise UploadError("Please upload a .csv or .xlsx file.")
    except UploadError:
        raise
    except Exception:
        raise UploadError("The file could not be read. Please check it is a valid CSV or Excel file.")
    if len(df) > max_rows:
        raise UploadError(f"The file has more than {max_rows} rows. Please split it into smaller files.")
    return df.dropna(how="all")


def match_columns(df: pd.DataFrame, labels: dict) -> Optional[pd.DataFrame]:
    """Map the uploaded headers to request fields by their label or field name. Unknown columns are ignored."""
    lookup = {v.strip().lower(): k for k, v in labels.items()}
    lookup.update({k.lower(): k for k in labels})
    mapped = {c: lookup[str(c).strip().lower()] for c in df.columns if str(c).strip().lower() in lookup}
    if not mapped:
        return None
    return df[list(mapped)].rename(columns=mapped)
