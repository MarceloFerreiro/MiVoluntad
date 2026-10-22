# Documentos de la base de conocimiento

## Inventario (22/10/2026)

| Archivo | Qué es | Fuente | Fragmentos |
|---|---|---|---|
| `pdfs/espana/codigo_civil.pdf` | Código Civil, texto consolidado | BOE-A-1889-4763 | 1.949 |
| `pdfs/espana/ley_del_notariado.pdf` | Ley del Notariado de 28 de mayo de 1862, consolidada | BOE-A-1862-4073 | 145 |
| `pdfs/espana/arancel_notarial_rd_1426_1989.pdf` | Real Decreto 1426/1989, Arancel de los Notarios | BOE-A-1989-28111 | 22 |
| `pdfs/ue/rgpd_reglamento_ue_2016_679.pdf` | RGPD, Reglamento (UE) 2016/679 | DOUE L 119 | 406 (99 arts., 173 considerandos) |
| `pdfs/ue/reglamento_ia_ue_2024_1689.pdf` | Reglamento de IA, Reglamento (UE) 2024/1689 | DOUE, Serie L, 12.7.2024 | 615 (113 arts., 180 considerandos) |
| `ocr/manual_el_testamento.pdf` → `manuales/manual_el_testamento.txt` | Libro sobre el testamento (escaneado, 50 págs.) | OCR Tesseract, 93 % de confianza | 182 |
| `modelos/modelo_testamento_abierto_notaria_fuengirola.pdf` | Testamento abierto completo (ejemplo real de notaría) | — | 11 |
| `modelos/modelo_testamento_estandar_notaria_barcelona.pdf` | Modelo estándar (varón casado con hijos) | Notaría Bosch-Bages | 3 |
| `modelos/modelo_testamento_olografo.doc` | Modelo orientativo de testamento ológrafo | — | 2 |
| `docs/cuestionario/CUESTIONARIO.docx` | Cuestionario original del equipo (no se indexa) | Equipo | — |

> **No están en el repositorio público** (derechos de autor): el libro escaneado y su texto
> (`ocr/manual_el_testamento.pdf`, `manuales/manual_el_testamento.txt`) y los tres modelos de testamento
> de `modelos/`. Están en `.gitignore`: hay que pedírselos al equipo y copiarlos en sus carpetas antes de
> `python server.py --rebuild`. Sin ellos el asistente funciona igual, solo con las leyes.
> El modelo estándar procede de la web de la Notaría Bosch-Bages (Barcelona).

Total: **3.335 fragmentos**. Los dos reglamentos de la UE estaban en `manuales/` y se movieron a
`pdfs/ue/` porque son normas y se trocean por artículo.

## Cómo añadir documentos

| Tengo… | Lo pongo en… |
|---|---|
| Una ley o real decreto consolidado del BOE (PDF) | `pdfs/espana/` |
| Un reglamento o directiva del DOUE (PDF) | `pdfs/ue/` |
| Un manual o libro con texto (PDF, .txt, .md) | `manuales/` |
| Un manual escaneado o capturas (PDF de imágenes, fotos) | `ocr/` |
| Un modelo de testamento (PDF, .doc, .docx, .txt) | `modelos/` |

Después:

```bash
python -m src.preprocessing.ocr     # opcional: extrae ocr/ → manuales/ (no rehace lo ya extraído)
python server.py --rebuild          # OCR pendiente + reconstruir el índice
```

Al reconstruir, cada ley muestra `✓ archivo.pdf (Nombre): N artículos, M fragmentos`. Si una ley sale
con «sin artículos reconocibles», tiene un formato distinto y se trocea por tamaño: revisarla.

## Revisar el OCR

`manuales/<nombre>.txt` lleva marcas `--- Página N ---`. Si una página sale con confianza baja, el
proceso lo avisa: se puede corregir el `.txt` a mano (no se sobrescribe) y reconstruir el índice.

## Notarías

Los datos de los 17 Colegios Notariales están en `src/notarias.py`, copiados de
<https://www.notariado.org/portal/colegios-notariales> el 22/10/2026. Si cambian, actualizar ese
diccionario y su fecha (`FECHA_DATOS_COLEGIOS`).
