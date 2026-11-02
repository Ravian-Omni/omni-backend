# Railway (one service: backend + built frontend)

Copy these files to the folder that holds both `omni-backend` and `omni-frontend`, then run `railway up --service daxagent` from it.

- Volume: mount one at `/data` (`DAXAGENT_DATA_DIR`). SQLite and every task folder live there, so keep one replica.
- Variables: the model and app keys from `omni-backend/.env`, plus `DAXAGENT_AUTH=on` and a random `DAXAGENT_ADMIN_TOKEN`.
- Clerk instead of local accounts: `DAXAGENT_AUTH=clerk` and `CLERK_PUBLISHABLE_KEY` (no secret key: the app checks Clerk's session tokens against the instance's published keys). Restrict sign-ups in the Clerk Dashboard, or anyone who signs up gets an account (with its own, empty workspace). Each person has their own chats and agents; there are no shared team workspaces (Clerk organizations are off). `DAXAGENT_OWNER` (a Clerk user id) takes over, at every start, whatever still belongs to `local_user`: data from before sign-in was per person, and chats the Teams and Slack bots start. A Clerk production instance needs a custom domain for Clerk's DNS records, so a `*.up.railway.app` domain can only run a development instance; with a production instance, add `https://clerk.<your-domain>` to `script-src` in `omni-frontend/index.html`.
- MCP servers: `MCP_URL_<NAME>` replaces a bundled server's address, e.g. `MCP_URL_USER_CONTEXT=https://<tunnel>/mcp` (the bundled config points at `127.0.0.1:8322`).
- Accounts: `curl -X POST https://<domain>/auth/users -H "X-Admin-Token: $DAXAGENT_ADMIN_TOKEN" -H 'content-type: application/json' -d '{"email": "...", "password": "...", "name": "..."}'` (posting again resets the password). Each account has its own chats, agents and connections.
- Moving local data: set `DAXAGENT_SEED_TOKEN`, run `scripts/seed_archive.sh`, POST the archive to `/settings/admin/seed` with header `X-Seed-Token`, delete the variable and restart (`src/seed.py`).

## Hosting somewhere else

The image is not tied to Railway. A host works if it gives:
- One container and one replica, with a persistent disk at `/data`. SQLite and the reply watcher assume a single process, and a network file share (EFS, Azure Files) breaks SQLite locking. That rules out Cloud Run, App Runner, Heroku and Vercel. Railway, Render with a disk, Fly.io with a volume, or a Linux VM with Docker all fit.
- WebSockets that stay open for many minutes, because agents stream whole runs over one socket.
- TLS at the host's proxy. The image trusts the proxy's `X-Forwarded-Proto` (`FORWARDED_ALLOW_IPS=*`) so OAuth callbacks are https. Expose only the proxy, never the container port.
- `PORT` from the host (default 8000) and a health check on `GET /health`.

What each capability needs on the new host:

| Capability | Needs |
|---|---|
| Models, agents | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DAXAGENT_AGENT_PROVIDER` (and any `DAXAGENT_AGENT_*` set on the current host) |
| Sign-in | `DAXAGENT_AUTH=on`, a new random `DAXAGENT_ADMIN_TOKEN`, then add accounts as above |
| Data Axle | Sign in again on the new domain; the callback `https://<domain>/mcp/callback/data-axle` registers itself |
| Gmail, Slack, Google Calendar | `COMPOSIO_API_KEY`; the connections live in Composio, so the same key brings them back |
| Jev (Inbox Agent) | Its key in Settings, API keys |
| Newton (Data Analyst) | Newton itself on a Linux VM with Docker: it creates its sandboxes through the host's Docker daemon, so no container platform can run it. Then add its public URL and key in Settings, Connections |
| User's Context | The brain server needs Apple Silicon (`mlx-whisper`). Keep it on the Mac behind a tunnel, or run it on Linux without audio transcription. Then `MCP_URL_USER_CONTEXT` and its bearer key in Settings, Connections |
| Teams and Slack bots | Point their endpoints at the new domain |

Seeding from a local `~/.daxagent` (above) also copies its API keys, MCP tokens and saved servers. A saved server that points at `127.0.0.1` (Newton) must be given its public URL afterwards.

## Microsoft Teams bot

Each Teams chat or channel thread with the bot is one task (the same task mode as the web app, visible there too). The agents' questions arrive as messages and the next reply answers them; `stop` cancels a run.

1. Azure portal: create an **Azure Bot**, note its Microsoft App ID and add a client secret.
2. Bot → Configuration → Messaging endpoint `https://<domain>/teams/messages`; Channels → add **Microsoft Teams**.
3. Railway variables: `DAXAGENT_TEAMS_APP_ID`, `DAXAGENT_TEAMS_APP_PASSWORD`, and `DAXAGENT_TEAMS_TENANT_ID` for a Single Tenant bot.
4. Install the bot in Teams (Developer Portal app package with that App ID, or sideload).

## Slack bot

A DM with the bot, or a channel thread where it is @mentioned, is one task (in a channel thread, @mention the bot in every message, including answers). `stop` cancels a run.

1. api.slack.com → Create New App (from scratch). OAuth & Permissions → bot scopes `app_mentions:read`, `chat:write`, `im:history`, `reactions:write`; install to the workspace and copy the Bot User OAuth Token. Basic Information → copy the Signing Secret.
2. Railway variables: `DAXAGENT_SLACK_SIGNING_SECRET`, `DAXAGENT_SLACK_BOT_TOKEN`; redeploy.
3. Event Subscriptions → enable, Request URL `https://<domain>/slack/events` (Slack verifies it against the running app), subscribe to bot events `app_mention` and `message.im`. App Home → allow users to send messages in the Messages tab.
