# Resultados de `benchmarks/privacidad.py`

6 textos ficticios en español, 35 datos personales anotados a mano (19 nombres).
"Ocultado" = el dato queda completamente tapado. CPU, sin GPU (8 núcleos, 15 GB RAM).

## 2026-10-22 · OpenAI Privacy Filter (opf) — descartado

Modelo local de 1.500M parámetros (50M activos), pesos de 2,7 GB, ~4 GB de RAM.

| | regex | regex + spaCy | regex + opf | regex + opf + spaCy |
|---|---|---|---|---|
| Nombres ocultados | 6/19 | 16/19 | 14/19 | 18/19 |
| Total ocultado | 22/35 | 32/35 | 30/35 | 34/35 |
| Falsos positivos | 0 | 0 | 0 | 0 |
| Tiempo medio por texto | 0 ms | 9 ms | ~5,8 s | ~5,8 s |

- opf solo, peor que spaCy: se le escapan nombres de pila sueltos ("Álvaro", "Inés", "Ramón", "Ernesto").
- Aporta en nombres en minúscula y sin tildes ("maria jose", "rocio"), que spaCy no ve.
- Velocidad en CPU: ~15 ms por carácter (frase corta 0,4 s; testamento de 1.264 caracteres ~20 s).
- Con opf + spaCy solo se escapó "paco" (caso difícil en minúsculas).
- Motivo del descarte: se sustituye por Microsoft Presidio (ver abajo).

## 2026-10-22 · Microsoft Presidio (presidio-analyzer 2.2.364) — en uso

Desde aquí el banco de pruebas tiene 7 textos: se añadió un chat en minúscula **sin nombres**
lleno de palabras que también son nombres ("dolores", "paz", "rosa", "tina", "cruz", "mercedes")
para medir falsos positivos del diccionario, y el IBAN de prueba pasó a ser uno válido.

Presidio configurado en español: motor spaCy `es_core_news_md`, reconocedores españoles
(NIF, NIE, pasaporte), email, IBAN, tarjeta, teléfono (región ES), URL y un **diccionario de
nombres de pila** (`src/privacy/nombres_es.py`, con y sin tildes; los que son también palabras
comunes solo cuentan con mayúscula).

| | regex | regex + spaCy | Presidio solo | regex + Presidio |
|---|---|---|---|---|
| Nombres ocultados | 6/19 | 16/19 | 14/19 | **19/19** |
| Total ocultado | 23/36 | 33/36 | 24/36 | **36/36** |
| Falsos positivos | 0 | 0 | 0 | **0** |
| Ocultado de más | 0 | 0 | 0 | **0** |
| Tiempo medio por texto | 0 ms | 10 ms | 40 ms | 15 ms |

(36 datos: se anotó también la dirección completa con piso. "Ocultado de más" = el span se come
palabras junto a un dato real, p. ej. "paco nada" -> "[PERSONA]", que cambia el sentido.)

- Presidio solo no basta en español: no reconoce direcciones españolas, referencia catastral,
  número de protocolo ni nombres en MAYÚSCULAS de las escrituras. Nuestras regex siguen siendo necesarias.
- El diccionario de nombres resuelve los nombres en minúscula del chat ("maria jose", "paco", "rocio").
- Ajustes hechos al ver falsos positivos: "tina" y "marcos" pasaron a "solo con mayúscula".
- spaCy marcaba "paco nada" como nombre y se perdía "nada": ahora se recortan por los extremos las
  palabras en minúscula que no son nombres del diccionario.
- Ojo: el diccionario y los casos los escribió la misma persona; validar con textos reales.

### Actualización: regla "me llamo …"

Se añadió al chat de prueba "me llamo rosario" (nombre ambiguo, en minúscula). Nueva regla de
contexto: lo que sigue a "me llamo" / "mi nombre es" es un nombre aunque esté en minúscula.
Resultado regex + Presidio: **37/37**, 0 falsos positivos, 0 ocultado de más.
