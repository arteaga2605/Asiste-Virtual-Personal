# tools/trello.py
import os
from trello import TrelloClient
from config import TRELLO_API_KEY, TRELLO_TOKEN

_client = None

def _get_client():
    global _client
    if _client is None:
        if not TRELLO_API_KEY or not TRELLO_TOKEN:
            raise Exception("TRELLO_API_KEY y TRELLO_TOKEN no están configurados.")
        _client = TrelloClient(api_key=TRELLO_API_KEY, token=TRELLO_TOKEN)
    return _client

def list_boards() -> list:
    """Devuelve todos los tableros del usuario."""
    try:
        client = _get_client()
        boards = client.list_boards()
        return [{"id": b.id, "name": b.name} for b in boards]
    except Exception as e:
        return [{"error": str(e)}]

def list_lists(board_name_or_id: str) -> list:
    """Devuelve las listas de un tablero (por nombre o ID)."""
    try:
        client = _get_client()
        boards = client.list_boards()
        board = None
        for b in boards:
            if b.id == board_name_or_id or b.name.lower() == board_name_or_id.lower():
                board = b
                break
        if not board:
            return [{"error": f"No se encontró el tablero '{board_name_or_id}'."}]
        lists = board.list_lists()
        return [{"id": l.id, "name": l.name, "board_name": board.name} for l in lists]
    except Exception as e:
        return [{"error": str(e)}]

def create_card(list_name_or_id: str, board_name_or_id: str, card_name: str, description: str = "") -> dict:
    """Crea una tarjeta en una lista de un tablero."""
    try:
        client = _get_client()
        boards = client.list_boards()
        board = None
        for b in boards:
            if b.id == board_name_or_id or b.name.lower() == board_name_or_id.lower():
                board = b
                break
        if not board:
            return {"error": f"No se encontró el tablero '{board_name_or_id}'."}

        lists = board.list_lists()
        target_list = None
        for l in lists:
            if l.id == list_name_or_id or l.name.lower() == list_name_or_id.lower():
                target_list = l
                break
        if not target_list:
            return {"error": f"No se encontró la lista '{list_name_or_id}'."}

        card = target_list.add_card(card_name, desc=description)
        return {"id": card.id, "name": card.name, "list": target_list.name, "board": board.name, "url": card.url}
    except Exception as e:
        return {"error": str(e)}

def list_cards(board_name_or_id: str, list_name_or_id: str = None) -> list:
    """Lista las tarjetas de un tablero (opcionalmente filtradas por lista)."""
    try:
        client = _get_client()
        boards = client.list_boards()
        board = None
        for b in boards:
            if b.id == board_name_or_id or b.name.lower() == board_name_or_id.lower():
                board = b
                break
        if not board:
            return [{"error": f"No se encontró el tablero '{board_name_or_id}'."}]

        if list_name_or_id:
            lists = board.list_lists()
            target_list = None
            for l in lists:
                if l.id == list_name_or_id or l.name.lower() == list_name_or_id.lower():
                    target_list = l
                    break
            if not target_list:
                return [{"error": f"No se encontró la lista '{list_name_or_id}'."}]
            cards = target_list.list_cards()
        else:
            cards = board.all_cards()

        return [{"id": c.id, "name": c.name, "description": c.description[:100] if c.description else "",
                 "list": getattr(c, 'list', None) and c.list.name, "url": c.url} for c in cards]
    except Exception as e:
        return [{"error": str(e)}]

def move_card(card_name_or_id: str, board_name_or_id: str, target_list_name_or_id: str) -> dict:
    """Mueve una tarjeta a otra lista."""
    try:
        client = _get_client()
        boards = client.list_boards()
        board = None
        for b in boards:
            if b.id == board_name_or_id or b.name.lower() == board_name_or_id.lower():
                board = b
                break
        if not board:
            return {"error": f"No se encontró el tablero '{board_name_or_id}'."}

        # Buscar la tarjeta
        all_cards = board.all_cards()
        card = None
        for c in all_cards:
            if c.id == card_name_or_id or c.name.lower() == card_name_or_id.lower():
                card = c
                break
        if not card:
            return {"error": f"No se encontró la tarjeta '{card_name_or_id}'."}

        # Buscar la lista destino
        lists = board.list_lists()
        target_list = None
        for l in lists:
            if l.id == target_list_name_or_id or l.name.lower() == target_list_name_or_id.lower():
                target_list = l
                break
        if not target_list:
            return {"error": f"No se encontró la lista '{target_list_name_or_id}'."}

        card.change_list(target_list.id)
        return {"id": card.id, "name": card.name, "new_list": target_list.name, "board": board.name}
    except Exception as e:
        return {"error": str(e)}

def add_comment(card_name_or_id: str, board_name_or_id: str, comment: str) -> dict:
    """Añade un comentario a una tarjeta."""
    try:
        client = _get_client()
        boards = client.list_boards()
        board = None
        for b in boards:
            if b.id == board_name_or_id or b.name.lower() == board_name_or_id.lower():
                board = b
                break
        if not board:
            return {"error": f"No se encontró el tablero '{board_name_or_id}'."}

        all_cards = board.all_cards()
        card = None
        for c in all_cards:
            if c.id == card_name_or_id or c.name.lower() == card_name_or_id.lower():
                card = c
                break
        if not card:
            return {"error": f"No se encontró la tarjeta '{card_name_or_id}'."}

        card.comment(comment)
        return {"id": card.id, "name": card.name, "comment": comment}
    except Exception as e:
        return {"error": str(e)}