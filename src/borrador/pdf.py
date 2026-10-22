"""Borrador de testamento en PDF (LaTeX) a partir de la conversación.

1. Claude extrae las respuestas del cuestionario de la conversación ENMASCARADA ([PERSONA_1]...).
2. Los datos reales se restauran aquí, en local, con la tabla de correspondencia.
3. Se rellena una plantilla LaTeX (todo el texto del usuario escapado) y se compila con pdflatex
   en una carpeta temporal que se borra al terminar.
"""
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.privacy.pseudonymizer import Pseudonymizer
from .cuestionario import Borrador, CIERRE, SECCIONES

EXTRACTION_PROMPT = """Eres un asistente que pasa a limpio las respuestas de una persona para su borrador de testamento.
A partir de la conversación, rellena los campos del cuestionario.

Reglas:
- Usa solo lo que la PERSONA haya dicho o confirmado. No inventes nada. Lo que no se sepa, déjalo vacío (null o lista vacía).
- Los datos personales aparecen como etiquetas ([PERSONA_1], [DIRECCION_1]...). Cópialas exactamente igual.
- Redacta en tercera persona y en lenguaje claro y formal ("Desea nombrar heredera a…").
- "herederos" son quienes reciben la herencia o "el resto" (por ejemplo, si dice "lo demás a partes iguales entre mis
  hijos", los herederos son sus hijos). "legados" son bienes concretos para personas concretas.
- En "avisos" anota con prudencia los posibles problemas a revisar con el notario: por ejemplo, si un deseo
  podría no respetar la legítima de los hijos, si vive en una comunidad con derecho civil propio, o si falta un dato
  importante. No afirmes que nada sea nulo o inválido.
- En "dudas_para_el_notario" anota las preguntas que la persona dejó abiertas.

Conversación:
{conversacion}"""

LOGO = Path(__file__).resolve().parents[2] / "web" / "assets" / "logo.png"

LATEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def latex_escape(text: Any) -> str:
    """Escape user text for LaTeX so it can never run commands."""
    return "".join(LATEX_SPECIAL.get(c, c) for c in str(text))


def _restore(value: Any, pseudo: Pseudonymizer) -> Any:
    """Put real values back in every string of the extracted structure."""
    if isinstance(value, str):
        return pseudo.restore(value)
    if isinstance(value, list):
        return [_restore(v, pseudo) for v in value]
    if isinstance(value, dict):
        return {k: _restore(v, pseudo) for k, v in value.items()}
    return value


def extraer(llm, history: List[Dict[str, str]]) -> Borrador:
    """Answers of the questionnaire from the masked conversation."""
    conversacion = "\n".join(f"Persona: {t['question']}\nAsistente: {t['answer']}" for t in history)
    return llm.with_structured_output(Borrador).invoke(EXTRACTION_PROMPT.format(conversacion=conversacion))


# ---------- LaTeX ----------

PREAMBULO = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[spanish,es-noshorthands]{babel}
\usepackage{lmodern}
\usepackage[margin=2.3cm,bottom=2.8cm]{geometry}
\usepackage{xcolor}
\usepackage{graphicx}
\usepackage{fancyhdr}
\usepackage{enumitem}
\usepackage{lastpage}
\usepackage{draftwatermark}
\SetWatermarkText{BORRADOR SIN VALIDEZ LEGAL}
\SetWatermarkAngle{45}
\SetWatermarkScale{0.55}
\SetWatermarkColor[gray]{0.88}
\definecolor{acento}{RGB}{123,79,39}
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\fancyfoot[L]{\scriptsize\color{gray}Página \thepage\ de \pageref{LastPage}}
\fancyfoot[R]{\scriptsize\color{gray}Generado con IA · Documento orientativo y no vinculante · No sustituye al notario}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\newcommand{\pendiente}{\textit{\color{gray}pendiente}}
\newcommand{\campo}[2]{\textbf{#1:} #2\par}
\begin{document}
"""


def _valor(value: Optional[str]) -> str:
    return latex_escape(value) if value else r"\pendiente"


def _persona(p: Optional[dict]) -> str:
    if not p or not p.get("nombre"):
        return r"\pendiente"
    relacion = f" ({latex_escape(p['relacion'])})" if p.get("relacion") else ""
    return latex_escape(p["nombre"]) + relacion


def _lista(items: List[str]) -> str:
    if not items:
        return r" \pendiente\par"
    return "\\begin{itemize}[leftmargin=1.2em,itemsep=1pt]\n" + "\n".join(f"\\item {i}" for i in items) + "\n\\end{itemize}"


def render_latex(b: dict, generado: datetime) -> str:
    """LaTeX source of the draft. `b` is the restored Borrador as a dict."""
    titulos = [titulo for titulo, _, _ in SECCIONES]
    partes = [PREAMBULO, r"""
\begin{center}
\includegraphics[width=1.9cm]{logo.png}\\[2pt]
{\large\color{acento} Mi Voluntad}\\[4pt]
{\LARGE\bfseries\color{acento} Borrador orientativo de testamento}\\[4pt]
{\small Para preparar la cita con el notario · Generado el """ + generado.strftime("%d/%m/%Y a las %H:%M") + r"""}
\end{center}
\vspace{4pt}
\fcolorbox{gray}{gray!8}{\parbox{\dimexpr\linewidth-2\fboxsep-2\fboxrule}{\small
\textbf{Este documento no es un testamento ni tiene validez legal.} Recoge, de forma orientativa, los deseos
expresados en una conversación con un asistente de inteligencia artificial, para facilitar la consulta con el notario.
No constituye asesoramiento jurídico. No lo firme ni lo copie a mano como si fuera un testamento.}}
\vspace{6pt}
"""]

    partes.append(f"\\section*{{{latex_escape(titulos[0])}}}\n")
    partes.append(r"\campo{Residencia}{" + _valor(b.get("residencia")) + "}")
    if b.get("vecindad_foral"):
        partes.append(r"\campo{Derecho civil propio}{" + latex_escape(b["vecindad_foral"]) + "}")
    partes.append(r"\campo{Estado civil}{" + _valor(b.get("estado_civil")) + "}")
    if b.get("regimen_economico") or b.get("conyuge"):
        partes.append(r"\campo{Régimen económico del matrimonio}{" + _valor(b.get("regimen_economico")) + "}")
        partes.append(r"\campo{Cónyuge}{" + _persona(b.get("conyuge")) + "}")
    partes.append(r"\textbf{Hijos:}" + _lista([_persona(h) for h in b.get("hijos", [])]))
    if b.get("nietos_de_hijos_fallecidos"):
        partes.append(r"\textbf{Nietos de hijos fallecidos:}" + _lista([_persona(n) for n in b["nietos_de_hijos_fallecidos"]]))
    if b.get("ascendientes_vivos"):
        partes.append(r"\campo{Ascendientes}{" + latex_escape(b["ascendientes_vivos"]) + "}")
    partes.append(r"\campo{Testamento anterior}{" + _valor(b.get("testamento_anterior")) + "}")

    partes.append(f"\\section*{{{latex_escape(titulos[1])}}}\n")
    partes.append(r"\textbf{Herederos:}" + _lista([_persona(h) for h in b.get("herederos", [])]))
    partes.append(r"\campo{Reparto}{" + _valor(b.get("reparto")) + "}")
    legados = [
        f"{latex_escape(l['bien'])} $\\rightarrow$ {latex_escape(l['beneficiario'])}"
        + (f" ({latex_escape(l['observaciones'])})" if l.get("observaciones") else "")
        for l in b.get("legados", [])
    ]
    partes.append(r"\textbf{Bienes concretos para personas concretas (legados):}" + _lista(legados))
    partes.append(r"\campo{Si un heredero falta (sustitución)}{" + _valor(b.get("sustitucion")) + "}")
    if b.get("conyuge") or b.get("disposicion_conyuge"):
        partes.append(r"\campo{Para el cónyuge}{" + _valor(b.get("disposicion_conyuge")) + "}")

    partes.append(f"\\section*{{{latex_escape(titulos[2])}}}\n")
    partes.append(r"\textbf{Bienes mencionados:}" + _lista([latex_escape(x) for x in b.get("inmuebles_y_bienes", [])]))
    partes.append(r"\campo{Bienes en el extranjero}{" + _valor(b.get("bienes_extranjero")) + "}")
    partes.append(r"{\small\color{gray} Para los inmuebles, el notario pedirá ubicación, superficie, linderos, referencia "
                  r"catastral y datos del Registro de la Propiedad.}\par")

    partes.append(f"\\section*{{{latex_escape(titulos[3])}}}\n")
    partes.append(r"\campo{Albacea}{" + _persona(b.get("albacea")) + "}")
    partes.append(r"\campo{Contador-partidor}{" + _persona(b.get("contador_partidor")) + "}")

    partes.append(f"\\section*{{{latex_escape(titulos[4])}}}\n")
    partes.append(r"\campo{Funeral}{" + _valor(b.get("funeral")) + "}")
    partes.append(r"\campo{Tutela o medidas de apoyo}{" + _valor(b.get("tutela_o_apoyos")) + "}")
    partes.append(r"\campo{Animales de compañía}{" + _valor(b.get("animales")) + "}")
    partes.append(r"\campo{Legado digital}{" + _valor(b.get("legado_digital")) + "}")

    if b.get("avisos"):
        partes.append(r"\section*{\color{acento}Aspectos a revisar con el notario}" + _lista([latex_escape(a) for a in b["avisos"]]))
    if b.get("dudas_para_el_notario"):
        partes.append(r"\section*{Dudas para preguntar al notario}" + _lista([latex_escape(d) for d in b["dudas_para_el_notario"]]))

    partes.append(r"\vfill{\small\color{gray}" + latex_escape(CIERRE) + r"}" + "\n\\end{document}\n")
    return "\n".join(partes)


def compilar(latex: str) -> bytes:
    """Compile with pdflatex (no shell escape) in a temporary folder that is deleted afterwards."""
    with tempfile.TemporaryDirectory() as tmp:
        tex = Path(tmp) / "borrador.tex"
        tex.write_text(latex, encoding="utf-8")
        shutil.copy(LOGO, Path(tmp) / "logo.png")
        for _ in range(2):  # second pass resolves "página X de Y"
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", tex.name],
                cwd=tmp, capture_output=True, timeout=60,
            )
        pdf = Path(tmp) / "borrador.pdf"
        if result.returncode != 0 or not pdf.exists():
            log = result.stdout.decode("utf-8", errors="replace")
            raise RuntimeError("Error al compilar el PDF: " + log[-800:])
        return pdf.read_bytes()


def generar_pdf(llm, history: List[Dict[str, str]], privacy_map: Dict[str, dict]) -> bytes:
    """Whole pipeline: masked conversation -> answers -> real data restored locally -> PDF."""
    borrador = extraer(llm, history)
    restaurado = _restore(borrador.model_dump(), Pseudonymizer(privacy_map))
    return compilar(render_latex(restaurado, datetime.now()))
