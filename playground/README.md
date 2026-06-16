# Playground

The playground is the test lane for pipeline changes. It uses the shared
`../pipeline` code with playground-owned data from `data/pipeline`.

Run the shared pipeline against playground data:

```bash
bash playground/run_pipeline.sh --topic "haunted school hallway" --genre scary_stories --duration 30
```

The backend uses the same `../pipeline` implementation, but points it at
`backend/data/pipeline` for production/runtime data.
