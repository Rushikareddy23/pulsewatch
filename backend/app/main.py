from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import engine
from .routers import auth, monitors

app = FastAPI(title="PulseWatch API", version="1.0.0", root_path="")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# Everything is served under /api so CloudFront can route /api/* to the load balancer.
app.include_router(auth.router, prefix="/api")
app.include_router(monitors.router, prefix="/api")


@app.get("/api/health", tags=["ops"])
def health():
    with engine.connect() as c:
        c.execute(text("select 1"))
    return {"status": "ok"}
