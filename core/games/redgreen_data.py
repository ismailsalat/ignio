# core/games/redgreen_data.py
"""
Scenario bank for the !flag (Red Flag / Green Flag) voting game.

Two kinds:
  GENERIC  — standalone relationship/dating scenarios.
  TARGETED — templates with {name} that get aimed at a mentioned person.

Tone: fun, spicy, a little mean sometimes — but never hateful, sexual, or about
protected characteristics. It's playful chaos for chat activity.
"""

# ---- standalone scenarios (no person involved) ----
GENERIC = [
    "They take 8 hours to reply but watch every single story.",
    "They still have photos with their ex as their phone wallpaper.",
    "They call their mom during the date... three times.",
    "They say 'I'm not like other people' completely unironically.",
    "They have 14k followers and follow 12k people.",
    "They text 'we need to talk' then go offline for a day.",
    "They like their own selfies from a second account.",
    "They bring up their ex within the first ten minutes.",
    "They split the bill down to who breathed more air.",
    "They say 'haha' to every single thing you send.",
    "They have a finsta JUST to watch you.",
    "They reply 'k'.",
    "They show up 40 minutes late with no apology and a Starbucks.",
    "They use 'per my last text' in a normal conversation.",
    "They ask for your Netflix password on the first date.",
    "They have a spreadsheet ranking their talking stage options.",
    "They say 'trust me' before doing something you should not trust.",
    "They left you on read but posted a thirst trap 2 minutes later.",
    "They have opinions about your friends they've never met.",
    "They screenshot your messages to send to the group chat.",
    "They say 'I don't really do labels' on month six.",
    "They reply to your paragraph with a single emoji.",
    "They keep score of every favor they've ever done.",
    "They 'forgot' their wallet again.",
    "They follow 47 of your mutuals before you've even met.",
    "They love-bomb you for a week then disappear for two.",
    "They say 'you're not like other people I've dated' (red flag factory).",
    "They have read receipts ON and still leave you on read.",
    "They unfollow you after every small argument.",
    "They text their 'best friend' more than they text you, and it's their ex.",
    "They plan the whole future on date one but can't pick a restaurant.",
    "They say 'I'm an empath' while ignoring how you feel.",
    "They keep their notifications hidden when you're around.",
    "They've been 'almost broken up' with their situationship for a year.",
    "They make you the main character one week and a stranger the next.",
]

# ---- targeted templates (use a mentioned person) ----
TARGETED = [
    "{name} showed up to the date 40 minutes late with no apology.",
    "{name} replied 'k' to your three-paragraph heartfelt message.",
    "{name} watched all your stories but didn't text back for two days.",
    "{name} brought their ex up on the first date... twice.",
    "{name} 'forgot' their wallet again, somehow.",
    "{name} liked someone else's selfie while on a date with you.",
    "{name} called you by the wrong name and didn't even flinch.",
    "{name} said 'we'll see' when you asked if they like you.",
    "{name} has a notes app list of everyone they're talking to — and you're #4.",
    "{name} left you on read then posted 'bored, someone text me'.",
    "{name} split the bill but ordered the lobster.",
    "{name} said 'I don't really believe in birthdays' on your birthday.",
    "{name} double texted your situationship 'just to check in'.",
    "{name} took a call from 'a friend' and whispered the whole time.",
    "{name} said your favorite show is 'kinda mid' to your face.",
    "{name} ghosted for a week then said 'my bad, been busy'.",
    "{name} made plans with you then posted being somewhere else.",
    "{name} asked to 'keep things casual' after meeting your parents.",
    "{name} reacted 😂 to you saying you had a hard day.",
    "{name} still likes their ex's posts from 2019.",
    "{name} said 'you're cute for someone like you'.",
    "{name} brought a friend to your one-on-one dinner 'for vibes'.",
    "{name} screenshots your texts to their group chat for ratings.",
    "{name} said 'I was gonna text you' three days later.",
    "{name} planned a whole future with you, then forgot your name.",
]


def all_count():
    return len(GENERIC) + len(TARGETED)
