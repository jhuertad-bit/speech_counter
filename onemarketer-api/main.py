#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloud Function para procesar datos de OneMarketer con autenticación X-Signature
Recibe día actual y cantidad de días hacia atrás para reprocesar
"""

import json
import requests
import hashlib
import pytz
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set
import os
import sys
from google.cloud import storage
from google.cloud import bigquery
import re


def calculate_sha256(text: str) -> str:
    """Calcula el hash SHA256 de un texto"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def calculate_login(user: str, password: str) -> str:
    """Calcula el hash de login"""
    login_string = f"{user}:{password}"
    return calculate_sha256(login_string)


def calculate_sig(user: str) -> str:
    """Calcula la firma con timestamp actual"""
    gmt_minus_3 = pytz.timezone('America/Sao_Paulo')
    timestamp = datetime.now(gmt_minus_3)
    formatted_time = timestamp.strftime('%Y-%m-%d %H:%M')
    sig_string = f"day={formatted_time}&user={user}"
    return calculate_sha256(sig_string)


def calculate_x_signature(login: str, sig: str) -> str:
    """Calcula el X-Signature final"""
    signature_string = f"login={login}&sig={sig}"
    return calculate_sha256(signature_string)


def get_access_key() -> str:
    """Obtiene el access_key para autenticación mediante OAuth"""
    USER = 'utppregradoapi'
    PASS = 'utppregradoOM.2O2S'

    # Generar X-Signature para OAuth
    login = calculate_login(USER, PASS)
    sig = calculate_sig(USER)
    x_signature = calculate_x_signature(login, sig)

    # Endpoint OAuth
    oauth_endpoint = 'https://utp.onemarketer.cl/utp_pregrado/oauth'

    # Headers y datos para OAuth
    headers = {
        'X-Signature': x_signature,
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'login': login,
        'sig': sig
    }

    try:
        print(f"Obteniendo access_key desde OAuth...")
        response = requests.post(oauth_endpoint, headers=headers, data=data, timeout=30)
        response.raise_for_status()

        oauth_data = response.json()
        access_key = oauth_data.get('access_key')

        if not access_key:
            raise ValueError("No se pudo obtener access_key del endpoint OAuth")

        print(f"Access key obtenido exitosamente")
        return access_key

    except Exception as e:
        print(f"Error obteniendo access_key: {e}")
        raise


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


def convert_time_format(message: Dict[str, Any], config: Dict[str, Any], table_type: str = None) -> Dict[str, Any]:
    """
    Convierte el formato de fecha de DD-MM-YYYY HH:MM:SS a YYYY-MM-DD HH:MM:SS
    Solo para campos definidos como TIMESTAMP en los esquemas de BigQuery

    Args:
        message (Dict[str, Any]): Mensaje con campos de fecha a convertir
        config (Dict[str, Any]): Configuración del sistema
        table_type (str): Tipo de tabla para determinar qué campos convertir

    Returns:
        Dict[str, Any]: Mensaje con el formato de fecha convertido
    """
    # Verificar si la conversión de fecha está habilitada
    if not config.get('date_conversion', {}).get('enabled', True):
        return message

    # Campos TIMESTAMP según el esquema de BigQuery
    timestamp_fields = {
        'reporteAtenciones': ['start_time', 'end_time'],
        'reporteAccesoOperadores': ['begin_time', 'end_time']
    }

    # Obtener campos a convertir según el tipo de tabla
    if table_type and table_type in timestamp_fields:
        date_fields = timestamp_fields[table_type]
    else:
        # Si no se especifica el tipo de tabla, usar todos los campos TIMESTAMP
        date_fields = ['start_time', 'end_time', 'begin_time']

    for field in date_fields:
        if field in message:
            time_str = message[field]

            # Verificar si es un valor especial que necesita conversión especial
            if time_str == "Not closed yet":
                # Convertir "Not closed yet" a null para campos TIMESTAMP
                message[field] = None
                continue
            elif time_str in ["NA", "N/A", "null", "NULL", "None", ""]:
                # Convertir valores especiales a null para campos TIMESTAMP
                message[field] = None
                continue

            # Patrón para DD-MM-YYYY HH:MM:SS
            pattern = r'^(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})$'
            match = re.match(pattern, time_str)

            if match:
                dd, mm, yyyy, hh, min_sec, ss = match.groups()

                # Crear nueva fecha en formato YYYY-MM-DD HH:MM:SS
                new_time = f"{yyyy}-{mm}-{dd} {hh}:{min_sec}:{ss}"
                message[field] = new_time
            else:
                # Intentar con formato DD-MM-YYYY (solo fecha)
                date_pattern = r'^(\d{2})-(\d{2})-(\d{4})$'
                date_match = re.match(date_pattern, time_str)
                if date_match:
                    dd, mm, yyyy = date_match.groups()
                    new_date = f"{yyyy}-{mm}-{dd}"
                    message[field] = new_date
                else:
                    # Solo mostrar advertencia si no es un valor especial conocido
                    special_values = ["Not closed yet", "NA", "N/A", "null", "NULL", "None"]
                    if time_str not in special_values:
                        print(f"Advertencia: No se pudo convertir el formato de fecha en {field}: {time_str}")

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
        write_disposition = bq_config.get('write_disposition', 'WRITE_TRUNCATE')

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
            autodetect=False,  # Se configurará después según si la tabla existe
            write_disposition=getattr(bigquery.WriteDisposition, write_disposition),
        )

        # Usar el esquema definido en la carpeta tablas si está disponible
        if schema:
            job_config.schema = [bigquery.SchemaField(field['name'], field['type'], mode=field['mode']) for field in schema]
            print(f"Usando esquema definido en tablas/{table_id}.json")
        else:
            # Fallback a detección automática si no hay esquema
            job_config.autodetect = True
            print("Usando detección automática de esquema (no se encontró esquema personalizado)")

        print(f"Cargando datos en BigQuery: {table_ref}")
        print(f"Desde archivo: {gcs_uri}")

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


def extract_data_with_access_key(fecha_inicio: str, table_type: str, config: Dict[str, Any], table_name: str = None) -> List[Dict[str, Any]]:
    """
    Extrae datos desde la API de OneMarketer usando access_key

    Args:
        fecha_inicio (str): Fecha de inicio en formato YYYY-MM-DD
        table_type (str): Tipo de tabla ('cases' o 'operator')
        config (Dict[str, Any]): Configuración del sistema
        table_name (str): Nombre de la tabla para filtrar campos (opcional)

    Returns:
        List[Dict[str, Any]]: Lista de datos extraídos
    """
    # Obtener configuración de API
    api_config = config.get('api', {})
    base_url = api_config.get('base_url', 'https://utp.onemarketer.cl/utp_pregrado/reportapi')
    context = api_config.get('context', 1)
    timeout = api_config.get('timeout', 30)

    # Construir URL con parámetros
    url = f"{base_url}?type={table_type}&day={fecha_inicio}&id_context={context}&gmt=GMT-03"

    # Obtener access_key fresco para cada llamada
    access_key = get_access_key()

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

    # Headers con access_key
    headers = {
        'X-Signature': access_key
    }

    try:
        print(f"Realizando consulta a la API...")
        print(f"URL: {url}")
        print(f"Tipo de tabla: {table_type}")
        print(f"Fecha: {fecha_inicio}")

        # Realizar la petición POST
        response = requests.post(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        # Decodificar la respuesta como UTF-8
        response.encoding = 'utf-8'
        data = response.json()

        # Extraer los datos del campo 'data' o directamente de la respuesta
        if 'data' in data and isinstance(data['data'], list):
            messages = data['data']
        elif isinstance(data, list):
            messages = data
        else:
            print("No se encontró el campo 'data' o no es una lista")
            return []

        print(f"Se encontraron {len(messages)} registros")

        # Convertir formato de fecha en cada mensaje
        print("Convirtiendo formato de fechas...")
        converted_messages = []
        batch_size = config.get('processing', {}).get('batch_size', 10000)
        show_progress = config.get('processing', {}).get('show_progress', True)
        filtered_count = 0

        for i, message in enumerate(messages):
            # Convertir formato de fecha
            converted_message = convert_time_format(message, config, table_type)

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
                print(f"Procesados {i + 1} registros...")

        if allowed_fields and filtered_count > 0:
            print(f"Registros con campos filtrados: {filtered_count}")

        return converted_messages

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
        print(f"Total de registros guardados: {len(messages)}")

    except Exception as e:
        print(f"Error al guardar el archivo: {e}")
        sys.exit(1)


def process_table(table_name: str, table_config: Dict[str, Any], gcp_config: Dict[str, Any], fecha_inicio: str) -> None:
    """
    Procesa una tabla específica según su configuración

    Args:
        table_name (str): Nombre de la tabla
        table_config (Dict[str, Any]): Configuración de la tabla
        gcp_config (Dict[str, Any]): Configuración de GCP
        fecha_inicio (str): Fecha de inicio en formato YYYY-MM-DD
    """
    if not table_config.get('enabled', False):
        print(f"Tabla {table_name} está deshabilitada, saltando...")
        return

    print(f"\n=== Procesando tabla: {table_name} ===")

    # Obtener configuración de la tabla
    processing_config = table_config.get('processing', {})
    storage_config = table_config.get('storage', {})
    bigquery_config = table_config.get('bigquery', {})
    date_config = table_config.get('date_conversion', {})

    # Determinar el tipo de tabla basado en el nombre
    if 'Atenciones' in table_name:
        table_type = 'cases'
    elif 'AccesoOperadores' in table_name:
        table_type = 'operator'
    else:
        print(f"Error: No se pudo determinar el tipo de tabla para {table_name}")
        return

    # Crear configuración temporal para compatibilidad
    temp_config = {
        'api': table_config.get('api', {}),
        'processing': processing_config,
        'date_conversion': date_config
    }

    # Obtener configuración de procesamiento
    output_file = processing_config.get('output_file', f"{table_name}_{fecha_inicio}.jsonl")
    upload_gcs = storage_config.get('upload_gcs', False)
    create_bigquery = bigquery_config.get('create_bigquery', False)

    print(f"Tipo de tabla: {table_type}")
    print(f"Fecha de inicio: {fecha_inicio}")
    print(f"Archivo de salida: {output_file}")
    print(f"Subir a GCS: {'Sí' if upload_gcs else 'No'}")
    print(f"Crear en BigQuery: {'Sí' if create_bigquery else 'No'}")
    print("-" * 40)

    # Extraer datos de la API
    messages = extract_data_with_access_key(fecha_inicio, table_type, temp_config, table_name)

    if not messages:
        print(f"No se encontraron registros para la tabla {table_name}")
        return

    # Guardar en formato JSONL
    save_to_jsonl(messages, output_file)

    # Subir a Google Cloud Storage si se solicita
    gcs_uri = None
    if upload_gcs:
        print(f"\n=== Subiendo {table_name} a Google Cloud Storage ===")
        gcs_path = storage_config.get('gcs_path', f"utp_pregrado/reporteAtenciones/landing")
        gcs_uri = upload_to_gcs(output_file, gcp_config, fecha_inicio, gcs_path)

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
            create_bigquery_table(gcs_uri, gcp_config, table_id, schema, bigquery_config, fecha_inicio)
        else:
            # Subir archivo a la ruta específica de BigQuery (raw)
            print(f"Subiendo archivo a GCS para BigQuery en directorio raw...")
            print(f"Ruta de destino: {bigquery_gcs_path}")
            temp_gcs_uri = upload_to_gcs(output_file, gcp_config, fecha_inicio, bigquery_gcs_path)
            create_bigquery_table(temp_gcs_uri, gcp_config, table_id, schema, bigquery_config, fecha_inicio)

    print(f"¡Tabla {table_name} procesada exitosamente!")


def generate_date_list(current_date: str, days_back: int) -> List[str]:
    """
    Genera una lista de fechas desde current_date hacia atrás por days_back días

    Args:
        current_date (str): Fecha actual en formato YYYY-MM-DD
        days_back (int): Cantidad de días hacia atrás a procesar

    Returns:
        List[str]: Lista de fechas en formato YYYY-MM-DD
    """
    dates = []
    base_date = datetime.strptime(current_date, '%Y-%m-%d')

    for i in range(days_back + 1):  # +1 para incluir el día actual
        date = base_date - timedelta(days=i)
        dates.append(date.strftime('%Y-%m-%d'))

    return dates


def process_date(fecha: str) -> bool:
    """
    Procesa datos para una fecha específica

    Args:
        fecha (str): Fecha en formato YYYY-MM-DD

    Returns:
        bool: True si la ejecución fue exitosa, False en caso contrario
    """
    try:
        print(f"Procesando fecha: {fecha}")

        # Cargar configuración
        config = load_config('config/config.json')
        gcp_config = config.get('gcp', {})

        # Procesar cada tabla configurada
        tables_processed = 0
        for table_name, table_config in config.items():
            if table_name == 'gcp':
                continue  # Saltar configuración de GCP

            if isinstance(table_config, dict) and 'enabled' in table_config:
                # Procesar la tabla
                process_table(table_name, table_config, gcp_config, fecha)
                tables_processed += 1

        if tables_processed == 0:
            print(f"❌ No se encontraron tablas habilitadas para procesar")
            return False

        print(f"✅ Fecha {fecha} procesada exitosamente - {tables_processed} tabla(s) procesada(s)")
        return True

    except Exception as e:
        print(f"❌ Error procesando fecha {fecha}: {e}")
        return False


def main(request, context=None):
    """
    Cloud Function principal

    Args:
        request: Request HTTP o diccionario con datos
        context: Contexto de Cloud Functions (opcional)

    Returns:
        Dict[str, Any]: Resultado del procesamiento
    """
    try:
        # Manejar diferentes tipos de entrada
        if hasattr(request, 'get_json'):
            # Es un objeto Request HTTP (Cloud Functions 2nd gen)
            try:
                event_data = request.get_json()
                if not event_data:
                    event_data = {}
            except Exception:
                event_data = {}
        elif isinstance(request, dict):
            # Es un diccionario directo
            event_data = request
        else:
            # Intentar convertir a diccionario
            event_data = dict(request) if hasattr(request, '__dict__') else {}

        # Extraer parámetros del evento
        print(f"=== Imprimiendo evento ===")
        print(event_data)
        print(f"=== Fin de evento ===")
        current_date = event_data.get('current_date')
        days_back = event_data.get('days_back', 0)

        if not current_date:
            raise ValueError("El evento debe contener 'current_date' en formato YYYY-MM-DD")

        # Validar formato de fecha
        try:
            if current_date.upper() == 'TODAY':
                current_date = datetime.now().strftime('%Y-%m-%d')
            else:
                datetime.strptime(current_date, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Formato de fecha inválido. Use YYYY-MM-DD. Recibido: {current_date}")

        # Validar days_back
        if not isinstance(days_back, int) or days_back < 0:
            raise ValueError(f"days_back debe ser un entero >= 0. Recibido: {days_back}")

        # Generar lista de fechas a procesar
        dates_to_process = generate_date_list(current_date, days_back)

        print(f"=== Cloud Function OneMarketer API ===")
        print(f"Fecha actual: {current_date}")
        print(f"Días hacia atrás: {days_back}")
        print(f"Fechas a procesar: {len(dates_to_process)} días")
        print(f"Rango: {dates_to_process[-1]} a {dates_to_process[0]}")
        print("=" * 50)

        # Procesar cada fecha
        successful = 0
        failed = 0
        results = []

        for i, fecha in enumerate(dates_to_process, 1):
            print(f"\n[{i}/{len(dates_to_process)}] Procesando fecha: {fecha}")

            if process_date(fecha):
                successful += 1
                results.append({"fecha": fecha, "status": "success"})
            else:
                failed += 1
                results.append({"fecha": fecha, "status": "failed"})

        # Resumen final
        print("\n" + "=" * 50)
        print("RESUMEN DE PROCESAMIENTO")
        print("=" * 50)
        print(f"Total de fechas: {len(dates_to_process)}")
        print(f"Exitosas: {successful}")
        print(f"Fallidas: {failed}")
        print(f"Tasa de éxito: {(successful/len(dates_to_process)*100):.1f}%")

        # Preparar respuesta
        response = {
            "status": "success" if failed == 0 else "partial_success",
            "total_dates": len(dates_to_process),
            "successful": successful,
            "failed": failed,
            "success_rate": round((successful/len(dates_to_process)*100), 1),
            "results": results
        }

        if failed > 0:
            print(f"\n⚠️  {failed} fecha(s) fallaron.")
            response["status"] = "partial_success"
        else:
            print(f"\n✅ Todas las fechas se procesaron exitosamente!")
            response["status"] = "success"

        return response

    except Exception as e:
        error_msg = f"Error en Cloud Function: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "status": "error",
            "error": error_msg
        }


# Función para testing local
def test_local():
    """Función para testing local sin Cloud Functions"""
    # Simular evento de Cloud Function
    event = {
        "current_date": "2025-01-15",
        "days_back": 2
    }

    result = main(event)
    print(f"\nResultado: {json.dumps(result, indent=2)}")


# Clase mock para simular request HTTP
class MockRequest:
    def __init__(self, data):
        self.data = data

    def get_json(self):
        return self.data


# Función para testing con request HTTP
def test_http():
    """Función para testing con request HTTP simulado"""
    # Simular request HTTP
    request = MockRequest({
        "current_date": "2025-01-15",
        "days_back": 2
    })

    result = main(request)
    print(f"\nResultado HTTP: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    test_local()
