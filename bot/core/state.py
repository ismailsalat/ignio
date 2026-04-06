# bot/core/state.py
from __future__ import annotations


class VcRuntimeState:
    """
    Runtime-only VC state.

    Holds:
    - current human members per voice channel
    - recently left users for disconnect buffer handling
    """

    def __init__(self):
        # guild_id -> channel_id -> set(user_id)
        self.channel_members: dict[int, dict[int, set[int]]] = {}

        # (guild_id, user_id) -> (channel_id, left_ts)
        self.recently_left: dict[tuple[int, int], tuple[int, int]] = {}

    def set_channel_members(self, guild_id: int, channel_id: int, members: set[int]) -> None:
        self.channel_members.setdefault(guild_id, {})[channel_id] = set(members)

    def get_channel_members(self, guild_id: int, channel_id: int) -> set[int]:
        return set(self.channel_members.get(guild_id, {}).get(channel_id, set()))

    def remove_channel(self, guild_id: int, channel_id: int) -> None:
        guild_channels = self.channel_members.get(guild_id)
        if guild_channels is None:
            return

        guild_channels.pop(channel_id, None)

        if not guild_channels:
            self.channel_members.pop(guild_id, None)

    def clear_guild(self, guild_id: int) -> None:
        self.channel_members.pop(guild_id, None)

        to_remove = [
            key
            for key in self.recently_left
            if key[0] == guild_id
        ]
        for key in to_remove:
            self.recently_left.pop(key, None)

    def mark_left(self, guild_id: int, user_id: int, channel_id: int, left_ts: int) -> None:
        self.recently_left[(guild_id, user_id)] = (channel_id, left_ts)

    def clear_left(self, guild_id: int, user_id: int) -> None:
        self.recently_left.pop((guild_id, user_id), None)