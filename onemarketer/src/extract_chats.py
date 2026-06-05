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
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
import urllib.parse
import re
import os
from google.cloud import storage
from google.cloud import bigquery

# Env vars inyectadas en deploy (Cloud Build → --set-env-vars). Sobrescriben config.json["gcp"].
_GCP_ENV_VARS = {
    "project_id": "GCP_PROJECT_ID",
    "bucket_name": "GCP_BUCKET_NAME",
    "dataset_id": "GCP_DATASET_ID",
    "region": "GCP_REGION",
    "function_name": "GCP_FUNCTION_NAME",
    "scheduler_name": "GCP_SCHEDULER_NAME",
    "service_account_name": "GCP_SERVICE_ACCOUNT_NAME",
}


def apply_gcp_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica overrides de entorno sobre la sección gcp (prioridad: env > config.json)."""
    gcp = config.setdefault("gcp", {})
    overrides = {key: os.environ[env_name] for key, env_name in _GCP_ENV_VARS.items() if os.environ.get(env_name)}
    if overrides:
        gcp.update(overrides)
        print(f"GCP config desde env: {', '.join(sorted(overrides))}")
    return config


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
        return apply_gcp_env_overrides(config)
        
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo de configuración: {config_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error al parsear el archivo de configuración: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error al cargar la configuración: {e}")
        sys.exit(1)


def add_date_fields(message: Dict[str, Any], fecha_inicio: str) -> Dict[str, Any]:
    """
    Agrega los campos fecha_evento y fecha_procesamiento a un mensaje
    OBLIGATORIO: fecha_evento es requerido para el particionado
    
    Args:
        message (Dict[str, Any]): Mensaje original
        fecha_inicio (str): Fecha de extracción en formato YYYY-MM-DD
    
    Returns:
        Dict[str, Any]: Mensaje con los nuevos campos agregados
    """
    # Validar formato de fecha_inicio
    try:
        from datetime import datetime
        datetime.strptime(fecha_inicio, '%Y-%m-%d')
    except ValueError:
        raise ValueError(f"Formato de fecha_inicio inválido. Debe ser YYYY-MM-DD. Recibido: {fecha_inicio}")
    
    # Crear una copia del mensaje para no modificar el original
    enhanced_message = message.copy()
    
    # OBLIGATORIO: Agregar fecha_evento (fecha de extracción)
    # Este campo es CRÍTICO para el particionado de la tabla
    enhanced_message['fecha_evento'] = fecha_inicio
    
    # Agregar fecha_procesamiento (fecha y hora actual en formato ISO)
    enhanced_message['fecha_procesamiento'] = datetime.now().isoformat()
    
    # Validar que los campos se agregaron correctamente
    if 'fecha_evento' not in enhanced_message:
        raise ValueError("Error crítico: No se pudo agregar el campo fecha_evento")
    
    if 'fecha_procesamiento' not in enhanced_message:
        raise ValueError("Error crítico: No se pudo agregar el campo fecha_procesamiento")
    
    return enhanced_message


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
    Sube un archivo a Google Cloud Storage
    
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
        
        # Crear ruta de destino en el bucket
        blob_name = f"{gcs_path}/{fecha_inicio}/{os.path.basename(file_path)}"
        blob = bucket.blob(blob_name)
        
        # Subir archivo
        print(f"Subiendo archivo a GCS: gs://{bucket_name}/{blob_name}")
        blob.upload_from_filename(file_path)
        
        print(f"Archivo subido exitosamente a: gs://{bucket_name}/{blob_name}")
        return f"gs://{bucket_name}/{blob_name}"
        
    except Exception as e:
        error_msg = f"Error al subir archivo a GCS: {e}"
        print(f"❌ {error_msg}")
        raise RuntimeError(error_msg) from e


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
    Elimina una partición específica de una tabla particionada por fecha_evento
    Esta función es CRÍTICA para el reprocesamiento de datos
    
    Args:
        table_ref (str): Referencia completa de la tabla
        partition_date (str): Fecha de la partición en formato YYYYMMDD
        client: Cliente de BigQuery
    
    Returns:
        bool: True si se eliminó la partición, False si no existía
    """
    try:
        # Construir el ID de la partición
        partition_id = f"{table_ref}${partition_date}"
        
        print(f"🔍 Verificando existencia de partición: {partition_id}")
        
        # Verificar si la partición existe
        try:
            partition = client.get_table(partition_id)
            print(f"📊 Partición encontrada:")
            print(f"   - ID: {partition_id}")
            print(f"   - Filas: {partition.num_rows}")
            print(f"   - Tamaño: {partition.num_bytes} bytes")
            
            # Eliminar la partición
            print(f"🗑️  Eliminando partición: {partition_id}")
            client.delete_table(partition_id)
            print(f"✅ Partición {partition_id} eliminada exitosamente")
            return True
            
        except Exception as get_error:
            # Verificar si el error es porque la partición no existe
            error_str = str(get_error).lower()
            if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                print(f"ℹ️  Partición {partition_id} no existe, no hay nada que eliminar")
                return False
            else:
                print(f"❌ Error al verificar partición {partition_id}: {get_error}")
                raise get_error
            
    except Exception as e:
        print(f"❌ Error crítico al eliminar partición {partition_date}: {e}")
        print(f"❌ Esto puede causar problemas en el reprocesamiento")
        # No hacer raise aquí para permitir que el proceso continúe
        return False


def create_bigquery_table(gcs_uri: str, gcp_config: Dict[str, Any], table_id: str, schema: List[Dict[str, Any]], bq_config: Dict[str, Any], fechaini: str = None) -> None:
    """
    Crea una tabla en BigQuery desde un archivo JSONL en GCS
    OBLIGATORIO: La tabla debe estar particionada por fecha_evento
    
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
                print(f"Dataset {dataset_ref} ya existe")
            except Exception as e:
                # Solo crear el dataset si realmente no existe
                error_str = str(e).lower()
                if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                    print(f"Creando dataset {dataset_ref}...")
                    dataset = bigquery.Dataset(dataset_ref)
                    dataset.location = "US"  # Puedes cambiar la ubicación según necesites
                    client.create_dataset(dataset, timeout=30)
                    print(f"Dataset {dataset_ref} creado exitosamente")
                else:
                    print(f"Error al verificar dataset {dataset_ref}: {e}")
                    raise
            
            # Crear la tabla con el esquema
            table = bigquery.Table(table_ref, schema=[
                bigquery.SchemaField(field['name'], field['type'], mode=field['mode']) 
                for field in schema
            ])
            
            # OBLIGATORIO: Configurar particionado por fecha_evento
            print(f"Configurando particionado OBLIGATORIO por fecha_evento para la tabla {table_ref}...")
            
            # Verificar que fecha_evento esté en el esquema
            fecha_evento_field = None
            for field in schema:
                if field['name'] == 'fecha_evento':
                    fecha_evento_field = field
                    break
            
            if not fecha_evento_field:
                print(f"❌ ERROR CRÍTICO: El campo 'fecha_evento' es OBLIGATORIO para el particionado")
                print(f"❌ El campo debe estar presente en el esquema de la tabla")
                raise ValueError("El campo 'fecha_evento' es obligatorio para el particionado de la tabla")
            
            # Verificar que fecha_evento sea de tipo DATE
            if fecha_evento_field['type'] != 'DATE':
                print(f"❌ ERROR CRÍTICO: El campo 'fecha_evento' debe ser de tipo DATE")
                print(f"❌ Tipo actual: {fecha_evento_field['type']}")
                raise ValueError("El campo 'fecha_evento' debe ser de tipo DATE para el particionado")
            
            # Configurar particionado por fecha_evento
            partition_config = bq_config.get('partition', {})
            partition_expiration_days = partition_config.get('expiration_days')
            
            # Siempre usar particionado por tiempo con fecha_evento
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field='fecha_evento'
            )
            print(f"  ✅ Tipo: Particionado por tiempo (DAY)")
            print(f"  ✅ Campo: fecha_evento")
            
            if partition_expiration_days:
                table.time_partitioning.expiration_ms = partition_expiration_days * 24 * 60 * 60 * 1000
                print(f"  ✅ Expiración: {partition_expiration_days} días")
            else:
                print(f"  ✅ Sin expiración configurada")
            
            table = client.create_table(table)
            print(f"Tabla {table_ref} creada exitosamente con {len(schema)} campos")
        
        # Configurar job de carga
        # Por defecto usar WRITE_APPEND para preservar datos existentes
        write_disposition = bq_config.get('write_disposition', 'WRITE_APPEND')
        
        # REPROCESAMIENTO: Si tenemos fechaini, SIEMPRE eliminar la partición específica
        partition_deleted = False
        if fechaini:
            # Convertir fechaini de YYYY-MM-DD a YYYYMMDD para la partición
            partition_date = fechaini.replace('-', '')
            print(f"\n🔄 INICIANDO REPROCESAMIENTO para fecha: {fechaini}")
            print(f"🔍 Buscando partición: {partition_date}")
            
            # Verificar que la tabla esté particionada correctamente
            if table_exists:
                try:
                    table_info = client.get_table(table_ref)
                    if not table_info.time_partitioning:
                        print(f"❌ ERROR CRÍTICO: La tabla {table_ref} no está particionada")
                        print(f"❌ El reprocesamiento requiere particionado por fecha_evento")
                        raise ValueError("La tabla debe estar particionada por fecha_evento para el reprocesamiento")
                    
                    if table_info.time_partitioning.field != 'fecha_evento':
                        print(f"❌ ERROR CRÍTICO: La tabla {table_ref} no está particionada por fecha_evento")
                        print(f"❌ Campo de partición actual: {table_info.time_partitioning.field}")
                        raise ValueError("La tabla debe estar particionada por fecha_evento para el reprocesamiento")
                    
                    print(f"✅ Tabla correctamente particionada por fecha_evento")
                    
                except Exception as e:
                    print(f"❌ Error al verificar particionado de la tabla: {e}")
                    raise
            
            # Eliminar la partición específica
            partition_deleted = delete_partition_by_date(table_ref, partition_date, client)
            
            if partition_deleted:
                print(f"✅ REPROCESAMIENTO: Partición del día {fechaini} eliminada exitosamente")
                print(f"✅ Se cargarán datos actualizados para la fecha {fechaini}")
                # La partición ya fue eliminada, usar WRITE_APPEND para cargar datos nuevos
                write_disposition = 'WRITE_APPEND'
                print(f"✅ Usando WRITE_APPEND para cargar datos en la partición del día {fechaini}")
            else:
                print(f"ℹ️  REPROCESAMIENTO: No existía partición del día {fechaini}")
                print(f"ℹ️  Se crearán nuevos datos para la fecha {fechaini}")
                print(f"ℹ️  Usando {write_disposition} para preservar datos existentes")
        else:
            print(f"ℹ️  No se especificó fecha de reprocesamiento, usando configuración por defecto")
        
        # Configurar autodetect basado en si tenemos esquema
        use_autodetect = not (schema and len(schema) > 0)
        if use_autodetect:
            # Si no hay esquema, usar autodetect=True
            autodetect_value = True
        else:
            # Si hay esquema, usar la configuración especificada o False por defecto
            autodetect_value = bq_config.get('autodetect', False)
        
        job_config = bigquery.LoadJobConfig(
            source_format=getattr(bigquery.SourceFormat, bq_config.get('source_format', 'NEWLINE_DELIMITED_JSON')),
            autodetect=autodetect_value,
            write_disposition=getattr(bigquery.WriteDisposition, write_disposition),
        )
        
        # Agregar esquema si está disponible
        if schema and len(schema) > 0:
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
        error_msg = f"Error al crear/cargar tabla en BigQuery: {e}"
        print(f"❌ {error_msg}")
        raise RuntimeError(error_msg) from e


def extract_chats(fecha_inicio: str, key: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrae datos de chats desde la API de OneMarketer
    
    Args:
        fecha_inicio (str): Fecha de inicio en formato YYYY-MM-DD
        key (str): Clave de autenticación para la API
        config (Dict[str, Any]): Configuración del sistema
    
    Returns:
        List[Dict[str, Any]]: Lista de mensajes extraídos
    """
    # Obtener configuración de API
    api_config = config.get('api', {})
    base_url = api_config.get('base_url', 'https://utp.onemarketer.cl/utp_pregrado_endpoint/reporteChats/services/getChats.php')
    context = api_config.get('context', 1)
    timeout = api_config.get('timeout', 300)  # Aumentado a 300 segundos (5 minutos) por defecto
    max_retries = api_config.get('max_retries', 3)  # Número máximo de reintentos
    retry_delay = api_config.get('retry_delay', 5)  # Segundos de espera entre reintentos
    
    # Parámetros de la consulta
    params = {
        'context': context,
        'fechaini': fecha_inicio,
        'key': key
    }
    
    # Intentar la petición con reintentos
    last_exception = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"Reintento {attempt + 1}/{max_retries} después de {retry_delay} segundos...")
                time.sleep(retry_delay)
            
            print(f"Realizando consulta a la API...")
            print(f"URL: {base_url}")
            print(f"Parámetros: {params}")
            print(f"Timeout configurado: {timeout} segundos")
            
            # Realizar la petición GET
            response = requests.get(base_url, params=params, timeout=timeout)
            response.raise_for_status()
            
            # Si llegamos aquí, la petición fue exitosa
            break
            
        except requests.exceptions.Timeout as e:
            last_exception = e
            error_msg = f"Timeout al realizar la petición HTTP (intento {attempt + 1}/{max_retries})"
            print(f"⚠️  {error_msg}")
            print(f"   Timeout configurado: {timeout} segundos")
            print(f"   URL: {base_url}")
            
            if attempt < max_retries - 1:
                print(f"   Reintentando en {retry_delay} segundos...")
            else:
                print(f"   ❌ Se agotaron los {max_retries} intentos")
                raise ValueError(f"Timeout después de {max_retries} intentos. La API no respondió en {timeout} segundos.") from e
                
        except requests.exceptions.RequestException as e:
            # Para otros errores de requests, no reintentar (probablemente es un error de configuración)
            raise ValueError(f"Error al realizar la petición HTTP: {e}") from e
    
    # Si llegamos aquí después de los reintentos, continuar con el procesamiento
    try:
        # Decodificar la respuesta como UTF-8
        response.encoding = 'utf-8'
        
        # Verificar que la respuesta tenga contenido antes de intentar parsear JSON
        response_text = response.text.strip()
        if not response_text:
            error_msg = f"La respuesta de la API está vacía. Status code: {response.status_code}, URL: {base_url}"
            print(f"❌ {error_msg}")
            print(f"Response headers: {dict(response.headers)}")
            raise ValueError(error_msg)
        
        # Intentar parsear JSON con mejor manejo de errores
        try:
            data = response.json()
        except json.JSONDecodeError as json_err:
            error_msg = f"Error al decodificar JSON de la respuesta. Status code: {response.status_code}"
            print(f"❌ {error_msg}")
            print(f"Response text (primeros 500 caracteres): {response_text[:500]}")
            print(f"Response headers: {dict(response.headers)}")
            print(f"Error de JSON: {json_err}")
            raise ValueError(f"{error_msg}. Respuesta recibida: {response_text[:200]}...")
        
        # Extraer los mensajes del campo 'data'
        if 'data' in data and isinstance(data['data'], list):
            messages = data['data']
            print(f"Se encontraron {len(messages)} mensajes")
            
            # Convertir formato de fecha en cada mensaje
            print("Convirtiendo formato de fechas...")
            converted_messages = []
            batch_size = config.get('processing', {}).get('batch_size', 10000)
            show_progress = config.get('processing', {}).get('show_progress', True)
            
            for i, message in enumerate(messages):
                # Convertir formato de fecha del campo 'time'
                converted_message = convert_time_format(message, config)
                # Agregar campos de fecha_evento y fecha_procesamiento
                enhanced_message = add_date_fields(converted_message, fecha_inicio)
                converted_messages.append(enhanced_message)
                
                # Mostrar progreso si está habilitado
                if show_progress and (i + 1) % batch_size == 0:
                    print(f"Procesados {i + 1} mensajes...")
            
            return converted_messages
        else:
            print("No se encontró el campo 'data' o no es una lista")
            print(f"Estructura de respuesta recibida: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            return []
            
    except requests.exceptions.Timeout as e:
        # Este error ya se maneja arriba con reintentos, pero por si acaso
        error_msg = f"Timeout al realizar la petición HTTP después de {max_retries} intentos: {e}"
        print(f"❌ {error_msg}")
        print(f"   Timeout configurado: {timeout} segundos")
        print(f"   Sugerencia: Considera aumentar el timeout en la configuración si la API tarda más en responder")
        raise ValueError(error_msg) from e
    except requests.exceptions.RequestException as e:
        error_msg = f"Error al realizar la petición HTTP: {e}"
        print(f"❌ {error_msg}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Status code: {e.response.status_code}")
            print(f"Response text: {e.response.text[:500]}")
        raise ValueError(error_msg) from e
    except (json.JSONDecodeError, ValueError) as e:
        # Ya se maneja arriba, pero por si acaso
        error_msg = f"Error al procesar respuesta de la API: {e}"
        print(f"❌ {error_msg}")
        raise ValueError(error_msg) from e
    except Exception as e:
        error_msg = f"Error inesperado al extraer chats: {e}"
        print(f"❌ {error_msg}")
        raise RuntimeError(error_msg) from e


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
        error_msg = f"Error al guardar el archivo: {e}"
        print(f"❌ {error_msg}")
        raise RuntimeError(error_msg) from e


def load_table_schema(table_name: str) -> List[Dict[str, Any]]:
    """
    Carga el esquema de una tabla desde el archivo JSON correspondiente
    VALIDA que el esquema incluya el campo fecha_evento obligatorio
    
    Args:
        table_name (str): Nombre de la tabla
    
    Returns:
        List[Dict[str, Any]]: Esquema de la tabla
    """
    # Mapear nombres de tabla a archivos de esquema
    schema_mapping = {
        'reporteChats': 'reporte_chats',
        'reporte_chats': 'reporte_chats'
    }
    
    schema_file_name = schema_mapping.get(table_name, table_name)
    schema_file = f"tablas/{schema_file_name}.json"
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
        
        # VALIDACIÓN CRÍTICA: Verificar que fecha_evento esté presente
        fecha_evento_field = None
        for field in schema:
            if field['name'] == 'fecha_evento':
                fecha_evento_field = field
                break
        
        if not fecha_evento_field:
            print(f"❌ ERROR CRÍTICO: El campo 'fecha_evento' es OBLIGATORIO")
            print(f"❌ El campo debe estar presente en el esquema de la tabla {table_name}")
            print(f"❌ Agregue el siguiente campo al esquema:")
            print(f"❌ {{'name': 'fecha_evento', 'type': 'DATE', 'mode': 'NULLABLE'}}")
            raise ValueError(f"El campo 'fecha_evento' es obligatorio en el esquema de {table_name}")
        
        # Validar que fecha_evento sea de tipo DATE
        if fecha_evento_field['type'] != 'DATE':
            print(f"❌ ERROR CRÍTICO: El campo 'fecha_evento' debe ser de tipo DATE")
            print(f"❌ Tipo actual: {fecha_evento_field['type']}")
            print(f"❌ Cambie el tipo a 'DATE' en el esquema de {table_name}")
            raise ValueError(f"El campo 'fecha_evento' debe ser de tipo DATE en {table_name}")
        
        print(f"✅ Campo fecha_evento validado correctamente")
        print(f"Esquema validado: {len(schema)} campos definidos")
        return schema
        
    except FileNotFoundError:
        print(f"Advertencia: No se encontró el archivo de esquema {schema_file}, usando detección automática")
        return []
    except Exception as e:
        print(f"Error al cargar el esquema: {e}")
        return []


def process_table(table_name: str, table_config: Dict[str, Any], gcp_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Procesa una tabla específica según su configuración
    
    Args:
        table_name (str): Nombre de la tabla
        table_config (Dict[str, Any]): Configuración de la tabla
        gcp_config (Dict[str, Any]): Configuración de GCP

    Returns:
        List[Dict[str, Any]]: Mensajes extraídos (vacío si se omitió o falló antes de extraer)
    """
    if not table_config.get('enabled', False):
        print(f"Tabla {table_name} está deshabilitada, saltando...")
        return []
    
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
        return []
    
    if not key:
        print(f"Error: key debe estar definido para la tabla {table_name}")
        return []
    
    # Validar formato de fecha
    try:
        datetime.strptime(fechaini, '%Y-%m-%d')
    except ValueError:
        print(f"Error: El formato de fecha debe ser YYYY-MM-DD para la tabla {table_name}")
        return []
    
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
    try:
        messages = extract_chats(fechaini, key, temp_config)
    except (ValueError, RuntimeError) as e:
        print(f"❌ Error al extraer chats para la tabla {table_name}: {e}")
        raise  # Re-lanzar la excepción para que sea manejada por el llamador
    
    if not messages:
        print(f"No se encontraron mensajes para la tabla {table_name}")
        return []
    
    # Guardar en formato JSONL
    try:
        save_to_jsonl(messages, output_file)
    except RuntimeError as e:
        print(f"❌ Error al guardar archivo JSONL para la tabla {table_name}: {e}")
        raise
    
    # Subir a Google Cloud Storage si se solicita
    gcs_uri = None
    if upload_gcs:
        try:
            print(f"\n=== Subiendo {table_name} a Google Cloud Storage ===")
            gcs_path = storage_config.get('gcs_path', f"utp_pregrado_endpoint/{table_name}")
            gcs_uri = upload_to_gcs(output_file, gcp_config, fechaini, gcs_path)
        except RuntimeError as e:
            print(f"❌ Error al subir archivo a GCS para la tabla {table_name}: {e}")
            raise
    
    # Crear tabla en BigQuery si se solicita
    if create_bigquery:
        try:
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
            
            if gcs_uri:
                create_bigquery_table(gcs_uri, gcp_config, table_id, schema, bigquery_config, fechaini)
            else:
                # Subir archivo temporalmente a GCS para BigQuery
                print(f"Subiendo archivo temporalmente a GCS para BigQuery...")
                gcs_path = storage_config.get('gcs_path', f"utp_pregrado_endpoint/{table_name}")
                temp_gcs_uri = upload_to_gcs(output_file, gcp_config, fechaini, gcs_path)
                create_bigquery_table(temp_gcs_uri, gcp_config, table_id, schema, bigquery_config, fechaini)
        except RuntimeError as e:
            print(f"❌ Error al procesar tabla en BigQuery para {table_name}: {e}")
            raise
    
    print(f"¡Tabla {table_name} procesada exitosamente!")
    return messages


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
        if table_name in ('gcp', 'descargaChatsMedia'):
            continue

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
