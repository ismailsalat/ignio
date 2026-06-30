"""test_no_command_collisions.py — no two commands may share a name or alias.
This catches the class of bug that makes a whole cog fail to load at boot."""
import re, glob, collections, sys

def main():
    print("[test_no_command_collisions]")
    names = collections.defaultdict(list)
    for f in glob.glob('core/**/*.py', recursive=True) + ['bot.py']:
        src = open(f, encoding='utf-8').read()
        # only top-level @commands.command (NOT @group.command subcommands, which
        # live in their own namespace)
        for m in re.finditer(
                r'@commands\.command\(name=(["\'])(\w+)\1(?:,\s*aliases=\[([^\]]*)\])?', src):
            primary = m.group(2)
            names[primary].append(f)
            if m.group(3):
                for a in re.findall(r'["\'](\w+)["\']', m.group(3)):
                    names[a].append(f + " (alias)")
    dupes = {k: v for k, v in names.items() if len(v) > 1}
    if dupes:
        print("  ❌ command name/alias collisions found:")
        for k, v in dupes.items():
            print(f"     '{k}': {v}")
        print("\n  RESULT: FAILED")
        sys.exit(1)
    print(f"  ✅ scanned {len(names)} command names/aliases — no collisions")
    print("\n  RESULT: PASSED")

if __name__ == "__main__":
    main()
