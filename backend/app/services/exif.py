import io
from typing import Optional

from PIL import Image

_GPS_IFD = 0x8825


def _to_float(v) -> float:
    try:
        return float(v)
    except TypeError:  # older Pillow rationals
        return v[0] / v[1]


def _dms_to_deg(dms, ref) -> Optional[float]:
    try:
        d, m, s = (_to_float(x) for x in dms)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    deg = d + m / 60.0 + s / 3600.0
    if isinstance(ref, bytes):
        ref = ref.decode(errors="ignore")
    if ref in ("S", "W"):
        deg = -deg
    return deg


def extract_gps(data: bytes) -> Optional[tuple[float, float]]:
    """Return (lat, lng) from EXIF GPS if present and sane, else None. Never raises."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            gps = img.getexif().get_ifd(_GPS_IFD)
    except Exception:
        return None
    if not gps:
        return None
    # tags: 1=LatRef 2=Lat 3=LngRef 4=Lng
    if not all(k in gps for k in (1, 2, 3, 4)):
        return None
    lat = _dms_to_deg(gps[2], gps[1])
    lng = _dms_to_deg(gps[4], gps[3])
    if lat is None or lng is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if lat == 0 and lng == 0:
        return None
    return lat, lng
