"""
============================================================
 app.py — Órbita · La industria espacial en cifras
============================================================
Aplicación Streamlit que explora la base de datos data/espacio.db
(construida con `python ingesta.py`).

Pestañas:
  1. 📊 Resumen          - métricas globales, evolución histórica y mapa
  2. 🚀 Lanzamientos     - exploración con filtros, tablas y gráficos
  3. 🏢 Agencias         - quién lanza, con qué fiabilidad
  4. 👨‍🚀 Astronautas     - las personas que han volado al espacio
  5. 📅 Próximos         - calendario de lanzamientos futuros
  6. 💬 Chat RAG         - preguntas en lenguaje natural sobre los datos
  7. 🌌 Imagen del día   - fotografía astronómica de la NASA (APOD)

Ejecución:  streamlit run app.py
============================================================
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

RAIZ = Path(__file__).resolve().parent
DB_PATH = RAIZ / "data" / "espacio.db"
CHROMA_PATH = RAIZ / "chroma_db"

MODELO_CHAT = os.getenv("OLLAMA_MODELO", "llama3.2")
MODELO_EMBEDDING = "nomic-embed-text"
URL_OLLAMA = "http://localhost:11434"

px.defaults.template = "plotly_dark"

st.set_page_config(
    page_title="Órbita · La industria espacial",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Pequeños ajustes de estilo
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem;}
      .ficha-metrica {border-radius: 10px; padding: 0.7rem 1rem;
                      background: #141a3a; border: 1px solid #26307a;}
      h1, h2, h3 {letter-spacing: 0.3px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def cargar_launches():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT * FROM launches", conn)
    conn.close()
    return df


@st.cache_data(ttl=60, show_spinner=False)
def cargar_agencias():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT * FROM agencies", conn)
    conn.close()
    return df


@st.cache_data(ttl=60, show_spinner=False)
def cargar_astronautas():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT * FROM astronauts", conn)
    conn.close()
    return df


@st.cache_data(ttl=60, show_spinner=False)
def cargar_pads():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        """SELECT p.id, p.name AS pad_name, p.latitude, p.longitude,
                  p.location_name, p.country_code, p.total_launch_count
           FROM pads p
           WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL""",
        conn,
    )
    conn.close()
    return df


@st.cache_data(ttl=60, show_spinner=False)
def ultima_ejecucion():
    conn = sqlite3.connect(str(DB_PATH))
    fila = conn.execute(
        "SELECT valor FROM meta_ingesta WHERE clave = 'ultima_ejecucion'"
    ).fetchone()
    conn.close()
    return fila[0] if fila else None


def preparar(launch):
    """Añade columnas derivadas y filtra ruido."""
    df = launch.copy()
    df["net_dt"] = pd.to_datetime(df["net"], errors="coerce", utc=True)
    df["anio"] = df["net_dt"].dt.year
    return df


# ---------------------------------------------------------------------------
# Control de la base de datos
# ---------------------------------------------------------------------------
if not DB_PATH.exists():
    st.error(
        "No se encuentra la base de datos `data/espacio.db`. "
        "Ejecuta antes:\n\n```bash\npython ingesta.py\n```"
    )
    st.stop()

launch = preparar(cargar_launches())
if launch.empty:
    st.error(
        "La base de datos está vacía. Ejecuta antes:\n\n```bash\npython ingesta.py\n```"
    )
    st.stop()

agencies = cargar_agencias()
astronauts = cargar_astronautas()
pads = cargar_pads()

ahora_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
proximos = launch[launch["net"] > ahora_iso].copy()
ultimo_update = ultima_ejecucion()


def tasa_exito(df):
    decididos = df[df["status_name"].isin(
        ["Success", "Failure", "Partial Failure", "Failed Launch"])]
    if decididos.empty:
        return None
    return (decididos["status_name"] == "Success").mean() * 100


# ---------------------------------------------------------------------------
# Barra lateral: filtros globales
# ---------------------------------------------------------------------------
st.sidebar.title("🚀 Órbita")

anios = sorted(int(a) for a in launch["anio"].dropna().unique())
if not anios:
    min_anio, max_anio = 1957, 2026
else:
    min_anio, max_anio = anios[0], anios[-1]
rango = st.sidebar.slider(
    "Periodo (años)",
    min_value=min_anio,
    max_value=max_anio,
    value=(min_anio, max_anio),
)

estados_disponibles = sorted(launch["status_name"].dropna().unique())
estados_sel = st.sidebar.multiselect("Estado", estados_disponibles)

top_agencias_lista = (
    launch.groupby("agency_name").size().sort_values(ascending=False).head(25).index.tolist()
)
agencias_sel = st.sidebar.multiselect(
    "Agencia", [a for a in top_agencias_lista if a]
)

orbits_lista = sorted(
    o for o in launch["orbit"].dropna().unique()
)
orbits_sel = st.sidebar.multiselect("Órbita", orbits_lista)

# Aplicar filtros
filtro = (launch["anio"] >= rango[0]) & (launch["anio"] <= rango[1])
if estados_sel:
    filtro &= launch["status_name"].isin(estados_sel)
if agencias_sel:
    filtro &= launch["agency_name"].isin(agencias_sel)
if orbits_sel:
    filtro &= launch["orbit"].isin(orbits_sel)
df = launch[filtro]

st.sidebar.metric("Lanzamientos filtrados", f"{len(df):,}")
if ultimo_update:
    st.sidebar.caption(f"Última actualización: {ultimo_update[:19].replace('T', ' ')} UTC")
st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Datos:** [Launch Library 2](https://ll.thespacedevs.com) · "
    "imágenes de la [NASA](https://api.nasa.gov)"
)


# ---------------------------------------------------------------------------
# Encabezado
# ---------------------------------------------------------------------------
st.title("🚀 Órbita · La industria espacial en cifras")
st.caption(
    "Más de 7.900 lanzamientos desde 1957. Explora quién lanza, con qué "
    "fiabilidad, desde dónde y qué viene. Los datos proceden de la API "
    "pública **Launch Library 2**, sin necesidad de registro."
)

tab_resumen, tab_lanzamientos, tab_agencias, tab_astronautas, tab_proximos, tab_chat, tab_apod = st.tabs(
    [
        "📊 Resumen",
        "🚀 Lanzamientos",
        "🏢 Agencias",
        "👨‍🚀 Astronautas",
        "📅 Próximos",
        "💬 Chat RAG",
        "🌌 Imagen del día",
    ]
)


# ========================== TAB 1: RESUMEN =================================
with tab_resumen:
    st.subheader("📊 Resumen global")

    t_exito = tasa_exito(df)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Lanzamientos", f"{len(df):,}")
    c2.metric("Tasa de éxito", f"{t_exito:.1f}%" if t_exito is not None else "—")
    c3.metric("Agencias activas", f"{df['agency_name'].nunique():,}")
    c4.metric("Astronautas", f"{len(astronauts):,}")
    c5.metric("Próximos lanzamientos", f"{len(proximos):,}")

    col_a, col_b = st.columns([3, 2])

    with col_a:
        por_anio = df.groupby("anio").size()
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=por_anio.index, y=por_anio.values,
            name="Lanzamientos", marker_color="#7aa2f7",
        ))
        fig.update_layout(
            title="Evolución anual",
            xaxis=dict(title="Año", type="category"),
            yaxis=dict(title="Nº de lanzamientos"),
            height=400,
        )
        st.plotly_chart(fig, width="stretch")

    with col_b:
        estados_count = df["status_name"].value_counts().head(8)
        fig = px.pie(
            estados_count, names=estados_count.index, values=estados_count.values,
            title="Lanzamientos por estado",
            hole=0.45,
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, width="stretch")

    col_c, col_d = st.columns([3, 2])

    with col_c:
        st.subheader("🗺️ Centros de lanzamiento")
        if not pads.empty:
            fig = go.Figure(go.Scattergeo(
                lat=pads["latitude"],
                lon=pads["longitude"],
                mode="markers",
                text=pads["pad_name"] + "<br>" + pads["location_name"],
                marker=dict(
                    size=8 + (pads["total_launch_count"].fillna(0) / 40),
                    color=pads["total_launch_count"],
                    colorscale="Viridis",
                    showscale=True,
                    colorbar=dict(title="Lanzamientos"),
                ),
            ))
            fig.update_geos(
                projection_type="natural earth",
                showcountries=True, countrycolor="#3b4a7a",
                lataxis_range=[-60, 80],
                lonaxis_range=[-180, 180],
            )
            fig.update_layout(
                height=460,
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig, width="stretch")

    with col_d:
        st.subheader("🏆 Top 10 agencias")
        top_agen = df.groupby("agency_name").size().sort_values(ascending=False).head(10)
        fig = px.bar(
            top_agen, x=top_agen.values, y=top_agen.index,
            orientation="h", color=top_agen.values,
            color_continuous_scale="Viridis",
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            xaxis_title="Lanzamientos", height=460,
        )
        st.plotly_chart(fig, width="stretch")

    with st.expander("ℹ️ Sobre el proyecto"):
        st.markdown(
            """
            **Órbita** es un producto de datos que responde a la pregunta:
            *¿cómo funciona realmente la industria espacial?* Útil para
            aficionados, periodistas de ciencia, estudiantes y analistas
            del sector.

            - **Ingesta:** `ingesta.py` descarga la API de Launch Library 2.
            - **Almacenamiento:** SQLite (`data/espacio.db`).
            - **Análisis:** `notebooks/eda.ipynb` con conclusiones.
            - **Chat:** pestaña de chat RAG sobre los propios datos.
            """
        )


# ========================== TAB 2: LANZAMIENTOS ============================
with tab_lanzamientos:
    st.subheader("🚀 Exploración de lanzamientos")

    c1, c2 = st.columns([2, 3])
    with c1:
        busqueda = st.text_input("🔍 Buscar por nombre o misión",
                                 placeholder="Ej: Starlink, Sputnik, Artemis")
        orden_por = st.selectbox(
            "Ordenar por",
            ["net", "name", "rocket_name", "agency_name", "status_name"],
            format_func=lambda c: {
                "net": "Fecha", "name": "Nombre", "rocket_name": "Cohete",
                "agency_name": "Agencia", "status_name": "Estado",
            }[c],
        )

    df_tab = df.copy()
    if busqueda:
        mascara = (
            df_tab["name"].str.contains(busqueda, case=False, na=False)
            | df_tab["mission_name"].str.contains(busqueda, case=False, na=False)
            | df_tab["rocket_name"].str.contains(busqueda, case=False, na=False)
        )
        df_tab = df_tab[mascara]

    st.markdown(f"**{len(df_tab):,} lanzamientos** con los filtros actuales.")

    col_l, col_r = st.columns(2)
    with col_l:
        top_cohetes = df_tab.groupby("rocket_name").size().sort_values(
            ascending=False).head(12)
        fig = px.bar(
            top_cohetes, x=top_cohetes.values, y=top_cohetes.index,
            orientation="h", color=top_cohetes.values,
            color_continuous_scale="Plasma",
            title="Top 12 cohetes",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=380)
        st.plotly_chart(fig, width="stretch")

    with col_r:
        top_orbits = df_tab["orbit"].value_counts().head(10)
        fig = px.bar(
            top_orbits, x=top_orbits.values, y=top_orbits.index,
            orientation="h", color=top_orbits.values,
            color_continuous_scale="Turbo",
            title="Órbitas objetivo",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=380)
        st.plotly_chart(fig, width="stretch")

    df_mostrar = df_tab.sort_values(orden_por).rename(columns={
        "name": "Lanzamiento", "net": "Fecha", "status_name": "Estado",
        "rocket_name": "Cohete", "agency_name": "Agencia",
        "location_name": "Cosmódromo", "orbit": "Órbita",
        "mission_name": "Misión",
    })
    st.dataframe(
        df_mostrar[["Lanzamiento", "Fecha", "Estado", "Cohete", "Agencia",
                    "Cosmódromo", "Órbita", "Misión"]],
        width="stretch",
        hide_index=True,
    )

    st.divider()
    st.markdown("#### 🛰️ Ficha de un lanzamiento")
    nombres = sorted(df_tab["name"].dropna().unique())
    if nombres:
        elegido = st.selectbox("Elige un lanzamiento", nombres)
        fila = df_tab[df_tab["name"] == elegido].iloc[0]
        c_izq, c_der = st.columns([1, 2])
        with c_izq:
            if fila["image_url"]:
                st.image(fila["image_url"], width="stretch")
        with c_der:
            st.markdown(
                f"**{fila['name']}**  \n"
                f"- **Fecha:** {fila['net'] or '—'}  \n"
                f"- **Estado:** {fila['status_name'] or '—'}  \n"
                f"- **Cohete:** {fila['rocket_name'] or '—'}  \n"
                f"- **Agencia:** {fila['agency_name'] or '—'}  \n"
                f"- **Cosmódromo:** {fila['location_name'] or '—'}  \n"
                f"- **Órbita:** {fila['orbit'] or '—'}  \n"
                f"- **Programas:** {fila['programs'] or '—'}"
            )
            if fila["mission_description"]:
                st.markdown(f"**Misión:** {fila['mission_description'][:500]}")
            if fila["failreason"]:
                st.warning(f"Motivo de fallo: {fila['failreason']}")


# ========================== TAB 3: AGENCIAS ================================
with tab_agencias:
    st.subheader("🏢 Agencias espaciales y operadores")

    tipos = sorted(a for a in agencies["type"].dropna().unique())
    tipo_sel = st.multiselect("Tipo de agencia", tipos)

    ag = agencies.copy()
    if tipo_sel:
        ag = ag[ag["type"].isin(tipo_sel)]

    # Actividad real calculada desde los lanzamientos
    actividad = df.groupby("agency_name").agg(
        lanzamientos=("id", "count"),
        exitos=("status_name", lambda s: (s == "Success").sum()),
    ).reset_index()
    actividad["tasa_%"] = (
        actividad["exitos"] / actividad["lanzamientos"] * 100
    ).round(1)
    actividad = actividad[actividad["lanzamientos"] > 0]

    tabla = ag.merge(
        actividad, left_on="name", right_on="agency_name", how="left"
    ).sort_values("lanzamientos", ascending=False)

    st.markdown(
        f"**{len(tabla):,} agencias**, de las cuales "
        f"{actividad['lanzamientos'].notna().sum():,} han lanzado alguna vez "
        f"(y {actividad[actividad['lanzamientos'] > 0].shape[0]:,} en el periodo filtrado)."
    )

    col_a, col_b = st.columns(2)

    with col_a:
        top = actividad.sort_values("lanzamientos", ascending=False).head(15)
        fig = px.bar(
            top, x="lanzamientos", y="agency_name", orientation="h",
            color="tasa_%", color_continuous_scale="Viridis",
            title="Top 15 agencias por lanzamientos (color = tasa de éxito)",
            labels={"agency_name": "", "lanzamientos": "Lanzamientos", "tasa_%": "% éxito"},
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=460)
        st.plotly_chart(fig, width="stretch")

    with col_b:
        fiables = actividad[actividad["lanzamientos"] >= 20]
        fig = px.scatter(
            fiables, x="tasa_%", y="lanzamientos",
            size="lanzamientos", color="tasa_%", text="agency_name",
            color_continuous_scale="Turbo",
            title="Fiabilidad vs volumen (agencias con ≥ 20 lanzamientos)",
            labels={"tasa_%": "Tasa de éxito (%)", "lanzamientos": "Lanzamientos"},
            size_max=55,
        )
        fig.update_layout(height=460)
        fig.update_traces(textposition="top center")
        st.plotly_chart(fig, width="stretch")

    paises = ag["country_code"].value_counts().head(12)
    fig = px.bar(
        paises, x=paises.values, y=paises.index, orientation="h",
        color=paises.values, color_continuous_scale="Cividis",
        title="Agencias por país",
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=360)
    st.plotly_chart(fig, width="stretch")

    st.markdown("#### Tabla de agencias")
    st.dataframe(
        tabla[["name", "type", "country_code", "founding_year",
               "lanzamientos", "tasa_%"]].rename(columns={
                   "name": "Nombre", "type": "Tipo", "country_code": "País",
                   "founding_year": "Fundación", "lanzamientos": "Lanzamientos",
                   "tasa_%": "Tasa éxito %",
               }),
        width="stretch",
        hide_index=True,
    )


# ========================== TAB 4: ASTRONAUTAS =============================
with tab_astronautas:
    st.subheader("👨‍🚀 Las personas que han volado al espacio")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total astronautas", f"{len(astronauts):,}")
    activos = astronauts[astronauts["status"] == "Active"]
    c2.metric("Activos", f"{len(activos):,}")
    c3.metric("Países representados", f"{astronauts['nationality'].nunique():,}")

    col_filtros, col_chart = st.columns([1, 2])
    with col_filtros:
        nats = sorted(n for n in astronauts["nationality"].dropna().unique())
        nat_sel = st.multiselect("Nacionalidad", nats)
        estados_ast = sorted(a for a in astronauts["status"].dropna().unique())
        estado_sel = st.multiselect("Estado", estados_ast)
        busqueda_ast = st.text_input("🔍 Buscar astronauta")

    ast = astronauts.copy()
    if nat_sel:
        ast = ast[ast["nationality"].isin(nat_sel)]
    if estado_sel:
        ast = ast[ast["status"].isin(estado_sel)]
    if busqueda_ast:
        ast = ast[ast["name"].str.contains(busqueda_ast, case=False, na=False)]

    with col_chart:
        nat_top = ast["nationality"].value_counts().head(12)
        fig = px.bar(
            nat_top, x=nat_top.values, y=nat_top.index, orientation="h",
            color=nat_top.values, color_continuous_scale="Viridis",
            title="Astronautas por nacionalidad (top 12)",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=360)
        st.plotly_chart(fig, width="stretch")

    col_x, col_y = st.columns(2)
    with col_x:
        estado_count = ast["status"].value_counts()
        fig = px.pie(
            estado_count, names=estado_count.index, values=estado_count.values,
            title="Estado actual", hole=0.45,
        )
        st.plotly_chart(fig, width="stretch")
    with col_y:
        vuelos = ast["flights_count"].dropna()
        if not vuelos.empty:
            fig = px.histogram(
                vuelos, nbins=15, title="Distribución de vuelos por astronauta",
                color_discrete_sequence=["#7aa2f7"],
            )
            fig.update_layout(xaxis_title="Nº de vuelos")
            st.plotly_chart(fig, width="stretch")

    st.markdown("#### Tabla de astronautas")
    st.dataframe(
        ast[["name", "nationality", "status", "agency", "flights_count",
             "first_flight", "date_of_birth"]].rename(columns={
                 "name": "Nombre", "nationality": "Nacionalidad",
                 "status": "Estado", "agency": "Agencia",
                 "flights_count": "Vuelos", "first_flight": "Primer vuelo",
                 "date_of_birth": "Nacimiento",
             }).sort_values("Nombre"),
        width="stretch",
        hide_index=True,
    )

    with st.expander("👤 Ver biografía de un astronauta"):
        if not ast.empty:
            eleccion = st.selectbox("Elige un astronauta",
                                    sorted(ast["name"].dropna().unique()))
            fila_ast = ast[ast["name"] == eleccion].iloc[0]
            c_izq, c_der = st.columns([1, 2])
            with c_izq:
                if fila_ast["profile_image"]:
                    st.image(fila_ast["profile_image"], width="stretch")
            with c_der:
                st.markdown(
                    f"**{fila_ast['name']}**  \n"
                    f"- **Nacionalidad:** {fila_ast['nationality'] or '—'}  \n"
                    f"- **Estado:** {fila_ast['status'] or '—'}  \n"
                    f"- **Agencia:** {fila_ast['agency'] or '—'}  \n"
                    f"- **Vuelos:** {fila_ast['flights_count'] or '—'}  \n"
                    f"- **Primer vuelo:** {fila_ast['first_flight'] or '—'}"
                )
                if fila_ast["bio"]:
                    st.markdown(fila_ast["bio"][:900])


# ========================== TAB 5: PRÓXIMOS ================================
with tab_proximos:
    st.subheader("📅 Próximos lanzamientos")

    if proximos.empty:
        st.info("No hay lanzamientos futuros en la base de datos. "
                "Ejecuta `python ingesta.py --update` para actualizar.")
    else:
        prox = proximos.sort_values("net").copy()
        prox["net_dt"] = pd.to_datetime(prox["net"], errors="coerce", utc=True)
        ahora = pd.Timestamp.now(timezone.utc)

        dentro_7 = (prox["net_dt"] - ahora).dt.total_seconds().between(0, 7 * 86400).sum()
        dentro_30 = (prox["net_dt"] - ahora).dt.total_seconds().between(0, 30 * 86400).sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("Próximos lanzamientos", f"{len(prox):,}")
        c2.metric("En los próximos 7 días", f"{int(dentro_7)}")
        c3.metric("En los próximos 30 días", f"{int(dentro_30)}")

        for _, fila in prox.head(8).iterrows():
            dias = (fila["net_dt"] - ahora).total_seconds() / 86400
            dias_txt = f"⏳ En {dias:.0f} días" if dias >= 1 else "🔴 ¡Hoy o mañana!"
            with st.container(border=True):
                cc1, cc2 = st.columns([3, 1])
                with cc1:
                    st.markdown(f"**{fila['name']}**  \n"
                                f"{fila['net'] or '—'} · {dias_txt}")
                    st.caption(
                        f"🚀 {fila['rocket_name'] or '—'} · "
                        f"🏛️ {fila['agency_name'] or '—'} · "
                        f"📍 {fila['location_name'] or '—'} · "
                        f"🛰️ {fila['orbit'] or '—'}"
                    )
                with cc2:
                    if fila["image_url"]:
                        st.image(fila["image_url"], width=90)

        st.divider()
        st.markdown("#### Todos los próximos")
        st.dataframe(
            prox[["name", "net", "rocket_name", "agency_name",
                  "location_name", "orbit", "status_name"]].rename(columns={
                      "name": "Lanzamiento", "net": "Fecha (UTC)",
                      "rocket_name": "Cohete", "agency_name": "Agencia",
                      "location_name": "Cosmódromo", "orbit": "Órbita",
                      "status_name": "Estado",
                  }),
            width="stretch",
            hide_index=True,
        )


# ========================== TAB 6: CHAT RAG ================================
with tab_chat:
    st.subheader("💬 Chat sobre la industria espacial")
    st.markdown(
        "Pregunta en lenguaje natural y el chat buscará la respuesta en "
        "**tus propios datos**. Ejemplos:\n\n"
        "- *¿Qué cohetes de SpaceX tienen más de 100 lanzamientos?*\n"
        "- *¿Cuál es la tasa de éxito de la NASA?*\n"
        "- *¿Cuántos astronautas españoles hay?*\n"
        "- *¿Qué lanzamientos están previstos para este mes?*"
    )

    if "mensajes" not in st.session_state:
        st.session_state.mensajes = []

    col_ctrl, col_info = st.columns([2, 2])
    with col_ctrl:
        k = st.slider("Fichas recuperadas (k)", 1, 10, 4, key="k_slider")
        if st.button("🗑️ Borrar conversación", width="stretch"):
            st.session_state.mensajes = []
            st.rerun()

    try:
        import chromadb
        from chromadb.utils import embedding_functions

        rag_disponible = True
    except ImportError:
        rag_disponible = False

    if not rag_disponible:
        st.warning(
            "`chromadb` no está instalado. Instálalo con "
            "`pip install -r requirements.txt`."
        )
    else:
        try:
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            embedding_fn = embedding_functions.OllamaEmbeddingFunction(
                model_name=MODELO_EMBEDDING,
                url=f"{URL_OLLAMA}/api/embeddings",
            )
            coleccion = client.get_collection(
                name="lanzamientos", embedding_function=embedding_fn
            )
        except Exception:
            coleccion = None

        if coleccion is None or coleccion.count() == 0:
            st.info(
                "No hay corpus indexado. Ejecuta primero:\n\n"
                "```bash\npython preparar_corpus.py\n```\n\n"
                "Necesitas tener **Ollama** funcionando con los modelos "
                f"`{MODELO_EMBEDDING}` y `{MODELO_CHAT}` descargados:"
                "\n\n```bash\nollama pull " + MODELO_EMBEDDING + "\n"
                "ollama pull " + MODELO_CHAT + "\n```"
            )
        else:
            for msg in st.session_state.mensajes:
                with st.chat_message(msg["rol"]):
                    st.markdown(msg["contenido"])

            if prompt := st.chat_input("Pregunta sobre el espacio..."):
                st.session_state.mensajes.append({"rol": "user", "contenido": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Buscando en la base de datos..."):
                        try:
                            resultados = coleccion.query(
                                query_texts=[prompt], n_results=k
                            )
                        except Exception as e:
                            st.error(
                                f"No se pudo consultar el índice vectorial: {e}\n\n"
                                "Comprueba que Ollama está en marcha y vuelve a "
                                "intentarlo."
                            )
                            resultados = None

                        contexto = ""
                        fuentes = []
                        if resultados and resultados.get("documents") and resultados["documents"][0]:
                            for i, doc in enumerate(resultados["documents"][0]):
                                meta = resultados["metadatas"][0][i]
                                contexto += (
                                    f"\n--- Fuente {i+1}: "
                                    f"[{meta.get('tipo', '')}] {meta.get('nombre', '')} ---\n"
                                    f"{doc}\n"
                                )
                                fuentes.append(
                                    f"{meta.get('tipo', '')} · {meta.get('nombre', '')}"
                                )

                        # Memoria conversacional: últimos mensajes
                        historial = [
                            {"role": m["rol"], "content": m["contenido"]}
                            for m in st.session_state.mensajes[-12:]
                        ]

                        system_prompt = (
                            "Eres un experto en exploración espacial y "
                            "lanzamientos de cohetes. Responde a la pregunta "
                            "del usuario usando SOLO la información del "
                            "contexto proporcionado. Si no encuentras la "
                            "respuesta en el contexto, dilo directamente. "
                            "Sé conciso, claro y en español."
                        )

                        try:
                            import ollama

                            respuesta_ollama = ollama.chat(
                                model=MODELO_CHAT,
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    *historial,
                                    {
                                        "role": "user",
                                        "content": (
                                            f"Contexto:\n{contexto}\n\n"
                                            f"Pregunta: {prompt}"
                                        ),
                                    },
                                ],
                            )
                            respuesta = respuesta_ollama["message"]["content"]
                        except Exception as e:
                            respuesta = (
                                f"⚠️ No se pudo conectar con Ollama: {e}\n\n"
                                f"**Contexto recuperado:**\n{contexto[:1200]}"
                            )

                        st.markdown(respuesta)

                        if fuentes:
                            st.markdown("---")
                            st.markdown(
                                "**Fuentes consultadas:** " + ", ".join(set(fuentes))
                            )

                st.session_state.mensajes.append({"rol": "assistant", "contenido": respuesta})

                if len(st.session_state.mensajes) > 24:
                    st.session_state.mensajes = st.session_state.mensajes[-24:]


# ========================== TAB 7: NASA APOD ===============================
with tab_apod:
    st.subheader("🌌 Imagen astronómica del día (NASA)")

    clave = None
    try:
        clave = st.secrets.get("NASA_API_KEY")
    except Exception:
        pass
    if not clave:
        clave = os.getenv("NASA_API_KEY", "DEMO_KEY")

    @st.cache_data(ttl=3600, show_spinner=False)
    def obtener_apod(api_key):
        url = "https://api.nasa.gov/planetary/apod"
        try:
            resp = requests.get(url, params={"api_key": api_key}, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    dato = obtener_apod(clave)

    if "error" in dato:
        st.warning(
            "No se pudo obtener la imagen del día. Si has usado la clave "
            "DEMO_KEY, puede que se haya agotado el límite de peticiones. "
            "Regístrate gratis en https://api.nasa.gov y añade tu clave en "
            "`.streamlit/secrets.toml`."
        )
        if dato["error"]:
            st.caption(f"Detalle: {dato['error']}")
    else:
        st.markdown(
            f"### {dato.get('title', '')}\n{dato.get('date', '')} · "
            f"{dato.get('copyright', 'NASA')}"
        )
        if dato.get("media_type") == "image":
            st.image(dato.get("url"), width="stretch")
        elif dato.get("media_type") == "video":
            st.video(dato.get("url"))
        st.caption(dato.get("explanation", ""))
