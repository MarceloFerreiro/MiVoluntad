"""Almacén cifrado de conversaciones: historial enmascarado y tabla de correspondencia.

- Cada conversación se guarda en un archivo cifrado con AES-256-GCM.
- La clave la genera el servidor al crear la conversación, se entrega UNA vez al navegador
  y no se guarda en ningún sitio del servidor: sin la clave del usuario, el archivo no se
  puede leer (cifrado en reposo).
- Borrado bajo demanda (botón "Borrar mis datos") y automático tras RETENTION_DAYS días sin uso.
"""
import base64
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))


class ConversationNotFound(Exception):
    """The conversation does not exist (deleted or expired) or the key is wrong."""


class EncryptedStore:
    """Encrypted per-conversation state on disk, with deletion on demand and expiry."""

    def __init__(self, folder: str = "data/conversaciones", retention_days: int = RETENTION_DAYS):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = retention_days * 24 * 3600
        self._lock = threading.Lock()

    def _path(self, conversation_id: str) -> Path:
        if not (len(conversation_id) == 32 and all(c in "0123456789abcdef" for c in conversation_id)):
            raise ConversationNotFound("Identificador no válido")
        return self.folder / f"{conversation_id}.bin"

    @staticmethod
    def _key(key_b64: str) -> AESGCM:
        try:
            key = base64.urlsafe_b64decode(key_b64.encode())
        except (ValueError, AttributeError):
            raise ConversationNotFound("Clave no válida")
        if len(key) != 32:
            raise ConversationNotFound("Clave no válida")
        return AESGCM(key)

    def create(self, state: dict) -> tuple:
        """New conversation. Returns (conversation_id, key); the key is not kept on the server."""
        conversation_id = secrets.token_hex(16)
        key = base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()
        self.save(conversation_id, key, state)
        return conversation_id, key

    def save(self, conversation_id: str, key: str, state: dict) -> None:
        nonce = secrets.token_bytes(12)
        data = json.dumps(state, ensure_ascii=False).encode("utf-8")
        # The id is authenticated too: a file cannot be swapped for another conversation's
        ciphertext = self._key(key).encrypt(nonce, data, conversation_id.encode())
        path = self._path(conversation_id)
        tmp = path.with_suffix(".tmp")
        with self._lock:
            tmp.write_bytes(nonce + ciphertext)
            os.replace(tmp, path)

    def load(self, conversation_id: str, key: str) -> dict:
        path = self._path(conversation_id)
        if not path.exists():
            raise ConversationNotFound("La conversación no existe o ya se borró")
        blob = path.read_bytes()
        try:
            data = self._key(key).decrypt(blob[:12], blob[12:], conversation_id.encode())
        except InvalidTag:
            raise ConversationNotFound("Clave incorrecta")
        os.utime(path)  # last use, for the automatic expiry
        return json.loads(data)

    def delete(self, conversation_id: str) -> bool:
        """Delete a conversation (no key needed: the random 128-bit id is enough to own it)."""
        path = self._path(conversation_id)
        with self._lock:
            if path.exists():
                path.unlink()
                return True
        return False

    def purge_expired(self) -> int:
        """Delete conversations unused for longer than the retention period."""
        limit = time.time() - self.retention_seconds
        removed = 0
        with self._lock:
            for path in self.folder.glob("*.bin"):
                if path.stat().st_mtime < limit:
                    path.unlink()
                    removed += 1
        return removed

    def start_purge_thread(self, every_seconds: int = 3600, on_purge=None) -> None:
        """Purge expired conversations now and then every hour, in the background."""
        def loop():
            while True:
                removed = self.purge_expired()
                if on_purge:
                    on_purge(removed)
                time.sleep(every_seconds)
        threading.Thread(target=loop, daemon=True).start()
