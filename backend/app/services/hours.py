"""Parse Google weekday opening-hours descriptions ("Saturday: 7:30 AM – 12:00 AM") into minutes."""
import re
from typing import Optional

_SP = str.maketrans({" ": " ", " ": " ", " ": " ", "–": "-", "—": "-"})
_TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap]m)?$", re.I)


def _t(tok: str, suffix: Optional[str] = None) -> Optional[tuple[int, Optional[str]]]:
    m = _TIME.match(tok.strip())
    if not m:
        return None
    h, mi, suf = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or suffix)
    if mi > 59 or h > 24:
        return None
    if suf:
        suf = suf.lower()
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if suf == "pm" else 0)
    return h * 60 + mi, (m.group(3) or None)


def parse_day_hours(desc: str):
    """None = unknown, [] = closed, list of (open_min, close_min); close > 1440 means past midnight."""
    if not isinstance(desc, str) or not desc.strip():
        return None
    text = desc.translate(_SP).strip()
    if re.match(r"^\s*[A-Za-z]+\s*:", text):
        text = text.split(":", 1)[1].strip()
    low = text.lower()
    if low.startswith("closed"):
        return []
    if "24 hours" in low:
        return [(0, 1440)]
    out = []
    for rng in text.split(","):
        parts = [x.strip() for x in rng.split("-")]
        if len(parts) != 2:
            return None
        second = _t(parts[1])
        if second is None:
            return None
        first = _t(parts[0], second[1])
        if first is None:
            return None
        o, c = first[0], second[0]
        if first[1] is None and second[1] is not None and o > c and o - 720 >= 0:
            o -= 720  # "11:00 - 2:00 PM" -> 11 AM
        if c == o:
            out.append((0, 1440))
            continue
        if c < o:
            c += 1440
        out.append((o, c))
    return out or None


def is_open_at(weekday_hours: list[str], weekday: int, minute: int) -> Optional[bool]:
    """weekday: Monday=0. Returns None when unknown. Handles ranges that run past midnight."""
    if len(weekday_hours) != 7:
        return None
    today = parse_day_hours(weekday_hours[weekday % 7])
    if today is None:
        return None
    for o, c in today:
        if o <= minute < c:
            return True
    prev = parse_day_hours(weekday_hours[(weekday - 1) % 7]) or []
    for o, c in prev:
        if c > 1440 and minute < c - 1440:
            return True
    return False
