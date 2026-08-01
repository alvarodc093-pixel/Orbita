# Diccionario de datos

Base de datos: `data/espacio.db` (SQLite)
Fuente de los datos: [Launch Library 2](https://ll.thespacedevs.com) (The Space Devs), API pública sin necesidad de registro.

## Tablas

### `launches`
Un lanzamiento orbital o suborbital. Es la tabla principal del proyecto (más de 7.900 registros desde 1957).

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | TEXT (PK) | Identificador único (UUID) |
| `slug` | TEXT | Identificador legible (ej. `sputnik-8k74ps-sputnik-1`) |
| `name` | TEXT | Nombre público del lanzamiento (cohete \| carga útil) |
| `status_id` | INTEGER | Código del estado (3 = Success, 4 = Failure…) |
| `status_name` | TEXT | Estado: Success, Failure, Partial Failure, Go, TBD… |
| `net` | TEXT | Fecha/hora prevista o real (ISO 8601, UTC) |
| `window_start` / `window_end` | TEXT | Ventana de lanzamiento (ISO 8601, UTC) |
| `anio` | INTEGER | Año del lanzamiento (derivado de `net`) |
| `probability` | REAL | Probabilidad de lanzamiento estimada (lanzamientos futuros) |
| `holdreason` | TEXT | Motivo de retención en tierra |
| `failreason` | TEXT | Motivo de fallo (si lo hubo) |
| `webcast_live` | INTEGER | 1 si hay emisión en directo |
| `image_url` | TEXT | Imagen del lanzamiento |
| `infographic_url` | TEXT | Infografía de la misión |
| `url` | TEXT | URL del registro en la API |
| `mission_id` | INTEGER | Identificador de la misión |
| `mission_name` | TEXT | Nombre de la misión (ej. "Sputnik 1") |
| `mission_description` | TEXT | Descripción de la misión |
| `mission_type` | TEXT | Tipo de misión (Test Flight, Communications…) |
| `orbit` | TEXT | Órbita objetivo (LEO, GTO, GEO, SSO…) |
| `rocket_id` | INTEGER | Identificador de la configuración del cohete |
| `rocket_name` | TEXT | Nombre del cohete (ej. "Falcon 9 Block 5") |
| `rocket_family` | TEXT | Familia del cohete (ej. "Falcon") |
| `rocket_variant` | TEXT | Variante (ej. "Block 5") |
| `agency_id` | INTEGER | Identificador de la agencia que lanza |
| `agency_name` | TEXT | Nombre de la agencia (ej. "SpaceX") |
| `agency_type` | TEXT | Tipo (Commercial, Government…) |
| `pad_id` | INTEGER | Identificador de la rampa |
| `pad_name` | TEXT | Nombre de la rampa (ej. "SLC-40") |
| `pad_latitude` / `pad_longitude` | REAL | Coordenadas de la rampa |
| `location_id` | INTEGER | Identificador del cosmódromo |
| `location_name` | TEXT | Nombre del cosmódromo (ej. "Cape Canaveral") |
| `location_country` | TEXT | Código de país (ej. "USA", "KAZ") |
| `programs` | TEXT | Programas asociados separados por comas (ej. "Starlink, ISS") |
| `created_at` | TEXT | Cuándo se ingirió el registro |

### `agencies`
Agencias espaciales y empresas implicadas en el sector (350 registros).

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER (PK) | Identificador |
| `name` | TEXT | Nombre (ej. "SpaceX") |
| `type` | TEXT | Commercial, Government, Multinational… |
| `country_code` | TEXT | Código de país |
| `abbrev` | TEXT | Abreviatura (ej. "NASA", "RFSA") |
| `description` | TEXT | Descripción de la agencia |
| `founding_year` | INTEGER | Año de fundación |
| `administrator` | TEXT | Persona al frente |
| `image_url` | TEXT | Logotipo o imagen |
| `url` | TEXT | URL del registro |

### `astronauts`
Astronautas y cosmonautas (858 registros).

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER (PK) | Identificador |
| `name` | TEXT | Nombre completo |
| `status` | TEXT | Active, Retired, Lost In Flight… |
| `type` | TEXT | Government, Commercial… |
| `nationality` | TEXT | Nacionalidad (ej. "American", "Russian") |
| `date_of_birth` / `date_of_death` | TEXT | Fechas de nacimiento/fallecimiento |
| `first_flight` / `last_flight` | TEXT | Primer y último vuelo |
| `flights_count` | INTEGER | Número de vuelos |
| `agency` | TEXT | Agencia de pertenencia |
| `bio` | TEXT | Biografía |
| `profile_image` | TEXT | Foto de perfil |
| `wiki` | TEXT | Enlace a Wikipedia |

### `locations`
Cosmódromos y centros de lanzamiento (53 registros).

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER (PK) | Identificador |
| `name` | TEXT | Nombre (ej. "Baikonur Cosmodrome") |
| `country_code` | TEXT | Código de país |
| `map_image` | TEXT | Mapa del lugar |
| `total_launch_count` | INTEGER | Lanzamientos totales según la API |
| `total_landing_count` | INTEGER | Aterrizajes totales |

### `pads`
Rampas de lanzamiento concretas (238 registros).

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | INTEGER (PK) | Identificador |
| `name` | TEXT | Nombre de la rampa (ej. "SLC-40") |
| `latitude` / `longitude` | REAL | Coordenadas |
| `map_image` | TEXT | Mapa |
| `location_id` | INTEGER | Cosmódromo al que pertenece |
| `location_name` | TEXT | Nombre del cosmódromo |
| `country_code` | TEXT | Código de país |
| `total_launch_count` | INTEGER | Lanzamientos desde esa rampa |
| `agency_id` | INTEGER | Agencia propietaria |

### `meta_ingesta`
Metadatos del proceso de ingesta.

| Campo | Tipo | Descripción |
|---|---|---|
| `clave` | TEXT (PK) | Identificador (ej. `ultima_ejecucion`) |
| `valor` | TEXT | Valor |
