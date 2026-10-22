"""Genera una conversación de prueba con el asistente y la guarda en conversacion_prueba.txt.

Uso: python conversacion_prueba.py
"""
import builtins
import datetime

from dotenv import load_dotenv
from rich.console import Console

builtins.rich_console = Console(width=110)
builtins.verbose_mode = False

from src.LLMManager import LLMManager
from src.preprocessing.DocumentProcessor import DocumentProcessor
from src.rag.RAGSystem import RAGSystem

MODEL = "claude-haiku-5-5"
ESCENARIO = "Hombre casado, tres hijos (uno fallecido con dos nietos), vive en Toledo."
TURNOS = [
    "Hola, buenos días",
    "Mi nieta me ha dicho que debería hacer testamento, pero no sé ni por dónde empezar",
    "Estoy casado con Carmen y tuvimos tres hijos: Luis, Ana y Pedro. Pedro murió hace dos años y dejó dos niños, Pablo y Lucía. Vivimos en Toledo.",
    "Lo que más me preocupa es que Carmen pueda seguir viviendo en nuestra casa cuando yo falte",
    "¿Qué tengo que llevar a la notaría? ¿Y cuánto me va a costar?",
    "¿Y si dentro de unos años cambio de opinión?",
    "Vale, hágame el borrador para llevarlo al notario",
    "Muchas gracias, ha sido usted muy amable",
]


def main():
    load_dotenv(".env")
    processor = DocumentProcessor()
    processor.load_vectorstore("local_vectorstore")
    rag = RAGSystem(
        vectorstore=processor.vectorstore,
        llm=LLMManager(model_name=MODEL).llm,
        llm_query=LLMManager(model_name=MODEL, max_tokens=2048).llm,
        k=8,
        state_dir=".doc_cache",
        bm25_mode="hybrid",
        bm25_weight=0.5,
        bm25_index=processor.bm25_index,
        bm25_documents=processor.bm25_documents,
    )

    total = 0.0
    out = [
        "CONVERSACIÓN DE PRUEBA — Testamento Fácil",
        f"Fecha: {datetime.date.today():%d/%m/%Y} · Modelo: {MODEL} (effort low) · RAG: Código Civil (FAISS + BM25)",
        f"Escenario: {ESCENARIO}",
        "=" * 90,
    ]
    for i, pregunta in enumerate(TURNOS, 1):
        respuesta, fuentes, coste = rag.query(pregunta, return_costs=True)
        total += coste["total_cost"]
        articulos = ", ".join(d.metadata["articulo"] for d in fuentes) or "ninguno (sin búsqueda)"
        out += [
            f"\n[{i}] USUARIO:\n{pregunta}",
            f"\n[{i}] ASISTENTE:\n{respuesta}",
            f"\n    (artículos recuperados: {articulos} · coste: ${coste['total_cost']:.5f})",
            "-" * 90,
        ]
        print(f"Turno {i}/{len(TURNOS)} listo")
    out.append(f"\nCoste total de la conversación: ${total:.5f}")

    with open("conversacion_prueba.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"Guardado en conversacion_prueba.txt (coste total ${total:.5f})")


if __name__ == "__main__":
    main()
