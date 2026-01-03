from __future__ import annotations

import difflib
import re
from typing import Literal, cast


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        try:
            value_num = cast(float | int | str, value)
            return int(float(value_num))
        except Exception:
            return default
    return default


def _to_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, str)):
        try:
            value_num = cast(float | int | str, value)
            return float(value_num)
        except Exception:
            return default
    return default


def _to_side(value: object) -> Literal["BUY", "SELL"]:
    raw = str(value)
    return cast(Literal["BUY", "SELL"], raw)


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _ratio(a: str, b: str) -> int:
    if not a or not b:
        return 0
    return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)


def _safe_path_segment(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_")
    return cleaned or "unknown"


def _extract_team_from_question(title: str) -> str | None:
    match = re.search(r"\bwill\s+(.+?)\s+win\b", title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
