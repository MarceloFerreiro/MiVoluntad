# Contexto: el problema y el alcance

## El reto

Reto 1 del Datathon de Brecha Judicial, «La desigualdad silenciosa»: muchas personas mayores no pueden
ejercer sus derechos en igualdad porque los trámites dependen de herramientas digitales, lenguaje
técnico y desplazamientos. El caso de uso del reto (una viuda de 78 años en un pueblo de Soria que
pierde una herencia por no entender una notificación) muestra el coste real de esa brecha.

Nuestra respuesta se centra en un trámite concreto y frecuente: **hacer testamento**. Mucha gente mayor
lo pospone por miedo, desconocimiento del lenguaje jurídico o por no saber qué llevar al notario.

## Qué hace Mi Voluntad

1. **Explica** en lenguaje sencillo, tratando de usted, los tipos de testamento, cómo se reparte la
   herencia (legítimas, mejora, libre disposición), qué es un albacea, cuánto cuesta…
2. **Guía un cuestionario** (situación familiar, reparto, bienes, cargos, deseos personales) sin agobiar.
3. **Genera un PDF del borrador** con las respuestas, para enseñárselo al notario. Lleva marca de agua
   diagonal «BORRADOR SIN VALIDEZ LEGAL» y la nota «Generado con IA · no vinculante».
4. **Lee fotos de documentos** (por ejemplo, un testamento anterior) y explica qué dicen.
5. **Indica dónde acudir**: el Colegio Notarial de su comunidad, el buscador oficial de notarios y,
   si se configura Google Maps, notarías cercanas con teléfono y horario.

## Qué NO hace

- No da asesoramiento jurídico ni garantiza la validez de nada.
- No redacta un testamento: el único válido es el que autoriza el notario (o el ológrafo que cumple
  los requisitos del Código Civil). El PDF dice expresamente que no se firme ni se copie a mano.
- No pide nombre, DNI ni dirección exacta: eso lo pide el notario.

## Ámbito: España

| Aspecto | Cómo lo trata el asistente |
|---|---|
| Derecho común | Se basa en el Código Civil, que rige la sucesión en la mayor parte de España. |
| Derechos forales | Cataluña, Aragón, Navarra, País Vasco, Galicia y Baleares tienen derecho civil propio (legítimas distintas, pactos sucesorios, testamento mancomunado…). Lo que cuenta es la **vecindad civil**. El asistente avisa y remite al notario. |
| Impuesto sobre Sucesiones | Lo regula cada comunidad autónoma. El asistente no calcula impuestos y remite a un asesor o a la hacienda autonómica. |
| Notarios | Ley del Notariado (1862, texto consolidado). Libre elección de notario. Honorarios fijados por el Arancel (RD 1426/1989). |
| Datos e IA | RGPD (Reglamento (UE) 2016/679) y Reglamento de IA (Reglamento (UE) 2024/1689): transparencia sobre el uso de IA y protección de datos. |

## Reglas jurídicas que el asistente no puede fallar

El reparto con hijos en Derecho común se explica siempre igual (art. 806 y siguientes del CC):

- La herencia se divide en **tres tercios**: legítima estricta, mejora y libre disposición.
- La **legítima estricta** (un tercio) se reparte a partes iguales entre todos los hijos.
- La **mejora** (un tercio) puede ir entera a un hijo o nieto.
- La **libre disposición** (un tercio) puede ir a cualquiera.
- Error frecuente de los modelos: decir que la legítima estricta son «dos tercios». Los dos tercios son
  la legítima *larga* (estricta + mejora). El prompt lo prohíbe expresamente y el servidor repite la
  respuesta si aparece la frase incorrecta (ver ARQUITECTURA.md).

## Usuarios y tono

Personas mayores, con poca soltura digital y, a menudo, con miedo a equivocarse: frases cortas, una o
dos preguntas por mensaje, términos jurídicos explicados en el momento, letra grande en la web y uso
desde el móvil (también para fotografiar documentos).

## Limitaciones conocidas

- El modelo puede equivocarse: las respuestas son orientativas y hay un banco de pruebas, pero no una
  validación jurídica exhaustiva.
- La letra manuscrita (testamentos ológrafos) no se lee: el OCR solo funciona con texto impreso.
- Sin clave de Google Maps no se listan notarías concretas, solo el Colegio Notarial y el buscador oficial.
- La política de privacidad es un borrador que debe revisar un jurista.
