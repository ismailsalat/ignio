"""test_mapgame.py — country guessing game: data, matching, rendering, rewards."""
import sys
sys.path.insert(0, '.')
from core.games.mapgame_data import COUNTRIES, ALIASES
from core.games.mapgame_cog import _matches, _norm, REWARD_BY_DIFFICULTY, DAILY_REWARD_CAP
from core.games.mapgame_render import render_board
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

def main():
    print("[test_mapgame]")
    # data sanity
    check("has a healthy number of countries", len(COUNTRIES) >= 50)
    check("Fiji is included", any(c["name"] == "Fiji" for c in COUNTRIES))
    check("all coords on the 1000x500 map", all(0 <= c["x"] <= 1000 and 0 <= c["y"] <= 500 for c in COUNTRIES))
    check("every country has emoji + difficulty", all(c.get("emoji") and c.get("difficulty") in (1,2,3) for c in COUNTRIES))
    check("no duplicate countries", len({c["name"] for c in COUNTRIES}) == len(COUNTRIES))
    # matching
    fiji = {"name": "Fiji"}
    us = {"name": "United States"}
    check("exact match (case-insensitive)", _matches("FIJI", fiji) and _matches("fiji ", fiji))
    check("alias match (usa/america)", _matches("usa", us) and _matches("america", us))
    check("wrong answer rejected", not _matches("France", fiji))
    check("empty answer rejected", not _matches("", fiji))
    # rewards configured sanely
    check("rewards increase with difficulty", REWARD_BY_DIFFICULTY[1] < REWARD_BY_DIFFICULTY[3])
    check("daily cap is positive", DAILY_REWARD_CAP > 0)
    # rendering works for a few countries (incl. edge island)
    for nm in ("Fiji", "France", "Japan", "Iceland"):
        c = [x for x in COUNTRIES if x["name"] == nm][0]
        buf = render_board(c["x"], c["y"], 1, 5)
        data = buf.read()
        check(f"renders board for {nm}", data[:8].startswith(b"\x89PNG"))
    test_session_dots()
    test_no_not_quite()
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAILURES:", FAIL); sys.exit(1)


def test_session_dots():
    from core.games.mapgame_cog import MapGameCog
    c = MapGameCog.__new__(MapGameCog)
    check("round 1 dots empty", c._dots(0) == "○ ○ ○ ○ ○")
    check("round 3 dots", c._dots(2) == "● ● ○ ○ ○")
    check("round 5 dots full", c._dots(5) == "● ● ● ● ●")


def test_no_not_quite():
    src = open("core/games/mapgame_cog.py").read()
    check("no 'Not quite' reply on wrong guess", "Not quite" not in src)
    check("wrong guesses filtered (only correct pass check)", "_matches(m.content, country)" in src)
    check("5-round session exists", "_run_session" in src and "total_rounds" in src)


if __name__ == "__main__":
    main()
