"""Main document processor that orchestrates document loading, chunking, and indexing."""
from typing import List, Dict, Any
from pathlib import Path

from src.LocalEmbeddings import LocalEmbeddings
from .ley_loader import LeyLoader
from .text_folder_loader import TextFolderLoader
from .ocr import extract_folder
from .vectorstore_manager import VectorstoreManager
from .bm25_manager import BM25Manager


class DocumentProcessor:
    """Orchestrates the pipeline: laws, manuals and testament models -> chunks -> FAISS + BM25.

    Folders:
        pdfs/      laws and BOE PDFs, split by article
        ocr/       photos of manual pages; their OCR text is written to manuales/
        manuales/  law manuals (.txt from OCR, or .txt/.md/.pdf added directly)
        modelos/   testament models
    """

    def __init__(
        self,
        pdfs_folder: str = "pdfs",
        ocr_folder: str = "ocr",
        manuales_folder: str = "manuales",
        modelos_folder: str = "modelos",
        embedding_model_name: str = "intfloat/multilingual-e5-base",
        max_chunk_size: int = 1500,
        chunk_overlap: int = 150,
        verbose: bool = False,
        cache_dir: str = ".doc_cache",
        batch_size: int = 128,
    ):
        """Initialize document processor.

        Args:
            pdfs_folder: Folder with laws and BOE PDFs
            ocr_folder: Folder with photos of manual pages to OCR into manuales_folder
            manuales_folder: Folder with law manuals
            modelos_folder: Folder with testament models
            embedding_model_name: Name of embedding model
            max_chunk_size: Articles longer than this are split into parts
            chunk_overlap: Overlap between parts of a long article
            verbose: Whether to show detailed information
            cache_dir: Directory for caching embeddings
            batch_size: Batch size for embedding generation (default: 128)
        """
        self.pdfs_folder = Path(pdfs_folder)
        self.ocr_folder = Path(ocr_folder)
        self.manuales_folder = Path(manuales_folder)
        self.cache_dir = Path(cache_dir)
        self.verbose = verbose
        self.batch_size = batch_size

        # Initialize embeddings
        self.embeddings = LocalEmbeddings(
            model_name=embedding_model_name,
            cache_dir=str(self.cache_dir / "embeddings")
        )

        # Initialize component managers
        self.loader = LeyLoader(
            max_chunk_size=max_chunk_size,
            chunk_overlap=chunk_overlap,
            verbose=self.verbose
        )

        self.manuales_loader = TextFolderLoader(
            folder=manuales_folder,
            fuente="manual",
            description="Manual de Derecho (doctrina, no es texto legal)",
            verbose=self.verbose
        )

        self.modelos_loader = TextFolderLoader(
            folder=modelos_folder,
            fuente="modelo",
            description="Modelo de testamento (ejemplo orientativo de redacción, no es texto legal)",
            verbose=self.verbose
        )


        self.vectorstore_manager = VectorstoreManager(
            embeddings=self.embeddings,
            batch_size=self.batch_size,
            verbose=self.verbose
        )

        self.bm25_manager = BM25Manager(verbose=self.verbose)

        # Expose vectorstore and BM25 for external access
        self.vectorstore = None
        self.bm25_index = None
        self.bm25_documents = []

    def load_documents(self) -> List:
        """Load laws (article-level chunks), manuals and testament models.

        Returns:
            List of Document chunks
        """
        pdfs = sorted(self.pdfs_folder.glob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError(f"No hay PDFs en {self.pdfs_folder}/")

        chunks = []
        for pdf in pdfs:
            chunks.extend(self.loader.load(pdf))
        chunks.extend(self.manuales_loader.load())
        chunks.extend(self.modelos_loader.load())
        return chunks

    def process(self) -> None:
        """OCR new manual photos, then build the vector store from scratch (embeddings are cached on disk)."""
        extracted = extract_folder(self.ocr_folder, self.manuales_folder, log=self.log)
        if extracted:
            self.log(f"[green]✓ OCR: {extracted} fotos nuevas extraídas a {self.manuales_folder}/[/green]")
        chunks = self.load_documents()
        self.log(f"[cyan]Generando embeddings de {len(chunks)} fragmentos (usa caché si existe)...[/cyan]")
        self.vectorstore_manager.create_vectorstore(chunks)
        self.vectorstore = self.vectorstore_manager.vectorstore
        self.log("[green]✓ Vectorstore construido[/green]")

    def save_vectorstore(self, path: str) -> None:
        """Save the vector store and BM25 index to disk.

        Args:
            path: Path to save the vectorstore
        """
        if self.vectorstore:
            self.vectorstore_manager.save_vectorstore(path)
            self.bm25_manager.build_index_from_vectorstore(path)
            self.bm25_manager.save_bm25(path)
            # Update exposed attributes
            self.bm25_index = self.bm25_manager.bm25_index
            self.bm25_documents = self.bm25_manager.bm25_documents
            if self.verbose:
                self.log(f"Vectorstore guardado en {path}", "success")
        else:
            self.log("No hay vectorstore para guardar. Ejecute process() primero.", "warning")

    def load_vectorstore(self, path: str) -> None:
        """Load a vector store and BM25 index from disk.

        Args:
            path: Path to load the vectorstore from
        """
        self.vectorstore_manager.load_vectorstore(path)
        self.vectorstore = self.vectorstore_manager.vectorstore
        self.bm25_manager.load_bm25(path)
        # Update exposed attributes
        self.bm25_index = self.bm25_manager.bm25_index
        self.bm25_documents = self.bm25_manager.bm25_documents

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the index and the embeddings cache."""
        return {
            'total_documents': len(self.vectorstore.docstore._dict) if self.vectorstore else 0,
            'embedding_cache': self.embeddings.get_cache_stats(),
            'pdfs_folder': str(self.pdfs_folder),
        }

    def log(self, message: str, level: str = "info") -> None:
        """Log a message with appropriate styling based on level."""
        from src.utils.rich_utils import get_console
        console = get_console()
        console.print(message)
