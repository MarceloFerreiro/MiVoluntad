"""Loader for consolidated laws published by the BOE (Código Civil, leyes, reales decretos)."""
import re
from pathlib import Path
from typing import List, Dict, Optional

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


# Lines repeated on every page of BOE consolidated PDFs
NOISE_LINE = re.compile(
    r'^(BOLETÍN OFICIAL DEL ESTADO|LEGISLACIÓN CONSOLIDADA|Página \d+|'
    r'Este documento es de carácter informativo y no tiene valor jurídico\.)$'
)
# "Artículo 695." (Código Civil) or "Artículo 1. Objeto de la ley." (modern laws, title on the same line)
ARTICLE = re.compile(r'^Artículos? (\d+(?:\.\d+)?(?: (?:bis|ter|quater|quinquies))?(?: a \d+)?)\.(?:\s+(.*))?$')
# Modern laws: "Disposición adicional primera. Título."
DISPOSITION = re.compile(r'^(Disposición (?:adicional|transitoria|derogatoria|final)(?: [a-zé]+)?)\.(?:\s+(.*))?$')
# Body headings come alone on their line ("TÍTULO III"); index entries carry a dot and page dots
HEADING = re.compile(r'^(LIBRO [A-ZÁÉÍÓÚ]+|TÍTULO PRELIMINAR|TÍTULO [IVXLC]+|CAPÍTULO [IVXLC]+)$')
SECTION = re.compile(r'^(Sección \d+\.ª .+)$')
# Código Civil style: a plain heading followed by "Primera.", "Segunda."... (not indexed)
END_OF_ARTICLES = re.compile(r'^Disposiciones (transitorias|adicionales|finales)$', re.IGNORECASE)
# Title block on the first page ends where the publication data starts
TITLE_END = re.compile(r'^(Ministerio|Jefatura del Estado|Comunidad Autónoma|«|Referencia:)')
EMPTY_ARTICLE = re.compile(r'^\((Suprimidos?|Derogados?|Sin contenido)\)\.?$', re.IGNORECASE)

LEVELS = ["libro", "titulo", "capitulo", "seccion"]


class LeyLoader:
    """Splits a BOE consolidated law into one Document per article, keeping its place in the law.

    PDFs without recognizable articles (other documents saved in pdfs/) are split by size.
    """

    def __init__(self, max_chunk_size: int = 1500, chunk_overlap: int = 150, verbose: bool = False):
        """Initialize loader.

        Args:
            max_chunk_size: Articles longer than this (in characters) are split into parts
            chunk_overlap: Overlap between parts of a long article
            verbose: Whether to show detailed information
        """
        self.splitter = RecursiveCharacterTextSplitter(chunk_size=max_chunk_size, chunk_overlap=chunk_overlap)
        self.max_chunk_size = max_chunk_size
        self.verbose = verbose

        from src.utils.rich_utils import get_console
        self.console = get_console()

    @staticmethod
    def _law_name(lines: List[str], pdf_path: Path) -> str:
        """Short name of the law from the title on the first page, e.g. 'Código Civil' or 'Ley 39/2015'."""
        title_lines = []
        for line in lines[:8]:
            if TITLE_END.match(line):
                break
            title_lines.append(line)
        title = " ".join(title_lines).strip().rstrip(".")
        if not title:
            return pdf_path.stem

        published = re.search(r'por (?:el|la) que se (?:publica|aprueba)\s+(?:el |la )?(?:texto refundido de (?:la |el )?)?(.+)$', title)
        if published:
            name = published.group(1)
            return name[0].upper() + name[1:]
        numbered = re.match(r'((?:Real Decreto(?: Legislativo| Ley)?|Ley(?: Orgánica)?|Decreto(?: Legislativo)?) \d+/\d{4})', title)
        if numbered:
            return numbered.group(1)
        return title[:90]

    def _read_lines(self, pdf_path: Path) -> List[str]:
        """Extract text lines from the PDF, dropping page headers and footers."""
        reader = PdfReader(str(pdf_path))
        lines = []
        for page in reader.pages:
            for line in page.extract_text().splitlines():
                line = line.strip()
                if line and not NOISE_LINE.match(line):
                    lines.append(line)
        return lines

    def _parse_articles(self, lines: List[str]) -> List[Dict]:
        """Walk the lines tracking the heading hierarchy and collect article texts."""
        hierarchy: Dict[str, Optional[str]] = {level: None for level in LEVELS}
        articles = []
        current = None
        i = 0

        while i < len(lines):
            line = lines[i]

            if '....' in line:  # index entry
                i += 1
                continue

            if END_OF_ARTICLES.match(line):
                break

            heading = HEADING.match(line)
            section = SECTION.match(line)
            article = ARTICLE.match(line) or DISPOSITION.match(line)

            if heading:
                level = {"LIBRO": "libro", "TÍTULO": "titulo", "CAPÍTULO": "capitulo"}[line.split()[0]]
                name = lines[i + 1] if i + 1 < len(lines) else ""
                hierarchy[level] = f"{line}. {name}"
                for lower in LEVELS[LEVELS.index(level) + 1:]:
                    hierarchy[lower] = None
                current = None
                i += 2
                continue

            if section:
                hierarchy["seccion"] = section.group(1).rstrip('.')
                current = None
                i += 1
                continue

            if article:
                current = {"articulo": article.group(1), "lines": [], **hierarchy}
                if article.group(2):  # title on the same line
                    current["lines"].append(article.group(2))
                articles.append(current)
                i += 1
                continue

            if current is not None:
                current["lines"].append(line)
            i += 1

        return articles

    @staticmethod
    def _header(article: Dict, norma: str) -> str:
        """Human readable location of the article, prepended to every chunk."""
        path = " > ".join(article[level] for level in LEVELS if article[level])
        unit = article["articulo"] if article["articulo"].startswith("Disposición") else f"artículo {article['articulo']}"
        return f"{norma}, {unit}\n{path}\n"

    def _load_unstructured(self, lines: List[str], pdf_path: Path, norma: str) -> List[Document]:
        """Fallback for PDFs without articles: plain chunks by size."""
        header = f"{norma} ({pdf_path.name})\n"
        return [
            Document(page_content=header + part,
                     metadata={"source": pdf_path.name, "fuente": "ley", "norma": norma, "articulo": None, "parte": n})
            for n, part in enumerate(self.splitter.split_text("\n".join(lines)), 1)
        ]

    def load(self, pdf_path: str) -> List[Document]:
        """Load a law PDF as article-level chunks.

        Args:
            pdf_path: Path to the BOE consolidated PDF

        Returns:
            List of Document chunks, one per article (or per part of a long article)
        """
        pdf_path = Path(pdf_path)
        lines = self._read_lines(pdf_path)
        norma = self._law_name(lines, pdf_path)
        articles = self._parse_articles(lines)
        if not articles:
            documents = self._load_unstructured(lines, pdf_path, norma)
            if self.verbose:
                self.log(f"[yellow]{pdf_path.name}: sin artículos reconocibles, {len(documents)} fragmentos por tamaño[/yellow]")
            return documents

        documents = []
        skipped = 0
        for article in articles:
            text = "\n".join(article["lines"]).strip()
            if not text or EMPTY_ARTICLE.match(text):
                skipped += 1
                continue

            parts = [text] if len(text) <= self.max_chunk_size else self.splitter.split_text(text)
            header = self._header(article, norma)
            for n, part in enumerate(parts, 1):
                metadata = {level: article[level] for level in LEVELS}
                metadata.update({
                    "source": pdf_path.name,
                    "fuente": "ley",
                    "norma": norma,
                    "articulo": article["articulo"],
                    "parte": n,
                    "partes": len(parts),
                })
                suffix = f"(parte {n} de {len(parts)})\n" if len(parts) > 1 else ""
                documents.append(Document(page_content=header + suffix + part, metadata=metadata))

        if self.verbose:
            self.log(f"[green]✓ {pdf_path.name} ({norma}): {len(articles)} artículos "
                     f"({skipped} derogados o sin contenido), {len(documents)} fragmentos[/green]")
        return documents

    def log(self, message: str, level: str = "info") -> None:
        """Log a message with appropriate styling based on level."""
        self.console.print(message)
