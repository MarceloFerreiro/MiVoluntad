"""Reconocimiento de voz local con Whisper (faster-whisper): el audio nunca sale del equipo.

El texto transcrito vuelve al navegador para que la persona lo revise y, al enviarlo, pasa por
la seudonimización como cualquier otro mensaje. El audio se borra nada más transcribirlo.

Modelo: WHISPER_MODEL en .env (por defecto "small": ~2,5 s para 11 s de audio en CPU y
transcripción perfecta en nuestras pruebas; "medium" es ~3 veces más lento).
"""
import os
import tempfile
import threading
from typing import Optional

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # ~10 min de opus; de sobra para un mensaje hablado
EXTENSIONS = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
              "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/aac": ".aac"}

_model = None
_lock = threading.Lock()


def model_name() -> str:
    return os.environ.get("WHISPER_MODEL", "small")


def get_model():
    """Load Whisper once (the first time it downloads ~0.5 GB for 'small')."""
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(model_name(), device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    return _model


def preload_in_background() -> None:
    """Load the model while the server starts, so the first message is not slow."""
    threading.Thread(target=get_model, daemon=True).start()


def transcribir(audio: bytes, content_type: Optional[str] = None) -> str:
    """Spanish transcription of a short recording (webm/opus from Chrome, mp4 from Safari, etc.)."""
    if not audio:
        raise ValueError("El audio está vacío")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("La grabación es demasiado larga")
    suffix = EXTENSIONS.get((content_type or "").split(";")[0].strip(), ".webm")
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(audio)
        tmp.flush()
        segments, _ = get_model().transcribe(tmp.name, language="es", vad_filter=True, beam_size=1)
        return " ".join(segment.text.strip() for segment in segments).strip()
