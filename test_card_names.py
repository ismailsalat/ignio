"""
test_card_names.py — cards must never render ☐ boxes for exotic glyphs or
overflow with long names/emoji. Locks in the name-cleaning + ellipsizing.
"""
import sys
sys.path.insert(0, '.')
from core.profile.render import clean_name
from core.profile.small_cards import _clean_name, _safe_name
from core.profile.render import f_title
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

def main():
    print("[test_card_names]")
    f = f_title(26)
    # cuneiform / exotic scripts stripped
    check("cuneiform stripped from name", "𒅒" not in clean_name("ceo shukri𒅒𒅒"))
    check("ceo shukri preserved", clean_name("ceo shukri𒅒𒅒") == "ceo shukri")
    check("SINCERELY name cleaned", clean_name("SINCERELY S3NSEI𒉭") == "SINCERELY S3NSEI")
    # emoji stripped
    check("emoji stripped", "😭" not in clean_name("😭man😭"))
    # normal names untouched
    check("normal latin untouched", clean_name("Rip(GFT)") == "Rip(GFT)")
    check("accented latin kept", clean_name("Ñoño") == "Ñoño")
    check("CJK kept", clean_name("日本語") == "日本語")
    # never returns empty boxes — falls back to something printable
    check("all-exotic name doesn't crash", isinstance(clean_name("𒅒𒉭𒀀"), str))
    # small_cards safe_name ellipsizes long names to fit
    long = "this is an extremely long server nickname that should be cut off"
    fitted = _safe_name(long, f, max_w=200)
    check("long name ellipsized with …", fitted.endswith("…") and len(fitted) < len(long))
    check("short name not ellipsized", _safe_name("asma", f, 200) == "asma")
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAILURES:", FAIL); sys.exit(1)

if __name__ == "__main__":
    main()
