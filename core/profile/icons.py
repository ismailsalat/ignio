# core/profile/icons.py
"""Reusable icon loader. Drop PNGs in core/profile/icons/ and grab them here."""
import os
from PIL import Image

ICON_DIR = os.path.dirname(__file__) + "/icons"
_cache = {}


def icon(name: str, size: int | None = None) -> Image.Image | None:
    """Load an icon by name (without .png). Cached. Optional resize."""
    key = (name, size)
    if key in _cache:
        return _cache[key].copy()
    path = os.path.join(ICON_DIR, name + ".png")
    if not os.path.exists(path):
        return None
    img = Image.open(path).convert("RGBA")
    if size:
        img = img.resize((size, size))
    _cache[key] = img
    return img.copy()


def paste_icon(canvas, name, xy, size):
    ic = icon(name, size)
    if ic is not None:
        canvas.alpha_composite(ic, xy)
