"""Human readable labels for retrieved chunks."""
from typing import Dict

LEVELS = ("libro", "titulo", "capitulo", "seccion")


def source_label(metadata: Dict) -> str:
    """Short name of where a chunk comes from, e.g. 'Código Civil, art. 695' or 'Manual: tema3.txt'."""
    fuente = metadata.get("fuente")
    page = f", pág. {metadata['pagina']}" if metadata.get("pagina") else ""
    if fuente == "manual":
        return f"Manual: {metadata.get('source', '?')}{page}"
    if fuente == "modelo":
        return f"Modelo de testamento: {metadata.get('source', '?')}{page}"
    norma = metadata.get("norma", "Código Civil")
    articulo = metadata.get("articulo")
    if not articulo:
        return norma
    named = articulo.startswith(("Disposición", "Número", "Considerando", "ANEXO"))
    return f"{norma}, {articulo}" if named else f"{norma}, art. {articulo}"


def source_detail(metadata: Dict) -> str:
    """Second line for the UI: place in the law, or what kind of material it is."""
    fuente = metadata.get("fuente")
    if fuente == "manual":
        return "Manual de Derecho (doctrina, no es texto legal)"
    if fuente == "modelo":
        return "Modelo de testamento (orientativo)"
    return " > ".join(metadata[level] for level in LEVELS if metadata.get(level))
