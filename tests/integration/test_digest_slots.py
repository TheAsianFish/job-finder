"""Digest slot scheduling: fires once per slot per day, works outside the daemon."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from opportunity_radar.config import AppSettings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.models.company import CompanySource
from opportunity_radar.notifications.digest import (
    LAST_EVENING_DIGEST_KEY,
    LAST_MORNING_DIGEST_KEY,
    send_digest_if_due,
)
from opportunity_radar.notifications.discord import DiscordNotifier
from tests.unit.test_db import alias_hashes, make_record

WEBHOOK = "https://discord.com/api/webhooks/777/slots"


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/slots.db"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    with session_scope(url) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        record = make_record("1", "Backend Engineer Intern - Spring 2027")
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 75.0
        row.digest_pending = True
    yield url
    reset_engine()


def _settings(morning: int, evening: int) -> AppSettings:
    config = AppSettings()
    config.scheduler.morning_digest_hour = morning
    config.scheduler.evening_digest_hour = evening
    return config


@respx.mock
async def test_slot_fires_once_per_day(db):
    route = respx.post(WEBHOOK).mock(return_value=Response(204))
    # Both slots at hour 0 -> always due today.
    settings = _settings(0, 0)
    notifier = DiscordNotifier(WEBHOOK)

    sent = await send_digest_if_due(settings, notifier, db_url=db)
    assert sent is True
    first_calls = route.call_count
    assert first_calls >= 1

    # Second invocation the same day: slots already consumed, nothing sent.
    sent_again = await send_digest_if_due(settings, notifier, db_url=db)
    assert sent_again is False
    assert route.call_count == first_calls

    with session_scope(db) as session:
        assert repo.meta_get(session, LAST_MORNING_DIGEST_KEY) is not None
        assert repo.meta_get(session, LAST_EVENING_DIGEST_KEY) is not None


@respx.mock
async def test_slot_not_due_before_hour(db):
    route = respx.post(WEBHOOK).mock(return_value=Response(204))
    # Both slots at hour 23 -> not due unless it's 23:00 local right now.
    from datetime import datetime

    if datetime.now().astimezone().hour >= 23:
        pytest.skip("running at 23:00 local — slot would legitimately be due")
    settings = _settings(23, 23)
    sent = await send_digest_if_due(settings, DiscordNotifier(WEBHOOK), db_url=db)
    assert sent is False
    assert route.call_count == 0
