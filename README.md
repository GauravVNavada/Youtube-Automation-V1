# DesktopApp

DesktopApp is our calibrated YouTube Shorts studio. It combines an Electron frontend, FastAPI backend, master-agent chat routing, queue workers, and a local FFmpeg generation pipeline to turn conversational prompts into preview-ready vertical videos.

For the full system design, see [architecture.md](architecture.md). For environment variables and provider setup, see [configuration.md](configuration.md).

## Services

- `frontend`: Electron desktop UI with setup, calibration, continuous chat, previews, downloads, and feedback memory.
- `backend`: FastAPI API for auth, onboarding, encrypted API keys, chats, master-agent routing, jobs, and knowledge records.
- `worker`: RQ worker pool that consumes production video jobs and runs `backend/pipeline`.
- `playground-api`: isolated experiment API that runs `playground/pipeline` before production promotion.
- `nginx`: local reverse proxy for `/api` and `/playground/`.
- `db`: production Postgres for users, chats, messages, jobs, calibration, and feedback.
- `playground-db`: separate Postgres for playground runs and agent-stage inspection.
- `redis`: queue backend for asynchronous production rendering.

## Setup

1. Copy `.env.example` to `.env`.
2. Put your Google TTS service account at `secrets/google-tts.json`.
3. Fill in at least one LLM key and asset API key in `.env`.
4. Start the stack:

```bash
docker compose up --build
```

Start the backend stack, then run or package the desktop app:

```bash
cd frontend
npm install
npm run desktop
```

To install a Linux app launcher after packaging:

```bash
npm run desktop:pack
npm run desktop:install:linux
```

To create Linux release artifacts:

```bash
npm run desktop:dist:linux
```

For a Windows installer from a Windows machine:

```bash
npm run desktop:dist:win
```

On Linux, the Windows installer target requires Wine. Without Wine, use the unpacked Windows build below.

For an unpacked Windows `.exe` folder without creating an installer:

```bash
npm run desktop:pack:win
```

For a Windows user-friendly `.zip` package:

```bash
npm run desktop:zip:win
```

The desktop app talks to `http://localhost:8080/api` by default. Override it with `DESKTOPAPP_API_BASE`.

## Product Flow

The desktop app follows this production flow:

```text
Login/signup
-> API setup
-> genre + creator intent
-> 3 calibration videos
-> pick preferred style
-> continuous video chat
-> master extracts route/settings
-> worker renders
-> preview/download
-> save feedback memory
```

After calibration, every prompt goes through the master agent. If you say "make the voice faster" after a previous render, the backend keeps the selected style and latest video context, extracts only the new change, and queues an updated job with the right parent video/settings.

License purchase and YouTube channel connection are intentionally skipped in this version. Preview/download is the production-safe output flow. API keys can be entered in the app and are stored encrypted; `.env` keys are fallback configuration. Feedback saved after preview is injected into later generations so repeated mistakes are avoided.

## Pipeline Workflow

There are two pipeline copies on purpose:

- `playground/pipeline`: experiment copy. Make future pipeline changes here first.
- `backend/pipeline`: production copy. Promote changes here only after the playground run works.

The playground API builds from `playground/pipeline`, while production backend/worker images build from `backend/pipeline`. This keeps experiments from accidentally changing production behavior.

Recommended workflow:

1. Change `DesktopApp/playground/pipeline`.
2. Rebuild and test `playground-api`.
3. Inspect the playground graph, logs, artifacts, and rendered video.
4. Promote the proven change into `DesktopApp/backend/pipeline`.
5. Rebuild `backend` and `worker`.

The current generation method is a free-first growth pipeline: discovery and research enrich the topic before scripting, the asset agent keeps image fallbacks for every cue and prefers Pexels stock video b-roll when available, and the thumbnail agent creates both a Shorts cover and a 16:9 YouTube thumbnail after render. The FFmpeg renderer preserves cue order, uses clips first, and falls back to matching images for resilient renders.

This app targets YouTube Shorts-style generation with managed LLM providers, optional Google TTS narration, free EdgeTTS fallback, local Whisper alignment, and local preview/download. Pexels and Pixabay keys improve visuals but are no longer required for the desktop setup gate.

## LLM Setup

The API setup screen supports four online LLM providers:

- OpenAI / ChatGPT
- Claude / Anthropic
- Gemini
- Groq

Choose a provider, choose a model version, paste the API key, then press Enter or `Save + Test LLM`. The backend validates the selected key/model with a tiny provider request. User-saved keys override `.env` keys for that user's video jobs.

## Database UI

Open Adminer at `http://localhost:8081` after Docker Compose starts.

- System: `PostgreSQL`
- Server: `db`
- Username/password/database: use the values from `.env`

## Scaling Workers

The worker container starts `WORKER_CONCURRENCY=3` worker processes by default. That lets the 3 calibration samples render in parallel instead of one after another.

Lower it on smaller machines or raise it on stronger machines:

```bash
WORKER_CONCURRENCY=2 docker compose up
```

Individual video stages still run in dependency order, but separate jobs are parallelized across worker processes.
