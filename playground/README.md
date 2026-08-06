# Playground

The playground is the test lane for pipeline changes. It uses the shared
`../final_pipeline` code, but stores run and agent-stage snapshots in the
playground database so test data does not slow down desktop user data.

The backend now uses three databases:

- user database: accounts, chats, jobs, onboarding, calibration, feedback
- static database: `genres`, `reference_examples`, and `static_assets`
- playground database: playground run snapshots and stage payloads

The `genres` table stores the niche-intelligence profile for each genre:
hook patterns, forbidden phrases, visual style, topic rules, and retention
structure live in JSON columns so the static database stays easy to browse.

Large artifacts such as videos, images, audio, and logs remain on disk and are
referenced from database records.

View the databases in the browser:

```bash
docker compose up dbgate
```

Open `http://localhost:8082` and choose one of the preconfigured connections:
`User database`, `Static assets database`, or `Playground database`.

Run the shared pipeline against playground data:

```bash
bash playground/run_pipeline.sh --topic "haunted school hallway" --genre scary_stories --duration 30
```

The backend uses the same `../final_pipeline` implementation and points it at
`backend/data/pipeline` for production/runtime data.

Run the React playground UI:

```bash
cd playground/ui
npm install
npm run dev
```
