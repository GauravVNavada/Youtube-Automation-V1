# Playground

The playground is the experiment lane for DesktopApp video-generation changes.

Use it when you want to change agent prompts, asset retrieval, audio timing, caption logic, FFmpeg rendering, validation, or route constraints without touching the production backend pipeline first.

## What Runs Here

- `api/`: FastAPI service that stores playground runs, agent stages, logs, and artifacts.
- `ui/`: browser UI served at `/playground/` through nginx.
- `pipeline/`: isolated copy of the video generation pipeline used only by `playground-api`.

The playground has its own Postgres service (`playground-db`) and run artifact volume (`playground_runs`). Production jobs use the main `db`, `redis`, `backend`, `worker`, and `backend/pipeline` path instead.

## Development Rule

Future pipeline work starts here:

```text
edit playground/pipeline
-> rebuild playground-api
-> test through /playground/
-> inspect logs/artifacts/video
-> promote the proven change to backend/pipeline
-> rebuild backend + worker
```

This keeps experimental pipeline behavior out of production until the output is actually good.

## Docker

Rebuild only the playground API after playground pipeline edits:

```bash
docker compose build playground-api
docker compose up -d playground-api
```

Then open:

```text
http://localhost:8080/playground/
```

The playground API container still uses `PIPELINE_ROOT=/app/pipeline` internally, but that `/app/pipeline` is built from `DesktopApp/playground/pipeline`, not `DesktopApp/backend/pipeline`.
