"""WhatsApp channel through Twilio: one conversation per phone number, same assistant as the web chat.

Two ways to answer (WHATSAPP_MODO in .env):
- "twiml" (default): the answer goes in the webhook response itself. It is the only way that
  works on Twilio's trial / "Try it out" WhatsApp senders, where messages sent through the REST
  API need an approved template ("ContentSid Required"). Twilio cuts webhooks off after 15 s, so
  if the answer takes longer the person is asked to send any message ("ok") to receive it.
- "api": the webhook only acknowledges and the answer is sent later through the REST API.
  For a production WhatsApp Business sender, where free text is allowed within 24 h.

Configuration (.env):
    TWILIO_ACCOUNT_SID     Account SID (AC...)
    TWILIO_AUTH_TOKEN      Auth Token: validates Twilio signatures and sends messages
    TWILIO_WHATSAPP_FROM   Sender, e.g. whatsapp:+14155238886 (sandbox)
    PUBLIC_URL             Exact webhook URL configured in Twilio, e.g. https://abc.ngrok-free.app/whatsapp
    WHATSAPP_MODO          twiml (default) or api
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
# Twiml mode: answer within the webhook if ready before this; Twilio gives up at 15 s
SYNC_BUDGET_SECONDS = 12
STILL_WORKING = (
    "Lo estoy preparando, tardo un poco más de lo normal. "
    "Envíeme cualquier mensaje (por ejemplo, *ok*) en unos segundos y le respondo."
)
ERROR_TEXT = "Perdone, ha habido un problema al responderle. ¿Puede intentarlo otra vez?"

HELP_TEXT = (
    "Soy *Mi Voluntad*. Le explico cómo hacer su testamento con palabras sencillas.\n\n"
    "• Escríbame su duda, por ejemplo: _quiero hacer mi testamento_.\n"
    "• Puede enviarme una *foto* de un documento (por ejemplo, su testamento) y se lo explico.\n"
    "• Escriba *borrar* para empezar una conversación nueva.\n\n"
    "Sus datos personales se ocultan antes de consultar a la inteligencia artificial."
)


def empty_twiml() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def message_twiml(*texts: str) -> str:
    """TwiML answering with one WhatsApp message per text."""
    body = "".join(f"<Message>{escape(text)}</Message>" for text in texts)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


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
        self.mode = os.environ.get("WHATSAPP_MODO", "twiml").strip().lower()
        self.send = sender or self._twilio_send
        self.fetch_media = media_fetcher or self._twilio_fetch_media
        # phone number -> {"history": [...], "privacy_map": {...}}; the history is the masked one
        self.sessions: Dict[str, dict] = {}
        # twiml mode: phone number -> answer still being prepared {"done": Event, "parts": [...]}
        self.pending: Dict[str, dict] = {}
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
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client
            # Without a timeout a stuck request would block this person's conversation forever
            self._client = Client(self.account_sid, self.auth_token, http_client=TwilioHttpClient(timeout=30))
        self._client.messages.create(from_=self.from_number, to=to, body=body)

    def _twilio_fetch_media(self, url: str) -> bytes:
        import requests
        response = requests.get(url, auth=(self.account_sid, self.auth_token), timeout=30)
        response.raise_for_status()
        return response.content

    def purge_expired(self, max_age_seconds: float) -> int:
        """Forget conversations (history and correspondence table) unused for too long."""
        limit = time.time() - max_age_seconds
        expired = [n for n, s in list(self.sessions.items()) if s.get("last_seen", 0) < limit]
        for number in expired:
            self.sessions.pop(number, None)
            self.pending.pop(number, None)
        return len(expired)

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

        # Twiml mode: an answer that was too slow for the previous webhook is delivered now
        waiting = self.pending.get(number)
        if waiting is not None:
            if not waiting["done"].is_set():
                return message_twiml("Todavía lo estoy preparando. Escríbame de nuevo en unos segundos, por favor.")
            del self.pending[number]
            return message_twiml(*waiting["parts"])

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

        if self.mode == "api":
            threading.Thread(target=self._answer_by_api, args=(number, text, media), daemon=True).start()
            if media:
                return message_twiml("He recibido la foto. La estoy leyendo, deme un momento…")
            return empty_twiml()

        # Twiml mode: wait a little for the answer; if it is slower, keep it for the next message
        job = {"done": threading.Event(), "parts": []}

        def work():
            job["parts"] = self._answer_parts(number, text, media)
            job["done"].set()

        threading.Thread(target=work, daemon=True).start()
        if job["done"].wait(SYNC_BUDGET_SECONDS):
            return message_twiml(*job["parts"])
        self.pending[number] = job
        return message_twiml(STILL_WORKING)

    def _answer_by_api(self, number: str, text: str, media: Optional[tuple]) -> None:
        """Api mode, in background: compute the answer and send it through the REST API."""
        for part in self._answer_parts(number, text, media):
            try:
                self.send(number, part)
            except Exception as e:
                print(f"[whatsapp] {self._log_id(number)}: no se pudo enviar: {type(e).__name__}: {e}")
                return

    def _answer_parts(self, number: str, text: str, media: Optional[tuple]) -> List[str]:
        """Run the assistant for this person and return the answer as WhatsApp messages."""
        with self._lock_for(number):
            started = time.time()
            session = self.sessions.setdefault(number, {"history": [], "privacy_map": {}})
            session["last_seen"] = time.time()
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

                parts = split_message(to_whatsapp_format(result["answer"]))
                print(f"[whatsapp] {self._log_id(number)}: respuesta lista en {time.time() - started:.1f}s "
                      f"({len(parts)} mensaje(s), memoria {len(session['history'])} turnos)")
                return parts
            except Exception as e:
                # Never log the user's text or number
                print(f"[whatsapp] {self._log_id(number)}: error {type(e).__name__}: {e}")
                return [ERROR_TEXT]
