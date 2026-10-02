"""Explicit download step. No audio is read; downloads are cached outside Git."""
from huggingface_hub import snapshot_download
from moonshine_voice import get_model_for_language, ModelArch
from runtime import MODEL, REVISION
print(snapshot_download(MODEL, revision=REVISION))
print(get_model_for_language('en', ModelArch.MEDIUM_STREAMING))
