import psycopg2
import pandas as pd
import argparse
import os
from datetime import datetime

# --- CONFIGURACIÓN DESDE VARIABLES DE AMBIENTE ---
PG_HOST = os.environ.get("PG_HOST")
PG_PORT = int(os.environ.get("PG_PORT"))
PG_DB = os.environ.get("PG_DB")
PG_USER = os.environ.get("PG_USER")
PG_PASSWORD = os.environ.get("PG_PASSWORD")
PG_SCHEMA_RAW = os.environ.get("PG_SCHEMA_RAW")
PG_SCHEMA_ANALYTICS = os.environ.get("PG_SCHEMA_ANALYTICS")

# --- MAPEOS ---
VENDOR_NAME_CASE = """
CASE "VendorID"
  WHEN 1 THEN 'Creative Mobile Technologies'
  WHEN 2 THEN 'Curb Mobility'
  WHEN 6 THEN 'Myle Technologies'
  WHEN 7 THEN 'Helix'
  ELSE 'Other'
END
"""

RATE_CODE_DESC_CASE = """
CASE "RatecodeID"
  WHEN 1 THEN 'Standard rate'
  WHEN 2 THEN 'JFK'
  WHEN 3 THEN 'Newark'
  WHEN 4 THEN 'Nassau/Westchester'
  WHEN 5 THEN 'Negotiated fare'
  WHEN 6 THEN 'Group ride'
  ELSE 'Other'
END
"""

PAYMENT_TYPE_DESC_CASE = """
CASE payment_type
  WHEN 0 THEN 'Flex Fare trip'
  WHEN 1 THEN 'Credit card'
  WHEN 2 THEN 'Cash'
  WHEN 3 THEN 'No charge'
  WHEN 4 THEN 'Dispute'
  WHEN 5 THEN 'Unknown'
  WHEN 6 THEN 'Voided trip'
  ELSE 'Other'
END
"""

def create_obt_table(cur):
    """Crea la tabla OBT si no existe"""
    cur.execute(f"""
    CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA_ANALYTICS};

    CREATE TABLE IF NOT EXISTS {PG_SCHEMA_ANALYTICS}.obt_trips (
        pickup_datetime TIMESTAMP,
        dropoff_datetime TIMESTAMP,
        pickup_hour INT,
        pickup_dow INT,
        month INT,
        year INT,
        pu_location_id INT,
        pu_zone TEXT,
        pu_borough TEXT,
        do_location_id INT,
        do_zone TEXT,
        do_borough TEXT,
        service_type TEXT,
        vendor_id INT,
        vendor_name TEXT,
        rate_code_id INT,
        rate_code_desc TEXT,
        payment_type INT,
        payment_type_desc TEXT,
        trip_type INT,
        passenger_count INT,
        trip_distance DOUBLE PRECISION,
        fare_amount DOUBLE PRECISION,
        extra DOUBLE PRECISION,
        mta_tax DOUBLE PRECISION,
        tip_amount DOUBLE PRECISION,
        tolls_amount DOUBLE PRECISION,
        improvement_surcharge DOUBLE PRECISION,
        congestion_surcharge DOUBLE PRECISION,
        cbd_congestion_fee DOUBLE PRECISION,
        airport_fee DOUBLE PRECISION,
        total_amount DOUBLE PRECISION,
        store_and_fwd_flag TEXT,
        trip_duration_min DOUBLE PRECISION,
        avg_speed_mph DOUBLE PRECISION,
        tip_pct DOUBLE PRECISION,
        run_id TEXT,
        source_year INT,
        source_month INT,
        ingested_at_utc TIMESTAMP
    );
    """)

def get_yellow_query(years):
    """Genera query para yellow taxi"""
    return f"""
    SELECT
      y.tpep_pickup_datetime AS pickup_datetime,
      y.tpep_dropoff_datetime AS dropoff_datetime,
      EXTRACT(HOUR FROM y.tpep_pickup_datetime)::INT AS pickup_hour,
      EXTRACT(DOW  FROM y.tpep_pickup_datetime)::INT AS pickup_dow,
      y.source_month AS month,
      y.source_year AS year,
      y."PULocationID" AS pu_location_id,
      zpu.zone AS pu_zone,
      zpu.borough AS pu_borough,
      y."DOLocationID" AS do_location_id,
      zdo.zone AS do_zone,
      zdo.borough AS do_borough,
      'yellow' AS service_type,
      y."VendorID" AS vendor_id,
      {VENDOR_NAME_CASE} AS vendor_name,
      y."RatecodeID" AS rate_code_id,
      {RATE_CODE_DESC_CASE} AS rate_code_desc,
      y.payment_type,
      {PAYMENT_TYPE_DESC_CASE} AS payment_type_desc,
      NULL::INT AS trip_type,
      y.passenger_count,
      y.trip_distance,
      y.fare_amount,
      y.extra,
      y.mta_tax,
      y.tip_amount,
      y.tolls_amount,
      y.improvement_surcharge,
      y.congestion_surcharge,
      y.cbd_congestion_fee,
      y.airport_fee,
      y.total_amount,
      y.store_and_fwd_flag,
      GREATEST(EXTRACT(EPOCH FROM (y.tpep_dropoff_datetime - y.tpep_pickup_datetime))/60.0, 0) AS trip_duration_min,
      CASE
        WHEN (EXTRACT(EPOCH FROM (y.tpep_dropoff_datetime - y.tpep_pickup_datetime))/3600.0) > 0
          THEN y.trip_distance / (EXTRACT(EPOCH FROM (y.tpep_dropoff_datetime - y.tpep_pickup_datetime))/3600.0)
        ELSE NULL
      END AS avg_speed_mph,
      CASE WHEN NULLIF(y.total_amount,0) IS NOT NULL THEN y.tip_amount / NULLIF(y.total_amount,0)
           ELSE NULL END AS tip_pct,
      y.run_tag AS run_id, y.source_year, y.source_month, y.ingested_at_utc
    FROM {PG_SCHEMA_RAW}.yellow_taxi_trip y
    LEFT JOIN {PG_SCHEMA_RAW}.taxi_zone_lookup zpu ON zpu.locationid = y."PULocationID"
    LEFT JOIN {PG_SCHEMA_RAW}.taxi_zone_lookup zdo ON zdo.locationid = y."DOLocationID"
    WHERE y.source_year IN %s
    """

def get_green_query(years):
    """Genera query para green taxi"""
    return f"""
    SELECT
      g.lpep_pickup_datetime AS pickup_datetime,
      g.lpep_dropoff_datetime AS dropoff_datetime,
      EXTRACT(HOUR FROM g.lpep_pickup_datetime)::INT AS pickup_hour,
      EXTRACT(DOW  FROM g.lpep_pickup_datetime)::INT AS pickup_dow,
      g.source_month AS month,
      g.source_year AS year,
      g."PULocationID" AS pu_location_id,
      zpu.zone AS pu_zone,
      zpu.borough AS pu_borough,
      g."DOLocationID" AS do_location_id,
      zdo.zone AS do_zone,
      zdo.borough AS do_borough,
      'green' AS service_type,
      g."VendorID" AS vendor_id,
      {VENDOR_NAME_CASE} AS vendor_name,
      g."RatecodeID" AS rate_code_id,
      {RATE_CODE_DESC_CASE} AS rate_code_desc,
      g.payment_type,
      {PAYMENT_TYPE_DESC_CASE} AS payment_type_desc,
      g.trip_type,
      g.passenger_count,
      g.trip_distance,
      g.fare_amount,
      g.extra,
      g.mta_tax,
      g.tip_amount,
      g.tolls_amount,
      g.improvement_surcharge,
      g.congestion_surcharge,
      g.cbd_congestion_fee,
      NULL::DOUBLE PRECISION AS airport_fee,
      g.total_amount,
      g.store_and_fwd_flag,
      GREATEST(EXTRACT(EPOCH FROM (g.lpep_dropoff_datetime - g.lpep_pickup_datetime))/60.0, 0) AS trip_duration_min,
      CASE
        WHEN (EXTRACT(EPOCH FROM (g.lpep_dropoff_datetime - g.lpep_pickup_datetime))/3600.0) > 0
          THEN g.trip_distance / (EXTRACT(EPOCH FROM (g.lpep_dropoff_datetime - g.lpep_pickup_datetime))/3600.0)
        ELSE NULL
      END AS avg_speed_mph,
      CASE WHEN NULLIF(g.total_amount,0) IS NOT NULL THEN g.tip_amount / NULLIF(g.total_amount,0)
           ELSE NULL END AS tip_pct,
      g.run_tag AS run_id, g.source_year, g.source_month, g.ingested_at_utc
    FROM {PG_SCHEMA_RAW}.green_taxi_trip g
    LEFT JOIN {PG_SCHEMA_RAW}.taxi_zone_lookup zpu ON zpu.locationid = g."PULocationID"
    LEFT JOIN {PG_SCHEMA_RAW}.taxi_zone_lookup zdo ON zdo.locationid = g."DOLocationID"
    WHERE g.source_year IN %s
    """

def build_obt_full(conn, cur, years, services, run_id, overwrite):
    """Modo FULL: reconstruye toda la OBT"""
    start_time = datetime.now()
    print(f"\n{'='*60}")
    print(f"Iniciando construcción OBT - Modo FULL")
    print(f"{'='*60}")
    print(f"Años: {years}")
    print(f"Servicios: {services}")
    print(f"Run ID: {run_id}")
    print(f"Overwrite: {overwrite}")
    print(f"{'='*60}\n")
    
    # Crear tabla si no existe
    create_obt_table(cur)
    conn.commit()
    
    if overwrite:
        print(" Limpiando tabla destino (TRUNCATE)...")
        cur.execute(f"TRUNCATE {PG_SCHEMA_ANALYTICS}.obt_trips;")
        conn.commit()
    
    years_tuple = tuple(years)
    total_rows = 0
    
    # Procesar cada servicio
    for service in services:
        print(f"\nProcesando {service.upper()} taxi...")
        service_start = datetime.now()
        
        if service == 'yellow':
            query = get_yellow_query(years_tuple)
        elif service == 'green':
            query = get_green_query(years_tuple)
        else:
            print(f"Servicio '{service}' no reconocido, saltando...")
            continue
        
        cur.execute(f"INSERT INTO {PG_SCHEMA_ANALYTICS}.obt_trips {query}", (years_tuple,))
        rows_inserted = cur.rowcount
        total_rows += rows_inserted
        
        service_duration = (datetime.now() - service_start).total_seconds()
        print(f"{rows_inserted:,} filas insertadas en {service_duration:.2f}s")
    
    conn.commit()
    
    # Resumen final
    duration = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*60}")
    print(f" CONSTRUCCIÓN COMPLETA")
    print(f"{'='*60}")
    print(f"Total de filas insertadas: {total_rows:,}")
    print(f"Duración total: {duration:.2f}s")
    print(f"{'='*60}\n")
    
    # Validación
    print(" Resumen por servicio:")
    df_summary = pd.read_sql(f"""
    SELECT service_type, COUNT(*) AS filas, 
           MIN(year) AS min_year, MAX(year) AS max_year,
           MIN(month) AS min_month, MAX(month) AS max_month
    FROM {PG_SCHEMA_ANALYTICS}.obt_trips
    GROUP BY service_type
    ORDER BY service_type;
    """, conn)
    print(df_summary.to_string(index=False))
    
    print(f"\n📈 Resumen por año:")
    df_year = pd.read_sql(f"""
    SELECT year, service_type, COUNT(*) AS filas
    FROM {PG_SCHEMA_ANALYTICS}.obt_trips
    GROUP BY year, service_type
    ORDER BY year, service_type;
    """, conn)
    print(df_year.to_string(index=False))

def build_obt_by_partition(conn, cur, years, services, run_id, overwrite):
    """Modo BY-PARTITION: procesa solo particiones faltantes"""
    start_time = datetime.now()
    print(f"\n{'='*60}")
    print(f" Iniciando construcción OBT - Modo BY-PARTITION")
    print(f"{'='*60}")
    print(f"Años: {years}")
    print(f"Servicios: {services}")
    print(f"Run ID: {run_id}")
    print(f"{'='*60}\n")
    
    # Crear tabla si no existe
    create_obt_table(cur)
    conn.commit()
    
    total_rows = 0
    
    for year in years:
        for service in services:
            partition_start = datetime.now()
            print(f"\n Procesando {service.upper()} - Año {year}...")
            
            # Verificar si ya existe
            cur.execute(f"""
            SELECT COUNT(*) FROM {PG_SCHEMA_ANALYTICS}.obt_trips 
            WHERE source_year = %s AND service_type = %s
            """, (year, service))
            existing_rows = cur.fetchone()[0]
            
            if existing_rows > 0 and not overwrite:
                print(f"   Partición ya existe ({existing_rows:,} filas), saltando...")
                continue
            
            if existing_rows > 0 and overwrite:
                print(f"    Eliminando partición existente ({existing_rows:,} filas)...")
                cur.execute(f"""
                DELETE FROM {PG_SCHEMA_ANALYTICS}.obt_trips 
                WHERE source_year = %s AND service_type = %s
                """, (year, service))
            
            # Insertar datos
            if service == 'yellow':
                query = get_yellow_query((year,))
            elif service == 'green':
                query = get_green_query((year,))
            else:
                continue
            
            cur.execute(f"INSERT INTO {PG_SCHEMA_ANALYTICS}.obt_trips {query}", ((year,),))
            rows_inserted = cur.rowcount
            total_rows += rows_inserted
            
            partition_duration = (datetime.now() - partition_start).total_seconds()
            print(f"{rows_inserted:,} filas insertadas en {partition_duration:.2f}s")
            
            conn.commit()
    
    # Resumen final
    duration = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*60}")
    print(f"CONSTRUCCIÓN COMPLETA")
    print(f"{'='*60}")
    print(f"Total de filas procesadas: {total_rows:,}")
    print(f"Duración total: {duration:.2f}s")
    print(f"{'='*60}\n")

def main():
    parser = argparse.ArgumentParser(
        description='Construye la tabla OBT (analytics.obt_trips) desde raw.*',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--mode',
        choices=['full', 'by-partition'],
        default='full',
        help='Modo de construcción: full (reconstruir todo) o by-partition (incremental)'
    )
    
    parser.add_argument(
        '--year-start',
        type=int,
        default=2022,
        help='Año inicial (inclusive)'
    )
    
    parser.add_argument(
        '--year-end',
        type=int,
        default=2024,
        help='Año final (inclusive)'
    )
    
    parser.add_argument(
        '--services',
        default='yellow,green',
        help='Servicios a procesar, separados por coma (ej: yellow,green)'
    )
    
    parser.add_argument(
        '--run-id',
        default='manual',
        help='Identificador de ejecución'
    )
    
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Si está presente, sobrescribe particiones existentes'
    )
    
    args = parser.parse_args()
    
    # Preparar parámetros
    years = list(range(args.year_start, args.year_end + 1))
    services = [s.strip() for s in args.services.split(',')]
    
    # Conectar a la base de datos
    print(f"\nConectando a PostgreSQL...")
    print(f"   Host: {PG_HOST}:{PG_PORT}")
    print(f"   Database: {PG_DB}")
    print(f"   User: {PG_USER}")
    
    try:
        conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            dbname=PG_DB,
            user=PG_USER,
            password=PG_PASSWORD
        )
        cur = conn.cursor()
        print(f"Conexión establecida\n")
        
        # Ejecutar construcción según modo
        if args.mode == 'full':
            build_obt_full(conn, cur, years, services, args.run_id, args.overwrite)
        else:
            build_obt_by_partition(conn, cur, years, services, args.run_id, args.overwrite)
        
        cur.close()
        conn.close()
        print("\nProceso finalizado exitosamente!")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        raise

if __name__ == '__main__':
    main()
