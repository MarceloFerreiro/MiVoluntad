"""Loader for folders of plain documents: law manuals and testament models."""
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

TEXT_EXTENSIONS = {".txt", ".md"}
WORD_EXTENSIONS = {".doc", ".docx", ".odt"}
SUPPORTED = TEXT_EXTENSIONS | WORD_EXTENSIONS | {".pdf"}
# Page markers written by the OCR step (src/preprocessing/ocr.py)
PAGE_MARKER = re.compile(r'^--- Página (\d+) ---$', re.MULTILINE)


class TextFolderLoader:
    """Splits every .txt, .md, Word document and text PDF of a folder into chunks tagged with their kind of source.

    Chunks never cross pages when the page is known (PDFs and OCR text with page markers),
    so every chunk can be cited with its page.
    """

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

    def _word_to_text(self, path: Path) -> str:
        """Convert .doc/.docx/.odt to plain text with LibreOffice (headless)."""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", tmp, str(path)],
                check=True, capture_output=True, timeout=120,
            )
            return (Path(tmp) / f"{path.stem}.txt").read_text(encoding="utf-8", errors="replace")

    def _read_pages(self, path: Path) -> List[Tuple[Optional[int], str]]:
        """(page number or None, text) for every page of the document."""
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pages = [(n, page.extract_text() or "") for n, page in enumerate(PdfReader(str(path)).pages, 1)]
            if sum(len(text.strip()) for _, text in pages) < 50:
                self.log(f"[yellow]{path.name} parece escaneado (sin texto). "
                         f"Póngalo en ocr/ para extraer su texto a manuales/.[/yellow]")
            return pages
        text = self._word_to_text(path) if suffix in WORD_EXTENSIONS else path.read_text(encoding="utf-8")
        markers = list(PAGE_MARKER.finditer(text))
        if not markers:
            return [(None, text)]
        return [
            (int(m.group(1)), text[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)])
            for i, m in enumerate(markers)
        ]

    def load(self) -> List[Document]:
        """Load all documents of the folder as chunks.

        Returns:
            List of Document chunks
        """
        if not self.folder.exists():
            return []

        files = sorted(p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
        documents = []
        for path in files:
            n = 0
            for page, text in self._read_pages(path):
                if not text.strip():
                    continue
                where = f", página {page}" if page else ""
                header = f"{self.description} ({path.name}{where})\n"
                for part in self.splitter.split_text(text):
                    n += 1
                    documents.append(Document(
                        page_content=header + part,
                        metadata={"source": path.name, "fuente": self.fuente, "pagina": page, "parte": n},
                    ))

        if self.verbose:
            self.log(f"[green]✓ {self.folder}/: {len(files)} archivos, {len(documents)} fragmentos[/green]")
        return documents

    def log(self, message: str, level: str = "info") -> None:
        """Log a message with appropriate styling based on level."""
        self.console.print(message)
