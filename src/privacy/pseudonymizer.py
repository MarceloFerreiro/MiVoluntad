"""Local pseudonymization: replace personal data with labels before text reaches the LLM.

The mapping label -> original value never leaves the user's machine: the local
server uses it to put the real values back into the answer.
"""
import os
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
HONORIFICS = r'(?:DON|DOÑA|Don|Doña|Y|y)\b'
# A capitalized name word that is not an honorific or the conjunction "y"
NAME_WORD = rf'(?!{HONORIFICS})[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñü]+'

# (type, pattern, group to mask). Order matters: earlier detectors win on overlaps.
REGEX_DETECTORS: List[Tuple[str, re.Pattern, int]] = [
    ("EMAIL", re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b'), 0),
    ("IBAN", re.compile(r'\bES\d{2}(?:[ -]?\d{4}){5}\b', re.IGNORECASE), 0),
    ("NIE", re.compile(r'\b[XYZ][- ]?\d{7}[- ]?[A-Z]\b'), 0),
    ("DNI", re.compile(r'\b(\d{1,2}\.?\d{3}\.?\d{3})[- ]?([A-Z])\b'), 0),
    ("REF_CATASTRAL", re.compile(r'\b\d{7}[A-Z]{2}\d{4}[A-Z]\d{4}[A-Z]{2}\b'), 0),
    # 9 digits starting with 6-9, any grouping: 612 345 678, 699 88 77 66, +34 612345678
    ("TELEFONO", re.compile(r'(?<!\d)(?:\+34[ -]?)?[6789](?:[ -]?\d){8}(?!\d)'), 0),
    ("DIRECCION", re.compile(
        r'\b(?:calle|c/|avenida|avda\.?|plaza|pza\.?|paseo|camino|carretera|ronda|travesía|urbanización)'
        r'\s+[A-ZÁÉÍÓÚÑa-záéíóúñü0-9 .\'-]{2,60}?,?\s*(?:n[º°o]\.?\s*|número\s*)?\d{1,4}'
        r'(?:\s*,?\s*\d{1,2}[º°]?(?:\s*(?:izquierda|derecha|izda\.?|dcha\.?|[A-Z])\b)?)?',
        re.IGNORECASE), 0),
    ("PROTOCOLO", re.compile(r'\bprotocolo\b\D{0,15}?(\d(?:[\d.]*\d)?)', re.IGNORECASE), 1),
    # Notarial formulas: "DOÑA ROSARIO PÉREZ GÓMEZ", "D. Juan López de la Fuente"
    ("PERSONA", re.compile(
        rf'\b(?:D\.ª|Dª|D\.|DON|DOÑA|Don|Doña)\s+({NAME_WORD}(?:\s+(?:de\s+la\s+|de\s+|del\s+)?{NAME_WORD}){{0,4}})'), 1),
    # "Yo, ANA RUIZ, Notario" / "Ante mí, ANTONIO RUIZ MARTÍN, Notario"
    ("PERSONA", re.compile(rf'\b(?:Yo|mí),\s+({NAME_WORD}(?:\s+{NAME_WORD}){{1,4}}),\s+Notari'), 1),
]

# Capitalized words spaCy sometimes tags as people in legal texts
NOT_NAMES = {
    "notario", "notaria", "testador", "testadora", "código", "civil", "dios", "ilustre", "colegio",
    "don", "doña", "registro", "estado", "ley", "artículo", "testamento", "señor", "señora", "doy", "fe",
    "sr", "sra", "dña", "dª", "nombra", "lega", "instituye", "dispone", "comparece", "otorga", "revoca",
}

HONORIFIC_PREFIX = re.compile(r'^(?:D\.ª|Dª|D\.|Dña\.?|Sra?\.|DON|DOÑA|Don|Doña)\s+')

# Model-based detectors used when none is given: "presidio" (Microsoft Presidio, Spanish) and/or "spacy"
DEFAULT_NER = tuple(n for n in os.environ.get("PRIVACY_NER", "presidio").split(",") if n)


LABEL_PATTERN = re.compile(
    r'\[?\b((?:PERSONA|DNI|NIE|PASAPORTE|IBAN|CUENTA|TELEFONO|EMAIL|URL|DIRECCION|REF_CATASTRAL|PROTOCOLO)_\d+)\b\]?'
)


def _normalize(text: str) -> str:
    """Lowercase without accents or extra spaces, to compare values."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text).strip().lower()


# Compare without accents, like every other value ("Dña" -> "dna")
NOT_NAMES = {_normalize(word) for word in NOT_NAMES}


def _name_tokens(name: str) -> set:
    return {t for t in _normalize(name).split() if t not in {"de", "del", "la", "y"}}


class Pseudonymizer:
    """Masks personal data with stable labels such as [PERSONA_1] and restores it afterwards."""

    _nlp = None  # spaCy model, loaded once for all instances

    def __init__(
        self,
        mapping: Optional[Dict[str, Dict[str, str]]] = None,
        use_ner: bool = True,
        ner: Optional[Sequence[str]] = None,
        regex: bool = True,
    ):
        """Initialize, optionally continuing an existing conversation mapping.

        Args:
            mapping: {label: {"type": ..., "value": ...}} from previous messages
            use_ner: Run the model-based detectors (False = only fixed-format regex)
            ner: Model-based detectors, in priority order: "presidio" (Microsoft Presidio with
                Spanish recognizers) and/or "spacy" (es_core_news_md). Default: PRIVACY_NER env var.
            regex: Run our Spanish regex detectors (DNI, address, cadastral ref., notarial formulas)
        """
        self.mapping: Dict[str, Dict[str, str]] = dict(mapping or {})
        self.use_ner = use_ner
        self.ner = tuple(DEFAULT_NER if ner is None else ner)
        self.regex = regex

    # ---------- detection ----------

    @classmethod
    def _get_nlp(cls):
        if cls._nlp is None:
            import spacy
            cls._nlp = spacy.load("es_core_news_md", disable=["parser", "lemmatizer"])
        return cls._nlp

    @staticmethod
    def _is_name(text: str, require_capital: bool = True) -> bool:
        """Discard capitalized legal words that NER models tag as people ("Nombra", "Sra. Dña").

        require_capital: spaCy only finds capitalized names; the Presidio name dictionary
        also finds lowercase ones ("mi sobrina maria jose").
        """
        words = text.split()
        kept = [
            w for w in words
            if (w[:1].isupper() or not require_capital) and _normalize(w).strip(".,;:") not in NOT_NAMES
        ]
        return bool(kept) and len(" ".join(kept)) >= 3 and len(kept) == len(words)

    @staticmethod
    def _trim_name(text: str, start: int, end: int) -> Tuple[int, int]:
        """Drop lowercase non-name words at the edges of a name span.

        spaCy sometimes tags lowercase chat text like "paco nada" as a person; hiding "nada"
        would change the meaning ("to my brother paco, nothing").
        """
        from .nombres_es import NAME_TOKENS

        words = [(m.start() + start, m.end() + start) for m in re.finditer(r'\S+', text[start:end])]

        def keep(word: str) -> bool:
            return word[:1].isupper() or _normalize(word).strip(".,;:") in NAME_TOKENS

        while words and not keep(text[words[0][0]:words[0][1]]):
            words.pop(0)
        while words and not keep(text[words[-1][0]:words[-1][1]]):
            words.pop()
        return (words[0][0], words[-1][1]) if words else (start, start)

    def _presidio_spans(self, text: str) -> List[Tuple[int, int, str]]:
        """Spans found by Microsoft Presidio (Spanish recognizers + spaCy NER)."""
        from .presidio_engine import analyze

        spans = []
        for start, end, kind in analyze(text):
            if kind == "PERSONA":
                # Keep "DOÑA" outside the label, like the regex detectors do
                honorific = HONORIFIC_PREFIX.match(text[start:end])
                if honorific:
                    start += honorific.end()
                start, end = self._trim_name(text, start, end)
                if end <= start or not self._is_name(text[start:end], require_capital=False):
                    continue
            spans.append((start, end, kind))
        return spans

    def _spacy_spans(self, text: str) -> List[Tuple[int, int, str]]:
        """Person names found by spaCy, filtering capitalized legal words."""
        spans = []
        for ent in self._get_nlp()(text).ents:
            if ent.label_ != "PER":
                continue
            if not self._is_name(ent.text):
                continue
            spans.append((ent.start_char, ent.end_char, "PERSONA"))
        return spans

    @staticmethod
    def _valid_dni(match: re.Match) -> bool:
        number = int(match.group(1).replace(".", ""))
        return DNI_LETTERS[number % 23] == match.group(2).upper()

    def _detect(self, text: str) -> List[Tuple[int, int, str]]:
        """Find (start, end, type) spans, resolving overlaps in favour of earlier detectors."""
        spans: List[Tuple[int, int, str]] = []

        def add(start: int, end: int, kind: str) -> None:
            if all(end <= s or start >= e for s, e, _ in spans):
                spans.append((start, end, kind))

        for kind, pattern, group in (REGEX_DETECTORS if self.regex else []):
            for m in pattern.finditer(text):
                if kind == "DNI" and not self._valid_dni(m):
                    continue
                add(m.start(group), m.end(group), kind)

        if self.use_ner:
            detectors = {"presidio": self._presidio_spans, "spacy": self._spacy_spans}
            for name in self.ner:
                for start, end, kind in detectors[name](text):
                    add(start, end, kind)

        return sorted(spans)

    # ---------- labels ----------

    def _label_for(self, kind: str, value: str) -> str:
        """Reuse the label of an already known value, or create a new one."""
        norm = _normalize(value)
        if kind == "PERSONA":
            tokens = _name_tokens(value)
            # "Marta" and "MARTA PÉREZ LÓPEZ" are the same person if only one known name matches
            matches = [
                label for label, info in self.mapping.items()
                if info["type"] == "PERSONA" and (tokens <= _name_tokens(info["value"]) or _name_tokens(info["value"]) <= tokens)
            ]
            if len(matches) == 1:
                label = matches[0]
                if len(tokens) > len(_name_tokens(self.mapping[label]["value"])):
                    self.mapping[label]["value"] = value.title()  # keep the most complete form
                return label
        else:
            for label, info in self.mapping.items():
                known = _normalize(info["value"])
                # "calle Alfonso VI, 12" and "calle Alfonso VI, 12, 3º B" are the same address
                same = known.startswith(norm) or norm.startswith(known) if kind == "DIRECCION" else known == norm
                if info["type"] == kind and same:
                    if len(value) > len(info["value"]):
                        info["value"] = value
                    return label

        count = sum(1 for info in self.mapping.values() if info["type"] == kind) + 1
        label = f"{kind}_{count}"
        self.mapping[label] = {"type": kind, "value": value.title() if kind == "PERSONA" else value}
        return label

    # ---------- public API ----------

    def mask(self, text: str) -> str:
        """Replace every detected personal datum with its label, e.g. [DNI_1]."""
        out, last = [], 0
        for start, end, kind in self._detect(text):
            out.append(text[last:start])
            out.append(f"[{self._label_for(kind, text[start:end])}]")
            last = end
        out.append(text[last:])
        return "".join(out)

    def mask_known(self, text: str) -> str:
        """Replace values already in the mapping (e.g. the person writes a name from their document)."""
        variants: List[Tuple[str, str]] = []
        first_names: Dict[str, List[str]] = {}
        for label, info in self.mapping.items():
            variants.append((info["value"], label))
            if info["type"] == "PERSONA":
                first = info["value"].split()[0]
                if len(first) >= 3:
                    first_names.setdefault(first, []).append(label)
        # Given names alone only when they identify a single person
        variants += [(name, labels[0]) for name, labels in first_names.items() if len(labels) == 1]

        for value, label in sorted(variants, key=lambda v: -len(v[0])):
            text = re.sub(rf'(?<!\w){re.escape(value)}(?!\w)', f"[{label}]", text, flags=re.IGNORECASE)
        return text

    def restore(self, text: str) -> str:
        """Put the original values back in place of the labels."""
        return LABEL_PATTERN.sub(lambda m: self.mapping.get(m.group(1), {}).get("value", m.group(0)), text)

    def summary(self) -> Dict[str, int]:
        """How many values of each type are masked (for the UI)."""
        counts: Dict[str, int] = {}
        for info in self.mapping.values():
            counts[info["type"]] = counts.get(info["type"], 0) + 1
        return counts
