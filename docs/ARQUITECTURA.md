# Arquitectura técnica

## Visión general

```
 Navegador (web/index.html)                          Servidor local (server.py, un solo proceso)
 ┌──────────────────────────┐   /api/conversacion   ┌──────────────────────────────────────────────┐
 │ consentimiento           │ ────────────────────► │ EncryptedStore (src/privacy/store.py)          │
 │ chat · 📎 foto · 📄 PDF   │   /api/chat           │   data/conversaciones/<id>.bin  AES-256-GCM   │
 │ 🗑️ borrar                 │ ────────────────────► │                                              │
 │ guarda: mensajes en       │   /api/borrador       │ chat():                                      │
 │ pantalla + id + clave     │ ────────────────────► │   OCR local (Tesseract) ─┐                    │
 └──────────────────────────┘   /api/borrar          │   Pseudonymizer ◄────────┘ (regex + Presidio) │
                                                     │   RAGSystem ──► Claude Haiku 5.5 (Anthropic)   │
 WhatsApp (Twilio) ──── /whatsapp ─────────────────► │      ▲ FAISS + BM25 (local_vectorstore/)       │
                                                     │      └ notarias.buscar (Nominatim, Google)     │
                                                     │   restore() → respuesta con datos reales       │
                                                     │ borrador/pdf.py → pdflatex → PDF               │
                                                     └──────────────────────────────────────────────┘
```

Todo corre en un portátil (CPU, sin GPU). Solo salen a internet: el texto **seudonimizado** hacia
Anthropic y, si se piden notarías, el nombre del municipio hacia Nominatim/Google.

## Módulos

| Ruta | Responsabilidad |
|---|---|
| `server.py` | Servidor HTTP (stdlib), rutas web y WhatsApp, orquesta OCR → privacidad → RAG |
| `src/rag/RAGSystem.py` | Decide si buscar, recupera fragmentos, responde con historial |
| `src/rag/query_optimizer.py` | Llamada barata que decide: no buscar / buscar con una consulta / `NOTARIAS: lugar` |
| `src/rag/HybridRetriever.py` | Combina FAISS (semántico) y BM25 (palabras exactas: «artículo 808») |
| `src/rag/system_prompt.py` | Prompt del sistema (brevedad, una pregunta por mensaje, de usted, sin emojis, solo fuentes oficiales), de búsqueda y de clasificación |
| `src/preprocessing/ley_loader.py` | Leyes BOE y DOUE troceadas por artículo |
| `src/preprocessing/text_folder_loader.py` | Manuales y modelos (pdf, txt, md, doc, docx) por página |
| `src/preprocessing/ocr.py` | OCR de fotos y PDFs escaneados (`python -m src.preprocessing.ocr`) |
| `src/preprocessing/DocumentProcessor.py` | Construye el índice: OCR → carga → embeddings → FAISS + BM25 |
| `src/LocalEmbeddings.py` | Embeddings locales `intfloat/multilingual-e5-base`, con caché |
| `src/privacy/pseudonymizer.py` | Detecta y enmascara datos personales; tabla reversible |
| `src/privacy/presidio_engine.py`, `nombres_es.py` | Microsoft Presidio en español + diccionario de nombres |
| `src/privacy/store.py` | Conversaciones cifradas, borrado bajo demanda y caducidad |
| `src/borrador/cuestionario.py` | Cuestionario (fuente única), bienvenida y esquema del borrador |
| `src/borrador/pdf.py` | Extracción estructurada + plantilla LaTeX + compilación |
| `src/notarias.py` | Colegio Notarial por comunidad + buscador oficial + Google Places (opcional) |
| `src/voz.py` | Reconocimiento de voz local (Whisper) |
| `src/whatsapp.py` | Canal de WhatsApp por Twilio (aparcado, ver más abajo) |

## Flujo de un mensaje (web)

1. El navegador envía `conversation_id`, `key`, el mensaje y, opcionalmente, una foto.
2. El servidor descifra el estado (historial enmascarado + tabla de correspondencia).
3. Si hay foto: OCR local; si no se lee bien (pocas palabras o confianza < 45 %), se responde sin IA.
4. Seudonimización del documento y del mensaje: `Marta` → `[PERSONA_3]`, DNI → `[DNI_1]`…
5. `RAGSystem.query`:
   - el clasificador decide: sin búsqueda, búsqueda (consulta reescrita) o `NOTARIAS: <lugar>`;
   - se recuperan 8 fragmentos (híbrido FAISS + BM25) o se consulta `notarias.buscar`;
   - Claude responde con el prompt del sistema, el historial completo (hasta 30 turnos) y los fragmentos.
   - **Dos canales separados**: el material recuperado (leyes, manuales, modelos, notarías) va dentro de
     las instrucciones del sistema, en `<material_de_consulta>` / `<datos_de_notarias>`, marcado como
     interno; el turno de la persona lleva solo lo que ella escribió (y su foto, en
     `<documento_aportado_por_la_persona>`). Así el modelo no lo confunde con texto pegado por la persona.
     El material recuperado nunca entra en el historial.
6. Red de seguridad: si la respuesta dice «dos tercios de legítima estricta», se descarta y se repite una vez.
7. Se restauran los datos reales, se cifra y guarda el estado, y se devuelve la respuesta. El historial
   enmascarado y la tabla **no** viajan al navegador.

## Interfaz web

- **Consentimiento**: la bienvenida (`BIENVENIDA` en `src/borrador/cuestionario.py`) se muestra con el botón
  «He leído y acepto»; sin aceptar no se puede escribir.
- **Respuestas rápidas**: si la respuesta del bot termina en una línea `Opciones: Sí / No`, la web la quita del
  texto y la muestra como botones grandes (solo en el último mensaje). Es el protocolo entre prompt e interfaz.
- **Ver lo que vio la IA**: cada mensaje (del usuario y del bot) tiene un botón, visible al pasar el ratón
  (siempre visible en móvil), que despliega su versión enmascarada.
- **Modo desarrollador**: con `?dev` en la URL se ven los fragmentos consultados, la memoria y el coste.
  Por defecto no se muestran: el usuario no debe ver el material interno (manuales, modelos).

## Voz

- **Hablar** (`src/voz.py`, `POST /api/transcribir`): el navegador graba con `MediaRecorder` (webm/opus en
  Chrome, mp4 en Safari) y el servidor transcribe con **Whisper local** (`faster-whisper`, modelo `small`,
  int8 en CPU): ~2,5 s para 11 s de audio, sin errores en nuestras pruebas (`medium`: ~6,6 s, igual
  resultado). El texto vuelve al cuadro de texto para revisarlo y, al enviarlo, se seudonimiza como cualquier
  mensaje. El audio no se guarda. Modelo configurable con `WHISPER_MODEL`.
- **Escuchar**: cada respuesta se puede oír con la síntesis de voz del propio dispositivo (`speechSynthesis`,
  voz `es-ES`); no se envía nada.
- **HTTPS**: el micrófono solo funciona en páginas seguras. `scripts/crear_certificado.sh` crea un certificado
  autofirmado para la IP actual y `python server.py --https` sirve en el puerto 8443.

## Borrador en PDF

`/api/borrador` → `borrador/pdf.py`:
1. Claude extrae de la conversación **enmascarada** las respuestas al esquema `Borrador` (Pydantic,
   salida estructurada por herramienta; `json_schema` no admite tantos campos opcionales).
2. Se restauran los datos reales con la tabla, en local.
3. Se rellena la plantilla LaTeX. **Todo** texto del usuario pasa por `latex_escape` (nadie puede
   inyectar comandos) y `pdflatex` corre con `-no-shell-escape`.
4. Marca de agua `draftwatermark` (diagonal, «BORRADOR SIN VALIDEZ LEGAL») y pie con «Generado con IA ·
   Documento orientativo y no vinculante». Se compila en una carpeta temporal que se borra.

## Troceado (chunking) por tipo de documento

| Documento | Unidad | Detalle |
|---|---|---|
| BOE consolidado (Código Civil, Ley del Notariado) | Artículo | Ruta Libro > Título > Capítulo > Sección en la cabecera; artículos >1.500 caracteres en partes; derogados fuera |
| Arancel notarial | Artículo, «Número N.» del anexo, ANEXO | Cada «Número» es un tipo de documento y su precio |
| DOUE (RGPD, Reglamento de IA) | Artículo y considerando | Cabeceras del Diario Oficial eliminadas; notas al pie «(4) DO L…» descartadas; considerandos solo antes del art. 1 y en orden creciente |
| Manual (OCR) | Página → trozos de 1.200 | Cada trozo cita su página |
| Modelos de testamento | Página → trozos de 2.000 | Más grandes para no partir cláusulas |

Cada fragmento empieza por su procedencia («Código Civil, artículo 695 / LIBRO III > …»), que es lo
que el modelo cita y lo que se muestra en «fragmentos consultados».

## Modelos y costes

- Respuestas y clasificación: **Claude Haiku 5.5** (`claude-haiku-5-5`), esfuerzo `low`
  (`EFFORT` en `server.py`). Las versiones actuales no admiten `temperature`.
- Coste medido: unos **0,001–0,002 $ por mensaje**; una conversación completa con PDF, ~0,005–0,01 $.
- Embeddings locales (gratis): `multilingual-e5-base`, en CPU.

## Índice: tiempos

`python server.py --rebuild` (o `DocumentProcessor.process()`):

| Paso | Tiempo en este portátil (8 núcleos, CPU) |
|---|---|
| OCR del libro escaneado (50 páginas) | ~3–5 min (una sola vez; queda el .txt) |
| Índice completo, 3.335 fragmentos (embeddings sin caché) | 7 min 21 s |
| Reconstrucción con embeddings en caché | ~15 s |

## Configuración (`.env`)

| Variable | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | Obligatoria |
| `RETENTION_DAYS` | Días sin uso hasta el borrado automático (30 por defecto) |
| `GOOGLE_MAPS_API_KEY` | Opcional: notarías concretas con teléfono y horario |
| `TWILIO_*`, `PUBLIC_URL`, `WHATSAPP_MODO` | Solo para WhatsApp |

## Pruebas

- `python -m benchmarks.privacidad`: detección de datos personales (37/37 con regex + Presidio,
  0 falsos positivos, 0 ocultado de más; histórico en `benchmarks/resultados.md`).
- `python conversacion_prueba.py`: conversación completa guionizada → `conversacion_prueba.txt`.

## WhatsApp (aparcado)

`src/whatsapp.py` funciona con Twilio (firma validada, sesión por número, fotos, respuestas troceadas,
modo `twiml` o `api`). El número de prueba gratuito de Twilio («Try it out») solo admite plantillas, así
que hace falta el sandbox clásico o una cuenta de pago. Las sesiones de WhatsApp viven solo en memoria y
caducan con el mismo plazo de retención.
