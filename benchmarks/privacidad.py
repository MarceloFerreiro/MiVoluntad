"""Compara detectores de datos personales sobre textos ficticios en español anotados a mano.

Uso: python -m benchmarks.privacidad

Para cada configuración de detectores mide:
- Cobertura: qué parte de los datos anotados queda totalmente oculta (por tipo).
- Falsos positivos: fragmentos ocultados que no eran datos personales.
- Tiempo por texto en CPU.
Todos los nombres, DNI, cuentas y direcciones son inventados.
"""
import time
from collections import defaultdict

from src.privacy.pseudonymizer import DNI_LETTERS, Pseudonymizer


def dni(number: int) -> str:
    """DNI con letra válida."""
    return f"{number:08d}{DNI_LETTERS[number % 23]}"


DNI_A, DNI_B, DNI_C = dni(12345678), dni(45678912), dni(30112233)

# (texto, [(tipo, dato), ...]). El tipo solo sirve para el desglose; cuenta que el dato quede oculto.
CASOS = [
    (
        "testamento notarial (mayúsculas, fórmulas)",
        f"""NÚMERO OCHOCIENTOS DIECISIETE. Protocolo nº 817.
TESTAMENTO ABIERTO. En Toledo, a quince de marzo de dos mil veinticuatro.
Ante mí, ANTONIO RUIZ MARTÍN, Notario del Ilustre Colegio de Castilla-La Mancha, con residencia en Toledo,
COMPARECE: DOÑA ROSARIO PÉREZ GÓMEZ, mayor de edad, viuda, vecina de Toledo, con domicilio en la calle Alfonso VI, número 12, 3º B, y con DNI {DNI_A}.
DISPONE: PRIMERA.- Lega a su hija DOÑA MARTA PÉREZ SANZ, en concepto de mejora, la vivienda sita en la calle Alfonso VI, número 12, de Toledo, con referencia catastral 1234567VK1213S0001AB.
SEGUNDA.- Instituye herederos por partes iguales a sus hijos DON JORGE PÉREZ SANZ y DOÑA MARTA PÉREZ SANZ.
TERCERA.- Nombra albacea a su sobrino DON LUIS GÓMEZ ORTIZ.""",
        [("PERSONA", "ANTONIO RUIZ MARTÍN"), ("PERSONA", "ROSARIO PÉREZ GÓMEZ"), ("PERSONA", "MARTA PÉREZ SANZ"),
         ("PERSONA", "JORGE PÉREZ SANZ"), ("PERSONA", "LUIS GÓMEZ ORTIZ"), ("DIRECCION", "calle Alfonso VI, número 12, 3º B"),
         ("DIRECCION", "calle Alfonso VI, número 12"),
         ("DNI", DNI_A), ("REF_CATASTRAL", "1234567VK1213S0001AB"), ("PROTOCOLO", "817")],
    ),
    (
        "testamento en texto libre",
        f"""Yo, Manuel Ortega Ruiz, con DNI {DNI_B}, en pleno uso de mis facultades, dejo dicho lo siguiente.
A mi mujer, Pilar Sánchez Mora, le dejo el usufructo de la casa de la Avenida de América 45, 2º izquierda, en Madrid.
A mi nieto Álvaro le dejo el reloj de su abuelo, y a mi hija Inés el dinero de la cuenta ES91 2100 0418 4502 0005 1332.
Si hay cualquier duda, que llamen a mi sobrino Ramón al 655 123 456.""",
        [("PERSONA", "Manuel Ortega Ruiz"), ("DNI", DNI_B), ("PERSONA", "Pilar Sánchez Mora"),
         ("DIRECCION", "Avenida de América 45, 2º izquierda"), ("PERSONA", "Álvaro"), ("PERSONA", "Inés"),
         ("IBAN", "ES91 2100 0418 4502 0005 1332"), ("PERSONA", "Ramón"), ("TELEFONO", "655 123 456")],
    ),
    (
        "mensajes de chat",
        """Mi hija Lucía Fernández es la que me cuida desde que murió mi marido, Ernesto.
Mi hijo Andrés vive en Bilbao y casi no viene. Si quiere escribirme, mi correo es manolo.ortega@hotmail.com
y mi móvil el 699 88 77 66.""",
        [("PERSONA", "Lucía Fernández"), ("PERSONA", "Ernesto"), ("PERSONA", "Andrés"),
         ("EMAIL", "manolo.ortega@hotmail.com"), ("TELEFONO", "699 88 77 66")],
    ),
    (
        "carta administrativa",
        f"""Estimada Sra. Dña. Carmen López Vidal:
En relación con su expediente, le comunicamos que la notificación se remitió a su domicilio en Plaza Mayor 7, 1º A, de Valladolid.
Constan como interesados usted, con DNI {DNI_C}, y su hermano D. Francisco López Vidal, con NIE X1234567L.
Puede contactar con la gestora, Elena Marín, en el 983 456 789 o en elena.marin@gestoria-ejemplo.es.""",
        [("PERSONA", "Carmen López Vidal"), ("DIRECCION", "Plaza Mayor 7, 1º A"), ("DNI", DNI_C),
         ("PERSONA", "Francisco López Vidal"), ("NIE", "X1234567L"), ("PERSONA", "Elena Marín"),
         ("TELEFONO", "983 456 789"), ("EMAIL", "elena.marin@gestoria-ejemplo.es")],
    ),
    (
        "caso difícil (minúsculas, sin tildes)",
        """quiero dejarle la casa a mi sobrina maria jose porque me cuida, y a mi hermano paco nada de nada.
la casa esta en calle real 14 de segovia. mi dni lo tiene mi hija rocio.""",
        [("PERSONA", "maria jose"), ("PERSONA", "paco"), ("DIRECCION", "calle real 14"), ("PERSONA", "rocio")],
    ),
    (
        "sin datos personales (falsos positivos)",
        """Según el artículo 808 del Código Civil, la legítima de los hijos es de dos terceras partes de la herencia.
El Notario y el Tribunal Supremo han señalado que en Castilla y León se aplica el derecho común.
La Ley 39/2015 regula el procedimiento administrativo. El Registro General de Actos de Última Voluntad depende del Ministerio de Justicia.""",
        [],
    ),
    (
        "chat en minúscula sin nombres (falsos positivos del diccionario)",
        """tengo dolores de cabeza y la tensión alta, que dios nos de paz y salud.
en el jardín tengo una rosa preciosa y la tina del baño está rota. mi coche es un mercedes viejo.
fui a la cruz roja y a la farmacia. que alegría que me lo explique tan clara, de verdad.
quiero que mis hijos esten bien y que no se peleen, tengo fe en que el notario me ayude.
a mi edad uno ya no esta para sustos, la luz me la pagan mis nietos. el domingo voy a misa.""",
        [],
    ),
]

# nombre -> (detectores de modelo, usar nuestras regex españolas)
# Resultados anteriores (OpenAI Privacy Filter, descartado) en benchmarks/resultados.md
CONFIGS = {
    "regex": ([], True),
    "regex+spacy": (["spacy"], True),
    "presidio": (["presidio"], False),
    "regex+presidio": (["presidio"], True),
}


def evaluar(ner, regex):
    stats = defaultdict(lambda: [0, 0])  # tipo -> [ocultos, total]
    falsos, escapados, extendidos, tiempos = [], [], [], []
    for nombre, texto, gold in CASOS:
        pseudo = Pseudonymizer(ner=ner, regex=regex)
        t = time.time()
        spans = pseudo._detect(texto)
        tiempos.append(time.time() - t)
        covered = set()
        for start, end, _ in spans:
            covered.update(range(start, end))

        gold_chars = set()
        for kind, value in gold:
            positions = [i for i in range(len(texto)) if texto.startswith(value, i)]
            assert positions, f"{value!r} no está en el caso {nombre!r}"
            for i in positions:
                gold_chars.update(range(i, i + len(value)))
            stats[kind][1] += 1
            if all(set(range(i, i + len(value))) <= covered for i in positions):
                stats[kind][0] += 1
            else:
                escapados.append(f"{kind}:{value!r} ({nombre})")

        for start, end, kind in spans:
            chars = set(range(start, end))
            if not chars & gold_chars:
                falsos.append(f"{kind}:{texto[start:end]!r} ({nombre})")
            elif any(texto[i].isalpha() for i in chars - gold_chars):
                # Oculta palabras de más junto a un dato real ("paco nada"): puede cambiar el sentido
                extendidos.append(f"{kind}:{texto[start:end]!r} ({nombre})")
    return stats, falsos, escapados, extendidos, tiempos


def main():
    resultados = {}
    for nombre, (ner, regex) in CONFIGS.items():
        Pseudonymizer(ner=ner, regex=regex)._detect("Calentamiento de modelos.")  # no contar la carga inicial
        resultados[nombre] = evaluar(ner, regex)

    tipos = sorted({kind for _, _, gold in CASOS for kind, _ in gold})
    print(f"{'tipo':14}" + "".join(f"{n:>18}" for n in CONFIGS))
    for kind in tipos + ["TOTAL"]:
        fila = f"{kind:14}"
        for nombre in CONFIGS:
            stats = resultados[nombre][0]
            ok = sum(v[0] for v in stats.values()) if kind == "TOTAL" else stats[kind][0]
            total = sum(v[1] for v in stats.values()) if kind == "TOTAL" else stats[kind][1]
            fila += f"{f'{ok}/{total}':>18}"
        print(fila)
    print(f"{'falsos +':14}" + "".join(f"{len(resultados[n][1]):>18}" for n in CONFIGS))
    print(f"{'de más':14}" + "".join(f"{len(resultados[n][3]):>18}" for n in CONFIGS))
    print(f"{'ms/texto':14}" + "".join(f"{1000 * sum(resultados[n][4]) / len(CASOS):>18.0f}" for n in CONFIGS))

    for nombre in CONFIGS:
        stats, falsos, escapados, extendidos, _ = resultados[nombre]
        print(f"\n[{nombre}] datos que se escapan:")
        for e in escapados:
            print("   ", e)
        if not escapados:
            print("    ninguno")
        print(f"[{nombre}] falsos positivos:")
        for f in falsos:
            print("   ", f)
        if not falsos:
            print("    ninguno")
        print(f"[{nombre}] ocultado de más:")
        for e in extendidos:
            print("   ", e)
        if not extendidos:
            print("    ninguno")


if __name__ == "__main__":
    main()
