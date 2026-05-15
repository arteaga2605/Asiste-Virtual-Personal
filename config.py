# config.py
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:latest")
OLLAMA_TRADING_MODEL = os.getenv("OLLAMA_TRADING_MODEL", "deepseek-r1:8b")
OLLAMA_SPORTS_MODEL = os.getenv("OLLAMA_SPORTS_MODEL", "qwen3:8b")
OLLAMA_FAST_MODEL = os.getenv("OLLAMA_FAST_MODEL", "phi3:mini")
OLLAMA_CODE_MODEL = os.getenv("OLLAMA_CODE_MODEL", "codellama:latest")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

BUSINESS_DB_PATH = os.path.join(DATA_DIR, "business.db")
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

AVATAR_ENABLED = os.getenv("AVATAR_ENABLED", "True").lower() in ("true", "1", "yes")
AVATAR_IMAGE_PATH = os.path.join(BASE_DIR, "assets", "avatar.png")
THINKING_STATE_FILE = os.path.join(tempfile.gettempdir(), "asistente_thinking.txt")
ALERT_FILE = os.path.join(tempfile.gettempdir(), "asistente_alert.txt")
CELEBRATION_FILE = os.path.join(tempfile.gettempdir(), "asistente_celebration.txt")

COMMUNICATION_PORT = int(os.getenv("COMMUNICATION_PORT", "51234"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "20"))
SPORTS_REFRESH_INTERVAL = int(os.getenv("SPORTS_REFRESH_INTERVAL", str(45 * 60)))
STATUS_CHECK_INTERVAL = int(os.getenv("STATUS_CHECK_INTERVAL", "30"))
TASK_REMINDER_HOURS = int(os.getenv("TASK_REMINDER_HOURS", "24"))

# --------------- Trello ---------------
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY", "")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN", "")
TRELLO_BOARD_NAME = os.getenv("TRELLO_BOARD_NAME", "Crypto Predicciones")
TRELLO_LIST_PENDIENTES = os.getenv("TRELLO_LIST_PENDIENTES", "Pendientes")
TRELLO_LIST_GANANCIA = os.getenv("TRELLO_LIST_GANANCIA", "Ganancia")
TRELLO_LIST_PERDIDA = os.getenv("TRELLO_LIST_PERDIDA", "Perdida")

# Intervalo de evaluación de predicciones cripto (4 horas en segundos)
CRYPTO_EVALUATION_INTERVAL = int(os.getenv("CRYPTO_EVALUATION_INTERVAL", str(4 * 60 * 60)))