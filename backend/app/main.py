from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import SessionLocal, init_database
from app.routers import auth, chats, generation, health, jobs, knowledge, onboarding
from app.services.knowledge_seed import seed_pipeline_knowledge


settings = get_settings()
app = FastAPI(title="DesktopApp Video Pipeline API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_database()
    db = SessionLocal()
    try:
        seed_pipeline_knowledge(db)
    finally:
        db.close()


app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")
app.include_router(generation.router, prefix="/api")
app.include_router(chats.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
