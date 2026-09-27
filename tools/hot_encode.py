"""English text -> engine codes, with pixel-accurate word wrap.

A message is a list of lines; lines are joined with code 1 (newline) and the message
ends with code 0. Explicit '\\n' in the source is honoured; everything else is wrapped
to `max_px` pixels using the proportional widths from hot_font.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hot_font import CODE_OF, WIDTH_OF, text_width

DEFAULT_MAX_PX = 160


class EncodeError(ValueError):
    pass


def wrap_line(text: str, max_px: int) -> list[str]:
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        if w == "":
            continue
        cand = w if not cur else cur + " " + w
        if text_width(cand) <= max_px:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = w
        while text_width(cur) > max_px:          # a single word wider than the line
            for k in range(len(cur), 0, -1):
                if text_width(cur[:k]) <= max_px:
                    lines.append(cur[:k]); cur = cur[k:]; break
            else:
                raise EncodeError(f"cannot fit {cur!r}")
    if cur:
        lines.append(cur)
    return lines


def wrap(text: str, max_px: int = DEFAULT_MAX_PX) -> list[str]:
    out = []
    for para in text.split("\n"):
        if text_width(para) <= max_px:
            out.append(para)                     # verbatim: keeps deliberate spacing
        else:
            out.extend(wrap_line(para, max_px) or [""])
    return out


def encode_lines(lines: list[str]) -> list[int]:
    codes = []
    for i, line in enumerate(lines):
        for ch in line:
            if ch not in CODE_OF:
                raise EncodeError(f"no glyph for {ch!r} in line {line!r}")
            codes.append(CODE_OF[ch])
        if i < len(lines) - 1:
            codes.append(1)
    codes.append(0)
    return codes


def encode(text: str, max_px: int = DEFAULT_MAX_PX) -> list[int]:
    return encode_lines(wrap(text, max_px))


if __name__ == "__main__":
    s = " ".join(sys.argv[1:]) or "Let's take a peek at who will read your fortune."
    for ln in wrap(s):
        print(f"{text_width(ln):3d}px  {ln}")
    print(encode(s))
