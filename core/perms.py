# core/perms.py
"""
Per-server role permissions for Ignio.

Admins (Discord 'administrator' or 'manage_guild') and bot owners ALWAYS have
every permission. The role system only ADDS powers for non-admins.

Permissions are stored in guild_settings under keys like:
    perm:givesob   -> "roleid1,roleid2"
    perm:givetoken -> "roleid3"
...so no schema change is needed.
"""
from __future__ import annotations

# permission key -> human description (shown in !perms)
PERMISSIONS: dict[str, str] = {
    "givesob": "Give or remove sobs from users",
    "givetoken": "Grant snitch tokens to users",
    "manageshop": "Add/remove shop items, stock, prices, claim channel/role",
    "manageconfig": "Change threshold, emojis, boost multiplier; recount/reset",
}


def _setting_key(perm: str) -> str:
    return f"perm:{perm}"


def is_admin(member, settings) -> bool:
    """Discord admin / manage_guild, or a configured bot owner."""
    owner_ids = set(getattr(settings, "owner_ids", ()) or ())
    if member.id in owner_ids:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


async def get_role_ids_for_perm(sob_repo, guild_id: int, perm: str) -> set[int]:
    raw = await sob_repo.get_guild_setting(guild_id, _setting_key(perm))
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


async def set_role_ids_for_perm(sob_repo, guild_id: int, perm: str, role_ids: set[int]) -> None:
    value = ",".join(str(r) for r in sorted(role_ids))
    await sob_repo.set_guild_setting(guild_id, _setting_key(perm), value)


async def grant(sob_repo, guild_id: int, perm: str, role_id: int) -> None:
    ids = await get_role_ids_for_perm(sob_repo, guild_id, perm)
    ids.add(role_id)
    await set_role_ids_for_perm(sob_repo, guild_id, perm, ids)


async def revoke(sob_repo, guild_id: int, perm: str, role_id: int) -> None:
    ids = await get_role_ids_for_perm(sob_repo, guild_id, perm)
    ids.discard(role_id)
    await set_role_ids_for_perm(sob_repo, guild_id, perm, ids)


async def member_has_perm(sob_repo, member, settings, perm: str) -> bool:
    """True if the member is an admin/owner, or holds a role granted `perm`."""
    if is_admin(member, settings):
        return True
    allowed = await get_role_ids_for_perm(sob_repo, member.guild.id, perm)
    if not allowed:
        return False
    member_role_ids = {r.id for r in getattr(member, "roles", [])}
    return bool(member_role_ids & allowed)