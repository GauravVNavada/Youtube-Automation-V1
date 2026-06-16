# Backend Pipeline

This is the production copy used by DesktopApp backend and worker jobs.

Make future experimental pipeline changes in `DesktopApp/playground/pipeline` first. Once a playground run succeeds and the rendered video is good, promote the specific change into this folder for production jobs.

## Current Pipeline Shape

```text
Master route
-> Free topic discovery
-> Free research brief
-> Script JSON generation
-> Script validation and repair
-> Hybrid visual assets
-> Google TTS or EdgeTTS narration
-> Whisper word alignment
-> ASS/SRT captions
-> Render plan artifact
-> FFmpeg vertical render
-> Thumbnail generation
-> Validation and artifacts
```

Hybrid visuals mean the asset agent keeps image fallbacks for every cue and prefers Pexels stock video clips when available. The renderer normalizes every visual segment before transitions, then uses clips first and image fallbacks second.

The growth loop uses local niche profiles plus no-key web sources where available, then generates a vertical Shorts cover and a 16:9 YouTube thumbnail with Pillow. If discovery or research web calls fail, the pipeline continues with local profile/reference fallbacks.

ShortGPT-inspired free methods included in production:

- EdgeTTS is used as a free narrator fallback when Google TTS is not configured or fails.
- Bing image scraping is available as a no-key fallback after the existing visual providers.
- Downloaded images are copied into a reusable local asset cache under `data/assets/cache`.
- Each render writes `output/render_plan.json` so the final FFmpeg composition is inspectable.
- Fictional/comic/anime/superhero prompts are routed through a visual style plan. Famous IP names are rewritten into original-character wording, asset search becomes image-first with illustration terms, and Pexels stock video is skipped to avoid real-world footage.
- Script generation now requires header, mid, and footer sections. Validation rejects unrelated fact dumps and weak endings that feel like a pause, blackout, or direct stop before downstream agents run.
- Asset search now applies genre intent before ranking results. Known genres have seed profiles, custom/live genres infer a profile from genre metadata, and the asset agent can ask the configured LLM for a compact dynamic profile per run. If that AI profile fails, deterministic fallback scoring still keeps the pipeline running.
- FFmpeg output is forced to H.264 baseline, `yuv420p`, and `avc1` tagging after subtitles for better Electron preview compatibility.

## Promotion Rule

Do not edit this directory for experiments first. Promote only intentional, tested changes from:

```text
DesktopApp/playground/pipeline
```

After promotion, rebuild:

```bash
docker compose build backend worker
docker compose up -d backend worker
```
