# bot/core/state.py

class VcRuntimeState:
    """
    Runtime-only state for VC tracking.

    Holds:
    - channel membership snapshots
    - recent disconnect buffer
    """

    def __init__(self):
        # guild_id -> channel_id -> set(user_id)
        self.channel_members: dict[int, dict[int, set[int]]] = {}

        # (guild_id, user_id) -> (channel_id, left_ts)
        self.recently_left: dict[tuple[int, int], tuple[int, int]] = {}

    def set_channel_members(self, guild_id: int, channel_id: int, members: set[int]) -> None:
        self.channel_members.setdefault(guild_id, {})[channel_id] = members

    def remove_channel(self, guild_id: int, channel_id: int) -> None:
        if guild_id in self.channel_members:
            self.channel_members[guild_id].pop(channel_id, None)
            # cleanup empty dict
            if not self.channel_members[guild_id]:
                self.channel_members.pop(guild_id, None)

    def mark_left(self, guild_id: int, user_id: int, channel_id: int, left_ts: int) -> None:
        self.recently_left[(guild_id, user_id)] = (channel_id, left_ts)

    def clear_left(self, guild_id: int, user_id: int) -> None:
        self.recently_left.pop((guild_id, user_id), None)
