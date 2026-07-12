from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from mlx_worker import MLXWorkerService, MODEL_PATH
from parakeet_worker import PARAKEET_MODEL, ParakeetASRService
from session import SessionHub, TranscriptionSession


TRANSCRIPTION_ENGINE = os.getenv("TRANSCRIPTION_ENGINE", "gemma").lower()
worker = MLXWorkerService()
asr_worker = ParakeetASRService() if TRANSCRIPTION_ENGINE == "parakeet" else None
hub = SessionHub()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if asr_worker is not None:
        await asr_worker.start()
    if TRANSCRIPTION_ENGINE == "gemma":
        await worker.start()
    try:
        yield
    finally:
        if asr_worker is not None:
            await asr_worker.stop()
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
    return {
        "ok": True,
        "transcription_engine": TRANSCRIPTION_ENGINE,
        "asr_model": PARAKEET_MODEL if asr_worker is not None else None,
        "asr_state": asr_worker.status.state if asr_worker is not None else None,
        "translation_model": MODEL_PATH,
        "translation_state": "lazy" if TRANSCRIPTION_ENGINE == "parakeet" else "ready",
    }


@app.websocket("/")
async def websocket_root(websocket: WebSocket) -> None:
    await TranscriptionSession(
        websocket,
        worker,
        hub,
        transcription_engine=TRANSCRIPTION_ENGINE,
        asr_worker=asr_worker,
    ).run()


@app.websocket("/ws")
async def websocket_ws(websocket: WebSocket) -> None:
    await TranscriptionSession(
        websocket,
        worker,
        hub,
        transcription_engine=TRANSCRIPTION_ENGINE,
        asr_worker=asr_worker,
    ).run()
