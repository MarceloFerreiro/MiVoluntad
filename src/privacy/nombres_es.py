"""Diccionario de nombres de pila españoles para el reconocedor de Presidio.

Sirve para los nombres escritos en minúscula o sin tilde en el chat ("mi sobrina maria jose"),
que el modelo de spaCy no detecta. Se reconocen también sin tildes.
"""

# Nombres que nunca son palabras comunes: se reconocen en mayúscula o minúscula
NOMBRES = """
María, Carmen, Ana, Isabel, Laura, Cristina, Marta, Lucía, Paula, Elena, Sara, Raquel, Beatriz,
Silvia, Patricia, Nuria, Sandra, Irene, Andrea, Julia, Sofía, Teresa, Rocío, Inés, Eva, Mónica,
Lorena, Montserrat, Yolanda, Susana, Josefa, Francisca, Antonia, Manuela, Juana, Encarnación,
Ángela, Inmaculada, Natalia, Noelia, Verónica, Esther, Alicia, Claudia, Miriam, Begoña, Rebeca,
Vanesa, Olga, Ainhoa, Itziar, Aurora, Celia, Adriana, Lidia, Carla, Daniela, Martina, Valeria,
Emilia, Carlota, Mercedes, Ramona, Felisa, Gregoria, Petra, Agustina, Benita, Matilde, Antonio,
José, Manuel, Francisco, David, Juan, Javier, Daniel, Carlos, Alejandro, Miguel, Rafael, Pedro,
Pablo, Sergio, Fernando, Jorge, Luis, Alberto, Álvaro, Diego, Adrián, Raúl, Enrique, Ramón,
Vicente, Iván, Rubén, Óscar, Andrés, Joaquín, Santiago, Eduardo, Víctor, Roberto, Jaime, Mario,
Ignacio, Alfonso, Ricardo, Jordi, Emilio, Julián, Gabriel, Tomás, Agustín, Gonzalo, Félix,
Hugo, Ismael, Cristian, Mariano, Lorenzo, Josep, Gregorio, Ernesto, Marcelo, Arturo, Hernán,
Gerardo, Rodrigo, Martín, Nicolás, Samuel, Iker, Aitor, Asier, Xavier, Benito, Bernardo, Eusebio,
Fermín, Florencio, Saturnino, Teodoro, Valentín, Leandro, Lucas, Mateo, Bruno, Paco, Pepe, Pepa,
Manolo, Manoli, Lola, Loli, Pili, Charo, Conchi, Merche, Maite, Mari, Puri, Nacho, Quique, Chema,
Juanjo, Juanma, Toni, Pepito, Paquita, Rafa, Fran, Kike, Chus, Isa, Bea, Cris, Edu, Javi, Dani,
Santi, Sole, Reme, Tere, Inma, Nieves, Fede, Mila
"""

# Compuestos frecuentes (se buscan antes que los simples)
COMPUESTOS = """
María José, María Jesús, María Carmen, Mari Carmen, María Dolores, María Pilar, María Teresa,
María Isabel, María Ángeles, María Luisa, María Rosa, María Victoria, María Elena, Ana María,
Rosa María, José Luis, José Antonio, José Manuel, José María, José Ramón, José Miguel, José Carlos,
Juan Carlos, Juan José, Juan Antonio, Juan Manuel, Juan Luis, Francisco Javier, Miguel Ángel,
Luis Miguel, Jesús María, Pedro José
"""

# Nombres que también son palabras comunes ("dolores de cabeza", "la paz"): solo con mayúscula inicial
NOMBRES_AMBIGUOS = """
Pilar, Dolores, Rosario, Mercedes, Amparo, Consuelo, Soledad, Remedios, Asunción, Concepción,
Victoria, Esperanza, Luz, Paz, Cruz, Blanca, Ángeles, Nieves, Milagros, Socorro, Purificación,
Visitación, Patrocinio, Fe, Gracia, Reyes, Salud, Alegría, Feliciano, Domingo, Leal, Bueno, Cristo,
Santos, Ventura, Rosa, Clara, Gloria, Alba, Margarita, Concha, Fina, Tono, Encarna, Ángel, Jesús, Salvador,
Tina, Marcos
"""


def _split(block: str) -> list:
    return [n.strip() for n in block.replace("\n", " ").split(",") if n.strip()]


def _sin_tildes(name: str) -> str:
    return name.translate(str.maketrans("áéíóúÁÉÍÓÚüÜ", "aeiouAEIOUuU"))


def con_variantes(names: list) -> list:
    """Cada nombre con y sin tildes, sin duplicados, de más largo a más corto."""
    out = set()
    for name in names:
        out.add(name)
        out.add(_sin_tildes(name))
    return sorted(out, key=len, reverse=True)


AMBIGUOS = con_variantes(_split(NOMBRES_AMBIGUOS))
_ambiguos_lower = {n.lower() for n in AMBIGUOS}
CUALQUIER_CASO = con_variantes(
    [n for n in _split(COMPUESTOS) + _split(NOMBRES) if n.lower() not in _ambiguos_lower]
)

# Palabras sueltas de los nombres, en minúscula y sin tildes, para recortar spans ("paco nada" -> "paco")
NAME_TOKENS = {
    _sin_tildes(word).lower()
    for name in CUALQUIER_CASO + AMBIGUOS
    for word in name.split()
}
