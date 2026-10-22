# Privacidad: diseño técnico

Objetivo: que la IA externa **nunca vea datos personales reales**, que lo que se guarda esté **cifrado
y bajo control del usuario**, y que todo se **borre** a petición o, como mucho, a los 30 días sin uso.
(El texto para los usuarios está en `web/privacidad.html`, pendiente de revisión jurídica.)

## Qué sale del equipo

| Destino | Qué recibe | Cuándo |
|---|---|---|
| Anthropic (Claude) | Texto **seudonimizado**: mensajes, documentos y respuestas con `[PERSONA_1]`, `[DNI_1]`… | Cada mensaje y al generar el PDF |
| Nominatim (OpenStreetMap) | Solo el nombre del municipio | Si se piden notarías |
| Google Places (opcional) | Solo el nombre del municipio | Si se piden notarías y hay clave |

La voz (Whisper local; el audio se borra al transcribirlo), las fotos y el OCR, la tabla de correspondencia, el PDF con los nombres reales y los embeddings se
procesan **en local**.

## Seudonimización (`src/privacy/pseudonymizer.py`)

1. **Regex españolas** (prioridad): DNI/NIE con letra validada, IBAN, teléfono, email, dirección postal,
   referencia catastral, nº de protocolo, fórmulas notariales («DOÑA …», «Ante mí, …, Notario») y
   «me llamo …».
2. **Microsoft Presidio** en español: NIF/NIE/pasaporte, IBAN con dígito de control, teléfono (región
   ES), URL, nombres con spaCy `es_core_news_md` y un **diccionario de nombres de pila** (con y sin
   tilde; los que también son palabras comunes —Dolores, Paz, Rosa— solo con mayúscula).
3. Se recortan palabras de más («paco nada» → solo «paco») para no cambiar el sentido.
4. **Etiquetas estables**: la misma persona siempre es la misma etiqueta («Marta» = «MARTA PÉREZ SANZ»).
5. Lo que la persona escribe después también se enmascara con los nombres ya conocidos.
6. La respuesta de Claude se **restaura** en local antes de mostrarse.
7. Municipios y fechas **no** se ocultan: hacen falta para el derecho aplicable y los plazos.

Resultados medidos en `benchmarks/resultados.md` (37/37 datos ocultados, 0 falsos positivos).

## Cifrado (`src/privacy/store.py`)

- Cada conversación es un archivo `data/conversaciones/<id>.bin` cifrado con **AES-256-GCM**
  (`cryptography`), con nonce aleatorio por escritura y el id como dato autenticado.
- La **clave la genera el servidor al aceptar la política y se entrega una sola vez al navegador**.
  El servidor no la guarda: sin el dispositivo del usuario el archivo es ilegible (cifrado en reposo).
- El navegador guarda en `localStorage` el id, la clave, los mensajes que se ven en pantalla y su versión
  enmascarada (para el botón «Ver lo que vio la IA»).
- La tabla de correspondencia **no** se envía nunca al navegador.

## Borrado

| Mecanismo | Qué borra |
|---|---|
| Botón «🗑️ Borrar mis datos» | El archivo cifrado del servidor y la conversación del navegador |
| «Borrar todas mis conversaciones» | Todas las del navegador y sus archivos en el servidor |
| Automático, servidor | Al arrancar y cada hora: archivos sin uso durante `RETENTION_DAYS` (30) |
| Automático, navegador | Al abrir la página: conversaciones con más de 30 días sin uso |
| WhatsApp | Comando «borrar» y caducidad de 30 días (en memoria) |
| PDF | No se guarda: se compila en una carpeta temporal que se elimina |

## Límites y riesgos conocidos (sea honesto en la demo)

- **Mientras se procesa un mensaje**, los datos están en claro en la memoria del servidor.
- **El navegador** guarda en claro los mensajes que se ven en pantalla (incluidos nombres): están en el
  dispositivo del propio usuario y se borran con los mecanismos anteriores.
- **Cuasi-identificadores**: municipio + fechas + importes podrían reidentificar a alguien en un pueblo
  pequeño. La seudonimización reduce el riesgo, no lo elimina.
- **Detección imperfecta**: un nombre poco común escrito en minúscula y sin contexto puede escaparse.
- **WhatsApp**: sus sesiones están en memoria sin cifrar (canal aparcado).
- El proveedor de IA recibe texto seudonimizado: hay que revisar su contrato de encargado del
  tratamiento y las garantías de transferencia internacional antes de un uso real.

## RGPD: correspondencia

| Principio / artículo | Implementación |
|---|---|
| Consentimiento (6.1.a, 9.2.a) | Botón «Acepto» antes de poder escribir; se registra la fecha en el estado cifrado |
| Minimización (5.1.c) | No se pide nombre, DNI ni dirección exacta |
| Limitación del plazo (5.1.e) | Borrado automático a los 30 días |
| Seudonimización y cifrado (32) | Etiquetas antes de la IA; AES-256-GCM en reposo |
| Derecho de supresión (17) | Botón de borrado inmediato |
| Transparencia IA (art. 50 Reglamento de IA) | Se informa de que es una IA en la bienvenida y en la política |
