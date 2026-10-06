"""RFC 9309 matching: longest rule wins, Allow beats Disallow on ties."""

from opportunity_radar.utilities.robots import RobotsRules

UA = "OpportunityRadar/1.0 (+local personal job monitor)"


def test_longest_match_wins_over_file_order():
    rules = RobotsRules.parse("User-agent: *\nDisallow: /\nAllow: /api/apply\nAllow: /careers\n")
    assert rules.can_fetch(UA, "https://x.net/api/apply/v2/jobs?domain=x.com")
    assert rules.can_fetch(UA, "https://x.net/careers/job/1")
    assert not rules.can_fetch(UA, "https://x.net/admin")


def test_specific_agent_group_beats_wildcard():
    text = "User-agent: *\nAllow: /\n\nUser-agent: OpportunityRadar\nDisallow: /private\n"
    rules = RobotsRules.parse(text)
    assert not rules.can_fetch(UA, "https://x.net/private/1")
    assert rules.can_fetch(UA, "https://x.net/public")
    assert rules.can_fetch("OtherBot/2.0", "https://x.net/private/1")


def test_wildcards_and_anchors():
    rules = RobotsRules.parse("User-agent: *\nDisallow: /*/internal\nDisallow: /*.pdf$\n")
    assert not rules.can_fetch(UA, "https://x.net/en/internal")
    assert not rules.can_fetch(UA, "https://x.net/a/b.pdf")
    assert rules.can_fetch(UA, "https://x.net/a/b.pdf?x=1")
    assert rules.can_fetch(UA, "https://x.net/en/jobs")


def test_empty_and_comment_lines_tolerated():
    rules = RobotsRules.parse("# nothing\nUser-agent: *\nDisallow:\n")
    assert rules.can_fetch(UA, "https://x.net/anything")


def test_disallow_all_helper():
    assert not RobotsRules.disallow_all().can_fetch(UA, "https://x.net/")
