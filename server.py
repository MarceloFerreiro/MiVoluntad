"""Servidor local del chat: sirve web/index.html y expone la API del asistente.

Uso: python server.py [--rebuild] [--host 0.0.0.0]  ->  abrir http://localhost:8000
     --host 0.0.0.0 permite entrar desde el móvil en la misma wifi: http://<IP del portátil>:8000
     WhatsApp (Twilio): POST /whatsapp, configuración en src/whatsapp.py y .env.example
     --rebuild extrae con OCR las fotos y PDFs nuevos de ocr/ a manuales/ y vuelve a
               indexar pdfs/, manuales/ y modelos/

El servidor no guarda conversaciones. El navegador envía, con cada mensaje,
el historial de la conversación abierta; así la memoria del asistente es
exactamente lo que el usuario ve en pantalla y cada conversación es independiente.

Fotos de documentos y mensajes: el OCR (Tesseract) y el enmascarado de datos
personales (regex españolas + Microsoft Presidio) se hacen aquí, en local. A Claude solo le llega texto con etiquetas ([PERSONA_1],
[DNI_1]...); el mapa etiqueta -> dato real se guarda en el navegador y se usa aquí
para restaurar la respuesta. El historial que se devuelve para la memoria va
también enmascarado.
"""
import argparse
import base64
import binascii
import builtins
import json
import os
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from dotenv import load_dotenv
from rich.console import Console

builtins.rich_console = Console()
builtins.verbose_mode = False

from src.LLMManager import LLMManager
from src.preprocessing.DocumentProcessor import DocumentProcessor
from src.preprocessing.ocr import ocr_image, tesseract_available
from src.privacy.pseudonymizer import Pseudonymizer
from src.rag.RAGSystem import RAGSystem
from src import notarias, voz
from src.borrador.cuestionario import BIENVENIDA
from src.borrador.pdf import generar_pdf
from src.privacy.store import RETENTION_DAYS, ConversationNotFound, EncryptedStore
from src.utils.sources import source_detail, source_label
from src.whatsapp import WhatsAppChannel

HOST, PORT = "127.0.0.1", 8000
MODEL = "claude-haiku-5-5"
# Answer models the person can choose in the web ("Modelo de IA"). The search decision always uses Haiku.
MODELOS = {
    "rapido": {"modelo": "claude-haiku-5-5", "nombre": "Rápido (recomendado)", "detalle": "Claude Haiku 5.5 · ~0,001 $ por mensaje"},
    "preciso": {"modelo": "claude-sonnet-5-5", "nombre": "Más preciso", "detalle": "Claude Sonnet 5.5 · unas 20 veces más caro"},
    "maximo": {"modelo": "claude-opus-5-5", "nombre": "Máxima calidad", "detalle": "Claude Opus 5.5 · unas 40 veces más caro"},
}
MODELO_POR_DEFECTO = "rapido"
# Reasoning effort for answers: "low" is the cheapest; "medium" is a bit more precise (~35% more cost)
EFFORT = "low"
MAX_HISTORY_TURNS = 30
# Model-based personal data detectors, besides our Spanish regex (DNI, address, cadastral ref.):
# Microsoft Presidio with Spanish recognizers and a given-name dictionary. See benchmarks/.
PRIVACY_NER = ("presidio",)
# "Dos tercios de legítima estricta" is wrong: the strict legitime is ONE third (art. 808 CC)
LEGITIMA_ERROR = re.compile(
    r"dos\s+tercios\s+(?:de\s+(?:la\s+)?)?leg[ií]tima\s+estricta|leg[ií]tima\s+estricta\W{0,6}\(?\s*dos\s+tercios",
    re.IGNORECASE,
)
# Below this the photo is not readable enough to give advice about it
MIN_OCR_WORDS, MIN_OCR_CONFIDENCE = 15, 45
ROOT = Path(__file__).parent
WEB = ROOT / "web"

rag = None
whatsapp = None
store = None
_llms = {}  # (modelo, uso) -> chat model, created on first use


def llm_for(choice, purpose: str = "chat"):
    """Chat model for a choice of MODELOS ("rapido", "preciso", "maximo")."""
    model = MODELOS.get(choice if isinstance(choice, str) else "", MODELOS[MODELO_POR_DEFECTO])["modelo"]
    key = (model, purpose)
    if key not in _llms:
        max_tokens = 4000 if purpose == "pdf" else 8000
        _llms[key] = LLMManager(model_name=model, max_tokens=max_tokens, effort=EFFORT).llm
    return _llms[key]
# RAGSystem keeps the history of the request being answered: one request at a time
rag_lock = threading.Lock()


def build_rag(rebuild: bool = False) -> RAGSystem:
    """Load the vector store and the models once at startup."""
    load_dotenv(ROOT / ".env")
    processor = DocumentProcessor(
        pdfs_folder=str(ROOT / "pdfs"),
        ocr_folder=str(ROOT / "ocr"),
        manuales_folder=str(ROOT / "manuales"),
        modelos_folder=str(ROOT / "modelos"),
        cache_dir=str(ROOT / ".doc_cache"),
        verbose=rebuild,
    )
    vectorstore_path = str(ROOT / "local_vectorstore")
    if (ROOT / "local_vectorstore").exists() and not rebuild:
        processor.load_vectorstore(vectorstore_path)
    else:
        processor.process()
        processor.save_vectorstore(vectorstore_path)

    return RAGSystem(
        vectorstore=processor.vectorstore,
        llm=llm_for(MODELO_POR_DEFECTO),
        llm_query=LLMManager(model_name=MODEL, max_tokens=2048).llm,
        k=8,
        state_dir=str(ROOT / ".doc_cache"),
        bm25_mode="hybrid",
        bm25_weight=0.5,
        bm25_index=processor.bm25_index,
        bm25_documents=processor.bm25_documents,
        max_history_length=MAX_HISTORY_TURNS,
        notary_lookup=notarias.buscar,
    )


def clean_history(raw) -> list:
    """Validate the turns sent by the browser: only complete question/answer pairs."""
    if not isinstance(raw, list):
        return []
    turns = []
    for turn in raw:
        if not isinstance(turn, dict):
            continue
        question, answer = turn.get("question"), turn.get("answer")
        if isinstance(question, str) and isinstance(answer, str) and question.strip() and answer.strip():
            turns.append({"question": question, "answer": answer})
    return turns[-MAX_HISTORY_TURNS:]


def decode_image(data) -> bytes:
    """Accept a data URL or plain base64 string from the browser."""
    if not isinstance(data, str) or not data:
        raise ValueError("La imagen no es válida")
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("La imagen no es válida")


def unreadable_photo(ocr) -> dict:
    """Answer without calling the LLM when the photo cannot be read."""
    return {
        "answer": (
            "No he podido leer bien la foto. Pruebe a hacer otra:\n\n"
            "1. Con buena luz, sin sombras ni brillos.\n"
            "2. Con el papel recto y entero dentro de la foto.\n"
            "3. Sin mover el móvil al disparar.\n\n"
            "Si el documento está escrito a mano, todavía no sé leerlo. En ese caso, puede contarme con sus palabras lo que dice."
        ),
        "in_memory": False,
        "sources": [],
        "cost": 0.0,
        "used_retrieval": False,
        "history_turns": 0,
        "document": {"confidence": round(ocr.confidence), "words": ocr.words, "masked_text": None},
    }


def chat(payload: dict) -> dict:
    """Answer one message (optionally with a document photo) given the history of its conversation."""
    message = payload.get("message") or ""
    image = payload.get("image")
    if not isinstance(message, str) or (not message.strip() and not image):
        raise ValueError("El mensaje está vacío")

    mapping = payload.get("privacy_map")
    pseudo = Pseudonymizer(mapping if isinstance(mapping, dict) else None, ner=PRIVACY_NER)

    document = None
    if image:
        if not tesseract_available():
            raise ValueError("El OCR no está instalado en el servidor (sudo apt install tesseract-ocr tesseract-ocr-spa)")
        ocr = ocr_image(decode_image(image))
        if ocr.words < MIN_OCR_WORDS or ocr.confidence < MIN_OCR_CONFIDENCE:
            return unreadable_photo(ocr)
        document = {"confidence": round(ocr.confidence), "words": ocr.words, "masked_text": pseudo.mask(ocr.text)}

    # What the person types: names already known from their documents, then every detector
    question = pseudo.mask(pseudo.mask_known(message.strip()))
    if document:
        question = (
            f"{question or 'Explíqueme este documento, por favor.'}\n\n"
            "<documento_aportado_por_la_persona>\n"
            f"{document['masked_text']}\n"
            "</documento_aportado_por_la_persona>"
        )

    with rag_lock:
        rag.set_llm(llm_for(payload.get("modelo")))
        history = clean_history(payload.get("history"))
        for attempt in range(2):
            rag.conversation_history.conversation_history = list(history)
            answer_masked, sources, cost = rag.query(question, use_history=True, return_costs=True)
            # Safety net for the most harmful known mistake (~1 in 9 answers in our tests):
            # if it slips in, discard the answer and ask again once
            if not LEGITIMA_ERROR.search(answer_masked):
                break
            print("[aviso] respuesta con el error de la legítima estricta: se repite")
        turns_seen = len(rag.conversation_history.conversation_history) - 1

    return {
        "answer": pseudo.restore(answer_masked),
        "in_memory": True,
        # Masked versions: what the browser must send back as history
        "history_question": question,
        "history_answer": answer_masked,
        "privacy_map": pseudo.mapping,
        "privacy_summary": pseudo.summary(),
        "document": document,
        "sources": [
            {
                "label": source_label(doc.metadata),
                "ruta": source_detail(doc.metadata),
                "texto": doc.page_content,
            }
            for doc in sources
        ],
        "cost": cost["total_cost"],
        "used_retrieval": cost["used_retrieval"],
        "history_turns": turns_seen,
    }


# ---------- Web: conversaciones cifradas en el servidor ----------

def _credentials(payload: dict) -> tuple:
    conversation_id, key = payload.get("conversation_id"), payload.get("key")
    if not isinstance(conversation_id, str) or not isinstance(key, str):
        raise ConversationNotFound("Falta la conversación")
    return conversation_id, key


def web_new_conversation(payload: dict) -> dict:
    """Create an encrypted conversation once the person accepts the privacy policy."""
    if payload.get("acepta_privacidad") is not True:
        raise ValueError("Hay que aceptar la política de privacidad para empezar")
    now = datetime.now().isoformat(timespec="seconds")
    conversation_id, key = store.create({"history": [], "privacy_map": {}, "consentimiento": now})
    return {"conversation_id": conversation_id, "key": key, "retention_days": RETENTION_DAYS}


def web_chat(payload: dict) -> dict:
    """Answer using the history and privacy map stored (encrypted) for this conversation."""
    conversation_id, key = _credentials(payload)
    state = store.load(conversation_id, key)
    result = chat({
        "message": payload.get("message") or "",
        "image": payload.get("image"),
        "modelo": payload.get("modelo"),
        "history": state["history"],
        "privacy_map": state["privacy_map"],
    })
    if result.get("in_memory", True) and result.get("history_question"):
        state["history"] = (state["history"] + [
            {"question": result["history_question"], "answer": result["history_answer"]}
        ])[-MAX_HISTORY_TURNS:]
    if result.get("privacy_map") is not None:
        state["privacy_map"] = result["privacy_map"]
    store.save(conversation_id, key, state)
    # The correspondence table never leaves the server. The masked texts (labels only) are
    # returned so the person can see exactly what the AI received
    result.pop("privacy_map", None)
    result["masked_question"] = result.pop("history_question", None)
    result["masked_answer"] = result.pop("history_answer", None)
    return result


def web_borrador(payload: dict) -> bytes:
    conversation_id, key = _credentials(payload)
    state = store.load(conversation_id, key)
    if not state["history"]:
        raise ValueError("Todavía no hay respuestas para el borrador. Cuénteme primero su situación.")
    return generar_pdf(llm_for(payload.get("modelo"), "pdf"), state["history"], state["privacy_map"])


def web_transcribe(payload: dict) -> dict:
    """Speech to text, locally. Only for an existing conversation (accepted privacy policy)."""
    conversation_id, key = _credentials(payload)
    store.load(conversation_id, key)
    data = payload.get("audio")
    if not isinstance(data, str) or not data.startswith("data:"):
        raise ValueError("Audio no válido")
    header, _, b64 = data.partition(",")
    content_type = header[5:].split(";base64")[0]
    try:
        audio = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Audio no válido")
    texto = voz.transcribir(audio, content_type)
    if not texto:
        raise ValueError("No he entendido nada. Pruebe a hablar un poco más cerca del móvil.")
    return {"texto": texto}


def web_delete(payload: dict) -> dict:
    ids = payload.get("conversation_ids") or []
    if not isinstance(ids, list):
        raise ValueError("Lista de conversaciones no válida")
    deleted = 0
    for conversation_id in ids:
        try:
            deleted += store.delete(str(conversation_id))
        except ConversationNotFound:
            pass
    return {"borradas": deleted}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path in ("/assets/logo.png", "/assets/favicon.png"):
            self._send(200, (WEB / self.path.lstrip("/")).read_bytes(), "image/png")
        elif self.path == "/privacidad":
            self._send(200, (WEB / "privacidad.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._send_json(200, {
                "bienvenida": BIENVENIDA, "retention_days": RETENTION_DAYS, "model": MODEL,
                "ocr": tesseract_available(), "notarias_google": bool(os.environ.get("GOOGLE_MAPS_API_KEY")),
                "modelos": [{"id": k, "nombre": v["nombre"], "detalle": v["detalle"]} for k, v in MODELOS.items()],
                "modelo_por_defecto": MODELO_POR_DEFECTO,
            })
        elif self.path == "/api/health":
            self._send_json(200, {"ok": True, "model": MODEL, "ocr": tesseract_available()})
        else:
            self._send_json(404, {"error": "No encontrado"})

    def _whatsapp(self):
        """Twilio webhook: validate the signature, acknowledge at once, answer in background."""
        if not whatsapp.configured:
            self._send(503, b"WhatsApp no configurado", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        params = {key: values[0] for key, values in form.items()}
        if not whatsapp.valid_signature(params, self.headers.get("X-Twilio-Signature", "")):
            self._send(403, b"Firma de Twilio no valida", "text/plain; charset=utf-8")
            return
        self._send(200, whatsapp.handle(params).encode("utf-8"), "text/xml; charset=utf-8")

    def do_POST(self):
        if self.path == "/whatsapp":
            self._whatsapp()
            return
        routes = {"/api/chat": web_chat, "/api/conversacion": web_new_conversation,
                  "/api/borrar": web_delete, "/api/borrador": web_borrador, "/api/transcribir": web_transcribe}
        if self.path not in routes:
            self._send_json(404, {"error": "No encontrado"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = routes[self.path](payload)
            if isinstance(result, bytes):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", 'attachment; filename="borrador_testamento.pdf"')
                self.send_header("Content-Length", str(len(result)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(result)
            else:
                self._send_json(200, result)
        except ConversationNotFound as e:
            self._send_json(404, {"error": f"{e}. Puede que se haya borrado o caducado: empiece una conversación nueva."})
        except (ValueError, json.JSONDecodeError) as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            builtins.rich_console.print_exception()
            self._send_json(500, {"error": f"Error del asistente: {e}"})

    def log_message(self, format, *args):
        if self.path.startswith("/api/chat"):
            builtins.rich_console.print(f"[dim]{self.address_string()} {format % args}[/dim]")


def lan_ip() -> str:
    """IP of this computer in the local network (no packet is actually sent)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    global rag, whatsapp, store
    parser = argparse.ArgumentParser(description="Servidor local del chat Mi Voluntad")
    parser.add_argument("--rebuild", action="store_true", help="OCR de las fotos y PDFs de ocr/ a manuales/ y volver a indexar pdfs/, manuales/ y modelos/")
    parser.add_argument("--host", default=HOST,
                        help="Dirección en la que escuchar. 0.0.0.0 = accesible desde otros dispositivos de la red (móvil). Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="Puerto. Default: 8000 (8443 con --https)")
    parser.add_argument("--https", action="store_true",
                        help="Servir por HTTPS con certs/ (necesario para el micrófono en el móvil). "
                             "Crear el certificado con scripts/crear_certificado.sh")
    args = parser.parse_args()

    print("Cargando el asistente (embeddings, índice y modelo)...")
    rag = build_rag(rebuild=args.rebuild)
    print(f"Cargando detectores de datos personales (regex + {' + '.join(PRIVACY_NER)})...")
    Pseudonymizer(ner=PRIVACY_NER).mask("Precarga de los modelos de privacidad.")
    print(f"Cargando el reconocimiento de voz local (Whisper {voz.model_name()}) en segundo plano...")
    voz.preload_in_background()
    store = EncryptedStore(str(ROOT / "data" / "conversaciones"))
    whatsapp = WhatsAppChannel(chat)

    def on_purge(removed):
        removed += whatsapp.purge_expired(RETENTION_DAYS * 24 * 3600)
        if removed:
            print(f"Borradas {removed} conversaciones con más de {RETENTION_DAYS} días sin uso")
    store.start_purge_thread(on_purge=on_purge)
    print(f"Conversaciones cifradas en data/conversaciones (borrado automático a los {RETENTION_DAYS} días sin uso)")
    if whatsapp.configured:
        print(f"WhatsApp activo (modo {whatsapp.mode}): webhook de Twilio en {whatsapp.public_url}")
    else:
        print("WhatsApp desactivado: faltan TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM o PUBLIC_URL en .env")

    port = args.port or (8443 if args.https else PORT)
    scheme = "https" if args.https else "http"
    server = ThreadingHTTPServer((args.host, port), Handler)
    if args.https:
        import ssl
        cert, key = ROOT / "certs" / "cert.pem", ROOT / "certs" / "key.pem"
        if not cert.exists():
            raise SystemExit("Falta el certificado: ejecute scripts/crear_certificado.sh")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Listo: abre {scheme}://localhost:{port} en el navegador (Ctrl+C para parar)")
    if args.host == "0.0.0.0":
        print(f"Desde el móvil (misma wifi): {scheme}://{lan_ip()}:{port}")
        if args.https:
            print("  La primera vez el navegador avisará del certificado: Configuración avanzada → Continuar")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado")


if __name__ == "__main__":
    main()
