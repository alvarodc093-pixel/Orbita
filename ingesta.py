"""
============================================================
 ingesta.py — Descarga datos de Launch Library 2 a SQLite
============================================================
Módulo de ingesta del proyecto "Órbita · La industria espacial en cifras".

Flujo:  API pública de Launch Library 2 (https://ll.thespacedevs.com)
        -> copia cruda en data/raw/*.jsonl (caché)
        -> base de datos limpia en data/espacio.db

Recursos descargados:
  - launch   : todos los lanzamientos orbitales/suborbitales (1957 -> hoy)
  - agencies : agencias espaciales y empresas del sector
  - astronauts : astronautas (pasados, presentes y futuros)
  - locations : cosmódromos y centros de lanzamiento
  - pads      : rampas de lanzamiento concretas

La API de Launch Library 2 NO requiere registro ni API key.

Modos de uso:
  python ingesta.py                 # carga inicial completa
  python ingesta.py --update        # añade solo lo nuevo (incremental)
  python ingesta.py --limite 200    # prueba rápida con 200 lanzamientos
  python ingesta.py --sleep 2.0     # espaciado entre peticiones (seg)

Reanudación: si la descarga se interrumpe, al volver a ejecutar el script
se reanuda desde la última página completa sin repetir trabajo.
============================================================
"""

import argparse
import os
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# 1. CONFIGURACIÓN
# --------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent
# La API de producción permite ~15 peticiones/hora. Para la carga histórica completa
# se puede usar el endpoint de desarrollo (sin límite): LL2_BASE_URL=https://lldev.thespacedevs.com/2.0.0/
BASE_URL = os.environ.get("LL2_BASE_URL", "https://ll.thespacedevs.com/2.0.0/")
DB_PATH = RAIZ / "data" / "espacio.db"
RAW_DIR = RAIZ / "data" / "raw"
ESTADO_PATH = RAW_DIR / "_estado.json"

PAGE_SIZE = 100                    # lanzamientos por página (máximo de la API)
PAUSA_DEFECTO = 1.0                # segundos entre peticiones (modificable)
UPDATE_PAGINAS = 3                 # páginas recientes que se refrescan en --update
REINTENTOS = 5                     # reintentos ante fallos de red / 429 / 5xx

# Recursos que ingerimos: (nombre interno, endpoint, parámetros base)
RECURSOS = {
    "launch": ("launch/", {}),
    "agencies": ("agencies/", {}),
    "astronaut": ("astronaut/", {}),
    "location": ("location/", {}),
    "pad": ("pad/", {}),
}


# --------------------------------------------------------------------------
# 2. ACCESO A LA API
# --------------------------------------------------------------------------

def _peticion(url, params, reintentos=REINTENTOS, espera_inicial=2.0):
    """Petición GET con reintentos y backoff ante fallos de red o 429/5xx.

    - Error de red / 5xx : reintentos con backoff exponencial (máx. `reintentos`).
    - 429 (límite de peticiones): se respeta el tiempo que la propia API
      indica y se reintenta hasta conseguir la página (la descarga completa
      termina siempre, aunque sea lenta). Ctrl+C interrumpe.
    """
    espera = espera_inicial
    intentos_red = 0
    while True:
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            intentos_red += 1
            if intentos_red > reintentos:
                print(f"    ! Error de red persistente ({e}). Abandonando {url}")
                return None
            print(f"    ! Error de red ({e}). Reintento {intentos_red}/{reintentos}...")
            time.sleep(espera)
            espera *= 2
            continue

        if resp.status_code == 429:
            espera_429 = _segundos_espera_429(resp, espera)
            print(f"    ! Límite de peticiones. Esperando {espera_429:.0f}s...")
            time.sleep(espera_429)
            espera = espera_inicial
            continue

        if resp.status_code in (500, 502, 503, 504):
            intentos_red += 1
            if intentos_red > reintentos:
                print(f"    ! Respuesta {resp.status_code} persistente. Abandonando {url}")
                return None
            print(f"    ! Respuesta {resp.status_code}. Reintento {intentos_red}/{reintentos}...")
            time.sleep(espera)
            espera *= 2
            continue

        if resp.status_code != 200:
            print(f"    ! Respuesta {resp.status_code}. Abandonando {url}")
            return None

        return resp.json()


def _segundos_espera_429(resp, espera_actual):
    """Extrae los segundos de espera que indica la API en el 429."""
    try:
        detalle = resp.json().get("detail", "") or ""
        encontrado = re.search(r"(\d+)\s+seconds?", detalle)
        if encontrado:
            return min(int(encontrado.group(1)), 3600)
    except (ValueError, requests.RequestException):
        pass
    return min(espera_actual * 2, 3600)


def _generar_paginas(resource, params, pausa, limite=None, offset_inicial=0):
    """Generador de páginas (dict con 'results', 'next', ...) recorriendo
    todos los resultados con paginación por offset."""
    url = BASE_URL + resource
    offset = offset_inicial
    acumulado = 0
    while True:
        pagina_params = dict(params)
        pagina_params["limit"] = PAGE_SIZE      # la API usa limit=20 por defecto
        pagina_params["offset"] = offset
        data = _peticion(url, pagina_params)

        if not data or not data.get("results"):
            break

        yield data
        acumulado += len(data["results"])

        if limite is not None and acumulado >= limite:
            break
        if not data.get("next"):
            break

        offset += PAGE_SIZE
        time.sleep(pausa)


# --------------------------------------------------------------------------
# 3. CACHÉ LOCAL (data/raw/*.jsonl) Y ESTADO
# --------------------------------------------------------------------------

def _fichero_cached(resource):
    return RAW_DIR / f"{resource}.jsonl"


def leer_cached(resource):
    """Devuelve (lista de registros, nº de registros) desde la caché."""
    fichero = _fichero_cached(resource)
    if not fichero.exists():
        return [], 0
    registros = []
    with open(fichero, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                registros.append(json.loads(linea))
    return registros, len(registros)


def anadir_a_cached(resource, registros):
    """Añade registros al final del fichero de caché del recurso."""
    fichero = _fichero_cached(resource)
    fichero.parent.mkdir(parents=True, exist_ok=True)
    with open(fichero, "a", encoding="utf-8") as f:
        for reg in registros:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")


def sobreescribir_cached(resource, registros):
    """Reemplaza por completo la caché del recurso."""
    fichero = _fichero_cached(resource)
    fichero.parent.mkdir(parents=True, exist_ok=True)
    with open(fichero, "w", encoding="utf-8") as f:
        for reg in registros:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")


def _cargar_estado():
    if ESTADO_PATH.exists():
        with open(ESTADO_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _guardar_estado(estado):
    ESTADO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# 4. DESCARGAS
# --------------------------------------------------------------------------

def descargar_recurso_completo(resource, pausa):
    """Descarga (o reanuda) todas las páginas de un recurso con caché.

    - launch: reanuda desde el último offset completo registrado.
    - resto : pocas páginas, se descargan completas y se reemplaza la caché.
    """
    endpoint, params = RECURSOS[resource]

    estado = _cargar_estado()
    previos, n_previos = leer_cached(resource)

    if resource == "launch":
        offset_inicio = estado.get("launch", {}).get("ultimo_offset", 0)
    else:
        offset_inicio = 0
        # Los recursos pequeños se vuelven a descargar completos siempre,
        # así no hay sorpresas si la API corrige algún registro.
        previos, n_previos = [], 0
        sobreescribir_cached(resource, [])

    if n_previos >= estado.get(resource, {}).get("total", 0) and n_previos > 0:
        print(f"  [cache] {resource}: ya descargado completo ({n_previos} registros).")
        return previos

    nuevos = []
    offset = offset_inicio
    url = BASE_URL + endpoint
    total = None
    for pagina in _generar_paginas(endpoint, params, pausa, offset_inicial=offset_inicio):
        total = pagina.get("count", total)
        nuevos.extend(pagina["results"])
        offset += PAGE_SIZE
        if resource == "launch":
            # Guardado página a página: si se corta la descarga, al reanudar
            # solo se pierde la página en curso (offset ya actualizado).
            anadir_a_cached(resource, pagina["results"])
            estado.setdefault(resource, {})
            if total is not None:
                estado[resource]["total"] = total
            estado[resource]["ultimo_offset"] = offset
            estado[resource]["fecha"] = datetime.now(timezone.utc).isoformat()
            _guardar_estado(estado)

    registros = previos + nuevos
    if resource != "launch":
        anadir_a_cached(resource, nuevos)

    estado.setdefault(resource, {})
    if total is not None:
        estado[resource]["total"] = total
    estado[resource]["ultimo_offset"] = offset
    estado[resource]["fecha"] = datetime.now(timezone.utc).isoformat()
    _guardar_estado(estado)

    print(f"  [cache] {resource}: descargados {len(nuevos)} nuevos "
          f"(total en caché: {len(registros)}).")
    return registros


def descargar_actualizaciones(pausa):
    """Modo incremental. Para cada recurso añade solo lo nuevo.

    - launch: se refrescan las páginas más recientes (ordenados por fecha
      descendente) porque es donde aparecen lanzamientos nuevos o editados.
    - resto : pocas páginas, se vuelven a descargar completas.
    """
    print("Modo actualización incremental...")

    endpoint, params = RECURSOS["launch"]
    parametros_recientes = dict(params)
    parametros_recientes["ordering"] = "-net"

    previos, _ = leer_cached("launch")
    ids_previos = {r.get("id") for r in previos}
    recientes = []
    contador_paginas = 0
    for pagina in _generar_paginas(endpoint, parametros_recientes, pausa):
        contador_paginas += 1
        if contador_paginas > UPDATE_PAGINAS:
            break
        for reg in pagina["results"]:
            if reg.get("id") in ids_previos:
                continue  # ya lo teníamos
            recientes.append(reg)
            ids_previos.add(reg.get("id"))

    if recientes:
        anadir_a_cached("launch", recientes)
        print(f"  launch: {len(recientes)} lanzamientos nuevos añadidos.")
    else:
        print("  launch: sin lanzamientos nuevos.")

    for resource in ("agencies", "astronaut", "location", "pad"):
        registros = descargar_recurso_completo(resource, pausa)
        print(f"  {resource}: {len(registros)} registros actualizados.")

    return recientes


# --------------------------------------------------------------------------
# 5. LIMPIEZA Y CONVERSIÓN
# --------------------------------------------------------------------------

def _texto(valor):
    return (valor or "").strip() or None


def _numero(valor, tipo=float):
    try:
        return tipo(valor)
    except (TypeError, ValueError):
        return None


def _anio_de_net(net):
    if not net:
        return None
    try:
        return int(net[:4])
    except ValueError:
        return None


def limpiar_launch(reg):
    """Convierte un JSON de launch en una tupla ordenada para la tabla."""
    lsp = reg.get("launch_service_provider") or {}
    rocket = reg.get("rocket") or {}
    config = rocket.get("configuration") or {}
    mision = reg.get("mission") or {}
    orbita = mision.get("orbit") or {}
    pad = reg.get("pad") or {}
    ubicacion = pad.get("location") or {}
    programas = reg.get("program") or []

    return (
        reg.get("id"),
        _texto(reg.get("slug")),
        _texto(reg.get("name")),
        (reg.get("status") or {}).get("id"),
        _texto((reg.get("status") or {}).get("name")),
        reg.get("net"),
        reg.get("window_start"),
        reg.get("window_end"),
        _anio_de_net(reg.get("net")),
        _numero(reg.get("probability")),
        _texto(reg.get("holdreason")),
        _texto(reg.get("failreason")),
        1 if reg.get("webcast_live") else 0,
        _texto(reg.get("image")),
        _texto(reg.get("infographic")),
        _texto(reg.get("url")),
        mision.get("id"),
        _texto(mision.get("name")),
        _texto(mision.get("description")),
        _texto(mision.get("type")),
        _texto(orbita.get("name")),
        config.get("id"),
        _texto(config.get("name")),
        _texto(config.get("family")),
        _texto(config.get("variant")),
        lsp.get("id"),
        _texto(lsp.get("name")),
        _texto(lsp.get("type")),
        pad.get("id"),
        _texto(pad.get("name")),
        _numero(pad.get("latitude")),
        _numero(pad.get("longitude")),
        ubicacion.get("id"),
        _texto(ubicacion.get("name")),
        _texto(ubicacion.get("country_code")),
        ", ".join(_texto(p.get("name")) for p in programas if p.get("name")) or None,
        datetime.now(timezone.utc).isoformat(),
    )


def limpiar_agencia(reg):
    return (
        reg.get("id"),
        _texto(reg.get("name")),
        _texto(reg.get("type")),
        _texto(reg.get("country_code")),
        _texto(reg.get("abbrev")),
        _texto(reg.get("description")),
        _numero(reg.get("founding_year"), int),
        _texto(reg.get("administrator")),
        _texto(reg.get("image_url")),
        _texto(reg.get("url")),
    )


def limpiar_astronauta(reg):
    return (
        reg.get("id"),
        _texto(reg.get("name")),
        _texto((reg.get("status") or {}).get("name")),
        _texto((reg.get("type") or {}).get("name")),
        _texto(reg.get("nationality")),
        reg.get("date_of_birth"),
        reg.get("date_of_death"),
        reg.get("first_flight"),
        reg.get("last_flight"),
        _numero(reg.get("flights_count"), int),
        _texto((reg.get("agency") or {}).get("name")),
        _texto(reg.get("bio")),
        _texto(reg.get("profile_image")),
        _texto(reg.get("wiki")),
    )


def limpiar_ubicacion(reg):
    return (
        reg.get("id"),
        _texto(reg.get("name")),
        _texto(reg.get("country_code")),
        _texto(reg.get("map_image")),
        _numero(reg.get("total_launch_count"), int),
        _numero(reg.get("total_landing_count"), int),
    )


def limpiar_pad(reg):
    ubicacion = reg.get("location") or {}
    return (
        reg.get("id"),
        _texto(reg.get("name")),
        _numero(reg.get("latitude")),
        _numero(reg.get("longitude")),
        _texto(reg.get("map_image")),
        ubicacion.get("id"),
        _texto(ubicacion.get("name")),
        _texto(ubicacion.get("country_code")),
        _numero(reg.get("total_launch_count"), int),
        reg.get("agency_id"),
    )


LIMPIEZAS = {
    "launch": limpiar_launch,
    "agencies": limpiar_agencia,
    "astronaut": limpiar_astronauta,
    "location": limpiar_ubicacion,
    "pad": limpiar_pad,
}


# --------------------------------------------------------------------------
# 6. BASE DE DATOS
# --------------------------------------------------------------------------

def crear_esquema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS launches (
            id              TEXT PRIMARY KEY,
            slug            TEXT,
            name            TEXT,
            status_id       INTEGER,
            status_name     TEXT,
            net             TEXT,
            window_start    TEXT,
            window_end      TEXT,
            anio            INTEGER,
            probability     REAL,
            holdreason      TEXT,
            failreason      TEXT,
            webcast_live    INTEGER,
            image_url       TEXT,
            infographic_url TEXT,
            url             TEXT,
            mission_id      INTEGER,
            mission_name    TEXT,
            mission_description TEXT,
            mission_type    TEXT,
            orbit           TEXT,
            rocket_id       INTEGER,
            rocket_name     TEXT,
            rocket_family   TEXT,
            rocket_variant  TEXT,
            agency_id       INTEGER,
            agency_name     TEXT,
            agency_type     TEXT,
            pad_id          INTEGER,
            pad_name        TEXT,
            pad_latitude    REAL,
            pad_longitude   REAL,
            location_id     INTEGER,
            location_name   TEXT,
            location_country TEXT,
            programs        TEXT,
            created_at      TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_launches_anio   ON launches(anio);
        CREATE INDEX IF NOT EXISTS idx_launches_status ON launches(status_name);
        CREATE INDEX IF NOT EXISTS idx_launches_net    ON launches(net);
        CREATE INDEX IF NOT EXISTS idx_launches_agency ON launches(agency_name);
        CREATE INDEX IF NOT EXISTS idx_launches_orbit  ON launches(orbit);

        CREATE TABLE IF NOT EXISTS agencies (
            id            INTEGER PRIMARY KEY,
            name          TEXT,
            type          TEXT,
            country_code  TEXT,
            abbrev        TEXT,
            description   TEXT,
            founding_year INTEGER,
            administrator TEXT,
            image_url     TEXT,
            url           TEXT
        );

        CREATE TABLE IF NOT EXISTS astronauts (
            id             INTEGER PRIMARY KEY,
            name           TEXT,
            status         TEXT,
            type           TEXT,
            nationality    TEXT,
            date_of_birth  TEXT,
            date_of_death  TEXT,
            first_flight   TEXT,
            last_flight    TEXT,
            flights_count  INTEGER,
            agency         TEXT,
            bio            TEXT,
            profile_image  TEXT,
            wiki           TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_astronautas_nacionalidad ON astronauts(nationality);

        CREATE TABLE IF NOT EXISTS locations (
            id                 INTEGER PRIMARY KEY,
            name               TEXT,
            country_code       TEXT,
            map_image          TEXT,
            total_launch_count INTEGER,
            total_landing_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS pads (
            id                 INTEGER PRIMARY KEY,
            name               TEXT,
            latitude           REAL,
            longitude          REAL,
            map_image          TEXT,
            location_id        INTEGER,
            location_name      TEXT,
            country_code       TEXT,
            total_launch_count INTEGER,
            agency_id          INTEGER
        );

        CREATE TABLE IF NOT EXISTS meta_ingesta (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );
        """
    )
    conn.commit()


def set_meta(conn, clave, valor):
    conn.execute(
        "INSERT INTO meta_ingesta (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
        (clave, valor),
    )


def get_meta(conn, clave, default=None):
    fila = conn.execute(
        "SELECT valor FROM meta_ingesta WHERE clave = ?", (clave,)
    ).fetchone()
    return fila[0] if fila else default


SQL_UPSERT = {
    "launch": """
        INSERT INTO launches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            status_id=excluded.status_id, status_name=excluded.status_name,
            net=excluded.net, window_start=excluded.window_start,
            window_end=excluded.window_end, anio=excluded.anio,
            probability=excluded.probability, holdreason=excluded.holdreason,
            failreason=excluded.failreason, webcast_live=excluded.webcast_live,
            image_url=excluded.image_url, mission_name=excluded.mission_name,
            mission_description=excluded.mission_description,
            mission_type=excluded.mission_type, orbit=excluded.orbit,
            rocket_id=excluded.rocket_id, rocket_name=excluded.rocket_name,
            rocket_family=excluded.rocket_family, rocket_variant=excluded.rocket_variant,
            agency_id=excluded.agency_id, agency_name=excluded.agency_name,
            agency_type=excluded.agency_type, pad_id=excluded.pad_id,
            pad_name=excluded.pad_name, pad_latitude=excluded.pad_latitude,
            pad_longitude=excluded.pad_longitude, location_id=excluded.location_id,
            location_name=excluded.location_name, location_country=excluded.location_country,
            programs=excluded.programs
    """,
    "agencies": """
        INSERT INTO agencies VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, type=excluded.type, country_code=excluded.country_code,
            abbrev=excluded.abbrev, description=excluded.description,
            founding_year=excluded.founding_year, administrator=excluded.administrator,
            image_url=excluded.image_url, url=excluded.url
    """,
    "astronaut": """
        INSERT INTO astronauts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, status=excluded.status, type=excluded.type,
            nationality=excluded.nationality, date_of_birth=excluded.date_of_birth,
            date_of_death=excluded.date_of_death, first_flight=excluded.first_flight,
            last_flight=excluded.last_flight, flights_count=excluded.flights_count,
            agency=excluded.agency, bio=excluded.bio,
            profile_image=excluded.profile_image, wiki=excluded.wiki
    """,
    "location": """
        INSERT INTO locations VALUES (?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, country_code=excluded.country_code,
            map_image=excluded.map_image, total_launch_count=excluded.total_launch_count,
            total_landing_count=excluded.total_landing_count
    """,
    "pad": """
        INSERT INTO pads VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, latitude=excluded.latitude, longitude=excluded.longitude,
            map_image=excluded.map_image, location_id=excluded.location_id,
            location_name=excluded.location_name, country_code=excluded.country_code,
            total_launch_count=excluded.total_launch_count, agency_id=excluded.agency_id
    """,
}


def construir_db(recursos_descargados):
    """Vuelca las listas de registros a SQLite (UPSERT por id)."""
    conn = sqlite3.connect(str(DB_PATH))
    crear_esquema(conn)
    totales = {}

    for resource, registros in recursos_descargados.items():
        limpiar = LIMPIEZAS[resource]
        sql = SQL_UPSERT[resource]
        n_guardados = 0
        vistos = set()
        for reg in registros:
            fila = limpiar(reg)
            if fila[0] is None:
                continue
            if fila[0] in vistos:
                continue  # dedupe: quedarse con la primera aparición de la caché
            vistos.add(fila[0])
            conn.execute(sql, fila)
            n_guardados += 1
        conn.commit()
        totales[resource] = n_guardados
        print(f"  [db] {resource}: {n_guardados} registros en {DB_PATH.name}.")

    set_meta(conn, "ultima_ejecucion", datetime.now(timezone.utc).isoformat())
    conn.commit()
    conn.close()
    return totales


# --------------------------------------------------------------------------
# 7. PROGRAMA PRINCIPAL
# --------------------------------------------------------------------------

def ejecutar(modo, pausa, limite, desde):
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if modo == "actualizar":
        descargar_actualizaciones(pausa)
        recursos = {r: leer_cached(r)[0] for r in RECURSOS}
        construir_db(recursos)
        print("\nActualización completada. Base de datos lista.")
        return

    if limite is not None or desde is not None:
        print("Modo parcial (sin caché): solo lanzamientos.")
        params_parcial = dict(RECURSOS["launch"][1])
        if desde:
            params_parcial["net__gte"] = desde
            print(f"  Desde {desde}: historia desde esa fecha.")
        if limite is not None:
            print(f"  Máximo {limite} lanzamientos.")
        registros = []
        for pagina in _generar_paginas(
            RECURSOS["launch"][0], params_parcial, pausa, limite=limite
        ):
            registros.extend(pagina["results"])
            if limite is not None and len(registros) >= limite:
                registros = registros[:limite]
                break
        construir_db({"launch": registros})
        print("\nBase de datos (parcial) lista. Usa `python ingesta.py` sin "
              "--limite/--desde para la carga completa.")
        return

    print("Carga inicial completa...")
    descargados = {}
    for resource in RECURSOS:
        print(f"  Descargando {resource}...")
        descargados[resource] = descargar_recurso_completo(resource, pausa)

    construir_db(descargados)
    print("\nIngesta completada. Base de datos lista en:", DB_PATH)


def main():
    parser = argparse.ArgumentParser(
        description="Ingesta de Launch Library 2 a SQLite (data/espacio.db)"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Modo incremental: solo descarga/añade lo nuevo",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Prueba rápida: descarga solo N lanzamientos (sin caché)",
    )
    parser.add_argument(
        "--desde",
        type=str,
        default=None,
        help="Carga parcial: solo lanzamientos desde una fecha (AAAA-MM-DD)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=PAUSA_DEFECTO,
        help=f"Segundos entre peticiones a la API (por defecto {PAUSA_DEFECTO})",
    )
    args = parser.parse_args()

    if args.update and (args.limite is not None or args.desde is not None):
        parser.error("--update no puede combinarse con --limite/--desde.")

    modo = "actualizar" if args.update else "inicial"
    ejecutar(modo, args.sleep, args.limite, args.desde)


if __name__ == "__main__":
    main()
