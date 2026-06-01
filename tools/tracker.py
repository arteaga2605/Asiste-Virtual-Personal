# tools/tracker.py
import threading
import time
from datetime import datetime
from config import ALERT_FILE, TRACKER_INTERVAL_MINUTES

# Almacén en memoria de la operación actual (solo una)
_active_operation = None
_tracker_thread = None
_stop_event = threading.Event()

def _evaluate_current_operation() -> str:
    """Evalúa la operación guardada usando la misma lógica de evaluate_active_operation."""
    if not _active_operation:
        return "No hay operación activa."
    from main import evaluate_active_operation  # importación local para evitar circularidad
    return evaluate_active_operation(_active_operation)

def _send_persistent_alert(message: str):
    """Escribe una alerta persistente en ALERT_FILE."""
    try:
        with open(ALERT_FILE, "w", encoding="utf-8") as f:
            f.write(f"PERSIST:🔄 Seguimiento: {message}")
    except Exception as e:
        print(f"[TRACKER] Error escribiendo alerta: {e}")

def _monitor_loop():
    """Hilo que ejecuta la evaluación cada TRACKER_INTERVAL_MINUTES."""
    print(f"[TRACKER] Seguimiento iniciado cada {TRACKER_INTERVAL_MINUTES} minutos.")
    while not _stop_event.is_set():
        try:
            msg = _evaluate_current_operation()
            _send_persistent_alert(msg)
        except Exception as e:
            print(f"[TRACKER] Error evaluando: {e}")
        # Esperar el intervalo, pero despertar si se detiene
        _stop_event.wait(timeout=TRACKER_INTERVAL_MINUTES * 60)
    print("[TRACKER] Seguimiento detenido.")

def start_tracking(operation_text: str):
    """Inicia o reinicia el seguimiento de una operación."""
    global _active_operation, _tracker_thread, _stop_event
    # Detener hilo anterior si existe
    stop_tracking()
    _active_operation = operation_text
    _stop_event.clear()
    _tracker_thread = threading.Thread(target=_monitor_loop, daemon=True)
    _tracker_thread.start()
    return f"Seguimiento iniciado para: {operation_text[:80]}..."

def stop_tracking():
    """Detiene el seguimiento si está activo."""
    global _tracker_thread, _stop_event
    if _tracker_thread and _tracker_thread.is_alive():
        _stop_event.set()
        _tracker_thread.join(timeout=2)
    _tracker_thread = None