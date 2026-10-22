"""WhatsApp channel through Twilio: one conversation per phone number, same assistant as the web chat.

Twilio cuts webhooks off after 15 seconds and our answers take longer (RAG + LLM, OCR for
photos), so the webhook only acknowledges the message and the answer is sent afterwards
with the Twilio REST API from a background thread.

Configuration (.env):
    TWILIO_ACCOUNT_SID     Account SID (AC...)
    TWILIO_AUTH_TOKEN      Auth Token: validates Twilio signatures and sends messages
    TWILIO_WHATSAPP_FROM   Sender, e.g. whatsapp:+14155238886 (sandbox)
    PUBLIC_URL             Exact webhook URL configured in Twilio, e.g. https://abc.ngrok-free.app/whatsapp
"""
import base64
import hashlib
import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional
from xml.sax.saxutils import escape

MAX_HISTORY_TURNS = 30
# WhatsApp messages through Twilio are limited to 1600 characters
MAX_MESSAGE_CHARS = 1500
RESET_COMMANDS = {"borrar", "nueva conversacion", "nueva conversación", "empezar de nuevo", "reiniciar"}
HELP_COMMANDS = {"ayuda", "menu", "menú"}

HELP_TEXT = (
    "Soy *Testamento Fácil*. Le explico cómo hacer su testamento con palabras sencillas.\n\n"
    "• Escríbame su duda, por ejemplo: _quiero hacer mi testamento_.\n"
    "• Puede enviarme una *foto* de un documento (por ejemplo, su testamento) y se lo explico.\n"
    "• Escriba *borrar* para empezar una conversación nueva.\n\n"
    "Sus datos personales se ocultan antes de consultar a la inteligencia artificial."
)


def empty_twiml() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def message_twiml(text: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(text)}</Message></Response>'


def to_whatsapp_format(markdown: str) -> str:
    """WhatsApp uses *bold* and _italic_; it has no headings or horizontal rules."""
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', markdown)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*(-{3,}|\*{3,})\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^(\s*)[-•]\s+', r'\1• ', text, flags=re.MULTILINE)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> List[str]:
    """Split a long answer into WhatsApp-sized messages, preferably between paragraphs."""
    parts, current = [], ""
    for paragraph in text.split("\n\n"):
        while len(paragraph) > limit:  # a single huge paragraph: cut at the last space
            cut = paragraph.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                parts.append(current)
                current = ""
            parts.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > limit:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


class WhatsAppChannel:
    """Keeps one conversation per phone number and answers through a chat function."""

    def __init__(
        self,
        chat_fn: Callable[[dict], dict],
        sender: Optional[Callable[[str, str], None]] = None,
        media_fetcher: Optional[Callable[[str], bytes]] = None,
    ):
        """Initialize the channel.

        Args:
            chat_fn: The assistant (server.chat): payload with message, image, history and
                privacy_map -> answer plus the masked history and the updated privacy map
            sender: send(to, body); defaults to the Twilio REST API
            media_fetcher: fetch(url) -> bytes for photos; defaults to an authenticated download
        """
        self.chat_fn = chat_fn
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.environ.get("TWILIO_WHATSAPP_FROM", "")
        self.public_url = os.environ.get("PUBLIC_URL", "")
        self.send = sender or self._twilio_send
        self.fetch_media = media_fetcher or self._twilio_fetch_media
        # phone number -> {"history": [...], "privacy_map": {...}}; the history is the masked one
        self.sessions: Dict[str, dict] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._client = None

    # ---------- configuration and Twilio ----------

    @property
    def configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number and self.public_url)

    def valid_signature(self, params: Dict[str, str], signature: str) -> bool:
        """Check that the request really comes from Twilio."""
        from twilio.request_validator import RequestValidator
        return RequestValidator(self.auth_token).validate(self.public_url, params, signature)

    def _twilio_send(self, to: str, body: str) -> None:
        if self._client is None:
            from twilio.rest import Client
            self._client = Client(self.account_sid, self.auth_token)
        self._client.messages.create(from_=self.from_number, to=to, body=body)

    def _twilio_fetch_media(self, url: str) -> bytes:
        import requests
        response = requests.get(url, auth=(self.account_sid, self.auth_token), timeout=30)
        response.raise_for_status()
        return response.content

    # ---------- incoming messages ----------

    def _lock_for(self, number: str) -> threading.Lock:
        """One message at a time per person, so answers keep their order."""
        with self._locks_guard:
            return self._locks.setdefault(number, threading.Lock())

    @staticmethod
    def _log_id(number: str) -> str:
        """Short pseudonymous id for logs: never print phone numbers."""
        return hashlib.sha256(number.encode()).hexdigest()[:8]

    def handle(self, params: Dict[str, str]) -> str:
        """Process a Twilio webhook (already validated). Returns the TwiML to answer right away."""
        number = params.get("From", "")
        text = (params.get("Body") or "").strip()
        num_media = int(params.get("NumMedia") or 0)

        if not number:
            return empty_twiml()
        if text.lower() in RESET_COMMANDS:
            self.sessions.pop(number, None)
            return message_twiml("Hecho. He borrado nuestra conversación y sus datos. ¿En qué le puedo ayudar?")
        if text.lower() in HELP_COMMANDS:
            return message_twiml(HELP_TEXT)

        media = None
        if num_media:
            content_type = params.get("MediaContentType0", "")
            if not content_type.startswith("image/"):
                return message_twiml(
                    "Por ahora solo sé leer *fotos* y mensajes de texto. "
                    "Si es un documento, hágale una foto y envíemela."
                )
            media = (params.get("MediaUrl0", ""), content_type)
        elif not text:
            return message_twiml("Solo puedo leer mensajes de texto y fotos.")

        threading.Thread(target=self._answer, args=(number, text, media), daemon=True).start()
        if media:
            return message_twiml("He recibido la foto. La estoy leyendo, deme un momento…")
        return empty_twiml()

    def _answer(self, number: str, text: str, media: Optional[tuple]) -> None:
        """Background: run the assistant and send the answer through the REST API."""
        with self._lock_for(number):
            started = time.time()
            session = self.sessions.setdefault(number, {"history": [], "privacy_map": {}})
            try:
                payload = {
                    "message": text,
                    "history": session["history"][-MAX_HISTORY_TURNS:],
                    "privacy_map": session["privacy_map"],
                }
                if media:
                    url, content_type = media
                    image = base64.b64encode(self.fetch_media(url)).decode()
                    payload["image"] = f"data:{content_type};base64,{image}"

                result = self.chat_fn(payload)

                if result.get("in_memory", True) and result.get("history_question"):
                    session["history"].append({
                        "question": result["history_question"],
                        "answer": result["history_answer"],
                    })
                    session["history"] = session["history"][-MAX_HISTORY_TURNS:]
                if result.get("privacy_map") is not None:
                    session["privacy_map"] = result["privacy_map"]

                for part in split_message(to_whatsapp_format(result["answer"])):
                    self.send(number, part)
                print(f"[whatsapp] {self._log_id(number)}: respondido en {time.time() - started:.1f}s "
                      f"(memoria {len(session['history'])} turnos)")
            except Exception as e:
                # Never log the user's text or number
                print(f"[whatsapp] {self._log_id(number)}: error {type(e).__name__}: {e}")
                try:
                    self.send(number, "Perdone, ha habido un problema al responderle. ¿Puede intentarlo otra vez?")
                except Exception as send_error:
                    print(f"[whatsapp] {self._log_id(number)}: no se pudo avisar del error: {send_error}")
