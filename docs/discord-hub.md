# Discord hub

Discord is where everything reaches Patrick; the private repo's `hub/` is
where everything is remembered (AD-33).

| Channel | What lands there | Secret |
|---|---|---|
| `#job` (existing) | New-role alerts, digests | `DISCORD_WEBHOOK_URL` |
| `#resume` | Resume checks, tailored PDFs, bullet proposals to approve | `DISCORD_WEBHOOK_RESUME` |
| `#projects` | Project proposals, plan/milestone PRs, finished projects | `DISCORD_WEBHOOK_PROJECTS` |
| `#study` | Weekly study pack + quiz (Sundays) | `DISCORD_WEBHOOK_STUDY` |
| `#agent-log` | Weekly reviews and other agent reports | `DISCORD_WEBHOOK_AGENT_LOG` |

Any channel whose secret is missing falls back to `#job`, so nothing is lost
before setup.

## One-time bot setup (about 3 minutes)

1. https://discord.com/developers/applications → **New Application** → name it
   `Opportunity Radar`.
2. **Bot** tab → **Reset Token** → copy it. Add it to `job-finder/.env` as
   `DISCORD_BOT_TOKEN=...` (never paste it into a chat). On the same tab, turn
   on **Message Content Intent** (lets a later version read your quiz answers
   and approvals in Discord).
3. **OAuth2 → URL Generator**: scope `bot`; permissions **View Channels, Send
   Messages, Embed Links, Attach Files, Read Message History, Add Reactions,
   Manage Channels, Manage Webhooks**. Open the generated URL and add the bot
   to your server.
4. In Discord: Settings → Advanced → **Developer Mode** on; right-click your
   server → **Copy Server ID**.
5. Run:
   ```
   uv run opportunity-radar discord setup --guild <server id>
   gh secret set -f .env.discord --repo TheAsianFish/job-finder
   ```
   The first command creates the category, channels and webhooks (safe to
   re-run) and writes `.env` + `.env.discord` (git-ignored). The second
   uploads the webhooks for the cloud agents.
