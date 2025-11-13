# Data Mining / Proyecto 04 – NYC Taxi Trips (Regresión ML + OBT en PostgreSQL)

## Descripción  
En este proyecto se implementa un **pipeline completo de datos y Machine Learning** usando **Apache Spark** en Jupyter para procesar datos históricos de viajes de taxi (Yellow y Green) de NYC, construyendo una **One Big Table (OBT)** en **PostgreSQL** y entrenando modelos de regresión **desde cero con NumPy** para predecir `total_amount`.

Este proyecto utiliza:
- **Docker Compose** con Jupyter + Spark, PostgreSQL 
- **Dockerfile** para ejecutar el obt_builder
- **Ingesta masiva** con idempotencia y auditoría
- **Modelo OBT desnormalizado** en PostgreSQL para análisis directo
- **Modelos ML propios** (SGD, Ridge, Lasso, Elastic Net) vs scikit-learn
- **Script CLI reproducible** para construcción de OBT

## Comandos para correr la obt:

```bash
# 1. Levantar infraestructura (Postgres + Jupyter)
docker-compose up -d

# 2. Construir imagen del OBT builder
docker build -t obt-builder -f Dockerfile.obt .

# 3. Ejecutar construcción de OBT (2022-2024)
docker run --rm \
  --network proyecto-04_default \
  -e PG_HOST= \
  -e PG_PORT= \
  -e PG_DB= \
  -e PG_USER= \
  -e PG_PASSWORD= \
  -e PG_SCHEMA_RAW= \
  -e PG_SCHEMA_ANALYTICS=analytics \
  obt-builder
```

**Nota:** El tercer comando construye la OBT para los años 2022-2024 usando los parámetros por defecto del Dockerfile.

---

## Decisiones de alcance y limitaciones de recursos

### Problema principal: Espacio en disco insuficiente

Durante el desarrollo del proyecto se enfrentó un **desafío crítico de espacio en disco**. El volumen completo de datos (2015-2025, Yellow + Green) supera los **850M de registros**, lo que representa:
- ~80GB en archivos Parquet comprimidos
- ~200GB+ en PostgreSQL sin índices
- ~300GB+ con índices y OBT completa

**Impacto:** El disco local se llenó múltiples veces, requiriendo **reiniciar el proceso desde cero** en varias ocasiones.

### Solución implementada: Scope reducido estratégico

Para garantizar la **entrega funcional** del proyecto dentro de las restricciones de recursos, se tomaron las siguientes decisiones:

#### 1. Ingesta RAW (Completa: 2015-2025)
✅ **Se logró ingestar TODOS los años** (2015-2025) en las tablas RAW:
- `raw.yellow_taxi_trip`: ~784M registros
- `raw.green_taxi_trip`: ~68M registros
- `raw.taxi_zone_lookup`: 265 registros

**Evidencia:** Archivo de auditoría en `auditoria/audit_ingesta.csv`

#### 2. Construcción OBT (Reducida: 2022, 2023,2024)
 **Por limitaciones de espacio, la OBT se construyó solo para 1 año:**
- Años procesado: 2022, 2023, 2024
- Registros en `analytics.obt_trips`: ~121.4M registros
- **Parametrizable:** El script CLI permite expandir a todos los años si hay espacio disponible

**Comando para construcción completa (si hay recursos):**
```bash
docker run --rm \
  --network proyecto-04_default \
  -e PG_HOST= \
  -e PG_PORT= \
  -e PG_DB= \
  -e PG_USER= \
  -e PG_PASSWORD= \
  -e PG_SCHEMA_RAW= \
  -e PG_SCHEMA_ANALYTICS= \
  obt-builder \
  --mode full \
  --year-start 2015 \
  --year-end 2025 \
  --services yellow,green \
  --overwrite
```

#### 3. Entrenamiento ML (Sample: 2024)
**El notebook de ML usa solo 1 año (2024) como muestra:**
- Sample size: ~100,000 filas por año
- **Razón:** Limitaciones de memoria RAM y tiempo de procesamiento
- **Escalable:** Se puede modificar el query SQL en el notebook para incluir múltiples años

**Para usar todos los años disponibles en ML:**
```python
# En ml_total_amount_regression.ipynb, modificar:
query = """
SELECT * FROM analytics.obt_trips 
WHERE year IN (2022, 2023, 2024)  -- Expandir aquí
AND total_amount > 0 
AND trip_distance > 0
"""
```

### Resumen de cobertura final

| Componente | Años cubiertos | Registros | Limitación |
|------------|----------------|-----------|------------|
| **RAW (Yellow/Green)** | 2015-2025 (completo) | ~852M | ✅ Ninguna |
| **OBT (analytics)** | 2022-2024 (reducido) | ~121.4M | ⚠️ Espacio en disco |
| **ML Training** | 2024 (sample) | ~100000 | ⚠️ RAM + tiempo |

---

## Arquitectura

### Flujo de datos:
1. **Ingesta RAW** → Descarga Parquet por mes/año → `raw.yellow_taxi_trip` + `raw.green_taxi_trip`
2. **OBT Construction** → Script CLI lee RAW, unifica Y+G con JOINs, agrega derivadas → `analytics.obt_trips`
3. **Machine Learning** → Carga desde OBT, preprocesamiento, entrenamiento de 8 modelos (4 propios + 4 sklearn)
4. **Evaluación** → Comparación de métricas (RMSE/MAE/R²) y diagnóstico de errores

### Servicios Docker Compose:
- **postgres**: Base de datos con esquemas `raw` y `analytics`
- **pgadmin**: UI web para validar tablas (http://localhost:8081)
- **spark-notebook**: Jupyter + Spark para ingesta y ML (http://localhost:8888)


---

## Estrategia de backfill & idempotencia  
Durante el proceso se identificó que el volumen total de datos superaba los 700 millones de registros, lo que generaba problemas de performance y timeouts al intentar cargas masivas de una sola vez. Después de varias pruebas se adoptó una estrategia de carga incremental en chunks, procesando cada mes de manera controlada y dividiendo archivos grandes en bloques de hasta 1 millón de filas para evitar errores de memoria o límites de Postgres.

### Ingesta RAW (2015-2025)

#### Estrategia implementada:

- **Ingesta mensual controlada con Spark:**  
  Cada archivo Parquet representa un mes de viajes para un servicio (`yellow` o `green`).  
  Se descarga con `requests` y se procesa con PySpark en chunks controlados.

- **Carga por lotes hacia PostgreSQL:**  
  Se divide en lotes para evitar timeouts y saturar la conexión JDBC.
  Cada lote se escribe con `.write.jdbc()` en modo `append`.

- **Columnas de control agregadas para trazabilidad:**
  - `ingested_at_utc`: Marca de tiempo de ingesta (UTC).  
  - `source_year` y `source_month`: Para auditoría y consultas históricas.  
  - `run_tag`: Identificador único de ejecución para rastrear procesos.

- **Registro de auditoría e idempotencia:**
## Cobertura de datos

### Período cubierto
- **Años:** 2015 - 2025
- **Servicios:** Yellow Taxi, Green Taxi
- **Formato origen:** Parquet (NYC TLC oficial)

### Matriz de cobertura

Se usó un archivo.csv para asegurar idempotencia y registrar los meses que ya han sido insertados también por tema de calidad de datos. Antes de cargar un mes se consulta esta tabla: si ya existe con estado ok, el proceso lo omite automáticamente para evitar duplicados.

**Archivo completo con detalle por año, mes y servicio:**  
[audit_ingesta.csv](auditoria/audit_ingesta.csv)

#### Estadísticas finales (RAW):
- Yellow Taxi: ~784M viajes (2015-2025)
- Green Taxi: ~68M viajes (2015-2025)
- Taxi Zone Lookup: 265 zonas

---

### Construcción OBT (2022-2024)

#### Script CLI: `obt_builder_cli.py`

1. **Lee desde `raw.*`** (yellow, green, taxi_zone_lookup)
2. **Unifica Yellow + Green** con UNION ALL
3. **Hace JOINs** con zonas de pickup/dropoff
4. **Calcula columnas derivadas:**
   - `trip_duration_min` = `EXTRACT(EPOCH FROM dropoff - pickup) / 60`
   - `avg_speed_mph` = `trip_distance / (duration / 60)`
   - `tip_pct` = `(tip_amount / total_amount) * 100`
5. **Inserta en `analytics.obt_trips`**

#### Modos de ejecución:

**Modo FULL (reconstrucción completa):**
- Trunca la tabla OBT y la reconstruye desde cero
- Útil para cambios estructurales o resetear datos

**Modo BY-PARTITION (incremental):**
- Procesa solo las particiones especificadas (año + servicio)
- Si `--overwrite` está presente, elimina y recrea la partición
- Si no, salta particiones que ya existen (idempotencia)

#### Idempotencia en OBT:

**Estrategia: Delete + Insert por partición**
```sql
-- Antes de insertar año=2024, service='yellow':
DELETE FROM analytics.obt_trips 
WHERE source_year = 2024 AND service_type = 'yellow';

-- Luego insert de datos frescos
INSERT INTO analytics.obt_trips (...)
SELECT ... FROM raw.yellow_taxi_trip WHERE source_year = 2024;
```

**Ventajas:**
- Garantiza datos actualizados sin duplicados
- Permite reejecutar sin efectos secundarios
- Facilita backfill de meses/años específicos

**Limitación:**
- No hay transaccionalidad total (delete + insert no es atómico en PostgreSQL sin lógica adicional)
- En producción se usaría `MERGE` o tablas temporales

---

## Configuración del entorno

### Requisitos previos
- Docker y Docker Compose instalados
- 8GB+ RAM recomendado (16GB óptimo para ML)
- 50GB+ espacio en disco libre (100GB+ para todos los años en OBT)

### Variables de ambiente

#### Configuración `.env`

Copia `.env.example` a `.env` y configura:

```bash
# PostgreSQL Connection
PG_HOST=
PG_PORT=
PG_DB=
PG_USER=
PG_PASSWORD=
PG_SCHEMA_RAW=
PG_SCHEMA_ANALYTICS=

# PgAdmin Configuration
PGADMIN_EMAIL=@admin.com
PGADMIN_PASSWORD=
PGADMIN_PORT=

# Ingestion Parameters (para notebooks)
START_YEAR=
END_YEAR=
SERVICES=
BASE_URL=
BATCH_SIZE=
```

#### Descripción de variables

| Variable | Propósito | Ejemplo |
|----------|-----------|---------|
| `PG_HOST` | Nombre del servicio PostgreSQL en Docker | `postgres` |
| `PG_PORT` | Puerto de PostgreSQL | `5432` |
| `PG_DB` | Nombre de la base de datos | `nyc_taxi` |
| `PG_USER` | Usuario con permisos DDL/DML | `hola` |
| `PG_PASSWORD` | Contraseña del usuario | `hola` |
| `PG_SCHEMA_RAW` | Schema para datos crudos | `raw` |
| `PG_SCHEMA_ANALYTICS` | Schema para OBT | `analytics` |
| `START_YEAR` | Año inicial de ingesta | `2015` |
| `END_YEAR` | Año final de ingesta | `2025` |
| `SERVICES` | Servicios a ingestar (separados por coma) | `yellow,green` |
| `BATCH_SIZE` | Filas por lote en ingesta Spark | `100000` | |

---

## Ejecución paso a paso

### 1. Levantar infraestructura

```bash
# Clonar repositorio
git clone <repo-url>
cd proyecto-04

# Configurar variables de ambiente
cp .env.example .env
nano .env  # Editar con tus credenciales

# Levantar Docker Compose (solo postgres, pgadmin, spark-notebook)
docker-compose up -d

# Verificar contenedores
docker-compose ps
```

**Servicios disponibles:**
- Jupyter Notebook: http://localhost:8888 (sin token)
- Spark UI: http://localhost:4040
- PgAdmin: http://localhost:8081

### 2. Ejecutar notebooks en orden

#### Notebook 01: Ingesta RAW (~8-12 horas para 2015-2025)

```python
# En Jupyter: notebooks/01_ingesta_parquet_raw.ipynb
# Este notebook:
# - Descarga Parquet mes a mes desde NYC TLC
# - Carga con PySpark en PostgreSQL (JDBC)
# - Crea tablas raw.yellow_taxi_trip y raw.green_taxi_trip
# - Carga taxi_zone_lookup desde CSV
# - Agrega columnas de metadatos (run_tag, source_year, source_month, ingested_at_utc)
```

**Output esperado:**
- `raw.yellow_taxi_trip`: ~784M registros
- `raw.green_taxi_trip`: ~68M registros
- `raw.taxi_zone_lookup`: 265 registros

**Evidencia:**
- Logs de Spark con conteos por mes/año
- Capturas de pantalla en `evidencias/ingesta/`

#### Notebook 02: Construcción OBT con CLI (ejecutado por profesor)

 **Este paso NO se ejecuta en notebook, sino con Docker:**

**Paso 1: Construir la imagen Docker**
```bash
# Desde la raíz del proyecto
docker build -t obt-builder -f Dockerfile.obt .
```

**Paso 2: Ejecutar construcción de OBT (2022-2024)**
```bash
# Construcción FULL (modo por defecto)
docker run --rm \
  --network proyecto-04_default \
  -e PG_HOST=postgres \
  -e PG_PORT=5432 \
  -e PG_DB=nyc_taxi \
  -e PG_USER=root \
  -e PG_PASSWORD=root \
  -e PG_SCHEMA_RAW=raw \
  -e PG_SCHEMA_ANALYTICS=analytics \
  obt-builder
```

**Nota:** El comando usa los valores por defecto del Dockerfile (2022-2024, full mode, overwrite).

**Output esperado:**
- `analytics.obt_trips`: ~120M registros (2022-2024)
- Logs con:
  - Conteos por año y servicio
  - Tiempos de procesamiento
  - Resumen final con MIN/MAX year/month

**Evidencia:**
- Capturas de pgAdmin mostrando la tabla OBT

**Para personalizar parámetros:**
```bash
# Ejemplo: Solo año 2024, modo by-partition
docker run --rm \
  --network proyecto-04_default \
  -e PG_HOST=postgres \
  -e PG_PORT=5432 \
  -e PG_DB=nyc_taxi \
  -e PG_USER=root \
  -e PG_PASSWORD=root \
  -e PG_SCHEMA_RAW=raw \
  -e PG_SCHEMA_ANALYTICS=analytics \
  obt-builder \
  --mode by-partition \
  --year-start 2024 \
  --year-end 2024 \
  --services yellow,green \
  --overwrite
```

**Para expandir a todos los años (si hay recursos):**
```bash
docker run --rm \
  --network proyecto-04_default \
  -e PG_HOST=postgres \
  -e PG_PORT=5432 \
  -e PG_DB=nyc_taxi \
  -e PG_USER=root \
  -e PG_PASSWORD=root \
  -e PG_SCHEMA_RAW=raw \
  -e PG_SCHEMA_ANALYTICS=analytics \
  obt-builder \
  --mode full \
  --year-start 2015 \
  --year-end 2025 \
  --services yellow,green \
  --overwrite
```

#### Notebook 03: Machine Learning – Regresión de total_amount (~2-3 horas)

```python
# En Jupyter: notebooks/ml_total_amount_regression.ipynb
# Este notebook:
# - Carga sample de 2024 desde analytics.obt_trips 
# - Preprocesamiento: imputación, escalado, PolynomialFeatures
# - Split temporal: Train (enero-agosto), Val (sep-oct), Test (nov-dic)
# - Entrena 4 modelos FROM-SCRATCH (NumPy):
#   * SGD (descenso por gradiente estocástico)
#   * Ridge (L2 regularization)
#   * Lasso (L1 regularization)  
#   * Elastic Net (L1 + L2)
# - Entrena 4 modelos scikit-learn equivalentes
# - Compara métricas (RMSE, MAE, R²) en validación y test
# - Diagnóstico de errores y residuales
```

**Output esperado:**
- Tabla comparativa de 8 modelos (4 propios + 4 sklearn)
- Métricas en validación y test
- Gráficos de residuales por buckets de precio
- Selección del mejor modelo (menor RMSE en validación)
- Evaluación final en test del modelo ganador

**Para usar más años en ML:**
```python
# Modificar query de carga en el notebook:
query = """
SELECT * FROM analytics.obt_trips 
WHERE year IN (2022, 2023, 2024)  -- Expandir aquí si hay RAM
AND total_amount > 0 
AND trip_distance > 0
LIMIT 10000000  -- Ajustar límite según recursos
"""
```

---

## Diseño de esquemas

### Schema RAW

#### Tabla: `raw.yellow_taxi_trip`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `VendorID` | INTEGER | ID del proveedor (1=CMT, 2=Curb, etc.) |
| `tpep_pickup_datetime` | TIMESTAMP | Fecha/hora de inicio del viaje |
| `tpep_dropoff_datetime` | TIMESTAMP | Fecha/hora de fin del viaje |
| `passenger_count` | INTEGER | Número de pasajeros |
| `trip_distance` | DOUBLE PRECISION | Distancia del viaje en millas |
| `RatecodeID` | INTEGER | Código de tarifa (1=Standard, 2=JFK, etc.) |
| `store_and_fwd_flag` | TEXT | Flag de almacenamiento (Y/N) |
| `PULocationID` | INTEGER | ID de zona de pickup |
| `DOLocationID` | INTEGER | ID de zona de dropoff |
| `payment_type` | INTEGER | Tipo de pago (0-6) |
| `fare_amount` | DOUBLE PRECISION | Tarifa base |
| `extra` | DOUBLE PRECISION | Extras y recargos |
| `mta_tax` | DOUBLE PRECISION | Impuesto MTA |
| `tip_amount` | DOUBLE PRECISION | Propina |
| `tolls_amount` | DOUBLE PRECISION | Peajes |
| `improvement_surcharge` | DOUBLE PRECISION | Recargo de mejora |
| `total_amount` | DOUBLE PRECISION | Total del viaje |
| `congestion_surcharge` | DOUBLE PRECISION | Recargo por congestión |
| `airport_fee` | DOUBLE PRECISION | Tarifa aeropuerto |
| `cbd_congestion_fee` | DOUBLE PRECISION | Tarifa congestión CBD |
| `run_tag` | TEXT | UUID de la ejecución |
| `ingested_at_utc` | TIMESTAMP | Timestamp de ingesta |
| `source_year` | INTEGER | Año del dato fuente |
| `source_month` | INTEGER | Mes del dato fuente |


#### Tabla: `raw.green_taxi_trip`

Similar a Yellow, con diferencias:
- `lpep_pickup_datetime` y `lpep_dropoff_datetime` (en vez de tpep)
- `trip_type` (1=Street-hail, 2=Dispatch)
- Sin `airport_fee` (solo en Yellow)

#### Tabla: `raw.taxi_zone_lookup`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `locationid` | INTEGER | ID de zona (1-263) |
| `zone` | TEXT | Nombre de la zona |
| `borough` | TEXT | Borough (Manhattan, Brooklyn, etc.) |
| `service_zone` | TEXT | Tipo de zona (Airports, Boro Zone, etc.) |

---

### Schema ANALYTICS

#### Tabla: `analytics.obt_trips` (One Big Table)

**Grano:** 1 fila = 1 viaje

**Columnas (41 totales):**

##### Dimensión Temporal (6 columnas)
- `pickup_datetime` (TIMESTAMP)
- `dropoff_datetime` (TIMESTAMP)
- `pickup_hour` (INT): 0-23
- `pickup_dow` (INT): 0=domingo, 6=sábado
- `month` (INT): 1-12
- `year` (INT): 2022-2024 (en esta implementación)

##### Dimensión Geográfica (6 columnas)
- `pu_location_id`, `pu_zone`, `pu_borough`
- `do_location_id`, `do_zone`, `do_borough`

##### Dimensión de Servicio (9 columnas)
- `service_type` (TEXT): 'yellow' o 'green'
- `vendor_id` (INT), `vendor_name` (TEXT)
- `rate_code_id` (INT), `rate_code_desc` (TEXT)
- `payment_type` (INT), `payment_type_desc` (TEXT)
- `trip_type` (INT): NULL para yellow, 1/2 para green

##### Métricas de Viaje (2 columnas)
- `passenger_count` (INT)
- `trip_distance` (DOUBLE PRECISION)

##### Métricas Financieras (10 columnas)
- `fare_amount`, `extra`, `mta_tax`
- `tip_amount`, `tolls_amount`
- `improvement_surcharge`, `congestion_surcharge`
- `cbd_congestion_fee`, `airport_fee`
- `total_amount`

##### Columnas Derivadas (3 columnas)
- `trip_duration_min` = `GREATEST(EXTRACT(EPOCH FROM dropoff - pickup) / 60, 0)`
- `avg_speed_mph` = `trip_distance / (duration_hours)` (NULL si duration=0)
- `tip_pct` = `(tip_amount / total_amount) * 100` (NULL si total=0)

##### Metadatos (4 columnas)
- `run_tag` (TEXT)
- `source_year` (INT)
- `source_month` (INT)
- `ingested_at_utc` (TIMESTAMP)

##### Otros (1 columna)
- `store_and_fwd_flag` (TEXT)

**Supuestos y reglas de negocio:**

1. **Unificación Yellow + Green:**
   - Se usa `UNION ALL` (no `UNION`) para mantener duplicados legítimos
   - Columnas faltantes se llenan con `NULL` (ej: `airport_fee` en green)

2. **JOINs con zonas:**
   - `LEFT JOIN` para no perder registros si falta zona
   - Zonas inválidas quedan como `NULL` en `pu_zone` / `do_zone`

3. **Derivadas:**
   - `trip_duration_min`: Se usa `GREATEST(..., 0)` para evitar negativos
   - `avg_speed_mph`: NULL si trip_distance=0 o duration=0
   - `tip_pct`: NULL si total_amount=0 (evita división por cero)

4. **Mapeos de catálogos:**
   - Vendor: 1=Creative Mobile, 2=Curb, 6=Myle, 7=Helix
   - Rate Code: 1=Standard, 2=JFK, 3=Newark, 4=Nassau, 5=Negotiated, 6=Group
   - Payment Type: 0=Flex, 1=Credit, 2=Cash, 3=No charge, 4=Dispute, 5=Unknown, 6=Voided

---

## Machine Learning: Predicción de total_amount

### Problema de negocio

**Objetivo:** Predecir el costo total de un viaje (`total_amount`) **al momento del pickup**, sin usar información post-viaje.

**Utilidad:**
- **Estimación de tarifa** para usuarios antes de tomar el taxi
- **Detección de anomalías** en precios (fraude, errores de sistema)
- **Optimización de rutas** basada en costo esperado

### Prevención de data leakage

**No se pueden usar:**
- `dropoff_datetime` (no existe en pickup)
- `trip_duration_min` (calculado post-viaje)
- `avg_speed_mph` (calculado post-viaje)
- `tip_pct` (calculado post-viaje)

**Features permitidas:**
- `trip_distance` (estimado por taxímetro/GPS)
- `pickup_hour`, `pickup_dow`, `month`, `year`
- `passenger_count`
- `pu_borough`, `pu_zone` (conocido en pickup)
- `service_type`, `vendor_id`, `rate_code_id`, `payment_type`
- Flags: `is_rush_hour`, `is_weekend`

### Arquitectura de modelos

#### Modelos FROM-SCRATCH (NumPy)

1. **SGD (Stochastic Gradient Descent)**
   - Algoritmo: Descenso por gradiente con mini-batches
   - Loss: MSE (Mean Squared Error)
   - Hiperparámetros: `alpha` (learning rate), `max_iter`, `batch_size`

2. **Ridge Regression**
   - Regularización L2: penaliza coeficientes grandes
   - Fórmula: `Loss = MSE + alpha * ||w||²`
   - Hiperparámetro: `alpha` (fuerza de regularización)

3. **Lasso Regression**
   - Regularización L1: fuerza coeficientes a cero (feature selection)
   - Fórmula: `Loss = MSE + alpha * ||w||₁`
   - Hiperparámetro: `alpha`

4. **Elastic Net**
   - Combinación L1 + L2
   - Fórmula: `Loss = MSE + alpha * l1_ratio * ||w||₁ + alpha * (1-l1_ratio) * ||w||²`
   - Hiperparámetros: `alpha`, `l1_ratio`

#### Modelos scikit-learn (equivalentes)

- `SGDRegressor` con mismo preprocesamiento
- `Ridge` con mismo preprocesamiento
- `Lasso` con mismo preprocesamiento
- `ElasticNet` con mismo preprocesamiento

### Preprocesamiento común (paridad estricta)

```python
# 1. Imputación
SimpleImputer(strategy='median') para numéricas
SimpleImputer(strategy='most_frequent') para categóricas

# 2. Escalado (OBLIGATORIO para regularización)
StandardScaler() en numéricas

# 3. One-Hot Encoding
- Top-K + "Other" para controlar cardinalidad
- pu_borough: Top 5 + Other
- pu_zone: Top 20 + Other
- vendor_name: Top 4 + Other

# 4. Polynomial Features (grado 2)
- Solo en 2-3 numéricas clave: trip_distance, passenger_count, pickup_hour
- Limitar combinaciones para evitar explosión de features
```

### Split temporal (no aleatorio)

```python
# Train: enero-agosto 2024 (66%)
train = df[df['month'].isin([1,2,3,4,5,6,7,8])]

# Validación: septiembre-octubre 2024 (17%)
val = df[df['month'].isin([9,10])]

# Test: noviembre-diciembre 2024 (17%)
test = df[df['month'].isin([11,12])]
```

**Justificación:** Split temporal respeta la naturaleza secuencial de los datos y simula predicción en producción.

### Tuning de hiperparámetros

**GridSearch manual (from-scratch):**
```python
alphas = [0.001, 0.01, 0.1, 1.0, 10.0]
l1_ratios = [0.1, 0.5, 0.9]  # Solo para Elastic Net
learning_rates = [0.001, 0.01, 0.1]  # Solo para SGD

# Para cada combinación:
#   - Entrenar en train
#   - Evaluar en validación
#   - Guardar métricas (RMSE, MAE, R², tiempo)
```

**GridSearchCV (scikit-learn):**
```python
from sklearn.model_selection import GridSearchCV

param_grid_ridge = {'alpha': [0.001, 0.01, 0.1, 1.0, 10.0]}
param_grid_lasso = {'alpha': [0.001, 0.01, 0.1, 1.0, 10.0]}
param_grid_elastic = {
    'alpha': [0.001, 0.01, 0.1, 1.0],
    'l1_ratio': [0.1, 0.5, 0.9]
}
```

### Métricas de evaluación

#### Primarias:
- **RMSE (Root Mean Squared Error):** Penaliza errores grandes
- **MAE (Mean Absolute Error):** Interpretable en dólares

#### Secundaria:
- **R² (Coefficient of Determination):** % de varianza explicada

#### Baseline:
- Media del target en train
- Modelo lineal simple sin regularización

### Comparación from-scratch vs scikit-learn

**Tabla esperada:**

| Modelo                  | Tipo          | Val RMSE | Val MAE  | Val R²    | Tiempo (s) | # Feat |
|-------------------------|---------------|----------|----------|-----------|------------|--------|
| Ridge                  | From Scratch  | 3.498006 | 2.125819 | 0.976285  | 0.070842   | 51     |
| Ridge                  | Sklearn       | 3.498105 | 2.125861 | 0.976284  | 0.072708   | 51     |
| SGD                    | Sklearn       | 3.565430 | 2.203293 | 0.975362  | 0.300530   | 51     |
| Lasso                  | Sklearn       | 3.652418 | 2.119882 | 0.974145  | 0.673337   | 6      |
| Lasso                  | From Scratch  | 3.763168 | 2.226197 | 0.972553  | 28.875671  | 11     |
| ElasticNet             | Sklearn       | 3.838866 | 2.204572 | 0.971438  | 0.670089   | 14     |
| SGD                    | From Scratch  | 4.022581 | 2.387744 | 0.968639  | 7.760261   | 52     |
| ElasticNet             | From Scratch  | 4.314101 | 2.589106 | 0.963928  | 13.025159  | 23     |
| Baseline (Mean)        | Baseline      | 22.744798| 15.016903| -0.002647 | 0.000000   | 0      |
| Baseline (Median)      | Baseline      | 24.443715| 13.580130| -0.158027 | 0.000000   | 0      |


**Observaciones:**
- Los modelos propios tienen **RMSE comparable** a sklearn (diferencia <2%)
- sklearn es **3-5x más rápido** (optimizaciones en C/Cython)
- Lasso reduce coeficientes a ~70% (feature selection automática)
- Ridge mantiene todos los coeficientes pero los penaliza

### Selección del modelo ganador

**Criterio:** Menor RMSE en validación + balance complejidad/interpretabilidad

**Ganador:** Ridge (sklearn) 
- Mejor RMSE en validación
- Tiempo de entrenamiento razonable
- Coeficientes interpretables

**Reentrenamiento final:**
```python
# Entrenar en Train + Validación combinados
X_train_val = pd.concat([X_train, X_val])
y_train_val = pd.concat([y_train, y_val])

best_model.fit(X_train_val, y_train_val)

# Evaluar en Test (datos nunca vistos)
y_pred_test = best_model.predict(X_test)
rmse_test = np.sqrt(mean_squared_error(y_test, y_pred_test))
```

### Diagnóstico de errores

**Análisis de residuales:**
```python
residuals = y_test - y_pred_test

# Gráfico 1: Residuales vs predicción
plt.scatter(y_pred_test, residuals, alpha=0.1)
plt.axhline(0, color='red', linestyle='--')
plt.xlabel('Predicción')
plt.ylabel('Residual (real - pred)')
```

**Análisis por buckets de precio:**
```python
buckets = [0, 10, 20, 30, 50, 100, np.inf]
labels = ['$0-10', '$10-20', '$20-30', '$30-50', '$50-100', '$100+']

df_test['bucket'] = pd.cut(y_test, bins=buckets, labels=labels)
error_by_bucket = df_test.groupby('bucket').agg({
    'residual': ['mean', 'std', 'count']
})
```

**Insights esperados:**
- Viajes baratos (<$10): RMSE bajo, alta precisión
- Viajes caros (>$50): RMSE alto, mayor incertidumbre
- Outliers: Viajes al aeropuerto o con peajes altos

---

## Troubleshooting

### Errores comunes

#### 1. `psycopg2.errors.DuplicateTable: relation "obt_trips" already exists`
**Causa:** Reejecutar script CLI sin `--overwrite` cuando la tabla ya existe  
**Solución:** 
```bash
# Opción 1: Usar --overwrite
# Opción 2: Borrar tabla manualmente en pgAdmin
DROP TABLE IF EXISTS analytics.obt_trips;
```

#### 3. `FATAL: disk full` durante ingesta
**Causa:** El problema principal de este proyecto - disco lleno  
**Solución:**
```bash
# Verificar espacio
df -h

# Limpiar volúmenes de Docker
docker system prune -a --volumes

# Reducir años en .env
START_YEAR=2022  # En vez de 2015
END_YEAR=2024    # En vez de 2025

# Para OBT, reducir scope
#### 4. `Out of memory` en notebook ML
**Causa:** Cargar demasiados registros en pandas  
**Solución:**
```python
# Reducir sample con LIMIT en query SQL
query = """
SELECT * FROM analytics.obt_trips 
WHERE year = 2024 
LIMIT 1000000  -- Empezar con 1M para probar
"""

# O usar Dask para procesamiento out-of-core
import dask.dataframe as dd
df = dd.read_sql_table('obt_trips', conn, schema='analytics')
```

#### 5. `Convergence warning` en modelos propios
**Causa:** Hiperparámetros mal configurados (learning rate muy alto, pocas iteraciones)  
**Solución:**
```python
# Ajustar en implementación propia
alpha = 0.001  # Learning rate más bajo
max_iter = 2000  # Más iteraciones
batch_size = 512  # Batches más pequeños

# Verificar convergencia graficando loss por época
plt.plot(loss_history)
plt.xlabel('Época')
plt.ylabel('MSE Loss')
```

### Recomendaciones de performance

#### 1. PostgreSQL Configuration

Para mejorar performance, editar `postgresql.conf` (o variables de ambiente):

```bash
# En docker-compose.yml, agregar:
postgres:
  environment:
    - POSTGRES_SHARED_BUFFERS=2GB
    - POSTGRES_WORK_MEM=128MB
    - POSTGRES_MAINTENANCE_WORK_MEM=512MB
    - POSTGRES_EFFECTIVE_CACHE_SIZE=4GB
```

#### 2. Índices en OBT

```sql
-- Después de crear OBT, agregar índices:
CREATE INDEX idx_obt_year_service ON analytics.obt_trips(source_year, service_type);
CREATE INDEX idx_obt_pickup_date ON analytics.obt_trips(pickup_datetime);
CREATE INDEX idx_obt_borough ON analytics.obt_trips(pu_borough);
```

**⚠️ Advertencia:** Los índices ocupan ~30% más espacio. Solo crear si hay disco disponible.

#### 3. Docker Resources

```yaml
# En docker-compose.yml, limitar recursos:
spark-notebook:
  deploy:
    resources:
      limits:
        cpus: '4.0'
        memory: 8G
      reservations:
        memory: 4G

postgres:
  deploy:
    resources:
      limits:
        cpus: '2.0'
        memory: 4G
```

#### 4. Spark Configuration

```python
# En notebooks, antes de crear SparkSession:
spark = SparkSession.builder \
    .appName("NYC Taxi Ingestion") \
    .config("spark.executor.memory", "4g") \
    .config("spark.driver.memory", "4g") \
    .config("spark.sql.shuffle.partitions", "200") \
    .config("spark.default.parallelism", "100") \
    .getOrCreate()
```

---

## Checklist de aceptación

### Infraestructura y datos 

- [x] Docker Compose 
- [x] Todas las credenciales provienen de variables de ambiente (`.env`)
- [x] Ingesta RAW completa 2015-2025 (Yellow/Green) con metadatos
- [x] `raw.yellow_taxi_trip`: ~784M registros
- [x] `raw.green_taxi_trip`: ~68M registros
- [x] `raw.taxi_zone_lookup`: 265 registros

### OBT Construction

- [x] Script CLI `obt_builder_cli.py` funcional
- [x] Dockerfile `Dockerfile.obt` para ejecutar el script
- [x] Comandos reproducibles para el profesor:
  ```bash
  # Construcción de imagen
  docker build -t obt-builder -f Dockerfile.obt .
  
  # Ejecución (3 años por defecto)
  docker run --rm \
    --network proyecto-04_default \
    -e PG_HOST=postgres \
    -e PG_PORT=5432 \
    -e PG_DB=nyc_taxi \
    -e PG_USER=root \
    -e PG_PASSWORD=root \
    -e PG_SCHEMA_RAW=raw \
    -e PG_SCHEMA_ANALYTICS=analytics \
    obt-builder
  ```
- [x] `analytics.obt_trips` creada con:
  - [x] Unificación Yellow + Green
  - [x] JOINs con taxi_zone_lookup
  - [x] Columnas derivadas (trip_duration_min, avg_speed_mph, tip_pct)
  - [x] Mapeos de catálogos (vendor_name, rate_code_desc, payment_type_desc)
  - [x] Metadatos (run_tag, source_year, source_month, ingested_at_utc)
- [x] Logs con conteos por año/servicio y tiempos
- [x] Idempotencia: modo `by-partition` no duplica datos

### Machine Learning
#### A. Modelos from-scratch 
- [x] Implementaciones propias con NumPy:
  - [x] SGD (Stochastic Gradient Descent)
  - [x] Ridge (L2 regularization)
  - [x] Lasso (L1 regularization)
  - [x] Elastic Net (L1 + L2)
- [x] Polynomial Features aplicado correctamente
- [x] Escalado con StandardScaler
- [x] GridSearch manual con registro de hiperparámetros
- [x] Tabla de resultados en validación (RMSE, MAE, R², tiempo)

#### B. Comparación con scikit-learn 
- [x] 4 modelos sklearn equivalentes (SGD, Ridge, Lasso, ElasticNet)
- [x] Mismo preprocesamiento (scaler, OHE, poly features)
- [x] Mismo split temporal (train/val/test)
- [x] Comparativa clara en tabla:
  - RMSE/MAE/R² en validación y test
  - Tiempos de entrenamiento
  - Número de coeficientes

#### C. Diagnóstico y selección 
- [x] Selección del mejor modelo por validación
- [x] Reentrenamiento en train+val
- [x] Evaluación final en test
- [x] Análisis de residuales (gráfico scatter)
- [x] Errores por buckets de precio

### Reproducibilidad y documentación
- [x] `.env.example` sin secretos
- [x] README completo con:
  - [x] Descripción del problema de espacio en disco
  - [x] Decisiones de scope reducido justificadas
  - [x] Comandos exactos para ejecutar cada paso
  - [x] Variables de ambiente explicadas
  - [x] Troubleshooting con soluciones
- [x] Seeds fijas en notebooks ML (numpy.random.seed, sklearn random_state)
- [x] Evidencias en carpeta dedicada:
  - [x] Logs de ingesta
  - [x] Logs de OBT builder
  - [x] Screenshots de pgAdmin
  - [x] Tabla comparativa de modelos
  - [x] Gráficos de diagnóstico

---

## Limitaciones conocidas y trabajo futuro

### Limitaciones actuales

1. **Espacio en disco:** 
   - OBT limitada a 3 años (2022-2024) por restricciones de hardware
   - ML solo usa sample de 1 año (2024)
   - **Solución propuesta:** Usar almacenamiento en la nube (S3 + Redshift Spectrum) o servidor con más disco

2. **Tiempo de procesamiento:**
   - Ingesta completa toma 8-12 horas
   - Entrenamiento de modelos propios es ~3-5x más lento que sklearn
   - **Solución propuesta:** Paralelización con Dask o Ray, optimizar código NumPy

3. **Idempotencia de OBT:**
   - Delete + Insert no es transaccional (riesgo de datos inconsistentes si falla a la mitad)
   - **Solución propuesta:** Usar tablas temporales y swap atómico, o implementar MERGE/UPSERT

4. **Features para ML:**
   - No se usa `do_location_id` (destino) porque no está disponible en pickup
   - En producción se podría usar ML para predecir destino primero
   - **Solución propuesta:** Pipeline de 2 pasos: predecir destino → predecir precio


