def compute_streak_transition(
    min_required_seconds,
    today_seconds,
    today_day_key,
    last_completed_day_key,
    current_streak,
    longest_streak,
):

    if today_seconds < min_required_seconds:
        return False, current_streak, longest_streak

    if last_completed_day_key == today_day_key:
        return False, current_streak, longest_streak

    if last_completed_day_key == today_day_key - 1:
        new_current = current_streak + 1 if current_streak else 1
    else:
        new_current = 1

    new_longest = max(longest_streak, new_current)

    return True, new_current, new_longest
