"""Servidor local del chat: sirve web/index.html y expone la API del asistente.

Uso: python server.py [--rebuild]  ->  abrir http://localhost:8000
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
import threading
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
from src.utils.sources import source_detail, source_label
from src.whatsapp import WhatsAppChannel

HOST, PORT = "127.0.0.1", 8000
MODEL = "claude-haiku-5-5"
# Reasoning effort for answers: "low" is the cheapest; "medium" is a bit more precise (~35% more cost)
EFFORT = "low"
MAX_HISTORY_TURNS = 30
# Model-based personal data detectors, besides our Spanish regex (DNI, address, cadastral ref.):
# Microsoft Presidio with Spanish recognizers and a given-name dictionary. See benchmarks/.
PRIVACY_NER = ("presidio",)
# Below this the photo is not readable enough to give advice about it
MIN_OCR_WORDS, MIN_OCR_CONFIDENCE = 15, 45
ROOT = Path(__file__).parent
WEB = ROOT / "web"

rag = None
whatsapp = None
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
        llm=LLMManager(model_name=MODEL, effort=EFFORT).llm,
        llm_query=LLMManager(model_name=MODEL, max_tokens=2048).llm,
        k=8,
        state_dir=str(ROOT / ".doc_cache"),
        bm25_mode="hybrid",
        bm25_weight=0.5,
        bm25_index=processor.bm25_index,
        bm25_documents=processor.bm25_documents,
        max_history_length=MAX_HISTORY_TURNS,
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
            "Documento aportado por la persona (foto leída por OCR, datos personales sustituidos por etiquetas):\n"
            f"<<<\n{document['masked_text']}\n>>>"
        )

    with rag_lock:
        rag.conversation_history.conversation_history = clean_history(payload.get("history"))
        answer_masked, sources, cost = rag.query(question, use_history=True, return_costs=True)
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
        if self.path != "/api/chat":
            self._send_json(404, {"error": "No encontrado"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._send_json(200, chat(payload))
        except (ValueError, json.JSONDecodeError) as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            builtins.rich_console.print_exception()
            self._send_json(500, {"error": f"Error del asistente: {e}"})

    def log_message(self, format, *args):
        if self.path.startswith("/api/chat"):
            builtins.rich_console.print(f"[dim]{self.address_string()} {format % args}[/dim]")


def main():
    global rag, whatsapp
    parser = argparse.ArgumentParser(description="Servidor local del chat Testamento Fácil")
    parser.add_argument("--rebuild", action="store_true", help="OCR de las fotos y PDFs de ocr/ a manuales/ y volver a indexar pdfs/, manuales/ y modelos/")
    args = parser.parse_args()

    print("Cargando el asistente (embeddings, índice y modelo)...")
    rag = build_rag(rebuild=args.rebuild)
    print(f"Cargando detectores de datos personales (regex + {' + '.join(PRIVACY_NER)})...")
    Pseudonymizer(ner=PRIVACY_NER).mask("Precarga de los modelos de privacidad.")
    whatsapp = WhatsAppChannel(chat)
    if whatsapp.configured:
        print(f"WhatsApp activo: webhook de Twilio en {whatsapp.public_url}")
    else:
        print("WhatsApp desactivado: faltan TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM o PUBLIC_URL en .env")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Listo: abre http://localhost:{PORT} en el navegador (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado")


if __name__ == "__main__":
    main()
