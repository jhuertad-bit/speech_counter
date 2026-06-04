#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para extraer datos de chats desde la API de OneMarketer
y guardarlos en formato JSON separado por líneas (JSONL) con codificación UTF-8
"""

import requests
import json
import sys
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
import urllib.parse
import re
import os
from google.cloud import storage
from google.cloud import bigquery


def load_config(config_file: str) -> Dict[str, Any]:
    """
    Carga la configuración desde un archivo JSON

    Args:
        config_file (str): Ruta del archivo de configuración

    Returns:
        Dict[str, Any]: Configuración cargada
    """
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Validar estructura básica de configuración
        if 'gcp' not in config:
            print("Error: Sección 'gcp' faltante en el archivo de configuración")
            sys.exit(1)

        # Verificar que al menos una tabla esté configurada
        tables_found = 0
        for key, value in config.items():
            if key != 'gcp' and isinstance(value, dict) and 'enabled' in value:
                tables_found += 1

        if tables_found == 0:
            print("Error: No se encontraron tablas configuradas en el archivo de configuración")
            sys.exit(1)

        print(f"Configuración cargada desde: {config_file}")
        return config

    except FileNotFoundError:
        print(f"Error: No se encontró el archivo de configuración: {config_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error al parsear el archivo de configuración: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error al cargar la configuración: {e}")
        sys.exit(1)


def load_table_definitions(tablas_dir: str) -> Dict[str, Set[str]]:
    """
    Carga las definiciones de campos desde los archivos JSON en el directorio tablas

    Args:
        tablas_dir (str): Directorio que contiene los archivos de definición de tablas

    Returns:
        Dict[str, Set[str]]: Diccionario con el nombre de la tabla como clave y un conjunto de nombres de campos como valor
    """
    table_definitions = {}

    if not os.path.exists(tablas_dir):
        print(f"Advertencia: El directorio {tablas_dir} no existe")
        return table_definitions

    for filename in os.listdir(tablas_dir):
        if filename.endswith('.json'):
            table_name = filename.replace('.json', '')
            file_path = os.path.join(tablas_dir, filename)

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    fields_data = json.load(f)

                # Extraer los nombres de los campos
                field_names = set()
                for field in fields_data:
                    if isinstance(field, dict) and 'name' in field:
                        field_names.add(field['name'])

                table_definitions[table_name] = field_names
                print(f"Cargados {len(field_names)} campos para la tabla '{table_name}'")

            except Exception as e:
                print(f"Error al cargar {file_path}: {e}")

    return table_definitions


def filter_and_normalize_message(message: Dict[str, Any], allowed_fields: Set[str]) -> Dict[str, Any]:
    """
    Filtra el mensaje para incluir solo los campos permitidos y normaliza los campos faltantes

    Args:
        message (Dict[str, Any]): Mensaje original
        allowed_fields (Set[str]): Conjunto de campos permitidos

    Returns:
        Dict[str, Any]: Mensaje filtrado y normalizado
    """
    filtered_message = {}

    # Incluir solo los campos que están en la lista de campos permitidos
    for field_name in allowed_fields:
        if field_name in message and message[field_name] is not None:
            # Si el campo existe y tiene valor, incluirlo
            filtered_message[field_name] = message[field_name]
        else:
            # Si el campo no existe o es None, colocar cadena vacía
            filtered_message[field_name] = ""

    return filtered_message


def convert_time_format(message: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convierte el formato de fecha en el campo 'time' de YY-MM-DD HH:MM:SS a %Y-%m-%d %H:%M:%S

    Args:
        message (Dict[str, Any]): Mensaje con el campo 'time' a convertir
        config (Dict[str, Any]): Configuración del sistema

    Returns:
        Dict[str, Any]: Mensaje con el formato de fecha convertido
    """
    # Verificar si la conversión de fecha está habilitada
    if not config.get('date_conversion', {}).get('enabled', True):
        return message

    if 'time' in message and message['time']:
        time_str = message['time']

        # Patrón para YY-MM-DD HH:MM:SS
        pattern = r'^(\d{2})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$'
        match = re.match(pattern, time_str)

        if match:
            yy, mm, dd, hh, min_sec, ss = match.groups()

            # Convertir año de 2 dígitos a 4 dígitos usando configuración
            year = int(yy)
            threshold = config.get('date_conversion', {}).get('year_threshold', 30)

            if year <= threshold:
                year += 2000
            else:
                year += 1900

            # Crear nueva fecha en formato %Y-%m-%d %H:%M:%S
            new_time = f"{year:04d}-{mm}-{dd} {hh}:{min_sec}:{ss}"
            message['time'] = new_time
        else:
            print(f"Advertencia: No se pudo convertir el formato de fecha: {time_str}")

    return message


def upload_to_gcs(file_path: str, gcp_config: Dict[str, Any], fecha_inicio: str, gcs_path: str) -> str:
    """
    Sube un archivo a Google Cloud Storage preservando la fecha de extracción en la estructura de directorios

    Args:
        file_path (str): Ruta del archivo local a subir
        gcp_config (Dict[str, Any]): Configuración de GCP
        fecha_inicio (str): Fecha de inicio en formato YYYY-MM-DD
        gcs_path (str): Ruta base en el bucket de GCS

    Returns:
        str: Ruta completa del archivo en GCS
    """
    try:
        project_id = gcp_config.get('project_id')
        bucket_name = gcp_config.get('bucket_name')

        # Configurar cliente de Storage
        client = storage.Client(project=project_id)
        bucket = client.bucket(bucket_name)

        # Crear ruta de destino en el bucket preservando la fecha de extracción
        # Estructura: gcs_path/fecha_inicio/archivo
        blob_name = f"{gcs_path}/{fecha_inicio}/{os.path.basename(file_path)}"
        blob = bucket.blob(blob_name)

        # Subir archivo
        print(f"Subiendo archivo a GCS: gs://{bucket_name}/{blob_name}")
        blob.upload_from_filename(file_path)

        print(f"Archivo subido exitosamente a: gs://{bucket_name}/{blob_name}")
        return f"gs://{bucket_name}/{blob_name}"

    except Exception as e:
        print(f"Error al subir archivo a GCS: {e}")
        sys.exit(1)


def get_table_partitions_info(table_ref: str, client: bigquery.Client) -> None:
    """
    Muestra información sobre las particiones existentes en la tabla

    Args:
        table_ref (str): Referencia completa de la tabla
        client: Cliente de BigQuery
    """
    try:
        # Obtener información de la tabla
        table = client.get_table(table_ref)

        if table.time_partitioning:
            print(f"Tabla particionada por tiempo:")
            print(f"  - Campo de partición: {table.time_partitioning.field}")
            print(f"  - Tipo: {table.time_partitioning.type_}")
            if table.time_partitioning.expiration_ms:
                expiration_days = table.time_partitioning.expiration_ms / (1000 * 60 * 60 * 24)
                print(f"  - Expiración: {expiration_days:.0f} días")
        else:
            print("Tabla no particionada")

    except Exception as e:
        print(f"Error al obtener información de particiones: {e}")


def delete_partition_by_date(table_ref: str, partition_date: str, client: bigquery.Client) -> bool:
    """
    Elimina una partición específica de una tabla particionada por fecha

    Args:
        table_ref (str): Referencia completa de la tabla
        partition_date (str): Fecha de la partición en formato YYYYMMDD
        client: Cliente de BigQuery

    Returns:
        bool: True si se eliminó la partición, False si no existía
    """
    try:
        # Construir la consulta para eliminar la partición
        partition_id = f"{table_ref}${partition_date}"

        # Verificar si la partición existe
        try:
            partition = client.get_table(partition_id)
            print(f"Eliminando partición existente: {partition_id}")
            client.delete_table(partition_id)
            print(f"Particion {partition_id} eliminada exitosamente")
            return True
        except Exception:
            print(f"Particion {partition_id} no existe, no hay nada que eliminar")
            return False

    except Exception as e:
        print(f"Error al eliminar partición {partition_date}: {e}")
        return False


def create_bigquery_table(gcs_uri: str, gcp_config: Dict[str, Any], table_id: str, schema: List[Dict[str, Any]], bq_config: Dict[str, Any], fechaini: str = None) -> None:
    """
    Crea una tabla en BigQuery desde un archivo JSONL en GCS

    Args:
        gcs_uri (str): URI del archivo en GCS
        gcp_config (Dict[str, Any]): Configuración de GCP
        table_id (str): ID de la tabla de BigQuery
        schema (List[Dict[str, Any]]): Esquema de la tabla
        bq_config (Dict[str, Any]): Configuración de BigQuery
        fechaini (str): Fecha de inicio para eliminar partición específica
    """
    try:
        project_id = gcp_config.get('project_id')
        dataset_id = gcp_config.get('dataset_id')

        # Configurar credenciales si están especificadas
        credentials_path = gcp_config.get('credentials_path')
        if credentials_path and os.path.exists(credentials_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path

        # Configurar cliente de BigQuery
        client = bigquery.Client(project=project_id)

        # URI de la tabla de destino
        table_ref = f"{project_id}.{dataset_id}.{table_id}"

        # Verificar si la tabla existe
        table_exists = False
        try:
            client.get_table(table_ref)
            table_exists = True
            print(f"Tabla {table_ref} ya existe, saltando creación")
            # Mostrar información de particiones si la tabla existe
            get_table_partitions_info(table_ref, client)
        except Exception:
            print(f"Tabla {table_ref} no existe, será creada")

        # Si la tabla no existe y tenemos esquema, crear la tabla primero
        if not table_exists and schema:
            print(f"Creando tabla {table_ref} con esquema personalizado...")

            # Crear el dataset si no existe
            dataset_ref = f"{project_id}.{dataset_id}"
            try:
                client.get_dataset(dataset_ref)
            except Exception:
                print(f"Creando dataset {dataset_ref}...")
                dataset = bigquery.Dataset(dataset_ref)
                dataset.location = "US"  # Puedes cambiar la ubicación según necesites
                client.create_dataset(dataset, timeout=30)

            # Crear la tabla con el esquema
            table = bigquery.Table(table_ref, schema=[
                bigquery.SchemaField(field['name'], field['type'], mode=field['mode'])
                for field in schema
            ])

            # Configurar particionado si está especificado
            partition_config = bq_config.get('partition')
            if partition_config:
                print(f"Configurando particionado para la tabla {table_ref}...")

                partition_type = partition_config.get('type', 'DAY')
                partition_field = partition_config.get('field')
                partition_expiration_days = partition_config.get('expiration_days')

                if partition_type in ['TIME', 'DAY'] and partition_field:
                    # Particionado por tiempo
                    table.time_partitioning = bigquery.TimePartitioning(
                        type_=bigquery.TimePartitioningType.DAY,
                        field=partition_field
                    )
                    print(f"  - Tipo: Particionado por tiempo (DAY)")
                    print(f"  - Campo: {partition_field}")

                    if partition_expiration_days:
                        table.time_partitioning.expiration_ms = partition_expiration_days * 24 * 60 * 60 * 1000
                        print(f"  - Expiración: {partition_expiration_days} días")

                elif partition_type == 'RANGE' and partition_field:
                    # Particionado por rango
                    range_config = partition_config.get('range', {})
                    table.range_partitioning = bigquery.RangePartitioning(
                        field=partition_field,
                        range_=bigquery.PartitionRange(
                            start=range_config.get('start'),
                            end=range_config.get('end'),
                            interval=range_config.get('interval')
                        )
                    )
                    print(f"  - Tipo: Particionado por rango")
                    print(f"  - Campo: {partition_field}")
                    print(f"  - Rango: {range_config.get('start')} a {range_config.get('end')}")
                    print(f"  - Intervalo: {range_config.get('interval')}")

                elif partition_type == 'INGESTION_TIME':
                    # Particionado por tiempo de ingesta
                    table.time_partitioning = bigquery.TimePartitioning(
                        type_=bigquery.TimePartitioningType.DAY
                    )
                    print(f"  - Tipo: Particionado por tiempo de ingesta (DAY)")

                    if partition_expiration_days:
                        table.time_partitioning.expiration_ms = partition_expiration_days * 24 * 60 * 60 * 1000
                        print(f"  - Expiración: {partition_expiration_days} días")
                else:
                    print(f"Advertencia: Tipo de particionado '{partition_type}' no soportado o campo no especificado")

            table = client.create_table(table)
            print(f"Tabla {table_ref} creada exitosamente con {len(schema)} campos")

        # Configurar job de carga
        # Por defecto usar WRITE_APPEND para preservar datos existentes
        write_disposition = bq_config.get('write_disposition', 'WRITE_APPEND')

        # Si la tabla existe y tenemos fechaini, eliminar la partición específica
        partition_deleted = False
        if table_exists and fechaini:
            # Convertir fechaini de YYYY-MM-DD a YYYYMMDD para la partición
            partition_date = fechaini.replace('-', '')
            print(f"Verificando si existe partición del día {fechaini} ({partition_date})...")
            partition_deleted = delete_partition_by_date(table_ref, partition_date, client)
            if partition_deleted:
                print(f"Particion del día {fechaini} eliminada, se cargarán datos actualizados")
                # La partición ya fue eliminada, usar WRITE_APPEND para cargar datos nuevos
                print(f"Usando WRITE_APPEND para cargar datos en la partición del día {fechaini}")
            else:
                print(f"No existía partición del día {fechaini}, se crearán nuevos datos")
                print(f"Usando {write_disposition} para preservar datos existentes")

        job_config = bigquery.LoadJobConfig(
            source_format=getattr(bigquery.SourceFormat, bq_config.get('source_format', 'NEWLINE_DELIMITED_JSON')),
            autodetect=bq_config.get('autodetect', True) if not schema else False,
            write_disposition=getattr(bigquery.WriteDisposition, write_disposition),
        )

        # Agregar esquema si está disponible y no se creó la tabla previamente
        if schema and not (not table_exists and schema):
            job_config.schema = [bigquery.SchemaField(field['name'], field['type'], mode=field['mode']) for field in schema]



        print(f"Cargando datos en BigQuery: {table_ref}")
        print(f"Desde archivo: {gcs_uri}")
        if schema:
            print(f"Usando esquema personalizado con {len(schema)} campos")
        else:
            print("Usando detección automática de esquema")

        # Ejecutar job de carga
        load_job = client.load_table_from_uri(
            gcs_uri,
            table_ref,
            job_config=job_config
        )

        # Esperar a que termine el job
        load_job.result()

        # Obtener información de la tabla
        table = client.get_table(table_ref)
        print(f"Datos cargados exitosamente:")
        print(f"  - Tabla: {table_ref}")
        print(f"  - Filas: {table.num_rows}")
        print(f"  - Columnas: {len(table.schema)}")

    except Exception as e:
        print(f"Error al crear/cargar tabla en BigQuery: {e}")
        sys.exit(1)


def extract_chats(fecha_inicio: str, key: str, config: Dict[str, Any], table_name: str = None) -> List[Dict[str, Any]]:
    """
    Extrae datos de chats desde la API de OneMarketer

    Args:
        fecha_inicio (str): Fecha de inicio en formato YYYY-MM-DD
        key (str): Clave de autenticación para la API
        config (Dict[str, Any]): Configuración del sistema
        table_name (str): Nombre de la tabla para filtrar campos (opcional)

    Returns:
        List[Dict[str, Any]]: Lista de mensajes extraídos
    """
    # Obtener configuración de API
    api_config = config.get('api', {})
    base_url = api_config.get('base_url', 'https://utp.onemarketer.cl/utp_pregrado_endpoint/reporteChats/services/getChats.php')
    context = api_config.get('context', 1)
    timeout = api_config.get('timeout', 30)

    # Cargar definiciones de tablas para filtrado de campos
    tablas_dir = config.get('tablas_dir', 'tablas')
    table_definitions = load_table_definitions(tablas_dir)

    # Determinar qué campos usar para el filtrado
    allowed_fields = set()
    if table_name and table_name in table_definitions:
        allowed_fields = table_definitions[table_name]
        print(f"Usando campos de la tabla '{table_name}': {len(allowed_fields)} campos")
    elif table_definitions:
        # Si no se especifica tabla, usar todos los campos de todas las tablas
        for fields in table_definitions.values():
            allowed_fields.update(fields)
        print(f"Usando campos de todas las tablas: {len(allowed_fields)} campos")
    else:
        print("Advertencia: No se encontraron definiciones de tablas. Procesando todos los campos.")

    # Parámetros de la consulta
    params = {
        'context': context,
        'fechaini': fecha_inicio,
        'key': key
    }

    try:
        print(f"Realizando consulta a la API...")
        print(f"URL: {base_url}")
        print(f"Parámetros: {params}")

        # Realizar la petición GET
        response = requests.get(base_url, params=params, timeout=timeout)
        response.raise_for_status()

        # Decodificar la respuesta como UTF-8
        response.encoding = 'utf-8'
        data = response.json()

        # Extraer los mensajes del campo 'data'
        if 'data' in data and isinstance(data['data'], list):
            messages = data['data']
            print(f"Se encontraron {len(messages)} mensajes")

            # Convertir formato de fecha en cada mensaje
            print("Convirtiendo formato de fechas...")
            converted_messages = []
            batch_size = config.get('processing', {}).get('batch_size', 10000)
            show_progress = config.get('processing', {}).get('show_progress', True)
            filtered_count = 0

            for i, message in enumerate(messages):
                # Convertir formato de fecha
                converted_message = convert_time_format(message, config)

                # Filtrar y normalizar campos según las definiciones de tabla
                if allowed_fields:
                    filtered_message = filter_and_normalize_message(converted_message, allowed_fields)
                    if filtered_message != converted_message:
                        filtered_count += 1
                    final_message = filtered_message
                else:
                    final_message = converted_message

                converted_messages.append(final_message)

                # Mostrar progreso si está habilitado
                if show_progress and (i + 1) % batch_size == 0:
                    print(f"Procesados {i + 1} mensajes...")

            if allowed_fields and filtered_count > 0:
                print(f"Registros con campos filtrados: {filtered_count}")

            return converted_messages
        else:
            print("No se encontró el campo 'data' o no es una lista")
            return []

    except requests.exceptions.RequestException as e:
        print(f"Error al realizar la petición: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error al decodificar JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error inesperado: {e}")
        sys.exit(1)


def save_to_jsonl(messages: List[Dict[str, Any]], output_file: str) -> None:
    """
    Guarda los mensajes en formato JSONL (JSON Lines) con codificación UTF-8

    Args:
        messages (List[Dict[str, Any]]): Lista de mensajes a guardar
        output_file (str): Ruta del archivo de salida
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for message in messages:
                # Convertir el mensaje a JSON con codificación UTF-8
                json_line = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
                f.write(json_line + '\n')

        print(f"Archivo guardado exitosamente: {output_file}")
        print(f"Total de mensajes guardados: {len(messages)}")

    except Exception as e:
        print(f"Error al guardar el archivo: {e}")
        sys.exit(1)


def load_table_schema(table_name: str) -> List[Dict[str, Any]]:
    """
    Carga el esquema de una tabla desde el archivo JSON correspondiente

    Args:
        table_name (str): Nombre de la tabla

    Returns:
        List[Dict[str, Any]]: Esquema de la tabla
    """
    schema_file = f"tablas/{table_name}.json"
    try:
        with open(schema_file, 'r', encoding='utf-8') as f:
            schema = json.load(f)
        print(f"Esquema cargado desde: {schema_file}")

        # Validar estructura del esquema
        if not isinstance(schema, list):
            print(f"Error: El esquema debe ser una lista de campos")
            return []

        for i, field in enumerate(schema):
            if not isinstance(field, dict):
                print(f"Error: El campo {i} debe ser un diccionario")
                return []

            required_keys = ['name', 'type', 'mode']
            for key in required_keys:
                if key not in field:
                    print(f"Error: El campo {i} debe tener la propiedad '{key}'")
                    return []

        print(f"Esquema validado: {len(schema)} campos definidos")
        return schema

    except FileNotFoundError:
        print(f"Advertencia: No se encontró el archivo de esquema {schema_file}, usando detección automática")
        return []
    except Exception as e:
        print(f"Error al cargar el esquema: {e}")
        return []


def process_table(table_name: str, table_config: Dict[str, Any], gcp_config: Dict[str, Any]) -> None:
    """
    Procesa una tabla específica según su configuración

    Args:
        table_name (str): Nombre de la tabla
        table_config (Dict[str, Any]): Configuración de la tabla
        gcp_config (Dict[str, Any]): Configuración de GCP
    """
    if not table_config.get('enabled', False):
        print(f"Tabla {table_name} está deshabilitada, saltando...")
        return

    print(f"\n=== Procesando tabla: {table_name} ===")

    # Obtener configuración de la tabla
    api_config = table_config.get('api', {})
    processing_config = table_config.get('processing', {})
    storage_config = table_config.get('storage', {})
    bigquery_config = table_config.get('bigquery', {})
    date_config = table_config.get('date_conversion', {})

    # Validar parámetros requeridos
    fechaini = api_config.get('fechaini')
    key = api_config.get('key')

    if not fechaini:
        print(f"Error: fechaini debe estar definido para la tabla {table_name}")
        return

    if not key:
        print(f"Error: key debe estar definido para la tabla {table_name}")
        return

    # Validar formato de fecha
    try:
        datetime.strptime(fechaini, '%Y-%m-%d')
    except ValueError:
        print(f"Error: El formato de fecha debe ser YYYY-MM-DD para la tabla {table_name}")
        return

    # Crear configuración temporal para compatibilidad
    temp_config = {
        'api': api_config,
        'processing': processing_config,
        'date_conversion': date_config
    }

    # Obtener configuración de procesamiento
    output_file = processing_config.get('output_file', f"{table_name}_{fechaini}.jsonl")
    upload_gcs = storage_config.get('upload_gcs', False)
    create_bigquery = bigquery_config.get('create_bigquery', False)

    print(f"Fecha de inicio: {fechaini}")
    print(f"Archivo de salida: {output_file}")
    print(f"Subir a GCS: {'Sí' if upload_gcs else 'No'}")
    print(f"Crear en BigQuery: {'Sí' if create_bigquery else 'No'}")
    print("-" * 40)

    # Extraer datos de la API
    messages = extract_chats(fechaini, key, temp_config, table_name)

    if not messages:
        print(f"No se encontraron mensajes para la tabla {table_name}")
        return

    # Guardar en formato JSONL
    save_to_jsonl(messages, output_file)

    # Subir a Google Cloud Storage si se solicita
    gcs_uri = None
    if upload_gcs:
        print(f"\n=== Subiendo {table_name} a Google Cloud Storage ===")
        gcs_path = storage_config.get('gcs_path', f"utp_pregrado/reporteAtenciones/landing")
        gcs_uri = upload_to_gcs(output_file, gcp_config, fechaini, gcs_path)

    # Crear tabla en BigQuery si se solicita
    if create_bigquery:
        print(f"\n=== Procesando tabla {table_name} en BigQuery ===")
        table_id = bigquery_config.get('table_id', table_name)

        # Cargar esquema si está disponible
        schema = load_table_schema(table_name)

        if schema:
            print(f"Esquema personalizado encontrado para {table_name}:")
            for field in schema:
                print(f"  - {field['name']}: {field['type']} ({field['mode']})")
        else:
            print(f"Usando detección automática de esquema para {table_name}")

        # Usar ruta específica de BigQuery (raw) si está configurada
        bigquery_gcs_path = bigquery_config.get('gcs_path', storage_config.get('gcs_path', f"utp_pregrado/reporteAtenciones/landing"))

        if gcs_uri and bigquery_gcs_path == storage_config.get('gcs_path'):
            # Si ya se subió a la ruta correcta, usar ese URI
            create_bigquery_table(gcs_uri, gcp_config, table_id, schema, bigquery_config, fechaini)
        else:
            # Subir archivo a la ruta específica de BigQuery (raw)
            print(f"Subiendo archivo a GCS para BigQuery en directorio raw...")
            print(f"Ruta de destino: {bigquery_gcs_path}")
            temp_gcs_uri = upload_to_gcs(output_file, gcp_config, fechaini, bigquery_gcs_path)
            create_bigquery_table(temp_gcs_uri, gcp_config, table_id, schema, bigquery_config, fechaini)

    print(f"¡Tabla {table_name} procesada exitosamente!")


def main():
    """Función principal del script"""
    # Configurar argumentos de línea de comandos
    parser = argparse.ArgumentParser(description='Extractor de datos de OneMarketer')
    parser.add_argument('--fecha', required=True, help='Fecha en formato YYYY-MM-DD')
    parser.add_argument('--config', default='config/config.json', help='Archivo de configuración')

    args = parser.parse_args()

    # Validar formato de fecha
    try:
        datetime.strptime(args.fecha, '%Y-%m-%d')
    except ValueError:
        print(f"Error: El formato de fecha debe ser YYYY-MM-DD. Recibido: {args.fecha}")
        sys.exit(1)

    # Cargar configuración
    config = load_config(args.config)

    # Obtener configuración de GCP
    gcp_config = config.get('gcp', {})

    print("=== Extractor de Datos OneMarketer ===")
    print(f"Archivo de configuración: {args.config}")
    print(f"Fecha de procesamiento: {args.fecha}")
    print(f"Proyecto GCP: {gcp_config.get('project_id')}")
    print(f"Bucket GCS: {gcp_config.get('bucket_name')}")
    print(f"Dataset BigQuery: {gcp_config.get('dataset_id')}")
    print("=" * 50)

    # Procesar cada tabla configurada
    tables_processed = 0
    for table_name, table_config in config.items():
        if table_name == 'gcp':
            continue  # Saltar configuración de GCP

        if isinstance(table_config, dict) and 'enabled' in table_config:
            # Actualizar la fecha en la configuración de la tabla
            if 'api' in table_config:
                table_config['api']['fechaini'] = args.fecha
            process_table(table_name, table_config, gcp_config)
            tables_processed += 1

    if tables_processed == 0:
        print("No se encontraron tablas habilitadas para procesar")
        sys.exit(1)

    print(f"\n¡Proceso completado exitosamente! {tables_processed} tabla(s) procesada(s).")


if __name__ == "__main__":
    main()
