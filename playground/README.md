# Playground

The playground is the test lane for pipeline changes. It uses the shared
`../final_pipeline` code and the same backend database as the desktop app.
The database stores run and agent-stage snapshots; large artifacts such as
videos, images, and logs remain on disk and are referenced from those records.

Run the shared pipeline against playground data:

```bash
bash playground/run_pipeline.sh --topic "haunted school hallway" --genre scary_stories --duration 30
```

The backend uses the same `../final_pipeline` implementation and points it at
`backend/data/pipeline` for production/runtime data.
