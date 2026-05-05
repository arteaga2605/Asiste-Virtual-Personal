# agent.py
import ollama
from config import OLLAMA_MODEL, OLLAMA_HOST
import json

# Importamos las herramientas reales
from tools.trading import (
    get_symbol_data, 
    calculate_indicator, 
    get_live_price, 
    start_binance_stream
)
from tools.business import (
    add_note, list_notes,
    add_task, list_tasks, update_task_status,
    add_contact, list_contacts
)
from tools.code_executor import execute_python_code

# Configurar cliente
ollama_client = ollama.Client(host=OLLAMA_HOST)

# Definición de herramientas en formato OpenAI (compatible con Ollama)
TOOLS = [
    # ---------- Trading ----------
    {
        "type": "function",
        "function": {
            "name": "get_symbol_data",
            "description": "Obtiene datos históricos resumidos de un símbolo (ej. EURUSD, AAPL). Necesita archivo CSV local.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Símbolo del activo (ej. AAPL)"},
                    "start": {"type": "string", "description": "Fecha inicio opcional (YYYY-MM-DD)"},
                    "end": {"type": "string", "description": "Fecha fin opcional (YYYY-MM-DD)"}
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_indicator",
            "description": "Calcula un indicador técnico (RSI, SMA, EMA, MACD) sobre datos históricos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "indicator": {"type": "string", "enum": ["rsi", "sma", "ema", "macd"]},
                    "period": {"type": "integer", "default": 14}
                },
                "required": ["symbol", "indicator"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_price",
            "description": "Obtiene el precio en vivo de un par en Binance (ej. BTCUSDT). Requiere que el stream esté activo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Par en formato BTCUSDT"}
                },
                "required": ["symbol"]
            }
        }
    },
    # ---------- Negocios ----------
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": "Añade una nota al bloc de notas empresarial.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_notes",
            "description": "Lista todas las notas guardadas.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Añade una tarea.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "deadline": {"type": "string", "description": "Fecha límite YYYY-MM-DD (opcional)"}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "Lista las tareas. Por defecto muestra las pendientes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "done", "all"]}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_status",
            "description": "Actualiza el estado de una tarea.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "new_status": {"type": "string"}
                },
                "required": ["task_id", "new_status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact",
            "description": "Añade un contacto profesional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_contacts",
            "description": "Lista todos los contactos guardados.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    # ---------- Código ----------
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Ejecuta código Python de forma segura y devuelve la salida. Usa esta herramienta para probar fragmentos de código o ejecutar estrategias de trading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Código Python a ejecutar"}
                },
                "required": ["code"]
            }
        }
    }
]

# Mapeo de nombres de función a funciones Python
FUNCTION_MAP = {
    "get_symbol_data": get_symbol_data,
    "calculate_indicator": calculate_indicator,
    "get_live_price": get_live_price,
    "add_note": add_note,
    "list_notes": list_notes,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "update_task_status": update_task_status,
    "add_contact": add_contact,
    "list_contacts": list_contacts,
    "execute_python_code": execute_python_code,
}

SYSTEM_PROMPT = """
Eres un asistente virtual personal, amigable y servicial. Tu nombre es "Aria". Puedes conversar de forma natural y también ayudar en tareas específicas.

Áreas de especialidad:
- Trading y análisis de mercado (interpretar indicadores, datos históricos y precios en vivo de Binance).
- Gestión de empresa (notas, tareas, contactos).
- Programación Python (escribir, explicar y ejecutar código de forma segura).

Tienes acceso a herramientas para realizar acciones concretas. Úsalas solo cuando sea necesario (por ejemplo, si el usuario pide un cálculo, un precio en vivo, o administrar una tarea). Para saludos, preguntas generales o conversación casual, simplemente responde de manera natural y cálida, **sin usar herramientas**.

Siempre responde en español, de forma clara y amable. Si no sabes algo, dilo honestamente.
"""

def process_user_message(user_message: str, conversation_history: list = None):
    """
    Procesa un mensaje del usuario, manteniendo el historial de conversación.
    Devuelve (respuesta, historial_actualizado).
    """
    if conversation_history is None:
        conversation_history = []

    # Añadir mensaje del usuario al historial
    conversation_history.append({"role": "user", "content": user_message})

    # Llamar al modelo con herramientas
    response = ollama_client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *conversation_history
        ],
        tools=TOOLS,
        stream=False
    )

    assistant_message = response["message"]

    # Si el modelo solicitó una herramienta
    if assistant_message.get("tool_calls"):
        tool_calls = assistant_message["tool_calls"]
        # Ejecutar cada herramienta y agregar resultados al historial
        for tool_call in tool_calls:
            func_name = tool_call["function"]["name"]
            func_args = tool_call["function"]["arguments"]

            if func_name in FUNCTION_MAP:
                try:
                    result = FUNCTION_MAP[func_name](**func_args)
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as e:
                    result_str = json.dumps({"error": str(e)})
            else:
                result_str = json.dumps({"error": f"Función {func_name} no encontrada."})

            # Añadir al historial como mensaje de la herramienta
            conversation_history.append({
                "role": "tool",
                "content": result_str,
                "name": func_name
            })

        # Segunda llamada al modelo con los resultados de las herramientas
        final_response = ollama_client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *conversation_history
            ],
            stream=False
        )
        final_content = final_response["message"]["content"]
    else:
        final_content = assistant_message["content"]

    # Añadir respuesta del asistente al historial
    conversation_history.append({"role": "assistant", "content": final_content})
    return final_content, conversation_history