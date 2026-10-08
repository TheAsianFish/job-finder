"""Discord bot setup: the AI creates its own hub channels and webhooks (AD-33).

Patrick creates a bot once (docs/discord-hub.md) and invites it with Manage
Channels + Manage Webhooks. `opportunity-radar discord setup --guild <id>`
then makes an "Opportunity Radar" category with one channel per hub purpose
(notifications.discord.CHANNELS), a webhook in each, and stores the webhook
URLs as DISCORD_WEBHOOK_<NAME> in .env and as GitHub Actions secrets.
Idempotent: existing channels and webhooks are reused, never duplicated.
The bot token and webhook URLs are secrets and are never printed or logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from opportunity_radar.notifications.discord import CHANNELS, webhook_env

API = "https://discord.com/api/v10"
CATEGORY = "Opportunity Radar"
WEBHOOK_NAME = "Opportunity Radar"
TEXT, CATEGORY_TYPE = 0, 4


class DiscordBotError(RuntimeError):
    pass


@dataclass
class HubSetup:
    webhooks: dict[str, str] = field(default_factory=dict)  # channel -> webhook URL
    created_channels: list[str] = field(default_factory=list)
    created_webhooks: list[str] = field(default_factory=list)

    @property
    def env(self) -> dict[str, str]:
        return {webhook_env(name): url for name, url in self.webhooks.items()}


def _check(response: httpx.Response, what: str) -> httpx.Response:
    if response.status_code >= 400:
        hint = ""
        if response.status_code in (401, 403):
            hint = " (check the bot token and that the bot has Manage Channels + Manage Webhooks)"
        raise DiscordBotError(f"{what} failed: HTTP {response.status_code}{hint}")
    return response


def setup_hub(token: str, guild_id: str, client: httpx.Client | None = None) -> HubSetup:
    http = client or httpx.Client(timeout=20)
    http.headers.update({"Authorization": f"Bot {token}", "User-Agent": "OpportunityRadar"})
    result = HubSetup()
    channels = _check(http.get(f"{API}/guilds/{guild_id}/channels"), "listing channels").json()
    category = next(
        (c for c in channels if c.get("type") == CATEGORY_TYPE and c.get("name") == CATEGORY),
        None,
    )
    if category is None:
        category = _check(
            http.post(
                f"{API}/guilds/{guild_id}/channels", json={"name": CATEGORY, "type": CATEGORY_TYPE}
            ),
            "creating the category",
        ).json()
    for name, topic in CHANNELS.items():
        channel = next(
            (c for c in channels if c.get("type") == TEXT and c.get("name") == name), None
        )
        if channel is None:
            channel = _check(
                http.post(
                    f"{API}/guilds/{guild_id}/channels",
                    json={"name": name, "type": TEXT, "topic": topic, "parent_id": category["id"]},
                ),
                f"creating #{name}",
            ).json()
            result.created_channels.append(name)
        hooks = _check(
            http.get(f"{API}/channels/{channel['id']}/webhooks"), f"listing #{name} webhooks"
        ).json()
        hook = next((h for h in hooks if h.get("name") == WEBHOOK_NAME and h.get("token")), None)
        if hook is None:
            hook = _check(
                http.post(f"{API}/channels/{channel['id']}/webhooks", json={"name": WEBHOOK_NAME}),
                f"creating the #{name} webhook",
            ).json()
            result.created_webhooks.append(name)
            _check(
                http.post(
                    f"{API}/channels/{channel['id']}/messages",
                    json={"content": f"**#{name}**: {topic}. Posted here by Opportunity Radar."},
                ),
                f"posting the #{name} intro",
            )
        result.webhooks[name] = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"
    return result


def upsert_env(path, values: dict[str, str]) -> None:
    """Set KEY=value lines in a .env file, replacing existing keys."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
