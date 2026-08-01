"""
============================================================
 preparar_corpus.py — Genera el índice vectorial para el chat RAG
============================================================
Recorre la base de datos (data/espacio.db) y convierte cada registro
en una "ficha" de texto con los datos más relevantes:

  - Lanzamientos : nombre, fecha, cohete, agencia, sitio, órbita, misión
  - Cohetes      : resumen por modelo (familia, agencia, nº lanzamientos,
                   tasa de éxito, misiones de ejemplo)
  - Agencias     : nombre, tipo, país, descripción y actividad
  - Astronautas  : nacionalidad, estado, vuelos y biografía

Cada ficha se embebe con el modelo local de Ollama `nomic-embed-text`
y se guarda en Chroma (carpeta `chroma_db/`).

Requisito: tener Ollama instalado y ejecutándose con:
    ollama pull nomic-embed-text

Uso:
  python preparar_corpus.py               # indexa todo
  python preparar_corpus.py --limite 200  # prueba con 200 fichas
============================================================
"""

import argparse
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DB_PATH = RAIZ / "data" / "espacio.db"
CHROMA_PATH = RAIZ / "chroma_db"
COLECCION = "lanzamientos"
MODELO_EMBEDDING = "nomic-embed-text"
URL_OLLAMA = "http://localhost:11434/api/embeddings"


# --------------------------------------------------------------------------
# 1. GENERACIÓN DE FICHAS (texto)
# --------------------------------------------------------------------------

def _acortar(texto, maximo=900):
    if not texto:
        return ""
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > maximo:
        return texto[:maximo].rstrip() + "..."
    return texto


def fichas_lanzamientos(conn, limite=None):
    """Una ficha por lanzamiento."""
    sql = """
        SELECT id, name, net, status_name, rocket_name, rocket_family,
               agency_name, pad_name, location_name, location_country,
               orbit, mission_name, mission_type, mission_description,
               failreason, image_url
        FROM launches
        ORDER BY net
    """
    if limite is not None:
        sql += f" LIMIT {limite}"
    filas = conn.execute(sql).fetchall()

    fichas = []
    for f in filas:
        (lid, nombre, net, status, cohete, familia, agencia, pad, lugar,
         pais, orbita, mision, tipo_mision, desc, fallo, imagen) = f

        partes = [
            f"LANZAMIENTO: {nombre}",
            f"Fecha (net): {net or 'sin fecha'}"
            if net
            else "LANZAMIENTO: {nombre} (sin fecha)",
            f"Estado: {status or 'desconocido'}",
        ]
        if cohete:
            partes.append(f"Cohete: {cohete}" + (f" (familia {familia})" if familia else ""))
        if agencia:
            partes.append(f"Agencia: {agencia}")
        if pad or lugar:
            lugar_str = pad or ""
            if lugar:
                lugar_str += (f", {lugar}" if lugar_str else lugar)
            if pais:
                lugar_str += f" ({pais})"
            partes.append(f"Sitio de lanzamiento: {lugar_str}")
        if orbita:
            partes.append(f"Órbita objetivo: {orbita}")
        if mision:
            partes.append(f"Misión: {mision}" + (f" — {tipo_mision}" if tipo_mision else ""))
        if desc:
            partes.append(f"Descripción de la misión: {_acortar(desc)}")
        if fallo:
            partes.append(f"Motivo del fallo: {_acortar(fallo)}")

        texto = "\n".join(p for p in partes if p)
        anio = int(net[:4]) if net and net[:4].isdigit() else None
        fichas.append((
            f"lan_{lid}",
            texto,
            {
                "tipo": "lanzamiento",
                "nombre": nombre or "",
                "anio": anio or 0,
                "estado": status or "",
                "agencia": agencia or "",
                "imagen": imagen or "",
            },
        ))
    return fichas


def fichas_cohetes(conn):
    """Una ficha resumen por modelo de cohete."""
    sql = """
        SELECT rocket_name, rocket_family,
               COUNT(*) AS n,
               SUM(CASE WHEN status_name='Success' THEN 1 ELSE 0 END) AS exitos,
               SUM(CASE WHEN status_name IN ('Failure','Partial Failure')
                        THEN 1 ELSE 0 END) AS fallos,
               GROUP_CONCAT(DISTINCT agency_name) AS agencias
        FROM launches
        WHERE rocket_name IS NOT NULL
        GROUP BY rocket_name
        ORDER BY n DESC
    """
    filas = conn.execute(sql).fetchall()

    # Misiones de ejemplo por cohete (las 3 más recientes)
    ejemplos = defaultdict(list)
    for lid, nombre, mision, cohete in conn.execute(
        """SELECT id, name, mission_name, rocket_name
           FROM launches
           WHERE mission_name IS NOT NULL AND rocket_name IS NOT NULL
           ORDER BY net DESC"""
    ):
        ejemplos[cohete].append(mision)
        if len(ejemplos[cohete]) > 3:
            pass  # guardamos solo 3 al final

    fichas = []
    for cohete, familia, n, exitos, fallos, agencias in filas:
        ex = ", ".join(ejemplos.get(cohete, [])[:3]) or "sin datos"
        tasa = (exitos / n * 100) if n else 0.0
        partes = [
            f"COHETE: {cohete}" + (f" (familia {familia})" if familia else ""),
            f"Agencias que lo usan: {agencias}" if agencias else "",
            f"Número de lanzamientos: {n}",
            f"Lanzamientos exitosos: {exitos} ({tasa:.0f}% de éxito)" if n else "",
            f"Fallos: {fallos}" if fallos else "Sin fallos registrados",
            f"Misiones de ejemplo: {ex}",
        ]
        texto = "\n".join(p for p in partes if p)
        slug = re.sub(r"[^a-z0-9]+", "-", cohete.lower()).strip("-")
        fichas.append((
            f"cohete_{slug}",
            texto,
            {"tipo": "cohete", "nombre": cohete, "anio": 0,
             "estado": "", "agencia": agencias or "", "imagen": ""},
        ))
    return fichas


def fichas_agencias(conn):
    """Una ficha por agencia espacial."""
    sql = """
        SELECT a.id, a.name, a.type, a.country_code, a.founding_year,
               a.description,
               (SELECT COUNT(*) FROM launches l
                 WHERE l.agency_name = a.name) AS n_lanzamientos,
               (SELECT SUM(CASE WHEN l.status_name='Success' THEN 1 ELSE 0 END)
                  FROM launches l WHERE l.agency_name = a.name) AS n_exitos
        FROM agencies a
        ORDER BY n_lanzamientos DESC
    """
    filas = conn.execute(sql).fetchall()

    fichas = []
    for (aid, nombre, tipo, pais, fundacion, desc, n, exitos) in filas:
        if not nombre:
            continue
        tasa = (exitos / n * 100) if n else None
        partes = [
            f"AGENCIA: {nombre}",
            f"Tipo: {tipo}" if tipo else "",
            f"País: {pais}" if pais else "",
            f"Fundada en: {fundacion}" if fundacion else "",
            f"Lanzamientos en la base de datos: {n}" if n else
            "Sin lanzamientos registrados en la base de datos",
        ]
        if n:
            partes.append(f"Tasa de éxito: {tasa:.0f}% ({exitos} de {n})")
        if desc:
            partes.append(f"Descripción: {_acortar(desc)}")
        texto = "\n".join(p for p in partes if p)
        fichas.append((
            f"agencia_{aid}",
            texto,
            {"tipo": "agencia", "nombre": nombre, "anio": fundacion or 0,
             "estado": "", "agencia": nombre, "imagen": ""},
        ))
    return fichas


def fichas_astronautas(conn, limite=None):
    """Una ficha por astronauta."""
    sql = """
        SELECT id, name, status, nationality, agency, flights_count,
               first_flight, date_of_birth, bio, profile_image
        FROM astronauts
        ORDER BY name
    """
    if limite is not None:
        sql += f" LIMIT {limite}"
    filas = conn.execute(sql).fetchall()

    fichas = []
    for (aid, nombre, status, nacionalidad, agencia, vuelos,
         primer_vuelo, nacimiento, bio, imagen) in filas:
        if not nombre:
            continue
        partes = [
            f"ASTRONAUTA: {nombre}",
            f"Estado: {status}" if status else "",
            f"Nacionalidad: {nacionalidad}" if nacionalidad else "",
            f"Agencia: {agencia}" if agencia else "",
            f"Número de vuelos: {vuelos}" if vuelos else "",
            f"Primer vuelo: {primer_vuelo}" if primer_vuelo else "",
            f"Nacido en: {nacimiento}" if nacimiento else "",
        ]
        if bio:
            partes.append(f"Biografía: {_acortar(bio)}")
        texto = "\n".join(p for p in partes if p)
        fichas.append((
            f"astronauta_{aid}",
            texto,
            {"tipo": "astronauta", "nombre": nombre, "anio": 0,
             "estado": status or "", "agencia": agencia or "",
             "imagen": imagen or ""},
        ))
    return fichas


def generar_documentos(conn, limite=None):
    """Devuelve la lista completa de (id, texto, metadatos)."""
    documentos = []
    documentos += fichas_lanzamientos(conn, limite=limite)
    documentos += fichas_cohetes(conn)
    documentos += fichas_agencias(conn)
    if limite is None:
        documentos += fichas_astronautas(conn)
    else:
        documentos += fichas_astronautas(conn, limite=limite)
    return documentos


# --------------------------------------------------------------------------
# 2. INDEXADO EN CHROMA
# --------------------------------------------------------------------------

def indexar(documentos, reconstruir=False):
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    if reconstruir:
        try:
            client.delete_collection(COLECCION)
            print(f"  Colección '{COLECCION}' eliminada (reconstrucción).")
        except ValueError:
            pass

    embedding_fn = embedding_functions.OllamaEmbeddingFunction(
        model_name=MODELO_EMBEDDING,
        url=URL_OLLAMA,
    )

    coleccion = client.get_or_create_collection(
        name=COLECCION,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    ids = [d[0] for d in documentos]
    textos = [d[1] for d in documentos]
    metadatos = [d[2] for d in documentos]

    BATCH = 128
    for i in range(0, len(ids), BATCH):
        coleccion.upsert(
            ids=ids[i:i + BATCH],
            documents=textos[i:i + BATCH],
            metadatas=metadatos[i:i + BATCH],
        )
        print(f"  ...indexadas {min(i + BATCH, len(ids))}/{len(ids)} fichas")
        time.sleep(0.1)

    return coleccion.count()


def main():
    parser = argparse.ArgumentParser(
        description="Genera el índice vectorial para el chat RAG"
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Solo indexa las N primeras fichas (prueba rápida)",
    )
    parser.add_argument(
        "--reconstruir",
        action="store_true",
        help="Borra la colección anterior y la reconstruye desde cero",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("No se encuentra data/espacio.db. Ejecuta primero:\n"
              "  python ingesta.py")
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        print("Generando fichas desde la base de datos...")
        documentos = generar_documentos(conn, limite=args.limite)
        print(f"  {len(documentos)} fichas generadas.")

        total = indexar(documentos, reconstruir=args.reconstruir)
        print(f"\nListo. {total} fichas indexadas en '{CHROMA_PATH}'.")
        print("Ya puedes abrir la app y usar la pestaña de chat.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
