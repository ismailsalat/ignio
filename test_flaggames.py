"""test_flaggames.py — !mapflag (competitive flag) + !flag (red/green vote)."""
import sys
sys.path.insert(0, '.')
from core.games.flaggame_cog import _matches, REWARD_BY_DIFFICULTY, DAILY_REWARD_CAP, ROUND_SECONDS
from core.games.redgreen_data import GENERIC, TARGETED, all_count
from core.games.redgreen_cog import FlagVoteView, VOTE_SECONDS
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

def main():
    print("[test_flaggames]")
    # --- mapflag ---
    fiji = {"name": "Fiji"}
    check("flag match works (case-insensitive)", _matches("FIJI", fiji) and _matches("fiji ", fiji))
    check("flag rejects wrong answer", not _matches("germany", fiji))
    check("flag rewards scale with difficulty", REWARD_BY_DIFFICULTY[1] < REWARD_BY_DIFFICULTY[3])
    check("flag has a daily cap", DAILY_REWARD_CAP > 0)
    check("flag round time is sane", 10 <= ROUND_SECONDS <= 40)

    # --- redgreen scenarios ---
    check("has many generic scenarios", len(GENERIC) >= 25)
    check("has many targeted scenarios", len(TARGETED) >= 15)
    check("total scenario bank is big", all_count() >= 50)
    check("targeted templates have {name}", all("{name}" in t for t in TARGETED))
    check("generic templates have NO {name}", all("{name}" not in g for g in GENERIC))
    # format works
    formatted = TARGETED[0].format(name="Milk")
    check("targeted formats with a name", "Milk" in formatted and "{name}" not in formatted)

    # --- vote view logic ---
    v = FlagVoteView("test scenario")
    v.votes[1] = "red"; v.votes[2] = "green"; v.votes[3] = "red"
    red, green = v._counts()
    check("vote tally counts correctly", red == 2 and green == 1)
    # a user changing their vote doesn't double-count
    v.votes[1] = "green"
    red, green = v._counts()
    check("changing a vote moves the count (no double)", red == 1 and green == 2)
    # embed renders both open and closed
    check("embed renders (open)", v._embed() is not None)
    check("embed renders (closed)", v._embed(closed=True) is not None)
    check("vote window is sane", 20 <= VOTE_SECONDS <= 90)

    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAILURES:", FAIL); sys.exit(1)

if __name__ == "__main__":
    main()
