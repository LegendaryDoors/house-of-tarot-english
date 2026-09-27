"""Build 'House of Tarot (J) [EN].gg' from the pristine ROM.

Steps: expand to 256 KB -> patch the text engine (uncompressed messages, 3-byte
pointer table, proportional widths) -> write the English font -> insert every
message (English where a translation exists, original codes otherwise) -> save.

Engine patches (bank 0 unless noted), each verified against the original bytes:
  P1 0x18B2  symbol fetch: plain byte read from (C985) instead of Huffman decode
  P2 0x183F  message lookup: 3-byte pointer entries [bank][offset lo][offset hi]
  P3 0x1A91  advance: 'ld a,(C980)' -> 'call WIDTH' (per-glyph width table)
  P4 0x1AA3  dakuten overlay check disabled ('or a; ret')
  P5 0x1A24  glyphs per line: fixed 40 (lines end on code 1/0 instead)
  P6 0x1A57  line end: skip the space fill (buffer is pre-cleared)
  WIDTH routine at 0x4DD0 and width table at 0x4DE0 (old dictionary area, bank 1)
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hot_font import CODE_OF, WIDTH_OF, MAX_CODE, cell_bytes, CHAR_OF
from hot_encode import encode, encode_lines, EncodeError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "House of Tarot (J).gg"
DST = ROOT / "House of Tarot (J) [EN].gg"
MESSAGES = ROOT / "out/messages.json"
TRANSLATIONS = ROOT / "translations"
PTR_TABLE = 0x4F20
FONT = 0x38F0
WIDTH_ROUTINE, WIDTH_TABLE = 0x4DD0, 0x4DE0
FIRST_TEXT_BANK = 8
ROM_SIZE = 256 * 1024
BUFFER_LIMIT = 0x700          # inflated message must fit the relocated $D000-$D7FF buffer
TICKER_IDS = {762, 763, 764, 845}   # marquee messages: one long line, never wrapped
BUF_BASE, BUF_LIMIT = 0xD000, 0xD800  # relocated inflate buffer (was $C880-$C97F)

MARGIN_PX = 4                 # wrap 4 px short of the box: 2 px start offset (P10) + 2 px right margin
CARD_COLUMN = lambda mid: 720 <= mid < 741 or 818 <= mid < 842     # labels beside the card picture

def indent_px(mid: int) -> int:
    """Extra left indent, in 4-px spaces, for the card-reveal column so text stands off the card."""
    return 8 if CARD_COLUMN(mid) else 0


def fit_lines(mid: int, text: str) -> list[str]:
    """Wrap `text` for message `mid` and apply its indent. Shared by build, checker and renderer."""
    from hot_encode import wrap
    if mid in TICKER_IDS:
        return [text]
    lines = wrap(text, wrap_px(mid) - indent_px(mid))
    pad = " " * (indent_px(mid) // 4)
    return [pad + ln for ln in lines]

def wrap_px(mid: int) -> int:
    px, _ = layout(mid)
    if 776 <= mid < 788:            # zodiac menu names sit before a column gap; full 64 px is safe
        return px
    return px if px >= 10**5 else px - MARGIN_PX


def layout(mid: int) -> tuple[int, int]:
    """(max line width px, max lines) for a message id, from the drawing code in bank 0."""
    if mid < 660: return 160, 6            # readings (6-line box at row 6)
    if mid < 696: return 160, 6            # zodiac readings
    if mid < 720: return 96, 1             # category menu labels (0x16DB: 12 tiles)
    if mid < 741: return 72, 2             # category heading beside the card (0x1719: 9 tiles x 2)
    if mid < 762: return 112, 2            # reading-screen heading (0x1784: 14 tiles x 2)
    if mid in TICKER_IDS: return 10**6, 1
    if mid == 765: return 144, 1           # teller names under the portraits (18 tiles)
    if mid == 766 or 773 <= mid <= 775: return 160, 3
    if 767 <= mid <= 771: return 160, 2    # teller greeting (2 lines + prompt line 772)
    if mid == 772: return 160, 1
    if mid < 788: return 64, 1             # zodiac menu names after the 16-px symbol (0x1482: 10 tiles)
    if mid < 800: return 112, 1            # "<sign> person" (0x150C: 14 tiles)
    if mid < 812: return 160, 1            # date ranges
    if mid < 818: return 160, 3            # prompts
    if mid < 840: return 72, 2             # card names (0x1753: 9 tiles x 2)
    if mid < 842: return 72, 1             # upright / reversed
    if mid < 845: return 160, 3            # farewells
    return 160, 6


def patch(rom: bytearray, off: int, new: bytes, expect: bytes | None = None, name: str = ""):
    if expect is not None:
        got = bytes(rom[off:off + len(expect)])
        assert got == expect, f"{name}: bytes at {off:05X} are {got.hex(' ')}, expected {expect.hex(' ')}"
    rom[off:off + len(new)] = new


def apply_engine_patches(rom: bytearray):
    # P1: symbol fetch
    patch(rom, 0x18B2, bytes.fromhex("e5 2a 85 c9 7e 23 22 85 c9 e1 c9"),
          expect=bytes.fromhex("d5 e5 dd e5 21 c0 55"), name="P1")
    # P2: pointer lookup (3-byte entries); original 183F..1866, we use 183F..185E and jr to 1867
    new = bytes.fromhex("54 5d 29 19 11 20 4f 19 7e 32 ff ff 23 7e 23 66 6f 7c e6 3f f6 80 67 22 85 c9 af 32 88 c9 18 08")
    assert len(new) == 32 and 0x183F + 32 == 0x185F
    patch(rom, 0x183F, new + bytes(8), expect=bytes.fromhex("29 11 20 4f 19 7e 23 66 6f 7c cb 3f"), name="P2")
    assert rom[0x1867:0x186A] == bytes.fromhex("11 80 c8")
    # P3: per-glyph advance. The original 0x1A8A assumed advances >= 8 px (it always stepped
    # one tile); rewrite as: a = width(c) + shift; while a >= 8: a -= 8, buffer += 8; shift = a
    adv = bytes([0xF5, 0xE5, 0x6B, 0x62, 0x11, 0x08, 0x00,
                 0xCD, WIDTH_ROUTINE & 0xFF, WIDTH_ROUTINE >> 8,      # call WIDTH -> a
                 0x80,                                               # add a,b
                 0xFE, 0x08, 0x38, 0x04,                             # cp 8; jr c,+4
                 0x93, 0x19, 0x18, 0xF8,                             # sub e; add hl,de; jr -8
                 0x47, 0x5D, 0x54, 0xE1, 0xF1, 0xC9])                # ld b,a; ld e,l; ld d,h; pop hl; pop af; ret
    assert len(adv) == 25
    patch(rom, 0x1A8A, adv, expect=bytes.fromhex("f5 e5 6b 62 11 08 00 3a 80 c9 80 fe 10 38 02 93 19 93 19 47 5d 54 e1 f1 c9"), name="P3")
    # P4: dakuten overlay off
    patch(rom, 0x1AA3, bytes.fromhex("b7 c9"), expect=bytes.fromhex("fe 08 28 06"), name="P4")
    # P5: glyphs per line = 40
    patch(rom, 0x1A24, bytes.fromhex("06 28 00 00"), expect=bytes.fromhex("3a 81 c9 47"), name="P5")
    # P10: every line starts 2 px in (kana cells had built-in padding; Latin letters do not)
    patch(rom, 0x1A20, bytes.fromhex("dd 36 00 02"), expect=bytes.fromhex("dd 36 00 00"), name="P10")
    # P6: no space fill at line end -> jr 0x1A4A
    patch(rom, 0x1A57, bytes.fromhex("18 f1"), expect=bytes.fromhex("c5 dd 46 00 0e 02"), name="P6")
    # P7: ticker/typewriter packs two 8-px letters per 16-px cell:
    #   0x1282 'call 1AA3; jr nc,1296' -> 'ld a,(hl); cp 2; jr c,1296'  (peek next code; end/newline -> single)
    #   0x128E 'ld b,0' -> 'ld b,8'  (second glyph at pixel offset 8)
    #   0x1264 'ld b,0x10' -> 'ld b,0x20' (32 trailing spaces so the marquee scrolls fully out)
    patch(rom, 0x1282, bytes.fromhex("7e fe 02 38 0f"), expect=bytes.fromhex("cd a3 1a 30 0f"), name="P7a")
    patch(rom, 0x128E, bytes.fromhex("06 08"), expect=bytes.fromhex("06 00 4f cd d3 1a"), name="P7b")
    patch(rom, 0x1264, bytes.fromhex("06 20"), expect=bytes.fromhex("06 10 3e 02"), name="P7c")
    # P8: relocate the inflate/line buffer from $C880 (256 bytes before engine vars) to $D000 (2 KB)
    for off, old_w, new_w in ((0x123D, 0xC880, BUF_BASE), (0x1261, 0xC880, BUF_BASE), (0x126E, 0xC880, BUF_BASE),
                              (0x1867, 0xC880, BUF_BASE), (0x1904, 0xC880, BUF_BASE), (0x1929, 0xC880, BUF_BASE),
                              (0x14A2, 0xC885, BUF_BASE + 15), (0x14A5, 0xC886, BUF_BASE + 16),
                              (0x14B1, 0xC880, BUF_BASE), (0x18A7, 0xC980, BUF_LIMIT)):
        patch(rom, off + 1, bytes([new_w & 0xFF, new_w >> 8]), expect=bytes([old_w & 0xFF, old_w >> 8]), name=f"P8@{off:04X}")
    # P9: the zodiac-name shift that makes room for the symbol copied only 6 bytes (Japanese names
    # are <= 5 codes); copy 16 so English names up to 15 letters survive (buffer is 2 KB now)
    patch(rom, 0x14A8, bytes.fromhex("01 10 00"), expect=bytes.fromhex("01 06 00 ed b8"), name="P9")
    # WIDTH routine: push de; push hl; ld h,0; ld l,c; ld de,TABLE; add hl,de; ld a,(hl); pop hl; pop de; ret
    routine = bytes([0xD5, 0xE5, 0x26, 0x00, 0x69, 0x11, WIDTH_TABLE & 0xFF, WIDTH_TABLE >> 8, 0x19, 0x7E, 0xE1, 0xD1, 0xC9])
    patch(rom, WIDTH_ROUTINE, routine, name="WIDTH")
    table = bytearray([16] * 0xA9)          # codes 0..0xA8: Japanese glyphs and zodiac symbols keep 16 px
    table[0] = table[1] = 0
    for ch, code in CODE_OF.items():
        table[code] = WIDTH_OF[ch]
    patch(rom, WIDTH_TABLE, bytes(table), name="WIDTH_TABLE")
    assert WIDTH_TABLE + len(table) <= PTR_TABLE


def write_font(rom: bytearray):
    for ch, code in CODE_OF.items():
        off = FONT + (code - 2) * 32
        rom[off:off + 32] = cell_bytes(ch)


def load_translations() -> dict[int, str]:
    out: dict[int, str] = {}
    dirs = [ROOT / "translations"]                       # batch_*.json, then overrides.json (sorted)
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            for rec in json.loads(p.read_text(encoding="utf-8")):
                if rec.get("en"):
                    out[int(rec["id"])] = rec["en"]
    return out


def build(verbose: bool = True) -> bytearray:
    rom = bytearray(SRC.read_bytes())
    assert len(rom) == 128 * 1024
    rom += b"\xFF" * (ROM_SIZE - len(rom))
    rom[0x7FFF] = 0x50                       # header: GG Japan, 256 KB
    apply_engine_patches(rom)
    write_font(rom)

    msgs = json.loads(MESSAGES.read_text(encoding="utf-8"))
    tr = load_translations()
    bank, cur = FIRST_TEXT_BANK, 0
    n_en = 0
    problems = []
    for m in msgs:
        mid = m["id"]
        if mid in tr:
            try:
                px, max_lines = layout(mid)
                codes = encode_lines(fit_lines(mid, tr[mid]))
                n_lines = codes.count(1) + 1
                if n_lines > max_lines:
                    problems.append(f"{mid}: {n_lines} lines > {max_lines} allowed at {px}px: {tr[mid]!r}")
                n_en += 1
            except EncodeError as e:
                problems.append(f"{mid}: {e}"); codes = list(m["codes"])
        else:
            codes = list(m["codes"])
        if codes[-1] != 0:
            codes.append(0)
        if len(codes) > BUFFER_LIMIT:
            problems.append(f"{mid}: {len(codes)} codes exceed the {BUFFER_LIMIT}-byte line buffer")
        if cur + len(codes) > 0x4000:
            bank, cur = bank + 1, 0
        if bank * 0x4000 + cur + len(codes) > ROM_SIZE:
            raise SystemExit("out of ROM space for text")
        off = bank * 0x4000 + cur
        rom[off:off + len(codes)] = bytes(codes)
        e = PTR_TABLE + 3 * mid
        rom[e], rom[e + 1], rom[e + 2] = bank, cur & 0xFF, (cur >> 8) & 0xFF
        cur += len(codes)
    DST.write_bytes(rom)
    if verbose:
        print(f"wrote {DST.name}: {len(rom)//1024} KB; {n_en}/{len(msgs)} messages in English; "
              f"text occupies banks {FIRST_TEXT_BANK}-{bank} ({(bank-FIRST_TEXT_BANK)*0x4000+cur} bytes)")
        for p in problems:
            print("  problem:", p)
    return rom


if __name__ == "__main__":
    build()
