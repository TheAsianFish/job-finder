"""Usage governor for the project builder (AD-42)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from opportunity_radar.projects.builder import RepoState, Stage, pick
from opportunity_radar.projects.portfolio import Project, save_projects
from opportunity_radar.projects.usage import (
    MAX_PROJECTS,
    Meter,
    Row,
    capacity,
    ledger_path,
    load_ledger,
    parse_meter,
    projection,
    session_record,
)

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def _event(five: float, seven: float, status: str = "allowed", resets_in_days: float = 3.5) -> str:
    """A rate_limit_event as Claude Code prints it in stream-json (2026-10-16)."""
    seven_reset = (NOW + timedelta(days=resets_in_days)).timestamp()
    return json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": status,
                "resetsAt": 1792138800,
                "rateLimitType": "five_hour",
                "unifiedWindows": {
                    "five_hour": {"utilization": five, "resetsAt": 1792138800},
                    "seven_day": {"utilization": seven, "resetsAt": seven_reset},
                },
            },
        }
    )


def _result(cost: float, text: str = "done", error: bool = False) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": error,
            "result": text,
            "total_cost_usd": cost,
            "num_turns": 40,
            "duration_ms": 600000,
            "modelUsage": {"claude-opus-5-5": {}, "claude-fable-5-1": {}},
        }
    )


def test_meter_is_read_from_the_last_rate_limit_event():
    stream = "\n".join(
        ['{"type":"system","subtype":"init"}', _event(0.05, 0.18), _event(0.08, 0.2), _result(0.01)]
    )
    meter = parse_meter(stream)
    assert meter is not None and (meter.five_hour, meter.seven_day) == (0.08, 0.2)
    assert meter.seven_day_resets == NOW + timedelta(days=3.5)
    assert parse_meter('{"type":"result"}') is None
    assert "7-day 20%" in meter.summary()


@pytest.mark.parametrize(
    ("five", "seven", "status", "expected"),
    [
        (0.08, 0.10, "allowed", MAX_PROJECTS),  # mid-week, far behind pace
        (0.08, 0.30, "allowed", 3),  # pace at 3.5 of 7 days is ~42%
        (0.08, 0.40, "allowed", 2),
        (0.08, 0.47, "allowed", 1),
        (0.08, 0.60, "allowed", 0),  # well ahead: let the week catch up
        (0.08, 0.86, "allowed", 0),  # at the ceiling
        (0.85, 0.10, "allowed", 0),  # Patrick's 5-hour window nearly used
        (0.60, 0.10, "allowed", 1),  # over half: one project
        (0.10, 0.10, "rejected", 0),  # limit hit
    ],
)
def test_capacity_scales_with_the_meter(five, seven, status, expected):
    meter = parse_meter(_event(five, seven, status))
    room = capacity(meter, NOW)
    assert room.projects == expected, room.reason
    assert room.reason


def test_without_a_meter_the_governor_runs_one_project():
    assert capacity(None, NOW).projects == 1


def test_early_in_the_week_the_pace_floor_keeps_work_going():
    fresh_week = parse_meter(_event(0.0, 0.05, resets_in_days=6.9))
    assert capacity(fresh_week, NOW).projects == MAX_PROJECTS


def test_pick_lets_only_the_governed_number_of_projects_start_sessions():
    waiting = (Project(slug="replay", title="R"), RepoState(True), Stage("wait", reason="review"))
    building = (Project(slug="anvil", title="A"), RepoState(True), Stage("build"))
    merging = (Project(slug="kiln", title="K"), RepoState(True), Stage("merge"))
    held = pick([waiting, building], slots=1)
    assert held[0].slug == "anvil" and held[2].kind == "wait"
    assert held[2].reason.startswith("usage governor")
    assert pick([waiting, building], slots=2) is building
    assert pick([waiting, building, merging], slots=0) is merging  # no session: always
    assert pick([waiting], slots=0) is waiting


def test_session_record_reads_cost_meter_and_limit_hits():
    stream = "\n".join([_event(0.3, 0.4), _result(12.5)])
    record = session_record(stream, "build", 0)
    assert record["cost"] == 12.5 and record["seven_day"] == 0.4 and not record["limit_hit"]
    hit = session_record(
        _result(0.0, "You've hit your session limit · resets 3:45pm", True), "x", 1
    )
    assert hit["limit_hit"] and hit["error"]
    crashed = session_record("", "review", 124)
    assert crashed["error"] and crashed["seven_day"] is None


def test_projection_does_the_simple_math():
    rows = [
        Row(at="2026-10-15T01:00:00+00:00", slug="a", stage="build", seven_day_before=0.1,
            seven_day_after=0.14),
        Row(at="2026-10-15T05:00:00+00:00", slug="b", stage="build", seven_day_before=0.14,
            seven_day_after=0.2),
    ]  # fmt: skip
    text = projection(rows, Meter(five_hour=0.1, seven_day=0.25))
    assert "5.0% of the week" in text and "about 12 more" in text
    assert projection([], None) == "no measured runs yet"


def test_cli_records_runs_and_step_obeys_the_meter(tmp_path, monkeypatch):
    from opportunity_radar import cli_projects
    from opportunity_radar.cli import app
    from opportunity_radar.resume.paths import private_dir
    from tests.unit.test_projects import FakeGh

    sessions = tmp_path / "usage.json"
    sessions.write_text(
        json.dumps([session_record("\n".join([_event(0.3, 0.33), _result(9.0)]), "build", 0),
                    session_record("\n".join([_event(0.35, 0.36), _result(3.0)]), "review", 0)])
    )  # fmt: skip
    result = CliRunner().invoke(
        app, ["projects", "usage-record", "anvil", "build", "--sessions", str(sessions),
              "--before", "0.3"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    row = load_ledger(ledger_path(private_dir()))[-1]
    assert (row.cost, row.seven_day_before, row.seven_day_after) == (12.0, 0.3, 0.36)
    assert CliRunner().invoke(app, ["projects", "usage"]).exit_code == 0

    # Replay waits on its PR; with one slot, Anvil (second in line) is held.
    save_projects(
        [
            Project(slug="replay", title="Replay", status="building"),
            Project(slug="anvil", title="Anvil", status="approved"),
        ]
    )
    open_pr = [
        {"number": 8, "url": "u8", "headRefName": "dev/m7", "createdAt": "2026-10-15T07:00:00Z"}
    ]
    repos = {"TheAsianFish/replay": FakeGh(prs=open_pr), "TheAsianFish/anvil": FakeGh()}

    def fake(args):
        repo = next(a for a in args if a.startswith(("TheAsianFish/", "repos/")))
        return repos["/".join(repo.removeprefix("repos/").split("/")[:2])](args)

    monkeypatch.setattr("opportunity_radar.projects.builder.gh_cli", lambda token=None: fake)
    monkeypatch.setattr(cli_projects, "_candidate_summary", lambda: {})
    out = tmp_path / "context.json"
    step = ["projects", "step", "--out", str(out), "--no-push", "--dry-run"]
    tight, loose = tmp_path / "tight.jsonl", tmp_path / "loose.jsonl"
    reset = (datetime.now(UTC) + timedelta(days=3.5)).timestamp()
    for path, five in ((tight, 0.6), (loose, 0.05)):
        event = json.loads(_event(five, 0.05))
        event["rate_limit_info"]["unifiedWindows"]["seven_day"]["resetsAt"] = reset
        path.write_text(json.dumps(event))
    assert CliRunner().invoke(app, [*step, "--meter", str(tight)]).exit_code == 0
    context = json.loads(out.read_text())
    assert context["stage"] == "wait" and context["reason"].startswith("usage governor")
    assert context["seven_day_before"] == 0.05
    assert CliRunner().invoke(app, [*step, "--meter", str(loose)]).exit_code == 0
    assert json.loads(out.read_text())["slug"] == "anvil"
    # A run for Anvil alone still counts its place in line.
    assert CliRunner().invoke(app, [*step, "--meter", str(tight), "--slug", "anvil"]).exit_code == 0
    assert json.loads(out.read_text())["stage"] == "wait"
    # The scan chain's wake-up check (no meter) only asks whether there is work.
    assert CliRunner().invoke(app, step).exit_code == 0
    assert json.loads(out.read_text())["slug"] == "anvil"


def test_spare_usage_gates_discretionary_work():
    from opportunity_radar.projects.usage import capacity

    roomy = parse_meter(_event(0.1, 0.05))
    assert capacity(roomy, NOW).spare
    assert not capacity(parse_meter(_event(0.6, 0.05)), NOW).spare  # 5-hour half used
    assert not capacity(parse_meter(_event(0.1, 0.40)), NOW).spare  # near the weekly pace
    assert not capacity(None, NOW).spare  # never blind
