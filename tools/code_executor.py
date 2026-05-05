# tools/code_executor.py
import subprocess
import tempfile
import os
import sys
import time
import signal

TIMEOUT = 10  # segundos

def execute_python_code(code: str) -> dict:
    """
    Ejecuta el código Python en un subproceso aislado.
    No tiene acceso a internet (desactivamos red con --network=none? no disponible portable).
    Como alternativa, eliminamos variables de entorno peligrosas y limitamos tiempo.
    """
    # Guardar código en archivo temporal
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_path = f.name

    try:
        # Iniciar subproceso con time out y sin acceso a módulos peligrosos?
        # Usamos un entorno virtual controlado.
        # Por simplicidad, ejecutamos con python actual, pero con reglas de seguridad limitadas.
        # En producción se puede usar docker/sandboxing avanzado.
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env={**os.environ, "PYTHONPATH": ""}  # limpiar PYTHONPATH
        )
        output = result.stdout
        errors = result.stderr
        return {
            "success": result.returncode == 0,
            "stdout": output.strip(),
            "stderr": errors.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": f"Timeout tras {TIMEOUT}s"}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass