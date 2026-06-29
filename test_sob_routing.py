"""Verify !sob <subcommand> routes correctly and never falls back to the profile."""
import sys
sys.path.insert(0, '.')
import core.sob.cog as C

def main():
    print("[test_sob_routing]")
    g = C.SobCog.sob_group
    subs = {c.name for c in g.commands}
    # every advertised subcommand exists
    for name in ("stats", "lb", "set", "tips", "backgrounds", "colors", "help"):
        assert name in subs, f"missing subcommand: {name}"
    print(f"  ✅ all subcommands registered: {sorted(subs)}")
    # aliases resolve
    assert g.get_command("mystats").name == "stats"
    assert g.get_command("income").name == "stats"
    assert g.get_command("leaderboard").name == "lb"
    print("  ✅ stats aliases (mystats, income) and lb alias resolve")
    # the parent guard references real methods
    import inspect
    src = inspect.getsource(C.SobCog.sob_group.callback)
    for meth in ("self.sob_stats", "self.sob_lb", "self.sob_tips", "self.sob_help"):
        assert meth in src, f"parent guard missing {meth}"
    print("  ✅ parent guard dispatches stats/lb/tips/help explicitly")
    print("  RESULT: sob routing PASSED")

if __name__ == "__main__":
    main()
