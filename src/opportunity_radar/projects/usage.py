"""Usage governor for the project builder (AD-42).

Patrick runs 2-4 projects at once only if the builder never eats his Claude
Max allowance. Claude Code reports the plan's real meters headlessly: with
`--output-format stream-json --verbose`, a `rate_limit_event` carries the
utilization (0-1) of the 5-hour and 7-day windows and when each resets. The
builder reads them and scales itself like an autoscaler:

- **Read.** The control job runs a one-line Haiku probe (`probe.sh`) and
  every agent session runs in stream-json, so the meter is read before the
  run decides anything and after each session.
- **Decide.** `capacity` turns the meter into how many projects may take
  agent sessions now, from MAX_PROJECTS down to 0, with the reason:
  - 5-hour window: the builder stops at FIVE_HOUR_STOP, so Patrick's own
    sessions are never starved, and runs a single project from
    FIVE_HOUR_SLOW.
  - 7-day window: the builder paces itself so the account ends the week at
    WEEKLY_CEILING at most. Usage ahead of a straight-line pace toward the
    ceiling scales down, usage behind it scales up.

  Merges and CI re-runs need no session and always go through.
- **Record.** Each session adds a row to `usage/builder.jsonl` in the private
  repo: project, stage, list-price cost, and the 7-day meter before and after.
  `projection` averages the per-session meter cost to say how many more
  sessions fit this week (the "simple math").

Weekly, not monthly: Max limits are a rolling 5-hour window and a 7-day
window, and those two are the only meters there are.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

MAX_PROJECTS = 4
WEEKLY_CEILING = 0.85  # the builder never pushes the 7-day meter past this
FIVE_HOUR_STOP = 0.80  # no new sessions above this 5-hour utilization
FIVE_HOUR_SLOW = 0.50  # one project at a time above this
PACE_FLOOR = 0.15  # early in the week the pace line starts here, not at 0
SPARE_RATIO = 0.8  # discretionary work (evolve) only this far behind the weekly pace
WEEK = timedelta(days=7)


@dataclass
class Meter:
    five_hour: float
    seven_day: float
    five_hour_resets: datetime | None = None
    seven_day_resets: datetime | None = None
    status: str = "allowed"  # "rejected" once a limit is hit

    def summary(self) -> str:
        def at(when: datetime | None) -> str:
            return f" (resets {when:%a %H:%M} UTC)" if when else ""

        return (
            f"5-hour {self.five_hour:.0%}{at(self.five_hour_resets)}, "
            f"7-day {self.seven_day:.0%}{at(self.seven_day_resets)}"
        )


def _epoch(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), UTC) if value else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_meter(stream: str) -> Meter | None:
    """The last rate_limit_event in Claude Code's stream-json output."""
    found: Meter | None = None
    for line in stream.splitlines():
        if '"rate_limit_event"' not in line:
            continue
        try:
            info = (json.loads(line) or {}).get("rate_limit_info") or {}
        except ValueError:
            continue
        windows = info.get("unifiedWindows") or {}
        five, seven = windows.get("five_hour") or {}, windows.get("seven_day") or {}
        if "utilization" not in five and "utilization" not in seven:
            continue
        found = Meter(
            five_hour=float(five.get("utilization") or 0.0),
            seven_day=float(seven.get("utilization") or 0.0),
            five_hour_resets=_epoch(five.get("resetsAt")),
            seven_day_resets=_epoch(seven.get("resetsAt")),
            status=str(info.get("status") or "allowed"),
        )
    return found


def parse_result(stream: str) -> dict:
    """The final result message of a stream-json session ({} if it crashed)."""
    result: dict = {}
    for line in stream.splitlines():
        if '"type":"result"' in line.replace(" ", ""):
            try:
                result = json.loads(line)
            except ValueError:
                continue
    return result


# ---------------------------------------------------------------- governor


@dataclass
class Capacity:
    projects: int  # how many projects may take agent sessions now
    reason: str
    meter: Meter | None = None
    # Room for discretionary work (evolve rounds, AD-44): clearly behind the
    # weekly pace and the 5-hour window under half used. Never without a meter.
    spare: bool = False

    def summary(self) -> str:
        reading = self.meter.summary() if self.meter else "meter unavailable"
        return f"{self.projects} project(s) may run · {reading} · {self.reason}"


def pace(meter: Meter, now: datetime) -> float:
    """Where the 7-day meter may be by now on a straight line to the ceiling."""
    if meter.seven_day_resets is None:
        return WEEKLY_CEILING
    elapsed = 1 - max(0.0, (meter.seven_day_resets - now) / WEEK)
    return max(PACE_FLOOR, WEEKLY_CEILING * min(1.0, elapsed))


def capacity(meter: Meter | None, now: datetime | None = None) -> Capacity:
    now = now or datetime.now(UTC)
    if meter is None:
        # No reading (probe failed): stay conservative rather than blind.
        return Capacity(1, "usage meter unreadable; running one project", None)
    if meter.status == "rejected" or meter.five_hour >= 1 or meter.seven_day >= 1:
        return Capacity(0, "usage limit reached; waiting for the reset", meter)
    if meter.seven_day >= WEEKLY_CEILING:
        return Capacity(0, f"7-day meter at the {WEEKLY_CEILING:.0%} ceiling", meter)
    if meter.five_hour >= FIVE_HOUR_STOP:
        return Capacity(0, "5-hour window nearly used; leaving it to you", meter)
    target = pace(meter, now)
    ratio = meter.seven_day / target
    # Like an autoscaler: the replica count follows how far ahead of the
    # week's pace the meter is.
    if ratio < 0.5:
        projects, why = MAX_PROJECTS, "well behind the weekly pace"
    elif ratio < 0.8:
        projects, why = 3, "behind the weekly pace"
    elif ratio < 1.0:
        projects, why = 2, "near the weekly pace"
    elif ratio < 1.2:
        projects, why = 1, "slightly ahead of the weekly pace"
    else:
        projects, why = 0, "ahead of the weekly pace; letting the week catch up"
    if projects > 1 and meter.five_hour >= FIVE_HOUR_SLOW:
        projects, why = 1, "5-hour window over half used"
    spare = ratio < SPARE_RATIO and meter.five_hour < FIVE_HOUR_SLOW
    return Capacity(projects, f"{why} (pace {target:.0%})", meter, spare)


# ---------------------------------------------------------------- ledger


@dataclass
class Row:
    at: str
    slug: str
    stage: str
    cost: float = 0.0  # Claude Code's list-price estimate; subagents included
    seven_day_before: float | None = None
    seven_day_after: float | None = None
    five_hour_after: float | None = None
    limit_hit: bool = False


def ledger_path(private: Path) -> Path:
    return private / "usage" / "builder.jsonl"


def load_ledger(path: Path) -> list[Row]:
    rows: list[Row] = []
    if not path.exists():
        return rows
    known = set(Row.__dataclass_fields__)
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("at"):
            rows.append(Row(**{k: v for k, v in data.items() if k in known}))
    return rows


def append(path: Path, rows: Iterable[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(asdict(row), sort_keys=True) + "\n")


def projection(rows: list[Row], meter: Meter | None) -> str:
    """How many more builder runs fit this week, from the average 7-day meter
    cost of recent runs (one run = one row: a stage's sessions)."""
    deltas = [
        r.seven_day_after - r.seven_day_before
        for r in rows[-20:]
        if r.seven_day_after is not None and r.seven_day_before is not None
    ]
    deltas = [d for d in deltas if d >= 0]
    if not deltas or meter is None:
        return "no measured runs yet"
    per_run = sum(deltas) / len(deltas)
    left = max(0.0, WEEKLY_CEILING - meter.seven_day)
    if per_run <= 0:
        return f"runs cost under 1% of the week each; {left:.0%} left to the ceiling"
    return (
        f"a run costs {per_run:.1%} of the week on average; about {int(left / per_run + 1e-9)} "
        f"more fit before the {WEEKLY_CEILING:.0%} ceiling"
    )


# ---------------------------------------------------------------- sessions

_LIMIT_TEXT = ("hit your session limit", "hit your weekly limit", "usage limit")


def session_record(stream: str, label: str, status: int) -> dict:
    """What one agent session cost and where it left the meter."""
    result, reading = parse_result(stream), parse_meter(stream)
    text = str(result.get("result") or "").lower()
    return {
        "label": label,
        "exit": status,
        "cost": round(float(result.get("total_cost_usd") or 0.0), 4),
        "turns": result.get("num_turns"),
        "minutes": round((result.get("duration_ms") or 0) / 60000, 1),
        "models": sorted((result.get("modelUsage") or {}).keys()),
        "error": bool(result.get("is_error")) or not result,
        "five_hour": reading.five_hour if reading else None,
        "seven_day": reading.seven_day if reading else None,
        "limit_hit": any(t in text for t in _LIMIT_TEXT)
        or (reading is not None and reading.status == "rejected"),
    }


def _main(argv: list[str]) -> int:
    """`usage.py session LOG LABEL STATUS OUT`: summarise one session for the
    runner (stdlib only, so it runs without the project's environment)."""
    if len(argv) != 6 or argv[1] != "session":
        print("usage: usage.py session LOG LABEL STATUS OUT")
        return 2
    log, label, status, out = Path(argv[2]), argv[3], int(argv[4]), Path(argv[5])
    stream = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    record = session_record(stream, label, status)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record), encoding="utf-8")
    meter = (
        f"5h {record['five_hour']:.0%}, 7d {record['seven_day']:.0%}"
        if record["seven_day"] is not None
        else "meter n/a"
    )
    print(
        f"{label}: exit {status}, error={record['error']}, turns={record['turns']}, "
        f"minutes={record['minutes']}, ${record['cost']:.2f} list price, {meter}"
        + (", USAGE LIMIT HIT" if record["limit_hit"] else "")
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
