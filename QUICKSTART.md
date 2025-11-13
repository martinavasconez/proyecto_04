# Guía Rápida - Proyecto 04

### Prerrequisitos
- Docker instalado y corriendo
- 50GB+ espacio en disco libre
- Puerto 5432, 8888 y 8081 disponibles

---

## Paso a paso

### 1️⃣ Levantar infraestructura
```bash
cd proyecto-04
docker-compose up -d
```

**Verificar:**
```bash
docker-compose ps
# Debe mostrar 3 contenedores: postgres, pgadmin, spark-notebook
```

**Servicios disponibles:**
- PostgreSQL: `localhost:5432` (user: root, pass: root)
- PgAdmin: http://localhost:8081 (admin@admin.com / admin)
- Jupyter: http://localhost:8888 (sin token)

---

### 2️⃣ Construir imagen del OBT Builder
```bash
docker build -t obt-builder -f Dockerfile.obt .
```

**Esperado:** 
```
Successfully built [image-id]
Successfully tagged obt-builder:latest
```

---

### 3️⃣ Ejecutar construcción de OBT (2022-2024)
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
  obt-builder
```

**Duración estimada:** 30-45 minutos (depende del hardware)

**Output esperado:**
```
==============================================================
 Iniciando construcción OBT - Modo FULL
==============================================================
Años: [2022, 2023, 2024]
Servicios: ['yellow', 'green']
Run ID: manual
Overwrite: True
==============================================================

Procesando YELLOW taxi...
45,234,567 filas insertadas en 456.78s

Procesando GREEN taxi...
3,876,543 filas insertadas en 67.23s

==============================================================
 CONSTRUCCIÓN COMPLETA
==============================================================
Total de filas insertadas: 49,111,110
Duración total: 524.01s
==============================================================

 Resumen por servicio:
 service_type  filas  min_year  max_year  min_month  max_month
        green   3.8M      2022      2024          1         12
       yellow  45.2M      2022      2024          1         12
```

---

## ✅ Validación

### Opción 1: PgAdmin (UI)
1. Ir a http://localhost:8081
2. Login: admin@admin.com / admin
3. Agregar servidor:
   - Host: 
   - Port: 
   - Database: 
   - User: 
   - Password: 
4. Navegar a: `nyc_taxi > Schemas > analytics > Tables > obt_trips`
5. Click derecho > View/Edit Data > First 100 Rows

### Opción 2: psql (Terminal)
```bash
docker exec -it nyc-taxi-postgres psql -U root -d nyc_taxi

-- Verificar conteos
SELECT 
    service_type, 
    year, 
    COUNT(*) as viajes,
    MIN(pickup_datetime) as primer_viaje,
    MAX(pickup_datetime) as ultimo_viaje
FROM analytics.obt_trips
GROUP BY service_type, year
ORDER BY service_type, year;
```

**Resultado esperado:**
```
 service_type | year |  viajes   |    primer_viaje     |    ultimo_viaje     
--------------+------+-----------+---------------------+---------------------
 green        | 2022 | 1,234,567 | 2022-01-01 00:00:12 | 2022-12-31 23:59:48
 green        | 2023 | 1,345,678 | 2023-01-01 00:00:05 | 2023-12-31 23:59:52
 green        | 2024 | 1,296,298 | 2024-01-01 00:00:18 | 2024-12-31 23:59:41
 yellow       | 2022 | 15,234,567| 2022-01-01 00:00:03 | 2022-12-31 23:59:59
 yellow       | 2023 | 15,345,678| 2023-01-01 00:00:01 | 2023-12-31 23:59:57
 yellow       | 2024 | 14,654,340| 2024-01-01 00:00:09 | 2024-12-31 23:59:55
```

---

## Comandos opcionales

### Expandir OBT a todos los años (si hay recursos)
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

### Construir solo un año específico
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
  --mode by-partition \
  --year-start 2024 \
  --year-end 2024 \
  --services yellow \
  --overwrite
```

### Ver logs en tiempo real
```bash
# El comando docker run muestra logs directamente en terminal
# Para guardarlo:
docker run --rm \
  --network proyecto-04_default \
  -e PG_HOST=postgres \
  -e PG_PORT=5432 \
  -e PG_DB=nyc_taxi \
  -e PG_USER=root \
  -e PG_PASSWORD=root \
  -e PG_SCHEMA_RAW=raw \
  -e PG_SCHEMA_ANALYTICS=analytics \
  obt-builder 2>&1 | tee logs_obt.txt
```

---

## Troubleshooting

### Error: "Connection refused to postgres"
**Causa:** PostgreSQL no está listo aún  
**Solución:**
```bash
# Esperar 10 segundos y reintentar
sleep 10
docker run --rm ...
```

### Error: "Network proyecto-04_default not found"
**Causa:** Docker Compose creó la red con otro nombre  
**Solución:**
```bash
# Ver redes disponibles
docker network ls | grep proyecto

# Usar el nombre correcto
docker run --rm \
  --network [nombre-correcto] \
  ...
```

### Error: "Disk full"
**Causa:** Espacio insuficiente (el problema principal del proyecto)  
**Solución:**
```bash
# Limpiar Docker
docker system prune -a --volumes

# O reducir años
docker run --rm ... obt-builder \
  --year-start 2023 \
  --year-end 2024  # Solo 2 años
```

---

## Notebooks de ML

Después de construir la OBT, abrir Jupyter:

http://localhost:8888

Ejecutar: `notebooks/ml_total_amount_regression.ipynb`

**Nota:** Este notebook usa solo datos de 2024 (sample) por limitaciones de RAM. Para usar todos los años disponibles, modificar el query SQL en la celda de carga de datos.

---

## Detener todo

```bash
# Detener contenedores
docker-compose downs

# Detener Y eliminar volúmenes (borrar datos)
docker-compose down -v
```

---

## Contacto

Si algo no funciona:
1. Verificar que los 3 servicios estén corriendo: `docker-compose ps`
2. Ver logs de postgres: `docker logs nyc-taxi-postgres`
3. Verificar espacio en disco: `df -h`

**Evidencias del proyecto:** Carpeta `evidencias/`
