# Development Guide

This guide is for changing the app, running tests, debugging the pipeline, and understanding how the repo fits together.

## Repository Map

```text
backend/
  app/
    main.py                 FastAPI app and router registration
    routers/                API routes
    services/               Billing, queue, API keys, pipeline runner, static asset helpers
    core/                   Config, database, security
    models.py               SQLAlchemy models
    schemas.py              Pydantic request and response models
  data/pipeline/            Runtime genre, reference, static asset, and run data

final_pipeline/
  main.py                   CLI pipeline entry point
  agents/                   Topic, research, script, asset, audio, caption, music, render, thumbnail agents
  modules/                  LLM, audio, asset, render, discovery, visual, safety helpers
  app/                      Pipeline-local config, schemas, paths, logger

desktop_app/
  src/                      Electron React UI
  electron/                 Main and preload processes

payment_website/
  src/                      React checkout/login/account site

playground/
  run_pipeline.sh           Direct CLI wrapper using playground data dirs
  ui/                       React stage playground

tests/                      Pytest coverage for billing and pipeline behavior
docker-compose.yaml         Local service stack
```

## Architecture

The normal production-like flow is:

1. The user signs up or logs in through the desktop app or payment website.
2. Billing routes verify Razorpay checkout and create an entitlement.
3. The desktop app calls authenticated backend routes under `/api`.
4. A generation request creates a `VideoJob` row and enqueues `app.jobs.run_video_job` on Redis/RQ.
5. The worker invokes `PipelineRunner`, which shells into `final_pipeline/main.py`.
6. Pipeline stages write logs and artifacts under a run directory.
7. The worker updates the job row with status, logs, output paths, and errors.
8. The desktop app polls job progress and exposes previews/downloads through backend file routes.

The playground uses the same `final_pipeline/` code, but stores run metadata in a separate playground database and uses separate playground run directories.

## Local Development Setup

Create `.env`:

```bash
cp .env.example .env
```

Start the service stack:

```bash
docker compose up --build backend worker payment_website
```

Install frontend dependencies:

```bash
cd desktop_app
npm install
cd ../payment_website
npm install
cd ../playground/ui
npm install
```

Start Electron:

```bash
cd desktop_app
npm start
```

Start frontend dev servers when you want hot reload:

```bash
cd payment_website
VITE_API_BASE=http://localhost:8084/api npm run dev
```

```bash
cd playground/ui
npm run dev
```

## Docker Services

Compose services:

- `db_user`: Postgres for accounts, chats, jobs, onboarding, calibration, and feedback.
- `db_static`: Postgres for static assets, genres, and reference examples.
- `db_playground`: Postgres for playground runs and stage payloads.
- `redis`: RQ queue broker.
- `backend`: FastAPI app served by Uvicorn.
- `worker`: RQ worker for generation jobs.
- `worker_calibration_1`, `worker_calibration_2`, `worker_calibration_3`: calibration queue workers.
- `payment_website`: nginx-served checkout site.
- `playground_ui`: nginx-served playground build.
- `dbgate`: database browser.

Useful commands:

```bash
docker compose ps
docker compose logs backend
docker compose logs worker
docker compose logs redis
docker compose down
```

Use `docker compose down -v` only when you intentionally want to remove local database volumes.

## Environment Variables

Core runtime:

- `APP_PORT`: host port for the backend API, default `8084`.
- `FRONTEND_PORT`: host port for nginx playground UI, default `3000`.
- `PAYMENT_WEBSITE_PORT`: host port for payment website, default `3001`.
- `DB_VIEWER_PORT`: host port for DbGate, default `8082`.
- `JWT_SECRET`: signing secret for auth tokens.
- `ACCESS_TOKEN_MINUTES`: token lifetime.
- `CORS_ORIGINS`: allowed browser origins.
- `WORKER_JOB_TIMEOUT`: job timeout in seconds.

Databases:

- `APP_DB_*`: user database credentials and host port.
- `STATIC_DB_*`: static database credentials and host port.
- `PLAYGROUND_DB_*`: playground database credentials and host port.
- `DATABASE_URL`, `USER_DATABASE_URL`, `STATIC_DATABASE_URL`, `PLAYGROUND_DATABASE_URL`: explicit SQLAlchemy URLs when not relying on compose defaults.

Queue:

- `REDIS_URL`: Redis URL.
- `QUEUE_NAME`: base queue name, default `video_jobs`.
- `WORKER_QUEUES`: comma-separated queue names for a worker process.

Pipeline:

- `MODULARSHORTS_DATA_DIR`: root data directory for genres, references, and assets.
- `MODULARSHORTS_RUNS_DIR`: root output directory for run artifacts.
- `STATIC_ASSET_EXTRA_ROOTS`: extra read-only asset roots, used by Docker for `PK_ASSETS_DIR`.
- `PLAYGROUND_PIPELINE_DATA_DIR`: playground pipeline data root.
- `PLAYGROUND_RUNS_DIR`: playground output root.
- `PLAYGROUND_MAX_MUSIC_UPLOAD_MB`: upload limit for playground music.

AI and media providers:

- `LLM_PROVIDER`: `auto` or a provider name.
- `LLM_API_KEY`, `LLM_MODEL`: generic provider config.
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `GROQ_API_KEY`, `GROQ_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- `PEXELS_API_KEY`
- `PIXABAY_API_KEY`
- `UNSPLASH_ACCESS_KEY`
- `GOOGLE_TTS_CREDENTIALS`

Billing:

- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`
- `PAYMENT_CURRENCY`
- `PAYMENT_SITE_URL`
- `PAYMENT_MONTHLY_PLAN_ID`
- `PAYMENT_YEARLY_PLAN_ID`
- `PAYMENT_MONTHLY_AMOUNT_PAISE`
- `PAYMENT_YEARLY_AMOUNT_PAISE`
- `PAYMENT_LIFETIME_AMOUNT_PAISE`

Desktop-specific:

- `DESKTOP_API_BASE`: API base URL used by Electron, default `http://127.0.0.1:8084/api`.
- `PAYMENT_SITE_URL`: external payment site URL opened by Electron.
- `ELECTRON_OPEN_DEVTOOLS=1`: open detached DevTools on launch.

Payment website-specific:

- `VITE_API_BASE`: API base URL used by Vite dev/build, default `/api`.

## Backend Development

The backend app is registered in `backend/app/main.py`. Routers are mounted with `/api` prefixes:

- `GET /api/health`
- `/api/auth`
- `/api/account`
- `/api/billing`
- `/api/onboarding`
- `/api/generate`
- `/api/chats`
- `/api/jobs`
- `/api/knowledge`
- `/api/assets`
- `/api/playground`

Configuration lives in `backend/app/core/config.py`. Database setup lives in `backend/app/core/database.py`. SQLAlchemy models live in `backend/app/models.py`; Pydantic schemas live in `backend/app/schemas.py`.

When adding a backend feature:

1. Add or update schemas in `backend/app/schemas.py`.
2. Add model fields or tables in `backend/app/models.py` if persistence is needed.
3. Add service logic under `backend/app/services/` when behavior is shared or stateful.
4. Add route handlers under `backend/app/routers/`.
5. Register a new router in `backend/app/main.py` if needed.
6. Add focused tests under `tests/`.

There is no migration system in this repo currently. `init_database()` creates tables from the models at startup, so schema changes may require local volume recreation during development.

## Pipeline Development

The pipeline CLI entry point is `final_pipeline/main.py`.

Main stages:

1. `topic_discovery_agent`
2. `research_agent`
3. `script_agent`
4. `validation_agent`
5. `audio_agent`
6. `caption_agent`
7. `timed_visual_agent`
8. `asset_agent`
9. `music_agent`
10. `render_agent`
11. `thumbnail_agent`
12. `final_output`

Stage inputs, outputs, events, and errors are written below each run directory:

```text
logs/
errors/
intermediate/
output/
```

Run the pipeline through the playground wrapper:

```bash
bash playground/run_pipeline.sh --topic "haunted school hallway" --genre scary_stories --duration 30
```

Run the pipeline directly:

```bash
cd final_pipeline
MODULARSHORTS_DATA_DIR=../backend/data/pipeline MODULARSHORTS_RUNS_DIR=../backend/data/pipeline/runs python3 main.py --topic "Why ships disappear in fog" --genre history_facts --duration 45
```

Rerender from existing artifacts:

```bash
cd final_pipeline
python3 rerun_render.py --run-dir ../backend/data/pipeline/runs/run_YYYYMMDD_HHMMSS --assets-json path/to/assets.json --audio-json path/to/audio.json --captions-json path/to/captions.json
```

When changing a stage:

- Keep stage output schemas compatible with downstream stages.
- Preserve stage log names because the jobs API maps progress and retry behavior from those names.
- Add or update tests when a stage contract changes.
- Prefer shared modules under `final_pipeline/modules/` for reusable rendering, audio, asset, LLM, and safety behavior.

## Frontend Development

Desktop app:

```bash
cd desktop_app
npm run build
npm start
```

Payment website:

```bash
cd payment_website
npm run build
npm run dev
```

Playground UI:

```bash
cd playground/ui
npm run build
npm run dev
```

All three frontend packages use Vite, React, TypeScript, and local package lockfiles. Install dependencies separately in each package directory.

## API Workflows

Create an account:

```bash
curl -X POST http://localhost:8084/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123","display_name":"Dev"}'
```

Log in:

```bash
curl -X POST http://localhost:8084/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123"}'
```

Generate a video with a bearer token and active entitlement:

```bash
curl -X POST http://localhost:8084/api/generate \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"genre_id":"scary_stories","topic":"haunted school hallway","settings":{"duration":30,"voice_speed":1,"caption_words":4,"image_count":8,"music_volume":0.18,"schedule":"now"}}'
```

Poll progress:

```bash
curl -H "Authorization: Bearer TOKEN" http://localhost:8084/api/jobs/JOB_ID/progress
```

Fetch stage logs:

```bash
curl -H "Authorization: Bearer TOKEN" http://localhost:8084/api/jobs/JOB_ID/stages/asset_agent/logs
```

## Testing

Run Python tests:

```bash
python3 -m pytest
```

Run a specific test file:

```bash
python3 -m pytest tests/test_billing.py
```

Run frontend type/build checks:

```bash
cd desktop_app
npm run build
```

```bash
cd payment_website
npm run build
```

```bash
cd playground/ui
npm run build
```

The backend Docker image installs Python dependencies from `backend/requirements.txt` with constraints from `backend/constraints.txt`.

## Static Data And Assets

Genres and reference scripts live under:

```text
backend/data/pipeline/genres/
backend/data/pipeline/reference_scripts/
backend/data/pipeline/niches/
```

Bundled music and sound effects live under:

```text
backend/data/pipeline/assets/music/
backend/data/pipeline/assets/sfx/
```

The static database is seeded at backend startup by `seed_pipeline_knowledge()`. Keep YAML and JSON files valid because startup reads them into the static database.

## Billing Development

Billing code is in:

```text
backend/app/routers/billing.py
backend/app/services/billing.py
tests/test_billing.py
```

Payment website checkout code is in:

```text
payment_website/src/api.ts
payment_website/src/App.tsx
```

For local Razorpay testing:

1. Set Razorpay env vars in `.env`.
2. Start `backend` and `payment_website`.
3. Expose the backend with a tunnel.
4. Configure Razorpay webhooks to `https://your-tunnel.example/api/billing/webhook`.
5. Watch backend logs while completing checkout.

## Common Development Tasks

Add a new genre:

1. Add a YAML file under `backend/data/pipeline/genres/`.
2. Add reference examples under `backend/data/pipeline/reference_scripts/` if needed.
3. Add or update niche profile data under `backend/data/pipeline/niches/` if the genre needs distinct strategy.
4. Restart the backend so static data is seeded.
5. Confirm the genre appears from `GET /api/onboarding/genres` and `GET /api/playground/genres`.

Add a new retryable stage:

1. Add the stage to the pipeline and logs.
2. Update stage labels and retry lists in `backend/app/routers/jobs.py`.
3. Update desktop UI retryable stage names in `desktop_app/src/App.tsx`.
4. Add tests for progress mapping or retry behavior.

Add a new provider key:

1. Update backend settings in `backend/app/core/config.py`.
2. Update account API key handling in `backend/app/services/api_keys.py`.
3. Update frontend provider lists in `desktop_app/src/App.tsx` and payment/account surfaces if needed.
4. Update docs and tests.

## Debugging Tips

Use API docs while the backend is running:

```text
http://localhost:8084/docs
```

Inspect service logs:

```bash
docker compose logs backend
docker compose logs worker
```

Inspect job stage artifacts on disk:

```text
backend/data/pipeline/runs/<run_id>/logs/<stage_name>/
```

Inspect databases:

```bash
docker compose up dbgate
```

Open `http://localhost:8082`.

If a code change looks correct but local data is stale, restart services first. Recreate volumes only when you deliberately want a clean database.

