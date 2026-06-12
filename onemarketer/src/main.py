#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloud Function para procesar datos de OneMarketer
Recibe día actual y cantidad de días hacia atrás para reprocesar
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List
from zoneinfo import ZoneInfo

PROCESS_TIMEZONE = "America/Lima"

# Importar funciones directamente de extract_chats.py
from extract_chats import load_config, process_table, print_runtime_gcp_info
from download_chat_media import process_media_for_date


def resolve_current_date(current_date: str) -> str:
    """Resuelve TODAY/YESTERDAY en America/Lima o valida YYYY-MM-DD."""
    today = datetime.now(ZoneInfo(PROCESS_TIMEZONE)).date()
    key = current_date.upper()
    if key == "TODAY":
        return today.strftime("%Y-%m-%d")
    if key == "YESTERDAY":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    datetime.strptime(current_date, "%Y-%m-%d")
    return current_date


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


def process_date(fecha: str, force_reprocess: bool = False) -> bool:
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
        
        media_cfg = config.get("descargaChatsMedia", {})
        source_table = media_cfg.get("source_table", "reporteChats")
        chat_messages: List[Dict[str, Any]] = []

        tables_processed = 0
        for table_name, table_config in config.items():
            if table_name in ('gcp', 'descargaChatsMedia'):
                continue

            if isinstance(table_config, dict) and 'enabled' in table_config:
                if 'api' in table_config:
                    table_config['api']['fechaini'] = fecha

                messages = process_table(table_name, table_config, gcp_config)
                if table_name == source_table and messages:
                    chat_messages = messages
                tables_processed += 1
        
        if tables_processed == 0:
            print(f"❌ No se encontraron tablas habilitadas para procesar")
            return False

        if media_cfg.get("enabled", False):
            print(f"\n=== Medios: reporteChats → descargachats → GCS/BQ ({fecha}) ===")
            if "api" in media_cfg:
                media_cfg["api"]["fechaini"] = fecha
            media_result = process_media_for_date(
                fecha,
                config,
                chat_messages=chat_messages or None,
                force_reprocess=force_reprocess,
            )
            if media_result.get("failed", 0) > 0:
                print(f"⚠️  Descarga de medios con {media_result['failed']} error(es)")
        
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
        force_reprocess = bool(event_data.get('force_reprocess', False))
        
        if not current_date:
            raise ValueError("El evento debe contener 'current_date' en formato YYYY-MM-DD")
        
        # Validar formato de fecha (TODAY/YESTERDAY en America/Lima o YYYY-MM-DD)
        try:
            current_date = resolve_current_date(current_date)
        except ValueError:
            raise ValueError(
                f"Formato de fecha inválido. Use YYYY-MM-DD, TODAY o YESTERDAY. Recibido: {current_date}"
            )
        
        # Validar days_back
        if not isinstance(days_back, int) or days_back < 0:
            raise ValueError(f"days_back debe ser un entero >= 0. Recibido: {days_back}")
        
        # Generar lista de fechas a procesar
        dates_to_process = generate_date_list(current_date, days_back)
        
        print(f"=== Cloud Function OneMarketer ===")
        print(f"Fecha actual: {current_date}")
        print(f"Días hacia atrás: {days_back}")
        print(f"Fechas a procesar: {len(dates_to_process)} días")
        print(f"Rango: {dates_to_process[-1]} a {dates_to_process[0]}")
        print(f"Force reprocess: {force_reprocess}")

        runtime_config = load_config('config/config.json')
        print_runtime_gcp_info(runtime_config, service_label="onemarketer-etl")
        print("=" * 50)
        
        # Procesar cada fecha
        successful = 0
        failed = 0
        results = []
        
        for i, fecha in enumerate(dates_to_process, 1):
            print(f"\n[{i}/{len(dates_to_process)}] Procesando fecha: {fecha}")
            
            if process_date(fecha, force_reprocess=force_reprocess):
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
        "current_date": "2025-03-21",
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
        "current_date": "2025-03-21",
        "days_back": 2
    })
    
    result = main(request)
    print(f"\nResultado HTTP: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    test_local()
