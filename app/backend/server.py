from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from mlx_worker import MLXWorkerService
from session import SessionHub, TranscriptionSession


worker = MLXWorkerService()
hub = SessionHub()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()


app = FastAPI(title="LiveTR3 Local Transcribe + Translate", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "model": "mlx-community/gemma-4-e4b-it-8bit"}


@app.websocket("/")
async def websocket_root(websocket: WebSocket) -> None:
    await TranscriptionSession(websocket, worker, hub).run()


@app.websocket("/ws")
async def websocket_ws(websocket: WebSocket) -> None:
    await TranscriptionSession(websocket, worker, hub).run()
