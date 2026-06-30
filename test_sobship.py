"""test_sobship.py — love-meter: random scores + renders cleanly for any name."""
import sys
sys.path.insert(0, '.')
from core.games.sobship_render import ship_score, make_sobship_gif, make_sobship_static
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

def main():
    print("[test_sobship]")
    # always in range
    check("score always in 0-100", all(0 <= ship_score(1, 2) <= 100 for _ in range(200)))
    # it's random: many calls for the SAME pair should produce more than one value
    vals = {ship_score(5, 9) for _ in range(200)}
    check("same pair gives varied scores (random each time)", len(vals) > 5)
    # renders cleanly with a real score
    img, s = make_sobship_static("alice", "bob", 1, 2)
    check("static render works", img is not None and 0 <= s <= 100)
    buf, s2 = make_sobship_gif("alice", "bob", 7, 8)
    data = buf.read()
    check("gif renders and is a real GIF", data[:6] in (b"GIF87a", b"GIF89a"))
    check("gif returns a score in range", 0 <= s2 <= 100)
    # UI handles every name size without crashing or overflowing
    for a, b in [
        ("xXx_TheLegendaryDragonSlayer9000_xXx", "AnotherSuperLongNicknameThatIsHuge"),
        ("a", "b"),
        ("😭🔥emoji😭🔥", "ceo shukri𒅒𒅒"),
    ]:
        try:
            img, sc = make_sobship_static(a, b, 1, 2)
            ok = img is not None and 0 <= sc <= 100
        except Exception:
            ok = False
        check(f"renders cleanly for names ({a[:10]}.., {b[:10]}..)", ok)
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAILURES:", FAIL); sys.exit(1)

if __name__ == "__main__":
    main()
