"""Ensure EVERY command in the code is discoverable in !help (the registry)."""
import sys
sys.path.insert(0, '.')
from core import commands_registry as R

def norm(n):
    return n.split(" @")[0].split(" #")[0].split(" <")[0].split(" [")[0].strip()

# Every command path that exists in the bot (kept in sync with the cogs).
REAL = {
    "sob","sob @user","sob lb","sob stats","sob set","sob backgrounds","sob colors",
    "sob set background","sob set color","sob tips","ss",
    "shop","daily","buy","me","use",
    "rate","value","worth","economy","rate set","tax","treasury","treasury give",
    "multiplier","rebalance",
    "roulette","roulettestats","steal","steal stats","sobship","mapgame","mapflag","flag","catchup","tldr","song","xray","map","weather","translate","caption","quote","afk",
    "admin profile","admin givesob","admin givetoken","admin reset","admin recount",
    "admin threshold","admin emoji","admin whoami","admin config","admin stats","admin servers",
    "admin altblock","admin tips","admin freeze","admin audit","admin audit tx","admin suspicious",
    "admin export","admin auditexport","admin import","admin weekly",
    "admin shop","admin item","admin category","admin auditcap","admin auditcd",
    "shop additem","shop setstock","shop removeitem","shop setchannel","shop setrole","shop boostmult",
    "disable","enable","commandconfig","perms","announce",
    "help","guide","about","version",
}

def main():
    print("[test_help_coverage]")
    reg_norm = {norm(c["name"]) for c in R.COMMANDS}
    missing = sorted(x for x in REAL if norm(x) not in reg_norm)
    assert not missing, f"commands missing from !help: {missing}"
    print(f"  ✅ all {len(REAL)} commands are discoverable in !help ({len(R.COMMANDS)} registry entries)")

    # every admin command renders into a help embed field under 1024 chars
    import core.help.cog as H
    e = H.category_embed("admin", "!", is_admin=True, is_owner=True)
    for f in e.fields:
        assert len(f.value) <= 1024, f"admin help field '{f.name}' too long: {len(f.value)}"
    print(f"  ✅ admin help splits into {len(e.fields)} clean sections, all within Discord limits")

    # every non-admin category renders
    for cat in ("sobs", "profile", "shop", "games", "economy", "info"):
        emb = H.category_embed(cat, "!", is_admin=False, is_owner=False)
        assert (emb.description and len(emb.description) <= 4096) or emb.fields, f"{cat} empty"
    print("  ✅ every category renders for normal users")

    # every category that has commands MUST appear in the help menu (this catches
    # the bug where a new category exists in the registry but the menu's hardcoded
    # list forgot it, so users never see it)
    import core.commands_registry as _R
    cats_with_cmds = {c["cat"] for c in _R.COMMANDS}
    menu = set(_R.visible_categories(is_admin=True))
    missing_from_menu = cats_with_cmds - menu - {"economy"}  # economy is folded into sobs view
    assert not missing_from_menu, f"categories missing from help menu: {missing_from_menu}"
    print("  \u2705 every category with commands appears in the help menu")

    print("  RESULT: help coverage PASSED")

if __name__ == "__main__":
    main()
