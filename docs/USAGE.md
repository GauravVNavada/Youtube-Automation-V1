# Usage Guide

This project packages a paid desktop studio for generating short-form videos, plus a payment website and a pipeline playground.

## What You Can Run

- Desktop studio: `desktop_app/`, an Electron app for signed-in paid users.
- Payment website: `payment_website/`, a React site for signup, login, Razorpay checkout, and entitlement status.
- Backend API: `backend/`, a FastAPI service that handles auth, billing, jobs, static assets, chats, onboarding, and playground runs.
- Worker: an RQ worker that runs video generation jobs through `final_pipeline/`.
- Playground: `playground/ui/`, a React interface for testing pipeline stages and rerunning stage snapshots.
- Database viewer: DbGate on top of the user, static-assets, and playground Postgres databases.

## Requirements

- Docker and Docker Compose.
- Node.js and npm for the React/Electron apps.
- Python 3.10 if running the pipeline directly outside Docker.
- FFmpeg if running the pipeline directly outside Docker.
- At least one LLM provider key for real generation. The app supports Gemini, Groq, OpenAI-compatible, and Anthropic configuration paths.
- Optional stock media keys: Pexels, Pixabay, Unsplash.
- Optional Google Text-to-Speech service account JSON for Google TTS. Without it, the pipeline can fall back to other audio paths where supported by the code.
- Razorpay credentials for live payment flows.

## First-Time Setup

Create a local env file from the sample:

```bash
cp .env.example .env
```

Edit `.env` and set the values you need:

```text
JWT_SECRET=replace-with-a-long-random-secret
GEMINI_API_KEY=...
GROQ_API_KEY=...
PEXELS_API_KEY=...
PIXABAY_API_KEY=...
UNSPLASH_ACCESS_KEY=...
GOOGLE_TTS_CREDENTIALS=/app/secrets/google-tts.json
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
PAYMENT_MONTHLY_PLAN_ID=...
PAYMENT_YEARLY_PLAN_ID=...
```

For Google TTS in Docker, place the service account file at:

```text
secrets/google-tts.json
```

The Docker compose file mounts `./secrets` into `/app/secrets`.

## Start The Main App

Start the backend, worker, databases, Redis, and payment website:

```bash
docker compose up --build backend worker payment_website
```

The important local URLs are:

- Backend API: `http://localhost:8084/api`
- API health check: `http://localhost:8084/api/health`
- API docs: `http://localhost:8084/docs`
- Payment website: `http://localhost:3001`

In a second terminal, start the desktop app:

```bash
cd desktop_app
npm install
npm start
```

`npm start` builds the desktop UI and launches Electron. By default the desktop app talks to `http://127.0.0.1:8084/api` and opens the payment site at `http://localhost:3001`.

To override those endpoints:

```bash
cd desktop_app
DESKTOP_API_BASE=http://127.0.0.1:8084/api PAYMENT_SITE_URL=http://localhost:3001 npm start
```

## Sign Up And Unlock Desktop Access

1. Open the desktop app.
2. Create an account or log in.
3. If the account is unpaid, choose the payment link from the locked screen.
4. Complete checkout on the payment website.
5. Return to the desktop app and refresh access.

Successful checkout verification grants access immediately. Webhooks keep subscription status synced after that.

For local webhook testing, expose the backend with a tunnel and configure Razorpay to send webhooks to:

```text
https://your-tunnel.example/api/billing/webhook
```

## Configure API Keys In The App

After login, use the app settings/profile area to save provider keys and model choices. The backend also reads provider defaults from `.env`, so local development can work before a user saves keys.

Common providers:

- `gemini`: default model `gemini-2.5-flash`
- `groq`: default model `openai/gpt-oss-20b`
- `openai`: model supplied by the user or env
- `anthropic`: default model `claude-3-5-sonnet-latest`
- `pexels`, `pixabay`, `unsplash`: stock media search
- `google_tts`: path to credentials JSON

## Generate A Video From The Desktop App

1. Make sure Docker services are running:

   ```bash
   docker compose up backend worker
   ```

2. Open the desktop app:

   ```bash
   cd desktop_app
   npm start
   ```

3. Log in with an active entitlement.
4. Complete onboarding if prompted.
5. Enter a topic, choose a genre, and adjust generation settings.
6. Start generation.
7. Watch job progress by stage.
8. Download or preview the generated video when the job succeeds.

Generation settings are clamped by the backend:

- Duration: 15 to 120 seconds.
- Voice speed: 0.75 to 1.4.
- Caption words per phrase: 1 to 10.
- Image count: 3 to 24.
- Music volume: 0.0 to 0.8.

## Job Outputs

Docker stores generated user pipeline output under:

```text
backend/data/pipeline/runs/
```

Each run directory contains:

- `logs/`: stage logs, inputs, outputs, and events.
- `errors/`: error records.
- `intermediate/`: intermediate artifacts.
- `output/`: final video and deliverables such as thumbnails and render plans.

The jobs API exposes these files through authenticated endpoints:

- `GET /api/jobs/{job_id}/preview`
- `GET /api/jobs/{job_id}/download`
- `GET /api/jobs/{job_id}/shorts-cover`
- `GET /api/jobs/{job_id}/youtube-thumbnail`
- `GET /api/jobs/{job_id}/render-plan`

## Retry A Failed Stage

The desktop app supports stage retry for retryable pipeline stages. The API endpoint is:

```text
POST /api/jobs/{job_id}/retry
```

Payload:

```json
{
  "stage_name": "asset_agent",
  "notes": "Try a more literal visual direction."
}
```

Leave `stage_name` empty to retry the whole job. Stage retry reuses upstream artifacts from the parent run where possible.

## Use The Payment Website In Development

Run the website through Docker with the backend:

```bash
docker compose up --build backend payment_website
```

Or run Vite directly:

```bash
cd payment_website
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5175`. Set `VITE_API_BASE` if the API is not available at `/api` through your current serving setup:

```bash
cd payment_website
VITE_API_BASE=http://localhost:8084/api npm run dev
```

## Use The Playground

The playground is for testing the shared pipeline without mixing test data into desktop user data.

Start the backend and database services:

```bash
docker compose up --build backend worker
```

Build and serve the playground UI through Docker/nginx:

```bash
cd playground/ui
npm install
npm run build
cd ../..
docker compose up playground_ui
```

Open:

```text
http://localhost:3000/playground
```

For local Vite development:

```bash
cd playground/ui
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

The playground UI calls `/api/playground`, so use the Docker/nginx route or configure a proxy if you run it outside the compose setup.

## Run The Pipeline Directly

Direct pipeline execution is useful for debugging generation without auth, billing, or RQ.

Install Python dependencies first:

```bash
cd backend
python3 -m pip install -r requirements.txt
```

Run against playground data:

```bash
bash playground/run_pipeline.sh --topic "haunted school hallway" --genre scary_stories --duration 30
```

Run from `final_pipeline/` directly:

```bash
cd final_pipeline
MODULARSHORTS_DATA_DIR=../backend/data/pipeline MODULARSHORTS_RUNS_DIR=../backend/data/pipeline/runs python3 main.py --topic "Why ships disappear in fog" --genre history_facts --duration 45
```

Useful CLI options:

- `--topic`: required topic or prompt.
- `--genre`: genre id such as `scary_stories`, `reddit_stories`, `history_facts`, or `comics`.
- `--duration`: target duration in seconds.
- `--notes`: style or content notes.
- `--voice-speed`: narration speed multiplier.
- `--caption-words`: words per caption phrase.
- `--image-count`: target visual variety count.
- `--music-path`: explicit background music path.
- `--music-volume`: background music volume.
- `--visual-motion`: `on` or `off`.
- `--transition-style`: `slide`, `fade`, `wipe`, or `cut`.
- `--transition-seconds`: transition duration.
- `--zoom-variant`: `mixed`, `center_in`, `center_out`, or `still`.

## View Databases

Start DbGate:

```bash
docker compose up dbgate
```

Open:

```text
http://localhost:8082
```

Configured connections:

- User database: accounts, chats, jobs, onboarding, calibration, feedback.
- Static assets database: genres, reference examples, static assets.
- Playground database: playground runs and stage snapshots.

## Build Distributables

Build the desktop app:

```bash
cd desktop_app
npm install
npm run build
```

Package an unpacked desktop build:

```bash
npm run desktop:pack
```

Build Linux packages:

```bash
npm run desktop:dist:linux
```

Build Windows zip:

```bash
npm run desktop:dist:win
```

Artifacts are written under `desktop_app/release/`.

## Troubleshooting

Backend is not reachable:

```bash
docker compose ps
docker compose logs backend
```

Worker is not processing queued jobs:

```bash
docker compose logs worker
docker compose logs redis
```

Desktop says API is down:

- Confirm `http://localhost:8084/api/health` works.
- Confirm `DESKTOP_API_BASE` points at the `/api` base URL.
- Restart Electron after changing env vars.

Checkout does not unlock access:

- Confirm Razorpay key, secret, webhook secret, and plan ids are set.
- Confirm the payment website points to the backend API.
- Confirm webhooks target `/api/billing/webhook`.

Pipeline fails during AI setup:

- Confirm at least one LLM provider key is set in `.env` or saved for the account.
- Check the stage logs through the desktop UI or `GET /api/jobs/{job_id}/stages/llm_provider/logs`.

Stock media is weak or missing:

- Set `PEXELS_API_KEY`, `PIXABAY_API_KEY`, or `UNSPLASH_ACCESS_KEY`.
- Add local static assets through the app or place assets in the configured static asset roots.

Google TTS fails:

- Confirm `secrets/google-tts.json` exists.
- Confirm `.env` has `GOOGLE_TTS_CREDENTIALS=/app/secrets/google-tts.json` for Docker.

