# Railway (one service: backend + built frontend)

Copy these files to the folder that holds both `omni-backend` and `omni-frontend`, then run `railway up --service daxagent` from it.

- Volume: mount one at `/data` (`DAXAGENT_DATA_DIR`). SQLite and every task folder live there, so keep one replica.
- Variables: the model and app keys from `omni-backend/.env`, plus `CLERK_PUBLISHABLE_KEY`, `VITE_CLERK_PUBLISHABLE_KEY` (build arg) and `CLERK_AUTHORIZED_PARTIES=https://<domain>`.
- Moving local data: set `DAXAGENT_SEED_TOKEN`, run `scripts/seed_archive.sh`, POST the archive to `/settings/admin/seed` with header `X-Seed-Token`, delete the variable and restart (`src/seed.py`).
