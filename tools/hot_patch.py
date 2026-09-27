"""Make IPS and BPS patches from the pristine ROM to the English build, and verify them.

    python3 tools/hot_patch.py            # writes dist/*.ips, dist/*.bps, dist/checksums.txt
"""
from __future__ import annotations
import hashlib, struct, sys, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "House of Tarot (J).gg"
DST = ROOT / "House of Tarot (J) [EN].gg"
DIST = ROOT / "dist"
NAME = "House-of-Tarot-English-Patch-v1.0"


def make_ips(src: bytes, dst: bytes) -> bytes:
    out = bytearray(b"PATCH")
    i, n = 0, len(dst)
    while i < n:
        if i < len(src) and src[i] == dst[i]:
            i += 1; continue
        j = i
        while j < n and (j >= len(src) or src[j] != dst[j]) and j - i < 0xFFFF:
            j += 1
        # extend over short equal gaps to keep record count down
        assert i != 0x454F46, "IPS offset collides with EOF marker"
        out += struct.pack(">I", i)[1:] + struct.pack(">H", j - i) + dst[i:j]
        i = j
    out += b"EOF"
    return bytes(out)


def apply_ips(src: bytes, ips: bytes) -> bytes:
    assert ips[:5] == b"PATCH"
    out = bytearray(src); p = 5
    while ips[p:p + 3] != b"EOF":
        off = int.from_bytes(ips[p:p + 3], "big"); size = int.from_bytes(ips[p + 3:p + 5], "big"); p += 5
        if size == 0:
            rle = int.from_bytes(ips[p:p + 2], "big"); val = ips[p + 2]; p += 3; data = bytes([val]) * rle
        else:
            data = ips[p:p + size]; p += size
        if off + len(data) > len(out): out += b"\x00" * (off + len(data) - len(out))
        out[off:off + len(data)] = data
    return bytes(out)


def bps_varint(v: int) -> bytes:
    out = bytearray()
    while True:
        x = v & 0x7F; v >>= 7
        if v == 0:
            out.append(x | 0x80); return bytes(out)
        out.append(x); v -= 1


def make_bps(src: bytes, dst: bytes) -> bytes:
    out = bytearray(b"BPS1") + bps_varint(len(src)) + bps_varint(len(dst)) + bps_varint(0)
    i, n = 0, len(dst)
    while i < n:
        j = i
        if i < len(src) and src[i] == dst[i]:
            while j < n and j < len(src) and src[j] == dst[j]: j += 1
            out += bps_varint(((j - i) - 1) << 2 | 0)                 # SourceRead
        else:
            while j < n and (j >= len(src) or src[j] != dst[j]): j += 1
            out += bps_varint(((j - i) - 1) << 2 | 1) + dst[i:j]      # TargetRead
        i = j
    out += struct.pack("<I", zlib.crc32(src)) + struct.pack("<I", zlib.crc32(dst))
    out += struct.pack("<I", zlib.crc32(bytes(out)))
    return bytes(out)


def apply_bps(src: bytes, bps: bytes) -> bytes:
    assert bps[:4] == b"BPS1"
    p = 4
    def varint():
        nonlocal p
        v, shift = 0, 1
        while True:
            x = bps[p]; p += 1
            v += (x & 0x7F) * shift
            if x & 0x80: return v
            shift <<= 7; v += shift
    ssize, tsize, msize = varint(), varint(), varint(); p += msize
    out = bytearray(); end = len(bps) - 12
    while p < end:
        data = varint(); action, length = data & 3, (data >> 2) + 1
        if action == 0: out += src[len(out):len(out) + length]
        elif action == 1: out += bps[p:p + length]; p += length
        else: raise NotImplementedError
    assert len(out) == tsize
    return bytes(out)


def main():
    src, dst = SRC.read_bytes(), DST.read_bytes()
    DIST.mkdir(exist_ok=True)
    ips, bps = make_ips(src, dst), make_bps(src, dst)
    assert apply_ips(src, ips) == dst, "IPS round-trip failed"
    assert apply_bps(src, bps) == dst, "BPS round-trip failed"
    (DIST / f"{NAME}.ips").write_bytes(ips); (DIST / f"{NAME}.bps").write_bytes(bps)
    lines = []
    for label, data in (("original ROM", src), ("patched ROM", dst), ("ips", ips), ("bps", bps)):
        lines.append(f"{label:13s} size {len(data):7d}  crc32 {zlib.crc32(data):08X}  md5 {hashlib.md5(data).hexdigest()}  sha1 {hashlib.sha1(data).hexdigest()}")
    (DIST / "checksums.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines)); print(f"ips {len(ips)} bytes, bps {len(bps)} bytes -> {DIST}")


if __name__ == "__main__":
    main()
