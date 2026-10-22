# Mi Voluntad

Asistente para que personas mayores de toda España preparen un **borrador orientativo de testamento**
para llevar al notario. Conversa en lenguaje sencillo, se apoya en las leyes (RAG sobre el Código Civil
y otras normas), guía un cuestionario, genera un **PDF del borrador** con marca de agua, indica el
**Colegio Notarial y notarías** de la zona y protege los datos personales: la IA nunca los ve.

Proyecto del Datathon de Brecha Judicial (Reto 1, «La desigualdad silenciosa»).

> El borrador no tiene validez legal y no sustituye al notario ni a un abogado.

## Puesta en marcha

```bash
cd dathaton && unset PYTHONPATH                 # PYTHONPATH de ROS interfiere con el venv
python3 -m venv .venv && source .venv/bin/activate
pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m spacy download es_core_news_md
sudo apt install tesseract-ocr tesseract-ocr-spa  # OCR; LaTeX (texlive) para el PDF
cp .env.example .env                              # y poner ANTHROPIC_API_KEY

python server.py --rebuild        # primera vez: OCR + índice (~7 min en CPU)
python server.py --host 0.0.0.0   # luego: abrir http://localhost:8000 (o la IP del portátil desde el móvil)
```

Para usar el **micrófono desde el móvil** hace falta HTTPS (lo exigen los navegadores):

```bash
./scripts/crear_certificado.sh            # certificado autofirmado para la IP actual (repetir si cambia de wifi)
python server.py --host 0.0.0.0 --https   # https://<IP del portátil>:8443
```

La primera vez, el móvil avisa de que el certificado no es de confianza: *Configuración avanzada → Continuar*.

## Carpetas

| Carpeta | Contenido |
|---|---|
| `pdfs/espana/`, `pdfs/ue/` | Leyes en PDF (BOE y DOUE), troceadas por artículo |
| `ocr/` | PDFs escaneados o fotos de manuales; su texto se extrae a `manuales/` |
| `manuales/` | Manuales de Derecho (.txt del OCR, .pdf, .md) |
| `modelos/` | Modelos de testamento (.pdf, .doc, .docx) |
| `docs/` | Documentación y el cuestionario |
| `src/` | Código: RAG, privacidad, borrador PDF, notarías, WhatsApp |
| `web/` | Chat web, política de privacidad y logo (`web/assets/`) |
| `docs/marca/` | Logo original de Mi Voluntad |
| `benchmarks/` | Banco de pruebas de la seudonimización |
| `data/` | Conversaciones cifradas (no se sube a git) |

## Documentación

- [docs/CONTEXTO.md](docs/CONTEXTO.md): el problema, a quién va dirigido, marco legal y alcance.
- [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md): cómo funciona por dentro (RAG, troceado, flujos, configuración).
- [docs/PRIVACIDAD.md](docs/PRIVACIDAD.md): qué datos se tratan, seudonimización, cifrado y borrado.
- [docs/DATOS.md](docs/DATOS.md): inventario de documentos y cómo añadir más.
- [docs/cuestionario/CUESTIONARIO.md](docs/cuestionario/CUESTIONARIO.md): el cuestionario del borrador.

## Licencia

El **código** de este repositorio se distribuye bajo licencia [MIT](LICENSE).
`src/preprocessing/BM25.py` procede de un gist bajo CC0.

Los **documentos** de `pdfs/`, `manuales/`, `ocr/` y `modelos/` **no** están cubiertos por la licencia
MIT: conservan sus propios derechos.

- Las leyes (BOE y Diario Oficial de la UE) son textos oficiales de libre reutilización, citando la fuente.
- El libro escaneado (`ocr/manual_el_testamento.pdf` y su texto en `manuales/`) y los modelos de testamento
  de notarías están protegidos por derechos de autor. Se usan solo como material de consulta interno del
  prototipo. Si el repositorio se hace público, hay que retirarlos o pedir permiso a sus autores.
