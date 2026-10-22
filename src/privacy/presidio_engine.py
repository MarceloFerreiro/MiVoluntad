"""Microsoft Presidio analyzer configured for Spanish (spaCy es_core_news_md + Spanish recognizers)."""
from functools import lru_cache
from typing import List, Tuple

from .nombres_es import AMBIGUOS, CUALQUIER_CASO

# Presidio entity -> our type. LOCATION, ORGANIZATION and DATE_TIME are kept on purpose:
# the municipality decides which civil law applies and dates matter for deadlines.
PRESIDIO_TYPES = {
    "PERSON": "PERSONA",
    "ES_NIF": "DNI",
    "ES_NIE": "NIE",
    "ES_PASSPORT": "PASAPORTE",
    "IBAN_CODE": "IBAN",
    "CREDIT_CARD": "CUENTA",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "TELEFONO",
    "URL": "URL",
}
SCORE_THRESHOLD = 0.4


@lru_cache(maxsize=1)
def get_analyzer():
    """Build the analyzer once: Spanish spaCy NLP engine, Spanish recognizers and a given-name dictionary."""
    import regex

    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import (
        CreditCardRecognizer,
        EmailRecognizer,
        EsNieRecognizer,
        EsNifRecognizer,
        EsPassportRecognizer,
        IbanRecognizer,
        PhoneRecognizer,
        SpacyRecognizer,
        UrlRecognizer,
    )

    nlp_engine = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "es", "model_name": "es_core_news_md"}],
        "ner_model_configuration": {
            "model_to_presidio_entity_mapping": {"PER": "PERSON", "LOC": "LOCATION", "ORG": "ORGANIZATION"},
            "labels_to_ignore": ["MISC"],
        },
    }).create_engine()

    registry = RecognizerRegistry(supported_languages=["es"])
    for recognizer in (
        EsNifRecognizer(),
        EsNieRecognizer(),
        EsPassportRecognizer(),
        SpacyRecognizer(supported_language="es"),
        EmailRecognizer(supported_language="es"),
        IbanRecognizer(supported_language="es"),
        CreditCardRecognizer(supported_language="es"),
        PhoneRecognizer(supported_language="es", supported_regions=["ES"]),
        UrlRecognizer(supported_language="es"),
        # Given-name dictionary for names typed in lowercase ("mi sobrina maria jose")
        PatternRecognizer(
            supported_entity="PERSON", name="SpanishNamesRecognizer", supported_language="es",
            deny_list=CUALQUIER_CASO, deny_list_score=0.6,
        ),
        # Names that are also common words ("dolores de cabeza") only count when capitalized
        PatternRecognizer(
            supported_entity="PERSON", name="SpanishAmbiguousNamesRecognizer", supported_language="es",
            deny_list=AMBIGUOS, deny_list_score=0.5, global_regex_flags=regex.M | regex.S,
        ),
    ):
        registry.add_recognizer(recognizer)

    return AnalyzerEngine(nlp_engine=nlp_engine, registry=registry, supported_languages=["es"])


def analyze(text: str) -> List[Tuple[int, int, str]]:
    """(start, end, our type) spans found by Presidio."""
    results = get_analyzer().analyze(
        text=text,
        language="es",
        entities=list(PRESIDIO_TYPES),
        score_threshold=SCORE_THRESHOLD,
    )
    # Longest first, so "Lucía Fernández" (spaCy) wins over "Lucía" (dictionary) when they overlap
    results = sorted(results, key=lambda r: (r.start - r.end, r.start))
    return [(r.start, r.end, PRESIDIO_TYPES[r.entity_type]) for r in results]
