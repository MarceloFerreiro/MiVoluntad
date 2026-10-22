"""Cuestionario del borrador de testamento: única fuente para el prompt, la extracción y el PDF.

Basado en docs/cuestionario/CUESTIONARIO.docx (versión del equipo), ampliado con lo que
un notario suele necesitar en España: vecindad civil (derecho foral), régimen económico del
matrimonio, hijos de relaciones anteriores, testamento anterior y testamento digital.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

BIENVENIDA = (
    "Hola. Soy un asistente virtual que le ayuda a preparar un **borrador orientativo de testamento** "
    "para llevar al notario.\n\n"
    "Este borrador no es asesoramiento jurídico, no tiene validez legal y no sustituye al notario.\n\n"
    "Sus datos solo se usan para preparar el borrador. Se guardan protegidos y puede borrarlos cuando quiera; "
    "si no, se borran solos a los 30 días.\n\n"
    "¿Ha leído y acepta la Política de Privacidad para empezar?"
)

# (título, explicación, preguntas). Preguntas cortas, de una en una, con opciones cuando la respuesta es cerrada.
# "→" indica cuándo hacer la pregunta. Las secciones 1 y 2 son las imprescindibles para el borrador.
SECCIONES = [
    (
        "1. Situación personal y familiar",
        "Lo mínimo para saber qué reglas se le aplican. El notario pedirá después su DNI y demás datos.",
        [
            "¿En qué comunidad autónoma vive?",
            "¿Está casado o casada? (Opciones: Sí / No / Viudo o viuda / Separado o divorciado)",
            "→ Si está casado: ¿se casaron en gananciales o con separación de bienes? (Opciones: Gananciales / Separación de bienes / No lo sé)",
            "¿Tiene hijos? (Opciones: Sí / No)",
            "→ Si tiene: ¿cuántos y cómo se llaman?",
            "→ Si tiene: ¿alguno ha fallecido dejando hijos? (Opciones: Sí / No)",
            "→ Si no tiene hijos ni nietos: ¿viven sus padres? (Opciones: Sí / No)",
            "¿Ha hecho testamento alguna vez? (Opciones: Sí / No / No lo recuerdo)",
        ],
    ),
    (
        "2. Reparto principal de la herencia",
        "A quién deja sus bienes y cómo.",
        [
            "¿A quién quiere dejar sus bienes en primer lugar?",
            "¿A partes iguales? (Opciones: Sí, a partes iguales / No, quiero favorecer a alguien)",
            "¿Quiere dejar algo concreto a alguien, como una casa, dinero o joyas? (Opciones: Sí / No)",
            "→ Si está casado: ¿qué quiere para su cónyuge? (Opciones: Lo que marca la ley / Que pueda usar todo de por vida / Otra cosa)",
            "Si alguno faltara antes que usted, ¿quiere que su parte pase a sus hijos? (Opciones: Sí / No)",
            "Ya tiene lo imprescindible: ¿genera ahora su borrador o quiere añadir algo más? (Opciones: Generar borrador / Añadir algo más)",
        ],
    ),
    (
        "3. Inmuebles y bienes concretos",
        "Opcional. Para los inmuebles, el notario pedirá su descripción y la referencia catastral.",
        [
            "¿Tiene casa o fincas que quiera mencionar? (Opciones: Sí / No)",
            "¿Tiene bienes fuera de España? (Opciones: Sí / No)",
        ],
    ),
    (
        "4. Cargos testamentarios",
        "Opcional. Personas de confianza que velan por que se cumpla el testamento.",
        [
            "¿Quiere nombrar a alguien de confianza que vele por que se cumpla su testamento (albacea)? (Opciones: Sí / No / Explíquemelo)",
            "¿Quiere nombrar a alguien que haga el reparto (contador-partidor)? (Opciones: Sí / No / Explíquemelo)",
        ],
    ),
    (
        "5. Disposiciones personales, tutela, animales y legado digital",
        "Opcional. Otros deseos.",
        [
            "¿Tiene algún deseo sobre su funeral? (Opciones: Sí / No)",
            "¿Tiene hijos menores o alguna persona a su cargo? (Opciones: Sí / No)",
            "¿Tiene animales que alguien deba cuidar? (Opciones: Sí / No)",
            "¿Quiere decir quién se ocupa de sus cuentas de internet o redes sociales? (Opciones: Sí / No)",
        ],
    ),
]

CIERRE = (
    "El borrador se formalizará ante notario, que indicará la fecha, la hora y el municipio del otorgamiento "
    "y lo autorizará en escritura pública. Solo entonces tendrá plena validez."
)


# ---------- Esquema de lo que se extrae de la conversación para el PDF ----------

class Persona(BaseModel):
    nombre: str = Field(description="Nombre tal como aparece en la conversación (puede ser una etiqueta como [PERSONA_2])")
    relacion: Optional[str] = Field(None, description="Relación con el testador: hija, cónyuge, sobrino, amiga…")


class Legado(BaseModel):
    bien: str = Field(description="Bien concreto que se deja")
    beneficiario: str = Field(description="Persona que lo recibe")
    observaciones: Optional[str] = None


class Borrador(BaseModel):
    """Respuestas al cuestionario. Todo lo que la persona no haya dicho queda en null o lista vacía."""

    residencia: Optional[str] = Field(None, description="Comunidad autónoma de residencia")
    vecindad_foral: Optional[str] = Field(
        None, description="Si vive en Cataluña, Aragón, Navarra, País Vasco, Galicia o Baleares: aviso de derecho foral")
    estado_civil: Optional[str] = None
    regimen_economico: Optional[str] = Field(None, description="Gananciales, separación de bienes…")
    conyuge: Optional[Persona] = None
    hijos: List[Persona] = Field(default_factory=list, description="Hijos, indicando si alguno es de relación anterior o ha fallecido")
    nietos_de_hijos_fallecidos: List[Persona] = Field(default_factory=list)
    ascendientes_vivos: Optional[str] = None
    testamento_anterior: Optional[str] = None

    herederos: List[Persona] = Field(
        default_factory=list,
        description="Personas que heredan la herencia o 'el resto' de ella. Si dice 'lo demás a partes iguales entre "
                    "mis hijos' (o entre X e Y), los herederos son esos hijos o esas personas. No dejar vacío si el reparto los nombra")
    reparto: Optional[str] = Field(None, description="Cómo se reparte la herencia: partes iguales, mejora, tercios…")
    legados: List[Legado] = Field(default_factory=list)
    sustitucion: Optional[str] = Field(None, description="Quién ocupa el lugar de un heredero que falte")
    disposicion_conyuge: Optional[str] = None

    inmuebles_y_bienes: List[str] = Field(default_factory=list)
    bienes_extranjero: Optional[str] = None

    albacea: Optional[Persona] = None
    contador_partidor: Optional[Persona] = None

    funeral: Optional[str] = None
    tutela_o_apoyos: Optional[str] = None
    animales: Optional[str] = None
    legado_digital: Optional[str] = None

    avisos: List[str] = Field(
        default_factory=list,
        description="Posibles problemas a revisar con el notario, p. ej. si un deseo choca con las legítimas")
    dudas_para_el_notario: List[str] = Field(default_factory=list)


def guion_para_prompt() -> str:
    """El cuestionario como texto para el prompt del sistema."""
    partes = []
    for titulo, explicacion, preguntas in SECCIONES:
        partes.append(f"{titulo}. {explicacion}\n" + "\n".join(f"   - {p}" for p in preguntas))
    return "\n".join(partes)


def cuestionario_markdown() -> str:
    """El cuestionario como Markdown legible (docs/cuestionario/CUESTIONARIO.md)."""
    lineas = [
        "# Cuestionario del borrador de testamento",
        "",
        "> Generado desde `src/borrador/cuestionario.py`, que es la fuente que usan el bot, la extracción y el PDF.",
        "> Versión mejorada de `CUESTIONARIO.docx` del equipo.",
        "",
        "## Mensaje de bienvenida",
        "",
        BIENVENIDA,
        "",
    ]
    for titulo, explicacion, preguntas in SECCIONES:
        lineas += [f"## {titulo}", "", explicacion, ""] + [f"- {p}" for p in preguntas] + [""]
    lineas += ["## Cierre", "", CIERRE, ""]
    return "\n".join(lineas)


if __name__ == "__main__":
    print(cuestionario_markdown())
