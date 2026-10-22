import os
from flask import Flask, request, abort
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
app = Flask(__name__)


# ===================== CLAVES / CONFIG =====================
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "SK364429ad15cae83b5ec9528c077d0a02")   # RELLENA (variable de entorno)
CHATBOT_API_KEY   = os.environ.get("CHATBOT_API_KEY", "")     # RELLENA (variable de entorno)
PUBLIC_URL        = os.environ.get("PUBLIC_URL", "")          # RELLENA: https://abc123.ngrok-free.app/whatsapp
VALIDAR_FIRMA     = True   # comprueba que las peticiones vienen de Twilio

# ===================== 1) PRIVACY FILTER =====================
# Carga el modelo UNA vez aquí arriba, no dentro de la función
# (si no, cada mensaje tardará demasiado y Twilio dará timeout).


# Se crea UNA vez al arrancar, no en cada mensaje
_configuracion = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "es", "model_name": "es_core_news_md"}],
}
_nlp = NlpEngineProvider(nlp_configuration=_configuracion).create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp, supported_languages=["es"])

# Qué tipos de dato enmascarar. AJUSTA según lo que veas con get_supported_entities
ENTIDADES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE",
    "CREDIT_CARD", "URL", "IP_ADDRESS",
     "ES_NIF", "ES_NIE", "LOCATION"   # actívalos si aparecen en tu versión y te interesan
]

def detectar_pii(texto: str) -> list[dict]:
    resultados = _analyzer.analyze(
        text=texto,
        language="es",
        entities=ENTIDADES,
        score_threshold=0.4,    # baja = más enmascarado; sube = menos falsos positivos
    )
    return [{"start": r.start, "end": r.end, "label": r.entity_type} for r in resultados]
print(_analyzer.get_supported_entities(language="es"))


# ===================== 2) MÁSCARA REVERSIBLE =====================
class Mascara:
    """Sustituye datos por etiquetas ([PERSON_1]) y guarda la tabla para revertirlas."""
    def __init__(self):
        self.tag_por_valor = {}   # (label, valor) -> "[PERSON_1]"
        self.valor_por_tag = {}   # "[PERSON_1]" -> valor original
        self.contador = {}

    def enmascarar(self, texto: str) -> str:
        spans = sorted(detectar_pii(texto), key=lambda s: (s["start"], -s["end"]))
        limpios, fin = [], -1
        for s in spans:                      # descarta solapes
            if s["start"] >= fin:
                limpios.append(s)
                fin = s["end"]

        salida, pos = [], 0
        for s in limpios:
            valor = texto[s["start"]:s["end"]]
            label = str(s["label"]).upper().replace(" ", "_")
            clave = (label, valor)
            if clave not in self.tag_por_valor:
                n = self.contador.get(label, 0) + 1
                self.contador[label] = n
                tag = f"[{label}_{n}]"
                self.tag_por_valor[clave] = tag
                self.valor_por_tag[tag] = valor
            salida.append(texto[pos:s["start"]])
            salida.append(self.tag_por_valor[clave])
            pos = s["end"]
        salida.append(texto[pos:])
        return "".join(salida)

    def desenmascarar(self, texto: str) -> str:
        for tag in sorted(self.valor_por_tag, key=len, reverse=True):
            texto = texto.replace(tag, self.valor_por_tag[tag])
        return texto

# ===================== 3) CHATBOT =====================
SYSTEM_PROMPT = (
    "Eres un asistente breve y amable. Responde en español. "
    "El texto puede contener etiquetas como [PERSON_1] o [EMAIL_1] que sustituyen "
    "datos personales. Cuando las uses en tu respuesta, escríbelas EXACTAMENTE igual, "
    "sin modificarlas ni inventar datos reales."
)

def llamar_chatbot(historial: list[dict]) -> str:
    """
    historial = [{"role": "user"/"assistant", "content": "..."}], ya enmascarado.
    Devuelve el texto de la respuesta (todavía enmascarado).
    """
    # RELLENA: llamada a tu chatbot usando CHATBOT_API_KEY y SYSTEM_PROMPT
    raise NotImplementedError

# ===================== 4) WEBHOOK DE TWILIO =====================
sesiones = {}   # número de WhatsApp -> {"mascara": Mascara(), "historial": [...]}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    if VALIDAR_FIRMA:
        validador = RequestValidator(TWILIO_AUTH_TOKEN)
        firma = request.headers.get("X-Twilio-Signature", "")
        if not validador.validate(PUBLIC_URL, request.form, firma):
            abort(403)

    numero = request.form.get("From", "")
    texto = request.form.get("Body", "").strip()
    resp = MessagingResponse()

    if not texto:
        resp.message("Solo puedo leer mensajes de texto.")
        return str(resp)

    ses = sesiones.setdefault(numero, {"mascara": Mascara(), "historial": []})

    try:
        # IDA: enmascarar antes de enviar al chatbot
        texto_enmascarado = ses["mascara"].enmascarar(texto)
        ses["historial"].append({"role": "user", "content": texto_enmascarado})

        respuesta_enmascarada = llamar_chatbot(ses["historial"][-10:])
        ses["historial"].append({"role": "assistant", "content": respuesta_enmascarada})

        # VUELTA: desenmascarar antes de mandarlo a WhatsApp
        respuesta = ses["mascara"].desenmascarar(respuesta_enmascarada)
    except Exception as e:
        print("Error:", repr(e))   # no imprimas el texto del usuario
        respuesta = "Ha habido un error, prueba otra vez."

    resp.message(respuesta[:1500])   # Twilio limita ~1600 caracteres
    return str(resp)

if __name__ == "__main__":
    app.run(port=5000)