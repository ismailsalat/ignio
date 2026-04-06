def compute_streak_transition(
    min_required_seconds: int,
    today_seconds: int,
    today_day_key: int,
    last_completed_day_key: int,
    current_streak: int,
    longest_streak: int,
) -> tuple[bool, int, int]:
    """
    Determines if today's progress completes the streak day and updates streak values.

    Returns:
        (became_completed, new_current_streak, new_longest_streak)
    """

    # not enough time today → nothing changes
    if today_seconds < min_required_seconds:
        return False, current_streak, longest_streak

    # already completed today → don't double count
    if last_completed_day_key == today_day_key:
        return False, current_streak, longest_streak

    # first ever completion OR gap → reset to 1
    if last_completed_day_key < 0:
        new_current = 1

    # consecutive day → extend streak
    elif last_completed_day_key == today_day_key - 1:
        new_current = current_streak + 1 if current_streak > 0 else 1

    # missed day → reset
    else:
        new_current = 1

    new_longest = max(longest_streak, new_current)

    return True, new_current, new_longest