import os
import sys
import argparse
import builtins
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.theme import Theme
from rich.progress import Progress, SpinnerColumn, TextColumn
from dotenv import load_dotenv


from .LLMManager import LLMManager
from .preprocessing.DocumentProcessor import DocumentProcessor
from .rag.RAGSystem import RAGSystem
from .utils.portada import titulo_ascii
from .utils.sources import source_label

def main():
    """Main function to run the testament assistant RAG system."""
    parser = argparse.ArgumentParser(description='Asistente de testamentos (RAG sobre el Código Civil)')

    # Document Processing
    parser.add_argument('--pdfs_folder', type=str, default='pdfs', help='Carpeta con los PDFs a indexar. Default: pdfs')
    parser.add_argument('--max_chunk_size', type=int, default=1500, help='Los artículos más largos se dividen en partes. Default: 1500')
    parser.add_argument('--chunk_overlap', type=int, default=150, help='Solapamiento entre partes de un artículo largo. Default: 150')

    # Retrieval
    parser.add_argument('--k', type=int, default=8, help='Number of documents to retrieve')
    parser.add_argument('--threshold', type=float, default=0.7, help='Similarity threshold for filtering')
    parser.add_argument('--search_type', type=str, default='similarity', help='Search type: similarity or mmr')

    # Vector Store
    parser.add_argument('--vector_store', type=str, default='local_vectorstore', help='Path to save/load vector store')
    parser.add_argument('--embedding_model', type=str, default='intfloat/multilingual-e5-base', help='HuggingFace embedding model')
    parser.add_argument('--rebuild', action='store_true', help='Rebuild vector store even if it exists')

    # BM25
    parser.add_argument('--use_bm25', action='store_true', default=True, help='Wether to use BM25')
    parser.add_argument('--bm25_mode', type=str, default='hybrid', help='BM25 mode: rerank, hybrid, bm25, or filter')
    parser.add_argument('--bm25_weight', type=float, default=0.5, help='BM25 weight in hybrid mode, default 0.5')
    parser.add_argument('--bm25_threshold', type=float, default=0.1, help='Minimum BM25 score for filter mode')

    # LLM
    parser.add_argument('--model', type=str, default='claude-haiku-5-5', help='Model name for final answers')
    parser.add_argument('--query_model', type=str, default='claude-haiku-5-5', help='Model name for query optimization')
    parser.add_argument('--use_query_optimization', default=True, action='store_true', help='Enable query optimization (two-stage LLM)')
    parser.add_argument('--api_key', type=str, default=None, help='API key (uses ANTHROPIC_API_KEY if not set)')
    parser.add_argument('--effort', type=str, default='low', choices=['low', 'medium', 'high', 'xhigh', 'max'], help='Reasoning effort for answers')
    parser.add_argument('--max_tokens', type=int, default=8000, help='Maximum tokens to generate (thinking included)')
    parser.add_argument('--max_history_length', type=int, default=30, help='Maximum conversation turns to keep')

    # Display options
    parser.add_argument('--verbose', action='store_true', help='Show detailed information')
    parser.add_argument('--crop_chunks', action='store_true', help='Crop displayed chunks to 200 characters (default: show full chunks in verbose mode)')

    # Cache & System
    parser.add_argument('--cache_dir', type=str, default='.doc_cache', help='Directory for cache storage')
    parser.add_argument('--clear-cache', action='store_true', help='Clear all caches before starting')

    args = parser.parse_args()

    load_dotenv()

    # Create a custom theme for rich
    custom_theme = Theme({
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
    })

    is_git_bash = 'MSYSTEM' in os.environ or 'MINGW' in os.environ.get('MSYSTEM', '')

    console = Console(
        theme=custom_theme,
        color_system="truecolor",
        legacy_windows=False if is_git_bash else None,
        force_terminal=True
    )

    # Share the console and verbose setting globally
    setattr(builtins, 'rich_console', console)
    setattr(builtins, 'verbose_mode', args.verbose)

    # Clear cache if requested
    if args.clear_cache:
        console.print("[yellow]Limpiando caché...[/yellow]")
        import shutil
        cache_dir = Path(args.cache_dir)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            console.print("[success]Caché eliminada[/success]")

    # Initialize the main LLM (for final answers)
    llm = LLMManager(
        model_name=args.model,
        api_key=args.api_key,
        max_tokens=args.max_tokens,
        effort=args.effort
    ).llm

    # Initialize query optimization LLM if enabled
    llm_query = None
    if args.use_query_optimization:
        llm_query = LLMManager(
            model_name=args.query_model,
            api_key=args.api_key,
            max_tokens=2048,
            effort='low'
        ).llm

        if args.verbose:
            console.print(f"[info]Query optimization enabled:[/info]")
            console.print(f"  - Query model: [yellow]{args.query_model}[/yellow]")
            console.print(f"  - Answer model: [yellow]{args.model}[/yellow]")

    # Initialize the document processor
    with Progress(
        SpinnerColumn(),
        TextColumn("[success]Cargando modelo de embeddings..."),
        console=console,
        transient=True
    ) as progress:
        progress.add_task("init", total=None)
        processor = DocumentProcessor(
            pdfs_folder=args.pdfs_folder,
            embedding_model_name=args.embedding_model,
            max_chunk_size=args.max_chunk_size,
            chunk_overlap=args.chunk_overlap,
            verbose=args.verbose,
            cache_dir=args.cache_dir
        )

    # Check if vector store exists and if we need to rebuild
    if not os.path.exists(args.vector_store) or args.rebuild:
        with Progress(
            SpinnerColumn(),
            TextColumn("[success]Procesando PDFs y construyendo la base vectorial..."),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Procesando...", total=None)
            processor.process()
            processor.save_vectorstore(args.vector_store)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[success]Cargando vectorstore..."),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("cargando", total=None)
            processor.load_vectorstore(args.vector_store)

    # Show cache stats if verbose
    if args.verbose:
        stats = processor.get_cache_stats()
        cache_info = f"[bold blue]Estadísticas del sistema:[/bold blue]"
        cache_info += f"\nFragmentos indexados: [yellow]{stats['total_documents']}[/yellow]"
        cache_info += f"\nEmbeddings en caché: [yellow]{stats['embedding_cache']['cached_documents']}[/yellow]"
        cache_info += f"\nTamaño caché: [yellow]{stats['embedding_cache']['cache_size_mb']:.2f} MB[/yellow]"
        console.print(Panel.fit(cache_info, title="Información del sistema", border_style="cyan"))

    # Initialize the RAG system
    with Progress(
        SpinnerColumn(),
        TextColumn("[success]Inicializando asistente..."),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("init", total=None)

        # Common parameters for RAG system
        rag_params = {
            'vectorstore': processor.vectorstore,
            'k': args.k,
            'state_dir': args.cache_dir,
            'threshold': args.threshold,
            'search_type': args.search_type,
            'language': 'spanish',
            'llm': llm,
            'llm_query': llm_query,
            'use_query_optimization': args.use_query_optimization,
            'max_history_length': args.max_history_length,
            'use_bm25': args.use_bm25,
            'bm25_mode': args.bm25_mode,
            'bm25_weight': args.bm25_weight,
            'bm25_threshold': args.bm25_threshold
        }

        # Add BM25 components if needed
        if args.bm25_mode == "hybrid" or args.bm25_mode == "bm25":
            rag_params.update({
                'bm25_index': processor.bm25_index,
                'bm25_documents': processor.bm25_documents
            })

        rag = RAGSystem(**rag_params)

    # Welcome message with system info
    system_info = "[bold blue]Asistente listo[/bold blue]"
    if args.verbose:
        system_info += f"\nModelo: [yellow]{args.model}[/yellow] (effort: {args.effort})"
        if args.use_query_optimization:
            system_info += f"\nModelo queries: [yellow]{args.query_model}[/yellow]"
        system_info += f"\nBase vectorial: [yellow]{args.vector_store}[/yellow]"
        system_info += f"\nEmbeddings: [yellow]{args.embedding_model}[/yellow]"
        system_info += f"\nTextos recuperados: [yellow]{args.k}[/yellow]"
        system_info += f"\nMétodo de recuperación: [yellow]{args.bm25_mode}[/yellow]"
        system_info += f"\nMax tokens: [yellow]{args.max_tokens}[/yellow]"

    system_info += "\nEscriba [bold red]'salir'[/bold red] para salir."

    console.print(Panel.fit(
        system_info,
        title="Testamento Fácil",
        border_style="green"
    ))

    console.print(titulo_ascii, style="rgb(46,125,90)")

    console.print("\n[dim]Comandos especiales:[/dim]")
    console.print("[dim]  - 'salir' → Salir del programa[/dim]")
    console.print("[dim]  - 'limpiar' → Borrar el historial de conversación[/dim]")
    console.print("[dim]  - 'historial' → Ver el historial de conversación[/dim]\n")

    while True:
        question = console.input("\n[bold cyan]Escriba su pregunta: [/bold cyan]")

        # Comandos especiales
        if question.lower() == 'salir':
            console.print("[yellow]¡Hasta pronto! 👋[/yellow]")
            break

        if question.lower() == 'limpiar':
            rag.clear_history()
            console.print("[green]✓ Historial de conversación borrado[/green]")
            continue

        if question.lower() == 'historial':
            history = rag.get_history()
            if not history:
                console.print("[yellow]No hay historial de conversación[/yellow]")
            else:
                console.print(Panel.fit(
                    "\n".join([
                        f"[cyan]P{i+1}:[/cyan] {h['question']}\n[green]R{i+1}:[/green] {h['answer'][:100]}..."
                        for i, h in enumerate(history)
                    ]),
                    title=f"Historial ({len(history)} interacciones)",
                    border_style="blue"
                ))
            continue

        if not question.strip():
            console.print("[yellow]Por favor, escriba una pregunta[/yellow]")
            continue

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[success]Pensando la respuesta..."),
                console=console,
                transient=True
            ) as progress:
                task = progress.add_task("procesando", total=None)
                # Obtener costes si verbose está activo
                if args.verbose:
                    answer, sources, cost_info = rag.query(question, use_history=True, return_costs=True)
                else:
                    answer, sources = rag.query(question, use_history=True, return_costs=False)

            # Construir título del panel con costes si verbose
            if args.verbose and cost_info and cost_info.get("total_cost", 0) > 0:
                by_stage = cost_info.get("by_stage", {})

                query_cost = by_stage.get("query_decision", 0.0)
                answer_cost = by_stage.get("answer", 0.0)

                title = (
                    f"Respuesta | "
                    f"💰 ${cost_info['total_cost']:.6f} "
                    f"(🤖 ${query_cost:.6f} + "
                    f"🧠 ${answer_cost:.6f})"
                )
            else:
                title = "Respuesta"

            console.print(Panel(
                Markdown(answer),
                title=title,
                border_style="green"
            ))

            if args.verbose:
                history_len = len(rag.get_history())
                console.print(f"[dim]Conversaciones en el historial: {history_len}[/dim]")
                console.print("\n[bold]Fragmentos de los que se extrae la información:[/bold]")

                for i, doc in enumerate(sources[:args.k]):
                    # Get relevance scores and method from metadata
                    relevance_score = doc.metadata.get('relevance_score', None)
                    vector_score = doc.metadata.get('vector_score', None)
                    bm25_score_meta = doc.metadata.get('bm25_score', None)
                    retrieval_method = doc.metadata.get('retrieval_method', 'unknown')

                    # Format score information
                    score_info = []
                    if relevance_score is not None:
                        score_info.append(f"[bold cyan]Score: {relevance_score:.4f}[/bold cyan]")
                    if vector_score is not None:
                        score_info.append(f"[cyan]Distancia vectorial: {vector_score:.4f}[/cyan]")
                    if bm25_score_meta is not None:
                        score_info.append(f"[yellow]BM25: {bm25_score_meta:.4f}[/yellow]")

                    method_emoji, method_text = {
                        'hybrid': ("🔄", "[bold magenta]Hybrid[/bold magenta] (Vector + BM25)"),
                        'vector': ("🎯", "[bold cyan]Vector[/bold cyan]"),
                        'bm25': ("📊", "[bold yellow]BM25[/bold yellow]"),
                    }.get(retrieval_method, ("❓", "[dim]Unknown[/dim]"))

                    score_line = " | ".join(score_info) if score_info else "[dim]No score info[/dim]"

                    # Show full chunks by default in verbose mode, crop only if --crop_chunks is specified
                    chunk_text = doc.page_content.strip()
                    if args.crop_chunks:
                        chunk_text = chunk_text[:200] + "..."

                    console.print(Panel(
                        f"{score_line}\n\n{chunk_text}",
                        title=f"{method_emoji} {source_label(doc.metadata)} - {method_text}",
                        border_style="blue" if retrieval_method == "vector" else "yellow" if retrieval_method == "bm25" else "magenta",
                        padding=(1, 2)
                    ))

        except Exception as e:
            console.print(f"[error]Error procesando la consulta:[/error] {e}")
            if args.verbose:
                import traceback
                console.print(traceback.format_exc())
if __name__ == "__main__":
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

    main()
