# core/backup.py
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


def backup_database(db_path: str, *, keep: int = 10) -> str | None:
    """
    Make a timestamped copy of the SQLite DB next to it, BEFORE migrations run.

    Safe by design:
      - Only acts if the DB file already exists (fresh installs are skipped).
      - Copies the main file plus -wal / -shm sidecars if present, so the
        snapshot is consistent.
      - Never touches or deletes the live DB.
      - Prunes old backups, keeping the most recent `keep`.

    Returns the backup path, or None if nothing was backed up.
    """
    src = Path(db_path)
    if not src.exists():
        return None  # fresh install, nothing to back up

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    backup_path = src.with_name(f"{src.stem}.backup-{stamp}{src.suffix}")

    # If two backups land in the same second, disambiguate with a counter so
    # we never silently overwrite an existing snapshot.
    if backup_path.exists():
        n = 1
        while True:
            candidate = src.with_name(f"{src.stem}.backup-{stamp}-{n}{src.suffix}")
            if not candidate.exists():
                backup_path = candidate
                break
            n += 1

    # Copy main file + WAL/SHM sidecars (copy2 preserves mtime).
    shutil.copy2(src, backup_path)
    for sidecar in (f"{db_path}-wal", f"{db_path}-shm"):
        if os.path.exists(sidecar):
            shutil.copy2(sidecar, f"{backup_path}-{sidecar.rsplit('-', 1)[1]}")

    _prune_old_backups(src, keep=keep)
    print(f"[Ignio] 🛟 DB backup created: {backup_path.name}")
    return str(backup_path)


def _prune_old_backups(src: Path, *, keep: int) -> None:
    """Keep only the most recent `keep` main-file backups; delete older ones."""
    pattern = f"{src.stem}.backup-*{src.suffix}"
    backups = sorted(
        (p for p in src.parent.glob(pattern) if "-wal" not in p.name and "-shm" not in p.name),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[keep:]:
        try:
            old.unlink()
            for sidecar_suffix in ("-wal", "-shm"):
                sidecar = old.with_name(old.name + sidecar_suffix)
                if sidecar.exists():
                    sidecar.unlink()
        except OSError:
            pass  # never let backup pruning crash startup
