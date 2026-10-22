"""Loader for folders of plain documents: law manuals and testament models."""
from pathlib import Path
from typing import List

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

TEXT_EXTENSIONS = {".txt", ".md"}


class TextFolderLoader:
    """Splits every .txt, .md and text PDF of a folder into chunks tagged with their kind of source."""

    def __init__(
        self,
        folder: str,
        fuente: str,
        description: str,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
        verbose: bool = False
    ):
        """Initialize loader.

        Args:
            folder: Folder with the documents
            fuente: Kind of source stored in metadata ("manual", "modelo")
            description: Text prepended to every chunk, telling the LLM what this source is
            chunk_size: Size of text chunks in characters
            chunk_overlap: Overlap between chunks
            verbose: Whether to show detailed information
        """
        self.folder = Path(folder)
        self.fuente = fuente
        self.description = description
        self.splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.verbose = verbose

        from src.utils.rich_utils import get_console
        self.console = get_console()

    def _read(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
            if len(text.strip()) < 50:
                self.log(f"[yellow]{path.name} parece escaneado (sin texto). "
                         f"Pase sus páginas como fotos a ocr/ para extraerlas.[/yellow]")
            return text
        return path.read_text(encoding="utf-8")

    def load(self) -> List[Document]:
        """Load all documents of the folder as chunks.

        Returns:
            List of Document chunks
        """
        if not self.folder.exists():
            return []

        files = sorted(
            p for p in self.folder.iterdir()
            if p.is_file() and (p.suffix.lower() in TEXT_EXTENSIONS or p.suffix.lower() == ".pdf")
        )
        documents = []
        for path in files:
            text = self._read(path)
            if not text.strip():
                continue
            header = f"{self.description} ({path.name})\n"
            for n, part in enumerate(self.splitter.split_text(text), 1):
                documents.append(Document(
                    page_content=header + part,
                    metadata={"source": path.name, "fuente": self.fuente, "parte": n},
                ))

        if self.verbose:
            self.log(f"[green]✓ {self.folder}/: {len(files)} archivos, {len(documents)} fragmentos[/green]")
        return documents

    def log(self, message: str, level: str = "info") -> None:
        """Log a message with appropriate styling based on level."""
        self.console.print(message)
