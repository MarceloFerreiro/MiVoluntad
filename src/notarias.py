"""Notarías cercanas a una localidad española.

1. Siempre: el Colegio Notarial de la comunidad autónoma (datos oficiales de notariado.org)
   y el buscador oficial "Elige a tu notario". La localidad se sitúa con Nominatim
   (OpenStreetMap), que solo recibe el nombre del municipio, nunca datos personales.
2. Opcional: notarías concretas con teléfono y horario de Google Places, si hay
   GOOGLE_MAPS_API_KEY en .env (requiere una cuenta de Google Cloud con facturación).

OpenStreetMap no se usa para listar notarías: en las pruebas tenía muy pocas registradas
(1 en 8 km de Toledo) y casi ninguna con teléfono u horario.
"""
import os
import time
import unicodedata
from functools import lru_cache
from typing import Dict, List, Optional

import requests

USER_AGENT = "TestamentoFacil/0.1 (prototipo datathon brecha judicial)"
BUSCADOR_OFICIAL = "https://www.notariado.org/portal/elige-a-tu-notario-orden"
# Copiado de https://www.notariado.org/portal/colegios-notariales (consultado el 22/10/2026)
FECHA_DATOS_COLEGIOS = "22/10/2026"

COLEGIOS: Dict[str, dict] = {
    "Andalucía": {"sedes": ["Sevilla: San Miguel, 1, 41002 Sevilla · Tel. 954 915 944",
                            "Granada: San Jerónimo, 50, 18001 Granada · Tel. 958 202 711"],
                  "email": "colegio@andalucia.notariado.org", "web": "https://andalucia.notariado.org"},
    "Aragón": {"sedes": ["Plaza del Justicia, 2, 50003 Zaragoza · Tel. 976 203 780"],
               "email": "info@aragon.notariado.org", "web": "https://aragon.notariado.org"},
    "Asturias": {"sedes": ["Pl. Alfonso II el Casto, 12, 33003 Oviedo · Tel. 985 213 008"],
                 "email": "colegio@asturias.notariado.org", "web": "https://asturias.notariado.org"},
    "Cantabria": {"sedes": ["Avenida de los Infantes, 5 (acceso por Sojo y Lomba), 39005 Santander · Tel. 942 274 011"],
                  "email": "colegio@cantabria.notariado.org", "web": "https://cantabria.notariado.org"},
    "Castilla y León": {"sedes": ["Burgos: Almirante Bonifaz, 18, 1º, 09003 Burgos · Tel. 947 203 874",
                                 "Valladolid: Teresa Gil, 14, 47002 Valladolid · Tel. 983 217 775"],
                        "email": "info@castillayleon.notariado.org", "web": "https://castillayleon.notariado.org"},
    "Castilla-La Mancha": {"sedes": ["Toledo: Avda. de Europa, 14 (entrada por C/ Berna, 2), 45003 Toledo · Tel. 925 299 457",
                                     "Albacete: C. Marqués de Molíns, 4, 02001 Albacete · Tel. 967 215 305"],
                           "email": "colegio@castilla-lamancha.notariado.org", "web": "https://castilla-lamancha.notariado.org"},
    "Cataluña": {"sedes": ["Calle Notariat, 4, 08001 Barcelona · Tel. 933 174 800"],
                 "email": "info@catalunya.notariado.org", "web": "https://www.colegionotarial.org/"},
    "Extremadura": {"sedes": ["C/ Muñoz Chaves, 10 (oficinas: C/ Camberos, 1), 10003 Cáceres · Tel. 927 245 143"],
                    "email": "colegio@extremadura.notariado.org", "web": "https://extremadura.notariado.org"},
    "Galicia": {"sedes": ["Arzobispo Lago, 12, 15004 A Coruña · Tel. 981 120 481"],
                "email": "info@galicia.notariado.org", "web": "https://galicia.notariado.org"},
    "La Rioja": {"sedes": ["República Argentina, 9, 1ª planta, 26002 Logroño · Tel. 941 273 504"],
                 "email": "colegio@larioja.notariado.org", "web": "https://larioja.notariado.org"},
    "Islas Baleares": {"sedes": ["C/ Vía Roma, 4, 07012 Palma de Mallorca · Tel. 971 712 244"],
                       "email": "colegio@baleares.notariado.org", "web": "https://baleares.notariado.org"},
    "Canarias": {"sedes": ["Las Palmas: C. Los Balcones, 18, 35001 Las Palmas de G.C. · Tel. 928 336 178",
                           "Santa Cruz de Tenerife: Calle Viera y Clavijo, 42 · Tel. 922 298 066"],
                 "email": "colegio@canarias.notariado.org", "web": "https://canarias.notariado.org"},
    "Comunidad de Madrid": {"sedes": ["C/ de Ruiz de Alarcón, 3, 28014 Madrid · Tel. 912 130 000"],
                            "email": "info@madrid.notariado.org", "web": "https://madrid.notariado.org"},
    "Región de Murcia": {"sedes": ["Alfaro, 9, 30001 Murcia · Tel. 968 214 511"],
                         "email": "oficialmayor@murcia.notariado.org", "web": "https://murcia.notariado.org"},
    "Navarra": {"sedes": ["Avda. Carlos III el Noble, 27, 31002 Pamplona · Tel. 948 228 938"],
                "email": "info@navarra.notariado.org", "web": "https://navarra.notariado.org"},
    "País Vasco": {"sedes": ["Henao, 8, 48009 Bilbao · Tel. 944 240 560"],
                   "email": "colegio@paisvasco.notariado.org", "web": "https://paisvasco.notariado.org"},
    "Comunidad Valenciana": {"sedes": ["Pascual y Genís, 21, 46002 Valencia · Tel. 963 512 585"],
                             "email": "colegio@cnotarial-valencia.com", "web": "https://valencia.notariado.org"},
}
# Ceuta y Melilla dependen del Colegio de Andalucía
ALIAS_CCAA = {
    "ceuta": "Andalucía", "melilla": "Andalucía", "comunitat valenciana": "Comunidad Valenciana",
    "illes balears": "Islas Baleares", "catalunya": "Cataluña", "euskadi": "País Vasco",
    "comunidad foral de navarra": "Navarra", "principado de asturias": "Asturias",
}
FORALES = {"Cataluña", "Aragón", "Navarra", "País Vasco", "Galicia", "Islas Baleares"}

_last_nominatim_call = 0.0


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def _colegio_para(ccaa: Optional[str]) -> Optional[str]:
    if not ccaa:
        return None
    key = _norm(ccaa)
    for nombre in COLEGIOS:
        if _norm(nombre) in key or key in _norm(nombre):
            return nombre
    for alias, nombre in ALIAS_CCAA.items():
        if alias in key:
            return nombre
    return None


@lru_cache(maxsize=256)
def geolocalizar(localidad: str) -> Optional[dict]:
    """Municipio, provincia y comunidad autónoma de una localidad española (Nominatim, 1 petición/s)."""
    global _last_nominatim_call
    wait = 1.1 - (time.time() - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)  # política de uso de Nominatim: máximo una petición por segundo
    _last_nominatim_call = time.time()
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": localidad, "countrycodes": "es", "format": "json", "addressdetails": 1, "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    address = results[0].get("address", {})
    return {
        "municipio": address.get("city") or address.get("town") or address.get("village") or address.get("municipality"),
        "provincia": address.get("province") or address.get("county"),
        "ccaa": address.get("state"),
        "lat": float(results[0]["lat"]),
        "lon": float(results[0]["lon"]),
    }


def _google_places(localidad: str, lugar: Optional[dict], api_key: str, max_results: int = 6) -> List[dict]:
    """Notarías concretas de Google Places (API New, Text Search)."""
    body = {"textQuery": f"notaría en {localidad}", "languageCode": "es", "regionCode": "ES", "pageSize": max_results}
    if lugar:
        body["locationBias"] = {"circle": {"center": {"latitude": lugar["lat"], "longitude": lugar["lon"]}, "radius": 15000.0}}
    response = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        json=body,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
                                "places.regularOpeningHours.weekdayDescriptions,places.googleMapsUri,places.websiteUri",
        },
        timeout=15,
    )
    response.raise_for_status()
    return [
        {
            "nombre": p.get("displayName", {}).get("text"),
            "direccion": p.get("formattedAddress"),
            "telefono": p.get("nationalPhoneNumber"),
            "horario": "; ".join(p.get("regularOpeningHours", {}).get("weekdayDescriptions", [])),
            "web": p.get("websiteUri"),
            "mapa": p.get("googleMapsUri"),
        }
        for p in response.json().get("places", [])
    ]


def buscar(localidad: str) -> str:
    """Bloque de texto con la información para el asistente (nunca lanza excepciones)."""
    lineas = [f'Notarías cercanas a "{localidad}"']
    try:
        lugar = geolocalizar(localidad)
    except requests.RequestException:
        lugar = None
    if lugar:
        sitio = ", ".join(x for x in (lugar["municipio"] or localidad, lugar["provincia"]) if x)
        lineas.append(f"Localidad encontrada: {sitio} ({lugar['ccaa'] or 'comunidad desconocida'})")
    else:
        lineas.append("No se ha podido situar la localidad en el mapa.")

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if api_key:
        try:
            notarias = _google_places(localidad, lugar, api_key)
            if notarias:
                lineas.append("Notarías encontradas (Google Maps; los horarios pueden cambiar, conviene llamar antes):")
                for i, n in enumerate(notarias, 1):
                    datos = [n["direccion"], f"Tel. {n['telefono']}" if n["telefono"] else "teléfono no disponible",
                             f"Horario: {n['horario']}" if n["horario"] else "horario no disponible", n["mapa"]]
                    lineas.append(f"{i}. {n['nombre']} — " + " — ".join(d for d in datos if d))
            else:
                lineas.append("Google Maps no ha devuelto notarías para esa localidad.")
        except requests.RequestException as e:
            lineas.append(f"No se pudo consultar Google Maps ({type(e).__name__}).")
    else:
        lineas.append("No hay listado de notarías concretas disponible (no está configurado Google Maps).")

    colegio = _colegio_para(lugar["ccaa"] if lugar else None)
    if colegio:
        c = COLEGIOS[colegio]
        lineas.append(f"Colegio Notarial que le corresponde ({colegio}; datos oficiales de notariado.org a {FECHA_DATOS_COLEGIOS}):")
        lineas += [f"- {sede}" for sede in c["sedes"]]
        lineas.append(f"- Email: {c['email']} · Web: {c['web']}")
        if colegio in FORALES:
            lineas.append(f"Nota: en {colegio} hay derecho civil propio en materia de herencias.")
    lineas.append(f"Buscador oficial de notarios del Consejo General del Notariado: {BUSCADOR_OFICIAL}")
    return "\n".join(lineas)


if __name__ == "__main__":
    import sys
    print(buscar(" ".join(sys.argv[1:]) or "Toledo"))
