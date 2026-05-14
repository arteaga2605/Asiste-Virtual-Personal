# agent.py
import ollama
from config import OLLAMA_MODEL, OLLAMA_HOST
import json

from tools.trading import (
    get_symbol_data, 
    calculate_indicator, 
    get_live_price, 
    start_binance_stream
)
from tools.business import (
    add_note, list_notes,
    add_task, list_tasks, update_task_status,
    add_contact, list_contacts,
    add_goal, list_goals, update_goal_progress
)
from tools.code_executor import execute_python_code
from tools.trello import (
    list_boards, list_lists, create_card,
    list_cards, move_card, add_comment
)

ollama_client = ollama.Client(host=OLLAMA_HOST)

TOOLS = [
    # ---------- Trading ----------
    {
        "type": "function",
        "function": {
            "name": "get_symbol_data",
            "description": "Obtiene datos históricos resumidos de un símbolo (ej. AAPL). Necesita archivo CSV local.",
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
    # Nuevas herramientas de metas
    {
        "type": "function",
        "function": {
            "name": "add_goal",
            "description": "Añade una meta empresarial (ej. 'aumentar productividad 20%').",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Descripción de la meta."},
                    "target_value": {"type": "number", "description": "Valor objetivo (por defecto 100)."},
                    "unit": {"type": "string", "description": "Unidad (%, unidades, etc.), por defecto '%'."}
                },
                "required": ["description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_goals",
            "description": "Lista las metas activas.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_goal_progress",
            "description": "Actualiza el progreso de una meta (valor actual).",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer"},
                    "current_value": {"type": "number"}
                },
                "required": ["goal_id", "current_value"]
            }
        }
    },
    # ---------- Código ----------
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Ejecuta código Python de forma segura y devuelve la salida.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Código Python a ejecutar"}
                },
                "required": ["code"]
            }
        }
    },
    # ---------- Trello ----------
    {
        "type": "function",
        "function": {
            "name": "list_boards",
            "description": "Lista todos los tableros de Trello del usuario.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_lists",
            "description": "Lista las listas de un tablero de Trello (por nombre o ID).",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_name_or_id": {"type": "string", "description": "Nombre o ID del tablero"}
                },
                "required": ["board_name_or_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_card",
            "description": "Crea una tarjeta en una lista de Trello.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list_name_or_id": {"type": "string", "description": "Nombre o ID de la lista donde crear la tarjeta"},
                    "board_name_or_id": {"type": "string", "description": "Nombre o ID del tablero que contiene la lista"},
                    "card_name": {"type": "string", "description": "Nombre de la tarjeta a crear"},
                    "description": {"type": "string", "description": "Descripción de la tarjeta (opcional)"}
                },
                "required": ["list_name_or_id", "board_name_or_id", "card_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_cards",
            "description": "Lista las tarjetas de un tablero (opcionalmente filtradas por lista).",
            "parameters": {
                "type": "object",
                "properties": {
                    "board_name_or_id": {"type": "string", "description": "Nombre o ID del tablero"},
                    "list_name_or_id": {"type": "string", "description": "Nombre o ID de la lista (opcional)"}
                },
                "required": ["board_name_or_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_card",
            "description": "Mueve una tarjeta de Trello a otra lista.",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_name_or_id": {"type": "string", "description": "Nombre o ID de la tarjeta"},
                    "board_name_or_id": {"type": "string", "description": "Nombre o ID del tablero"},
                    "target_list_name_or_id": {"type": "string", "description": "Nombre o ID de la lista destino"}
                },
                "required": ["card_name_or_id", "board_name_or_id", "target_list_name_or_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_comment",
            "description": "Añade un comentario a una tarjeta de Trello.",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_name_or_id": {"type": "string", "description": "Nombre o ID de la tarjeta"},
                    "board_name_or_id": {"type": "string", "description": "Nombre o ID del tablero"},
                    "comment": {"type": "string", "description": "Comentario a añadir"}
                },
                "required": ["card_name_or_id", "board_name_or_id", "comment"]
            }
        }
    }
]

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
    "add_goal": add_goal,
    "list_goals": list_goals,
    "update_goal_progress": update_goal_progress,
    "list_boards": list_boards,
    "list_lists": list_lists,
    "create_card": create_card,
    "list_cards": list_cards,
    "move_card": move_card,
    "add_comment": add_comment,
}

SYSTEM_PROMPT = """
Eres un asistente virtual personal, amigable y servicial. Tu nombre es "Aria". Puedes conversar de forma natural y también ayudar en tareas específicas.

Áreas de especialidad:
- Trading y análisis de mercado (interpretar indicadores, datos históricos y precios en vivo de Binance).
- Gestión de empresa (notas, tareas, contactos, metas de productividad).
- Programación Python (escribir, explicar y ejecutar código de forma segura).
- Gestión de proyectos en Trello (listar tableros, crear tarjetas, mover tareas).

Tienes acceso a herramientas para realizar acciones concretas. Úsalas solo cuando sea necesario. Para saludos, preguntas generales o conversación casual, simplemente responde de manera natural y cálida, **sin usar herramientas**.

Siempre responde en español, de forma clara y amable. Si no sabes algo, dilo honestamente.
"""

def process_user_message(user_message: str, conversation_history: list = None):
    if conversation_history is None:
        conversation_history = []

    conversation_history.append({"role": "user", "content": user_message})

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

    if assistant_message.get("tool_calls"):
        tool_calls = assistant_message["tool_calls"]
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

            conversation_history.append({
                "role": "tool",
                "content": result_str,
                "name": func_name
            })

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

    conversation_history.append({"role": "assistant", "content": final_content})
    return final_content, conversation_history