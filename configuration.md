# Configuration

DesktopApp reads configuration from `.env`, user-saved API keys, and Docker Compose environment variables. User-saved keys in the app override `.env` values for that user.

Use the managed LLM provider system already present in this project, optional Google TTS narration, EdgeTTS fallback, and local Whisper alignment.

## Required For Generation

| Variable | Description |
|---|---|
| One LLM key | Set one of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, or `LLM_API_KEY`. |

Google TTS, Pexels, and Pixabay are optional upgrades. Without them, the pipeline uses EdgeTTS for narration and free/no-key image fallbacks where possible.

## LLM Provider Variables

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `auto`, `openai`, `anthropic`, `gemini`, or `groq`. | `auto` |
| `LLM_API_KEY` | Generic LLM key. The app can infer provider from common key prefixes. | empty |
| `LLM_MODEL` | Generic model override for the selected provider. | provider default |
| `OPENAI_API_KEY` | OpenAI API key. | empty |
| `OPENAI_MODEL` | OpenAI model for master/script JSON generation. | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic API key. | empty |
| `ANTHROPIC_MODEL` | Anthropic model. | `claude-3-5-haiku-20241022` |
| `GEMINI_API_KEY` | Gemini API key. | empty |
| `GEMINI_MODEL` | Gemini model. | `gemini-2.5-flash` |
| `GROQ_API_KEY` | Groq API key. | empty |
| `GROQ_MODEL` | Groq model. | `openai/gpt-oss-20b` |

Compatibility aliases:

- `GEMINI_API_KEYS` is accepted as a comma-separated compatibility alias. The first key is used.
- `TTS_CREDENTIALS_PATH` is accepted as a compatibility alias for `GOOGLE_TTS_CREDENTIALS`.

Prefer the canonical names above for new deployments.

## Visual Assets

| Variable | Description |
|---|---|
| `PEXELS_API_KEY` | Enables Pexels image search and stock video b-roll. This is the preferred visual provider for the hybrid renderer. |
| `PIXABAY_API_KEY` | Enables Pixabay image fallback search. |

The asset agent always tries to keep an image fallback for each cue. If Pexels stock video clips are available, the renderer uses them first and falls back to the corresponding image when needed. Without visual provider keys, it still attempts free/no-key sources such as Openverse, Wikimedia, and Bing image search.

## Audio And Captions

| Variable | Description | Default |
|---|---|---|
| `GOOGLE_TTS_CREDENTIALS` | Google Cloud TTS service-account JSON path. | empty |
| `TTS_CREDENTIALS_PATH` | Compatibility alias for `GOOGLE_TTS_CREDENTIALS`. | empty |
| `EDGE_TTS_VOICE` | EdgeTTS voice used when Google TTS is not configured or fails. | `en-US-GuyNeural` |

Captions use local Whisper word alignment through `openai-whisper`. AssemblyAI is not required in the current DesktopApp pipeline.

## Runtime Services

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy DSN for the FastAPI backend. | Docker Compose sets Postgres DSN |
| `REDIS_URL` | Redis URL for RQ workers. | `redis://redis:6379/0` |
| `PIPELINE_ROOT` | Path to the pipeline inside the running service. Backend/worker images get `backend/pipeline`; playground images get `playground/pipeline`. | `/app/pipeline` in Docker |
| `PIPELINE_RUNS_DIR` | Directory for final backend/worker run artifacts. | `/app/pipeline/runs` in Docker |
| `PLAYGROUND_RUNS_DIR` | Directory for playground run artifacts. | `/app/playground-runs` |
| `WORKER_CONCURRENCY` | Number of worker processes started by the worker container. | `3` |
| `JWT_SECRET` | Secret used for auth tokens. Change in production. | `change-me-in-production` |
| `CORS_ORIGINS` | Allowed frontend origins. | `http://localhost:8080` |

## Docker Notes

Pipeline source is intentionally split:

- `DesktopApp/playground/pipeline` is for experiments.
- `DesktopApp/backend/pipeline` is for production jobs.

After changing `DesktopApp/playground/pipeline`, rebuild the playground API:

```bash
docker compose build playground-api
docker compose up -d playground-api
```

After promoting a proven change into `DesktopApp/backend/pipeline`, rebuild production backend/worker:

```bash
docker compose build backend worker
docker compose up -d backend worker
```

If Docker requires elevated permissions on your machine:

```bash
sudo docker compose build playground-api
sudo docker compose up -d playground-api

sudo docker compose build backend worker
sudo docker compose up -d backend worker
```

## Security Notes

- Do not paste API keys into chat messages or commit them into tracked files.
- If a key has appeared in chat, terminal output, screenshots, or source control, rotate it.
- User-saved API keys are encrypted in the database; `.env` keys are fallback configuration.
