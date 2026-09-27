"""Check a translation batch file: every 'en' must encode and fit its layout.
usage: python3 tools/hot_check_tr.py translations/batch_nana_a.json
Prints one line per problem and a summary; exit code 1 if any problem."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hot_encode import encode_lines, EncodeError
from hot_font import text_width
from hot_build import layout, fit_lines, TICKER_IDS

path = Path(sys.argv[1])
recs = json.loads(path.read_text(encoding="utf-8"))
bad = 0; done = 0
for r in recs:
    mid = int(r["id"]); en = r.get("en")
    if not en:
        continue
    done += 1
    px, max_lines = layout(mid)
    try:
        lines = fit_lines(mid, en)
        encode_lines(lines)
    except EncodeError as e:
        print(f"{mid}: ENCODE ERROR {e}"); bad += 1; continue
    if len(lines) > max_lines:
        print(f"{mid}: {len(lines)} lines > {max_lines} allowed ({px}px). Lines: {[f'{text_width(l)}px {l}' for l in lines]}"); bad += 1
    if mid in TICKER_IDS and "\n" in en:
        print(f"{mid}: marquee text must not contain newlines"); bad += 1
print(f"{path.name}: {done}/{len(recs)} translated, {bad} problems")
sys.exit(1 if bad else 0)
