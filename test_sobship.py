"""test_sobship.py — love-meter must be deterministic + order-independent + safe."""
import sys
sys.path.insert(0, '.')
from core.games.sobship_render import ship_score, make_sobship_gif, make_sobship_static
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

def main():
    print("[test_sobship]")
    check("score in 0-100", 0 <= ship_score(111, 222) <= 100)
    check("deterministic (same inputs same score)", ship_score(5, 9) == ship_score(5, 9))
    check("order-independent", ship_score(5, 9) == ship_score(9, 5))
    check("different pairs differ", ship_score(1, 2) != ship_score(1, 3))
    # render must not crash on emoji/exotic names
    img, s = make_sobship_static("😭man😭", "ceo shukri𒅒", 1, 2)
    check("static render works with bad names", img is not None and 0 <= s <= 100)
    buf, s2 = make_sobship_gif("alice", "bob", 7, 8)
    data = buf.read()
    check("gif renders and is a real GIF", data[:6] in (b"GIF87a", b"GIF89a"))
    check("gif score matches static score", s2 == ship_score(7, 8))
    # UI must handle every name size without crashing or overflowing
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
