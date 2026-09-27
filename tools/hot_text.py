"""House of Tarot text codec (derived from the Z80 decoder at ROM 0x183C).

Message n: ptr = u16 at 0x4F20 + 2n; bank = (ptr >> 14) + 1; src = bank*0x4000 + (ptr & 0x3FFF).
Bits are consumed LSB-first from each byte. Huffman tree at 0x55C0:
  node  = [skip (0xFF-chained)] left-subtree right-subtree   (bit 0 -> left, bit 1 -> skip to right)
  leaf  = 0x00 symbol
Symbols: 0 = end of message, 1 = newline (rest of line blank), 2 = space, 3..0x9C = glyph
(glyph bitmap at 0x38F0 + (code-2)*32, 1bpp 16x16 row-major), >= 0x9D = dictionary string
number code-0x9D from the zero-terminated string list at 0x4DD0 (strings are themselves symbol runs).
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PTR_TABLE, TREE, DICT, FONT = 0x4F20, 0x55C0, 0x4DD0, 0x38F0
N_MESSAGES = (TREE - PTR_TABLE) // 2          # 848 slots

PUNCT = " 、。・?!゛゜／"                       # codes 2..10
SEQ = ("『』ー0123456789BCDGHKLOU"
       "ぁあいうえぉおかきくけこさしすせそたちっつてとなにぬねのはひふへほまみむめもゃやゅゆょよらりるれろわをん"
       "ァアィイゥウエオカキクケコサシスセソタチッツテトナニヌネノハヒフヘホマミムメモャヤュユョヨラリルレロワン"
       "位吉逆口今座思自女小信心人星正大置分友力♈♉♊♋♌♍♎♏♐♑♒♓")   # codes 11..
DAKUTEN = {"か":"が","き":"ぎ","く":"ぐ","け":"げ","こ":"ご","さ":"ざ","し":"じ","す":"ず","せ":"ぜ","そ":"ぞ",
           "た":"だ","ち":"ぢ","つ":"づ","て":"で","と":"ど","は":"ば","ひ":"び","ふ":"ぶ","へ":"べ","ほ":"ぼ",
           "カ":"ガ","キ":"ギ","ク":"グ","ケ":"ゲ","コ":"ゴ","サ":"ザ","シ":"ジ","ス":"ズ","セ":"ゼ","ソ":"ゾ",
           "タ":"ダ","チ":"ヂ","ツ":"ヅ","テ":"デ","ト":"ド","ハ":"バ","ヒ":"ビ","フ":"ブ","ヘ":"ベ","ホ":"ボ","ウ":"ヴ"}
HANDAKUTEN = {"は":"ぱ","ひ":"ぴ","ふ":"ぷ","へ":"ぺ","ほ":"ぽ","ハ":"パ","ヒ":"ピ","フ":"プ","ヘ":"ペ","ホ":"ポ"}

def code_to_char(c: int) -> str:
    if 2 <= c <= 10: return PUNCT[c - 2]
    i = c - 11
    if 0 <= i < len(SEQ): return SEQ[i]
    return f"<{c:02X}>"

def codes_to_text(codes: list[int]) -> str:
    """Render a symbol run as readable Japanese (dakuten prefix folded into the next kana)."""
    out, i = [], 0
    while i < len(codes):
        c = codes[i]
        if c == 0: out.append("<END>"); i += 1; continue
        if c == 1: out.append("\n"); i += 1; continue
        if c in (8, 9) and i + 1 < len(codes):
            base = code_to_char(codes[i + 1]); tbl = DAKUTEN if c == 8 else HANDAKUTEN
            out.append(tbl.get(base, code_to_char(c) + base)); i += 2; continue
        out.append(code_to_char(c)); i += 1
    return "".join(out)

class Codec:
    def __init__(self, rom: bytes):
        self.rom = rom
        self.dict = self._read_dict()
    def _read_dict(self) -> list[list[int]]:
        out, p = [], DICT
        while p < PTR_TABLE and len(out) < 0x100 - 0x9D:
            s = []
            while self.rom[p] != 0: s.append(self.rom[p]); p += 1
            p += 1; out.append(s)
        return out
    def pointer(self, n: int) -> tuple[int, int, int]:
        ptr = self.rom[PTR_TABLE + 2*n] | (self.rom[PTR_TABLE + 2*n + 1] << 8)
        bank = (ptr >> 14) + 1
        return ptr, bank, bank * 0x4000 + (ptr & 0x3FFF)
    def decode_symbols(self, src: int, limit: int = 0x200) -> tuple[list[int], int]:
        """Huffman-decode symbols from ROM offset src until the end symbol. Returns (symbols, bytes consumed)."""
        rom, pos, bitbuf, nbits, out = self.rom, src, 0, 0, []
        def bit():
            nonlocal pos, bitbuf, nbits
            if nbits == 0: bitbuf, pos, nbits = rom[pos], pos + 1, 8
            b = bitbuf & 1; bitbuf >>= 1; nbits -= 1; return b
        while len(out) < limit:
            p = TREE
            while True:
                a = rom[p]; p += 1
                if a == 0:
                    sym = rom[p]; break
                skip = 0
                while a == 0xFF: skip += 0xFF; a = rom[p]; p += 1
                skip += a
                if bit(): p += skip
            out.append(sym)
            if sym == 0: break
        return out, pos - src
    def expand(self, symbols: list[int]) -> list[int]:
        codes = []
        for s in symbols:
            if s >= 0x9D: codes.extend(self.dict[s - 0x9D])
            else: codes.append(s)
        return codes
    def message(self, n: int) -> dict:
        ptr, bank, src = self.pointer(n)
        syms, nbytes = self.decode_symbols(src)
        codes = self.expand(syms)
        return {"id": n, "ptr": ptr, "bank": bank, "rom": src, "packed_bytes": nbytes,
                "symbols": syms, "codes": codes, "text": codes_to_text(codes)}

def main():
    rom = (ROOT / "House of Tarot (J).gg").read_bytes()
    cx = Codec(rom)
    print(f"dictionary: {len(cx.dict)} entries; e.g. " + " | ".join(codes_to_text(d) for d in cx.dict[:12]))
    msgs = []
    for n in range(N_MESSAGES):
        try: msgs.append(cx.message(n))
        except Exception as e: msgs.append({"id": n, "error": repr(e)})
    ok = [m for m in msgs if "error" not in m]
    total_codes = sum(len(m["codes"]) for m in ok)
    total_packed = sum(m["packed_bytes"] for m in ok)
    print(f"messages: {len(ok)}/{N_MESSAGES} decoded; total codes {total_codes} (packed {total_packed} bytes);"
          f" longest {max(len(m['codes']) for m in ok)} codes; banks used {sorted(set(m['bank'] for m in ok))}")
    lo = min(m["rom"] for m in ok); hi = max(m["rom"] + m["packed_bytes"] for m in ok)
    print(f"packed text spans ROM {lo:05X}-{hi:05X}")
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out/messages.json").write_text(json.dumps(msgs, ensure_ascii=False, indent=0), encoding="utf-8")
    with open(ROOT / "out/messages.txt", "w", encoding="utf-8") as f:
        for m in ok:
            f.write(f"=== {m['id']} (#{m['id']:03X}) rom {m['rom']:05X} bank {m['bank']} {len(m['codes'])} codes\n{m['text']}\n")
    for m in ok[:int(sys.argv[1]) if len(sys.argv) > 1 else 30]:
        print(f"--- {m['id']} rom {m['rom']:05X} [{len(m['codes'])}]: {m['text'][:120]!r}")

if __name__ == "__main__":
    main()
