"""Standalone FastAPI entry point for X Content Studio."""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load backend-only secrets before importing modules that read configuration.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend.x_content import router as content_router

app = FastAPI(title="X Content Studio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(content_router)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "x-content-studio"}
