# 🚀 Órbita · La industria espacial en cifras

Producto de datos completo sobre **lanzamientos espaciales** (1957 → hoy):
ingesta desde API, base de datos SQLite, análisis exploratorio, dashboard en
Streamlit y un **chat RAG** con IA que responde preguntas sobre tus propios
datos.

<p align="center">
  <em>¿Quién lanza más? ¿Qué cohetes son más fiables? ¿Cuántas personas han
  volado al espacio? ¿Qué lanzamientos vienen en los próximos meses?</em>
</p>

---

## Problema que resuelve

El sector espacial ha pasado de 3 lanzamientos al año (1957) a más de 250.
Seguir **quién lanza, con qué fiabilidad, desde dónde y hacia dónde** es
abrumador incluso para los profesionales del sector.

**Órbita** lo resume en un solo producto:

- 📊 **Explorar** la historia completa de los lanzamientos con filtros por
  año, estado, agencia y órbita.
- 🏢 **Comparar** agencias y cohetes por volumen y tasa de éxito.
- 👨‍🚀 **Conocer** a las personas que han volado al espacio.
- 📅 **Planificar** con el calendario de próximos lanzamientos.
- 💬 **Preguntar** en lenguaje natural con un chat RAG sobre los datos.

**Audiencia:** aficionados al espacio, periodistas de ciencia, estudiantes,
analistas del sector *new space* y equipos de comunicación que necesitan
datos fiables de la industria.

**Datos:** los **7.900+ lanzamientos** orbitales y suborbitales registrados
desde 1957, junto a **350 agencias**, **858 astronautas**, **53 cosmódromos**
y **238 rampas**, procedentes de la API pública
[Launch Library 2](https://ll.thespacedevs.com) (The Space Devs), **sin
necesidad de registro ni API key**.

---

## Estructura del proyecto

```
Nasa/
├── README.md                  ← este fichero
├── requirements.txt           ← dependencias
├── .gitignore
├── secrets_ejemplo.toml       ← plantilla de secrets (key NASA opcional)
├── ingesta.py                 ← API → SQLite (con caché y modo incremental)
├── preparar_corpus.py         ← SQLite → Chroma (fichas para el chat RAG)
├── app.py                     ← aplicación Streamlit (7 pestañas)
├── diccionario_datos.md       ← documentación del esquema de datos
├── data/
│   ├── espacio.db             ← base de datos SQLite (generada)
│   └── raw/                   ← copia cruda de la API (caché)
├── notebooks/
│   └── eda.ipynb              ← análisis exploratorio con conclusiones
├── capturas/                  ← capturas de pantalla de la app (opcional)
└── .streamlit/
    └── config.toml            ← tema visual de la app
```

---

## Requisitos

- **Python 3.10 o superior** (probado con 3.12+)
- **Ollama** (opcional, solo para el chat RAG) con los modelos
  `nomic-embed-text` y `llama3.2`:
  ```bash
  ollama pull nomic-embed-text
  ollama pull llama3.2
  ```
  La app funciona sin Ollama; el chat simplemente te avisará.

---

## Instalación y ejecución

```bash
# 1. Clonar el repositorio
git clone <repo-url>
cd Nasa

# 2. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ingesta de datos (descarga la API de Launch Library 2)
python ingesta.py

# ¿Prisa? Carga parcial rápida (solo lanzamientos recientes):
# python ingesta.py --desde 2010-01-01
# (La carga completa de 1957 → hoy puede tardar: la API limita el ritmo.
#  El script reanuda solo y guarda caché en data/raw/.)

# 5. (Opcional) Indexar el corpus para el chat RAG
python preparar_corpus.py

# 6. Lanzar la app
streamlit run app.py
```

> **Sin API key.** A diferencia de otros proyectos, Launch Library 2 no pide
> registro. La única clave opcional es la de la NASA (para la pestaña
> "Imagen del día"): cópia `secrets_ejemplo.toml` a `.streamlit/secrets.toml`
> y rellena `NASA_API_KEY` si quieres más límite que la `DEMO_KEY`.

---

## La API y los límites de peticiones

Los datos se descargan de `https://ll.thespacedevs.com/2.0.0/`. La
documentación oficial indica **~15 peticiones/hora** para uso gratuito,
aunque en la práctica admite ráfagas mayores. El script está preparado para
convivir con ese límite:

- **Caché local**: la primera descarga guarda una copia cruda en
  `data/raw/`. Re-ejecutar el script **no vuelve a descargarlo todo**.
- **Reanudación**: si se interrumpe, la siguiente ejecución continúa desde
  la última página completa.
- **Control de ritmo**: `--sleep` ajusta los segundos entre peticiones
  (por defecto 1 s). Ante un error `429` el script espera el tiempo que la
  propia API indica y reintenta.
- **Cargas parciales** para no esperar la descarga completa:
  ```bash
  python ingesta.py --limite 500      # solo 500 lanzamientos (prueba rápida)
  python ingesta.py --desde 2010-01-01 # solo lanzamientos desde 2010
  ```
- **Actualización incremental**: añade solo lo nuevo sin volver a descargar
  el histórico:
  ```bash
  python ingesta.py --update
  ```

---

## Funcionalidades de la app

### 📊 Resumen
- Métricas globales: lanzamientos, tasa de éxito, agencias, astronautas y
  próximos lanzamientos.
- Evolución anual, desglose por estado y top de agencias.
- **Mapa mundial** con todos los centros de lanzamiento.

### 🚀 Lanzamientos
- Filtros globales en la barra lateral (año, estado, agencia, órbita) y
  buscador textual.
- Gráficos de cohetes y órbitas más usadas.
- Tabla completa y **ficha visual** de cualquier lanzamiento.

### 🏢 Agencias
- Top de agencias por lanzamientos, coloreado por tasa de éxito.
- **Fiabilidad frente a volumen** (dispersión interactiva).
- Tabla filtrable por tipo de agencia y país.

### 👨‍🚀 Astronautas
- Métricas y distribución por nacionalidad y estado.
- Biografías con fotografía.

### 📅 Próximos
- Calendario de lanzamientos futuros con cuenta atrás.
- Tarjetas de los próximos 8 y tabla completa.

### 💬 Chat RAG
- Preguntas en lenguaje natural sobre **tus datos**.
- Recuperación de contexto con **Chroma + embeddings locales** de Ollama.
- Generación con Llama 3.2, **memoria conversacional** (últimos 12 mensajes),
  slider de fichas recuperadas (`k`) y botón para borrar la conversación.

### 🌌 Imagen del día
- Fotografía astronómica diaria de la **NASA APOD** (requiere clave opcional).

---

## Despliegue en Streamlit Cloud

1. Sube el repositorio a GitHub y conéctalo en
   [share.streamlit.io](https://share.streamlit.io).
2. En **⚙️ → Secrets** añade (opcional):
   ```toml
   NASA_API_KEY = "tu_clave_de_la_nasa"
   ```
3. **Ojo con el chat RAG en la nube:** los *embeddings* se generan con tu
   **Ollama local**, que en la nube no existe. En Streamlit Cloud funcionarán
   todas las pestañas de datos; el chat requiere ejecución local con Ollama
   encendido. (Reto avanzado: mover embeddings a un servicio en la nube.)

---

## Retos implementados

- [x] **Memoria conversacional** en el chat (seguimiento tipo *"¿y ese
      cuántos puntos tiene?"*).
- [x] **Slider** para el número de fichas recuperadas (`k`) y **botón de
      borrar** la conversación.
- [x] **Actualización incremental** de datos (`ingesta.py --update`).
- [x] **Reanudación** de la ingesta tras interrupción y **caché** local.
- [x] **Mapa interactivo** de centros de lanzamiento.
- [x] **Segundo conjunto de datos**: astronautas (más de 850 fichas).

---

## Solución de problemas

| Problema | Solución |
|---|---|
| `429 Too Many Requests` | La API ha limitado el ritmo. Espera unos minutos y vuelve a ejecutar `python ingesta.py` (reanuda solo). O usa `--sleep 5` para ir más lento. |
| *"No se encuentra la base de datos"* en la app | Ejecuta `python ingesta.py` antes de `streamlit run app.py`. |
| El chat dice que no hay corpus | Ejecuta `python preparar_corpus.py` con Ollama encendido. |
| *"No se pudo conectar con Ollama"* | Arranca Ollama (`ollama serve`) y descarga los modelos: `ollama pull nomic-embed-text` y `ollama pull llama3.2`. |
| La imagen del día falla | La `DEMO_KEY` tiene límite de ~30 peticiones/hora. Regístrate gratis en api.nasa.gov y añade tu clave en `.streamlit/secrets.toml`. |

---

## Datos

El esquema completo está documentado en
[`diccionario_datos.md`](diccionario_datos.md). Los datos pertenecen a
[The Space Devs](https://thespacedevs.com) (API Launch Library 2) y se usan
con fines educativos. Imágenes de la NASA bajo su
[política de medios](https://www.nasa.gov/multimedia/guidelines).

---

## Licencia

Proyecto educativo. Código MIT. Los datos son propiedad de sus respectivas
fuentes y se distribuyen según sus términos de servicio.
