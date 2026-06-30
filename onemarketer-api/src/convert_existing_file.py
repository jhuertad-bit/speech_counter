#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para convertir el formato de fecha y renombrar campos en un archivo JSONL existente
- Convierte el campo 'time' de YY-MM-DD HH:MM:SS a %Y-%m-%d %H:%M:%S
- Renombra 'Time Wait Operator' a 'time_wait_operator'
- Filtra solo los campos definidos en las configuraciones de tablas
- Coloca campos faltantes con valor de cadena vacía
"""

import json
import argparse
import sys
import re
import os
from typing import Dict, Any, List, Set


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


def convert_time_format(message: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convierte el formato de fecha en el campo 'time' de YY-MM-DD HH:MM:SS a %Y-%m-%d %H:%M:%S

    Args:
        message (Dict[str, Any]): Mensaje con el campo 'time' a convertir

    Returns:
        Dict[str, Any]: Mensaje con el formato de fecha convertido
    """
    if 'time' in message and message['time']:
        time_str = message['time']

        # Patrón para YY-MM-DD HH:MM:SS
        pattern = r'^(\d{2})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$'
        match = re.match(pattern, time_str)

        if match:
            yy, mm, dd, hh, min_sec, ss = match.groups()

            # Convertir año de 2 dígitos a 4 dígitos
            # Asumimos que años 00-30 son 2000-2030, años 31-99 son 1931-1999
            year = int(yy)
            if year <= 30:
                year += 2000
            else:
                year += 1900

            # Crear nueva fecha en formato %Y-%m-%d %H:%M:%S
            new_time = f"{year:04d}-{mm}-{dd} {hh}:{min_sec}:{ss}"
            message['time'] = new_time
        else:
            print(f"Advertencia: No se pudo convertir el formato de fecha: {time_str}")

    return message


def rename_fields(message: Dict[str, Any], renamed_fields_log: set) -> tuple[Dict[str, Any], set]:
    """
    Renombra campos específicos en el mensaje

    Args:
        message (Dict[str, Any]): Mensaje con campos a renombrar
        renamed_fields_log (set): Conjunto de campos ya renombrados para evitar logs duplicados

    Returns:
        tuple[Dict[str, Any], set]: Mensaje con campos renombrados y log actualizado
    """
    # Mapeo de campos a renombrar
    field_mapping = {
        'Time Wait Operator': 'time_wait_operator'
    }

    # Crear una copia del mensaje para evitar modificar el original
    converted_message = message.copy()

    # Renombrar campos según el mapeo
    for old_name, new_name in field_mapping.items():
        if old_name in converted_message:
            converted_message[new_name] = converted_message.pop(old_name)
            # Solo imprimir el log una vez por tipo de campo
            if old_name not in renamed_fields_log:
                print(f"Campo renombrado: '{old_name}' -> '{new_name}'")
                renamed_fields_log.add(old_name)

    return converted_message, renamed_fields_log


def convert_jsonl_file(input_file: str, output_file: str, tablas_dir: str = "tablas", table_name: str = None) -> None:
    """
    Convierte el formato de fecha y renombra campos en un archivo JSONL existente

    Args:
        input_file (str): Archivo JSONL de entrada
        output_file (str): Archivo JSONL de salida con fechas convertidas y campos renombrados
        tablas_dir (str): Directorio que contiene las definiciones de tablas
        table_name (str): Nombre de la tabla a usar para filtrar campos (opcional)
    """
    try:
        # Cargar definiciones de tablas
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

        converted_count = 0
        error_count = 0
        renamed_fields_count = 0
        filtered_count = 0
        renamed_fields_log = set()

        with open(input_file, 'r', encoding='utf-8') as infile, \
                open(output_file, 'w', encoding='utf-8') as outfile:

            for line_num, line in enumerate(infile, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    # Parsear la línea JSON
                    message = json.loads(line)

                    # Renombrar campos específicos
                    renamed_message, renamed_fields_log = rename_fields(message, renamed_fields_log)
                    if renamed_message != message:
                        renamed_fields_count += 1

                    # Convertir formato de fecha
                    converted_message = convert_time_format(renamed_message)

                    # Filtrar y normalizar campos según las definiciones de tabla
                    if allowed_fields:
                        filtered_message = filter_and_normalize_message(converted_message, allowed_fields)
                        if filtered_message != converted_message:
                            filtered_count += 1
                        final_message = filtered_message
                    else:
                        final_message = converted_message

                    # Escribir la línea convertida
                    json_line = json.dumps(final_message, ensure_ascii=False, separators=(',', ':'))
                    outfile.write(json_line + '\n')

                    converted_count += 1

                    # Mostrar progreso cada 10000 líneas
                    if converted_count % 10000 == 0:
                        print(f"Procesadas {converted_count} líneas...")

                except json.JSONDecodeError as e:
                    print(f"Error en línea {line_num}: {e}")
                    error_count += 1
                    continue
                except Exception as e:
                    print(f"Error inesperado en línea {line_num}: {e}")
                    error_count += 1
                    continue

        print(f"\n=== Conversión completada ===")
        print(f"Líneas procesadas exitosamente: {converted_count}")
        print(f"Registros con campos renombrados: {renamed_fields_count}")
        if allowed_fields:
            print(f"Registros con campos filtrados: {filtered_count}")
            print(f"Campos permitidos: {len(allowed_fields)}")
        print(f"Errores encontrados: {error_count}")
        print(f"Archivo de salida: {output_file}")

    except FileNotFoundError:
        print(f"Error: No se encontró el archivo {input_file}")
        sys.exit(1)
    except Exception as e:
        print(f"Error al procesar el archivo: {e}")
        sys.exit(1)


def main():
    """Función principal del script"""
    parser = argparse.ArgumentParser(
        description='Convierte el formato de fecha y renombra campos en un archivo JSONL existente'
    )

    parser.add_argument(
        '--input',
        required=True,
        help='Archivo JSONL de entrada'
    )

    parser.add_argument(
        '--output',
        required=True,
        help='Archivo JSONL de salida con fechas convertidas y campos renombrados'
    )

    parser.add_argument(
        '--tablas-dir',
        default='tablas',
        help='Directorio que contiene las definiciones de tablas (default: tablas)'
    )

    parser.add_argument(
        '--table',
        help='Nombre específico de la tabla a usar para filtrar campos (opcional)'
    )

    args = parser.parse_args()

    print("=== Convertidor de Formato de Fechas y Campos ===")
    print(f"Archivo de entrada: {args.input}")
    print(f"Archivo de salida: {args.output}")
    print(f"Directorio de tablas: {args.tablas_dir}")
    if args.table:
        print(f"Tabla específica: {args.table}")
    print("Conversiones aplicadas:")
    print("  - Formato de fecha: YY-MM-DD HH:MM:SS -> YYYY-MM-DD HH:MM:SS")
    print("  - Campo renombrado: 'Time Wait Operator' -> 'time_wait_operator'")
    print("  - Filtrado de campos según definiciones de tabla")
    print("  - Campos faltantes se rellenan con cadena vacía")
    print("-" * 60)

    convert_jsonl_file(args.input, args.output, args.tablas_dir, args.table)

    print("\n¡Conversión completada exitosamente!")


if __name__ == "__main__":
    main()
