# avatar.py
import sys
import os
import struct
import random
import socket
import threading
import json
import math
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout,
    QTextEdit, QScrollArea, QMenu, QAction, QSystemTrayIcon, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal, QPropertyAnimation
from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QBrush, QIcon
from config import (
    AVATAR_IMAGE_PATH, THINKING_STATE_FILE, ALERT_FILE, CELEBRATION_FILE,
    COMMUNICATION_PORT, STATUS_CHECK_INTERVAL
)
from tools.trading import SELECTED_CRYPTO


class ToastNotification(QWidget):
    """Notificación emergente que aparece en la esquina inferior derecha y se desvanece."""
    def __init__(self, message, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        label = QLabel(message)
        label.setStyleSheet("""
            background-color: #333;
            color: white;
            padding: 12px;
            border-radius: 10px;
            font-size: 14px;
        """)
        label.setWordWrap(True)
        layout = QVBoxLayout()
        layout.addWidget(label)
        self.setLayout(layout)

        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 20, screen.bottom() - self.height() - 20)

        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(0.9)
        self.animation.finished.connect(self.start_timer)
        self.animation.start()

    def start_timer(self):
        QTimer.singleShot(5000, self.fade_out)

    def fade_out(self):
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(500)
        self.animation.setStartValue(0.9)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()


class ExhaleParticle:
    """Partícula de humo exhalado."""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.opacity = 180
        self.size = random.randint(4, 8)
        self.vx = random.uniform(-0.5, 0.5)
        self.vy = random.uniform(-1.5, -0.5)
        self.life = 30

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.size += 0.2
        self.opacity -= 6
        self.life -= 1
        return self.life > 0


class FloatingAvatar(QWidget):
    response_ready = pyqtSignal(str)
    thinking_changed = pyqtSignal(bool)
    status_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.setMinimumSize(400, 300)
        self.avatar_width = 150
        self.chat_area_width = 320
        self.resize(self.avatar_width + self.chat_area_width, 380)

        self.use_custom_image = False
        if os.path.exists(AVATAR_IMAGE_PATH):
            loaded = QPixmap(AVATAR_IMAGE_PATH)
            if not loaded.isNull():
                self.pixmap = loaded.scaledToWidth(self.avatar_width, Qt.SmoothTransformation)
                self.use_custom_image = True
                self.avatar_height_body = self.pixmap.height()
        else:
            self.pixmap = None

        # Panel de estado
        self.status_panel = QWidget(self)
        self.status_panel.setStyleSheet("background: transparent;")
        status_layout = QHBoxLayout(self.status_panel)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(15)
        status_layout.addStretch()

        self.status_binance = QLabel("⬤")
        self.status_binance.setToolTip("Binance WebSocket")
        self.status_espn = QLabel("⬤")
        self.status_espn.setToolTip("ESPN API")
        self.status_ollama = QLabel("⬤")
        self.status_ollama.setToolTip("Ollama")
        for lbl in (self.status_binance, self.status_espn, self.status_ollama):
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet("color: gray;")
            status_layout.addWidget(lbl)
        status_layout.addStretch()

        self.status_updated.connect(self._update_status_indicators)

        # Zona de chat
        self.chat_widget = QWidget(self)
        self.chat_widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self.chat_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.response_scroll = QScrollArea()
        self.response_scroll.setWidgetResizable(True)
        self.response_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.response_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.response_bubble = QTextEdit()
        self.response_bubble.setReadOnly(True)
        self.response_bubble.setStyleSheet("""
            QTextEdit {
                background: white;
                border: 2px solid #aaa;
                border-radius: 15px;
                padding: 10px;
                font-size: 14px;
                color: black;
            }
        """)
        self.response_bubble.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.response_scroll.setWidget(self.response_bubble)
        self.response_scroll.hide()
        layout.addWidget(self.response_scroll, stretch=1)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Escribe aquí tu pregunta...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 2px solid #aaa;
                border-radius: 10px;
                padding: 8px;
                font-size: 14px;
                background: white;
            }
        """)
        self.input_field.returnPressed.connect(self.send_question)
        self.input_field.installEventFilter(self)
        layout.addWidget(self.input_field)

        self.bulb_label = QLabel("💡", self)
        self.bulb_label.setFont(QFont("Segoe UI", 24))
        self.bulb_label.setAlignment(Qt.AlignCenter)
        self.bulb_label.setStyleSheet("background: transparent;")
        self.bulb_label.setFixedSize(50, 50)
        self.bulb_label.hide()

        self.is_thinking = False
        self.eye_visible = True
        self.eyes_red = False
        self.movement_enabled = True
        self.user_interacting = False
        self.resizing = False
        self.resize_edge = None
        self.resize_start_pos = None
        self.resize_start_geom = None

        self.smoke_progress = 0.0
        self.target_smoke_progress = 0.0
        self.smoke_timer = QTimer(self)
        self.smoke_timer.timeout.connect(self._animate_smoke)

        self.puff_timer = QTimer(self)
        self.puff_timer.timeout.connect(self.start_puff_sequence)
        self.puff_sequence_active = False

        self.exhale_particles = []

        # Estado de celebración
        self.celebration = None  # 'success', 'fail', 'mixed'
        self.celebration_timer = QTimer(self)
        self.celebration_timer.timeout.connect(self._reset_celebration)

        self.thinking_changed.connect(self._on_thinking_changed)
        self.response_ready.connect(self._on_response_ready)

        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.blink)
        self.schedule_next_blink()

        self.target_pos = None
        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self.step_towards_target)
        QTimer.singleShot(2000, self.pick_new_destination)
        self.wander_timer = QTimer(self)
        self.wander_timer.timeout.connect(self.pick_new_destination)
        self.wander_timer.start(10000)

        self.drag_pos = QPoint()

        self.tray_icon = QSystemTrayIcon(self)
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setBrush(QColor(255, 180, 50))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, 28, 28)
        p.end()
        self.tray_icon.setIcon(QIcon(pix))
        self.tray_icon.setToolTip("Asistente Virtual")
        tray_menu = QMenu()
        mostrar_action = tray_menu.addAction("Mostrar")
        mostrar_action.triggered.connect(self.show_from_tray)
        ocultar_action = tray_menu.addAction("Ocultar")
        ocultar_action.triggered.connect(self.hide_to_tray)
        tray_menu.addSeparator()
        salir_action = tray_menu.addAction("Salir")
        salir_action.triggered.connect(QApplication.quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

        self.alert_timer = QTimer(self)
        self.alert_timer.timeout.connect(self.check_auto_alerts)
        self.alert_timer.start(10000)
        self.last_alert_msg = ""

        # Timer para leer archivo de celebración
        self.celebration_check_timer = QTimer(self)
        self.celebration_check_timer.timeout.connect(self.check_celebration)
        self.celebration_check_timer.start(5000)  # cada 5 segundos

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.request_status)
        self.status_timer.start(STATUS_CHECK_INTERVAL * 1000)
        self.request_status()

        self.show()
        self.raise_()
        self.update_geometry()

    # ------------------------------------------------------------
    # Redimensionamiento manual (sin cambios)
    # ------------------------------------------------------------
    def update_geometry(self):
        w = self.width()
        h = self.height()
        self.status_panel.setGeometry(self.avatar_width, 5, w - self.avatar_width - 10, 25)
        self.chat_widget.setGeometry(self.avatar_width, 35, w - self.avatar_width - 15, h - 45)

    def resizeEvent(self, event):
        self.update_geometry()
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edge = self._detect_edge(event.pos())
            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.resize_start_pos = event.globalPos()
                self.resize_start_geom = self.geometry()
                event.accept()
                return
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.resizing:
            delta = event.globalPos() - self.resize_start_pos
            new_geom = self.resize_start_geom
            if 'e' in self.resize_edge:
                new_geom.setRight(new_geom.right() + delta.x())
            if 'w' in self.resize_edge:
                new_geom.setLeft(new_geom.left() + delta.x())
            if 's' in self.resize_edge:
                new_geom.setBottom(new_geom.bottom() + delta.y())
            if 'n' in self.resize_edge:
                new_geom.setTop(new_geom.top() + delta.y())
            if new_geom.width() < self.minimumWidth():
                new_geom.setWidth(self.minimumWidth())
            if new_geom.height() < self.minimumHeight():
                new_geom.setHeight(self.minimumHeight())
            self.setGeometry(new_geom)
            event.accept()
            return
        elif event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_pos)
            event.accept()
        else:
            edge = self._detect_edge(event.pos())
            if edge == 'nw' or edge == 'se':
                self.setCursor(Qt.SizeFDiagCursor)
            elif edge == 'ne' or edge == 'sw':
                self.setCursor(Qt.SizeBDiagCursor)
            elif edge in ('n', 's'):
                self.setCursor(Qt.SizeVerCursor)
            elif edge in ('e', 'w'):
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self.resizing:
            self.resizing = False
            self.resize_edge = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _detect_edge(self, pos):
        margin = 8
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        edges = ''
        if x <= margin:
            edges += 'w'
        elif x >= w - margin:
            edges += 'e'
        if y <= margin:
            edges += 'n'
        elif y >= h - margin:
            edges += 's'
        return edges if edges else None

    # ------------------------------------------------------------
    # Toast de alertas (sin cambios)
    # ------------------------------------------------------------
    def check_auto_alerts(self):
        try:
            if os.path.exists(ALERT_FILE):
                with open(ALERT_FILE, "r", encoding="utf-8") as f:
                    msg = f.read().strip()
                if msg and msg != self.last_alert_msg:
                    self.last_alert_msg = msg
                    toast = ToastNotification(f"🔔 {msg}")
                    toast.show()
                    os.remove(ALERT_FILE)
        except Exception:
            pass

    # ------------------------------------------------------------
    # Estado del sistema (sin cambios)
    # ------------------------------------------------------------
    def request_status(self):
        def _ask():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect(("localhost", COMMUNICATION_PORT))
                msg = "__STATUS__"
                sock.sendall(struct.pack("!I", len(msg)) + msg.encode("utf-8"))
                raw_len = sock.recv(4)
                if len(raw_len) == 4:
                    (resp_len,) = struct.unpack("!I", raw_len)
                    data = sock.recv(resp_len).decode("utf-8")
                    status = json.loads(data)
                    self.status_updated.emit(status)
                sock.close()
            except Exception:
                self.status_updated.emit({"ollama": False, "binance": False, "espn": False})
        threading.Thread(target=_ask, daemon=True).start()

    def _update_status_indicators(self, status):
        def color(ok):
            return "green" if ok else "red"
        self.status_binance.setStyleSheet(f"color: {color(status.get('binance', False))};")
        self.status_espn.setStyleSheet(f"color: {color(status.get('espn', False))};")
        self.status_ollama.setStyleSheet(f"color: {color(status.get('ollama', False))};")

    # ------------------------------------------------------------
    # Parpadeo y ojos rojos (sin cambios)
    # ------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj == self.input_field:
            if event.type() == event.FocusIn:
                self.user_interacting = True
                self.move_timer.stop()
            elif event.type() == event.FocusOut:
                self.user_interacting = False
                if self.movement_enabled:
                    self.pick_new_destination()
        return super().eventFilter(obj, event)

    def schedule_next_blink(self):
        self.blink_timer.stop()
        interval = random.randint(2000, 4000)
        self.blink_timer.start(interval)

    def blink(self):
        self.eye_visible = False
        self.update()
        QTimer.singleShot(150, self.open_eyes)
        self.schedule_next_blink()

    def open_eyes(self):
        self.eye_visible = True
        self.update()

    # ------------------------------------------------------------
    # Movimiento (sin cambios)
    # ------------------------------------------------------------
    def pick_new_destination(self):
        if not self.movement_enabled or self.user_interacting or self.resizing:
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        target_x = random.randint(0, max(0, geom.width() - self.width()))
        target_y = random.randint(0, max(0, geom.height() - self.height()))
        self.target_pos = QPoint(target_x, target_y)
        if not self.move_timer.isActive():
            self.move_timer.start(30)

    def step_towards_target(self):
        if self.target_pos is None or not self.movement_enabled:
            self.move_timer.stop()
            return
        current = self.pos()
        dx = self.target_pos.x() - current.x()
        dy = self.target_pos.y() - current.y()
        distance = (dx**2 + dy**2) ** 0.5
        if distance < 5:
            self.move(self.target_pos)
            self.target_pos = None
            self.move_timer.stop()
            return
        step_size = 4 / distance
        new_x = int(current.x() + dx * step_size)
        new_y = int(current.y() + dy * step_size)
        self.move(new_x, new_y)

    # ------------------------------------------------------------
    # Animación del cigarro y caladas (sin cambios)
    # ------------------------------------------------------------
    def _animate_smoke(self):
        step = 0.05
        if self.target_smoke_progress > self.smoke_progress:
            self.smoke_progress = min(self.smoke_progress + step, self.target_smoke_progress)
            self.update()
        elif self.target_smoke_progress < self.smoke_progress:
            self.smoke_progress = max(self.smoke_progress - step, self.target_smoke_progress)
            self.update()
        for p in self.exhale_particles[:]:
            if not p.update():
                self.exhale_particles.remove(p)
        if self.smoke_progress == self.target_smoke_progress and not self.exhale_particles:
            if not self.is_thinking and not self.puff_sequence_active and self.smoke_progress == 0.0:
                self.smoke_timer.stop()

    def start_puff_sequence(self):
        if not self.is_thinking or self.puff_sequence_active:
            return
        self.puff_sequence_active = True
        self.target_smoke_progress = 1.0
        if not self.smoke_timer.isActive():
            self.smoke_timer.start(30)
        QTimer.singleShot(1500, self._lower_cigar)

    def _lower_cigar(self):
        self.target_smoke_progress = 0.0
        mouth_x = self.avatar_width // 2 - 5
        mouth_y = 110 + 25
        for _ in range(8):
            self.exhale_particles.append(ExhaleParticle(mouth_x + random.randint(-5, 5), mouth_y))
        QTimer.singleShot(500, self._end_puff_sequence)

    def _end_puff_sequence(self):
        self.puff_sequence_active = False

    def _start_smoke_timer_if_needed(self):
        if not self.smoke_timer.isActive():
            self.smoke_timer.start(30)

    # ------------------------------------------------------------
    # Comunicación con el servidor (sin cambios)
    # ------------------------------------------------------------
    def send_question(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self.start_query(text)

    def start_query(self, question: str):
        self.set_thinking(True)
        threading.Thread(target=self.query_server, args=(question,), daemon=True).start()

    def query_server(self, question):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1200)
            sock.connect(("localhost", COMMUNICATION_PORT))
            msg_bytes = question.encode("utf-8")
            sock.sendall(struct.pack("!I", len(msg_bytes)) + msg_bytes)
            raw_len = sock.recv(4)
            if len(raw_len) < 4:
                raise ConnectionError("No se recibió la longitud de la respuesta")
            (resp_len,) = struct.unpack("!I", raw_len)
            response_data = b""
            while len(response_data) < resp_len:
                chunk = sock.recv(resp_len - len(response_data))
                if not chunk:
                    raise ConnectionError("Conexión cerrada antes de recibir toda la respuesta")
                response_data += chunk
            answer = response_data.decode("utf-8")
        except socket.timeout:
            answer = "El servidor sigue procesando la respuesta (puede tardar varios minutos)."
        except Exception as e:
            answer = f"Error de conexión: {e}"
        finally:
            if sock:
                sock.close()
        self.thinking_changed.emit(False)
        self.response_ready.emit(answer)

    def _on_thinking_changed(self, state):
        self.is_thinking = state
        self.eyes_red = state
        self.bulb_label.setVisible(state)
        if state:
            self._start_smoke_timer_if_needed()
            self.puff_timer.start(5000)
            self.start_puff_sequence()
        else:
            self.puff_timer.stop()
            self.target_smoke_progress = 0.0
            self._start_smoke_timer_if_needed()
            self.puff_sequence_active = False
        self.update()

    def _on_response_ready(self, text):
        self.response_bubble.setPlainText(text)
        self.response_scroll.show()

    def set_thinking(self, state):
        self.is_thinking = state
        self.eyes_red = state
        self.bulb_label.setVisible(state)
        if state:
            self._start_smoke_timer_if_needed()
            self.puff_timer.start(5000)
            self.start_puff_sequence()
        else:
            self.puff_timer.stop()
            self.target_smoke_progress = 0.0
            self._start_smoke_timer_if_needed()
            self.puff_sequence_active = False
        self.update()

    def update_bulb_position(self):
        cx = self.avatar_width // 2
        self.bulb_label.move(cx - self.bulb_label.width()//2, 30)

    # ------------------------------------------------------------
    # CELEBRACIÓN (lectura del archivo y animación)
    # ------------------------------------------------------------
    def check_celebration(self):
        try:
            if os.path.exists(CELEBRATION_FILE):
                with open(CELEBRATION_FILE, "r", encoding="utf-8") as f:
                    tipo = f.read().strip()
                if tipo and tipo != self.celebration:
                    self.celebration = tipo
                    self.celebration_timer.start(10000)  # 10 segundos
                    self.update()
                # Eliminar archivo para no repetir
                os.remove(CELEBRATION_FILE)
        except Exception:
            pass

    def _reset_celebration(self):
        self.celebration = None
        self.celebration_timer.stop()
        self.update()

    # ------------------------------------------------------------
    # PINTADO DE TOALLIN (South Park) – con colores de celebración
    # ------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.avatar_width // 2
        cy = 110

        # Color base del cuerpo según celebración
        if self.celebration == 'success':
            body_color = QColor(100, 220, 100)  # verde
        elif self.celebration == 'fail':
            body_color = QColor(220, 100, 100)  # rojo
        elif self.celebration == 'mixed':
            body_color = QColor(255, 165, 0)   # naranja
        else:
            body_color = QColor(255, 255, 255)  # blanco normal

        if self.use_custom_image and self.pixmap:
            x = (self.avatar_width - self.pixmap.width()) // 2
            y = cy - self.pixmap.height()//2
            painter.drawPixmap(x, y, self.pixmap)
        else:
            toalla_w = 70
            toalla_h = 90
            painter.setBrush(body_color)
            painter.setPen(QPen(QColor(180, 180, 180), 2))
            painter.drawRoundedRect(cx - toalla_w//2, cy - toalla_h//2, toalla_w, toalla_h, 8, 8)

            # Dobleces
            pen_fold = QPen(QColor(220, 220, 220), 1)
            painter.setPen(pen_fold)
            for y_fold in range(cy - 30, cy + 30, 15):
                painter.drawLine(cx - 30, y_fold, cx + 30, y_fold)

            # Brazos y cigarro (sin cambios)
            painter.setPen(QPen(QColor(139, 90, 43), 4, Qt.SolidLine, Qt.RoundCap))
            shoulder_x = cx - 38
            shoulder_y = cy - 20
            hand_down_x = cx - 60
            hand_down_y = cy + 5
            mouth_x = cx - 8
            mouth_y = cy + 25
            current_hand_x = int(hand_down_x + (mouth_x - hand_down_x) * self.smoke_progress)
            current_hand_y = int(hand_down_y + (mouth_y - hand_down_y) * self.smoke_progress)
            painter.drawLine(shoulder_x, shoulder_y, current_hand_x, current_hand_y)
            if self.smoke_progress > 0.1:
                cigar_angle = 30
                cigar_length = 20
                rad = math.radians(cigar_angle)
                cigar_end_x = current_hand_x + int(cigar_length * math.cos(rad))
                cigar_end_y = current_hand_y - int(cigar_length * math.sin(rad))
                painter.setPen(QPen(QColor(200, 200, 200), 4, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(current_hand_x, current_hand_y, cigar_end_x, cigar_end_y)
                painter.setPen(QPen(QColor(255, 100, 0), 4, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(cigar_end_x - 4, cigar_end_y + 1, cigar_end_x, cigar_end_y)
                if self.smoke_progress > 0.5:
                    painter.setBrush(QColor(200, 200, 200, 100))
                    painter.setPen(Qt.NoPen)
                    for offset in [(8, -5), (12, -10), (6, -14)]:
                        px = cigar_end_x + offset[0] + random.randint(-2, 2)
                        py = cigar_end_y + offset[1] + random.randint(-2, 2)
                        painter.drawEllipse(px, py, 4, 4)

            # Brazo derecho y piernas
            painter.setPen(QPen(QColor(139, 90, 43), 4, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(cx + 38, cy - 20, cx + 60, cy + 5)
            painter.drawLine(cx + 60, cy + 5, cx + 52, cy + 15)
            painter.drawLine(cx - 10, cy + 45, cx - 15, cy + 70)
            painter.drawLine(cx + 10, cy + 45, cx + 15, cy + 70)

            # Ojos
            eye_y = cy - 20
            eye_spacing = 15
            if self.eye_visible:
                eye_color = QColor(255, 60, 60) if self.eyes_red else Qt.white
                painter.setBrush(eye_color)
                painter.setPen(QPen(Qt.black, 3))
                painter.drawEllipse(cx - eye_spacing - 12, eye_y - 14, 26, 26)
                painter.drawEllipse(cx + eye_spacing - 12, eye_y - 14, 26, 26)
                painter.setBrush(Qt.black)
                painter.drawEllipse(cx - eye_spacing - 3, eye_y - 5, 9, 9)
                painter.drawEllipse(cx + eye_spacing - 3, eye_y - 5, 9, 9)
            else:
                painter.setPen(QPen(Qt.black, 3))
                painter.drawLine(cx - eye_spacing - 14, eye_y, cx - eye_spacing + 4, eye_y)
                painter.drawLine(cx + eye_spacing - 4, eye_y, cx + eye_spacing + 14, eye_y)

            # Boca según celebración
            mouth_y_line = cy + 25
            if self.celebration == 'success':
                # Sonrisa amplia
                painter.setPen(QPen(Qt.black, 2))
                painter.drawArc(cx - 8, mouth_y_line - 4, 16, 12, 0, -180 * 16)
            elif self.celebration == 'fail':
                # Fruncido
                painter.setPen(QPen(Qt.black, 2))
                painter.drawArc(cx - 8, mouth_y_line + 2, 16, 10, 0, 180 * 16)
            elif self.celebration == 'mixed':
                painter.setPen(QPen(Qt.black, 2))
                painter.drawLine(cx - 5, mouth_y_line, cx + 5, mouth_y_line)
            else:
                if self.is_thinking and self.smoke_progress > 0.8:
                    painter.setBrush(QColor(0, 0, 0))
                    painter.setPen(QPen(Qt.black, 1))
                    painter.drawEllipse(cx - 3, mouth_y_line - 2, 6, 6)
                else:
                    painter.setPen(QPen(Qt.black, 2))
                    painter.drawLine(cx - 5, mouth_y_line, cx + 5, mouth_y_line)

            # Partículas de exhalación
            painter.setBrush(QColor(150, 150, 150, 120))
            painter.setPen(Qt.NoPen)
            for p in self.exhale_particles:
                painter.setOpacity(p.opacity / 255.0)
                painter.drawEllipse(int(p.x), int(p.y), int(p.size), int(p.size))

        self.update_bulb_position()

    # ------------------------------------------------------------
    # Menú contextual (con Trello y demás opciones)
    # ------------------------------------------------------------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self.movement_enabled:
            menu.addAction("🛑 No caminar").triggered.connect(self.toggle_movement)
        else:
            menu.addAction("🚶 Caminar").triggered.connect(self.toggle_movement)

        crypto_menu = QMenu("₿ Criptomonedas", self)
        for sym in SELECTED_CRYPTO:
            name = sym.replace("USDT", "")
            crypto_menu.addAction(f"₿ {name}").triggered.connect(lambda checked, s=sym: self.show_crypto_analysis(s))
        crypto_menu.addSeparator()
        crypto_menu.addAction("📊 Todas las criptos").triggered.connect(lambda: self.show_crypto_analysis("ALL"))
        menu.addMenu(crypto_menu)

        menu.addAction("📰 Noticias del día").triggered.connect(self.show_crypto_gems)

        sports_menu = QMenu("🏈 Deporte", self)
        sports_menu.addAction("Todos los deportes").triggered.connect(lambda: self.show_sports_analysis(None))
        sports_menu.addAction("Solo fútbol").triggered.connect(lambda: self.show_sports_analysis("soccer"))
        sports_menu.addAction("Solo baloncesto (NBA)").triggered.connect(lambda: self.show_sports_analysis("basketball"))
        sports_menu.addAction("Solo fútbol americano (NFL)").triggered.connect(lambda: self.show_sports_analysis("football"))
        sports_menu.addAction("Solo béisbol (MLB)").triggered.connect(lambda: self.show_sports_analysis("baseball"))
        sports_menu.addAction("Solo hockey (NHL)").triggered.connect(lambda: self.show_sports_analysis("hockey"))
        menu.addMenu(sports_menu)

        trello_menu = QMenu("📋 Trello", self)
        trello_menu.addAction("Listar tableros").triggered.connect(self.show_trello_boards)
        trello_menu.addAction("Listar listas").triggered.connect(self.show_trello_lists)
        trello_menu.addAction("Listar tarjetas").triggered.connect(self.show_trello_cards)
        trello_menu.addAction("Crear tarjeta").triggered.connect(self.show_trello_create_card)
        menu.addMenu(trello_menu)

        menu.addAction("📊 Reporte").triggered.connect(self.show_report)
        menu.addSeparator()
        menu.addAction("💡 Ideas de ingresos").triggered.connect(self.show_income_ideas)
        menu.addSeparator()
        menu.addAction("🎯 Metas").triggered.connect(self.show_goals)
        menu.addAction("📄 Informe Semanal").triggered.connect(self.show_weekly)
        menu.addSeparator()
        menu.addAction("📜 Historial").triggered.connect(self.show_history)
        menu.addAction("👻 Ocultar avatar").triggered.connect(self.hide_to_tray)
        menu.addAction("⬆️ Expandir burbuja").triggered.connect(self.expand_bubble)
        menu.addAction("❌ Esconder burbuja").triggered.connect(self.hide_bubble)
        menu.exec_(event.globalPos())

    def toggle_movement(self):
        self.movement_enabled = not self.movement_enabled
        if self.movement_enabled:
            self.pick_new_destination()
        else:
            self.move_timer.stop()
            self.target_pos = None

    def show_crypto_analysis(self, symbol):
        self.start_query(f"__CRYPTO__:{symbol}")
    def show_crypto_gems(self):
        self.start_query("__NEWS__")
    def show_sports_analysis(self, category=None):
        if category:
            self.start_query(f"__SPORTS__:{category}")
        else:
            self.start_query("__SPORTS__")
    def show_report(self):
        self.start_query("__REPORT__")
    def show_income_ideas(self):
        self.start_query("__INCOME_IDEAS__")
    def show_history(self):
        self.start_query("__HISTORY__")
    def show_goals(self):
        self.start_query("__GOALS__")
    def show_weekly(self):
        self.start_query("__WEEKLY__")

    def show_trello_boards(self):
        self.start_query("__TRELLO__:list_boards")
    def show_trello_lists(self):
        self.input_field.setText("Muéstrame las listas del tablero ")
        self.input_field.setFocus()
    def show_trello_cards(self):
        self.input_field.setText("Muéstrame las tarjetas del tablero ")
        self.input_field.setFocus()
    def show_trello_create_card(self):
        self.input_field.setText("Crea una tarjeta en Trello llamada ")
        self.input_field.setFocus()

    def hide_to_tray(self):
        self.hide()
        self.tray_icon.show()

    def show_from_tray(self):
        self.show()
        self.raise_()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_from_tray()

    def expand_bubble(self):
        new_h = self.height() + 100
        self.resize(self.width(), new_h)
        self.update_geometry()
        self.response_scroll.show()

    def hide_bubble(self):
        self.response_scroll.hide()

    def closeEvent(self, event):
        event.ignore()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    avatar = FloatingAvatar()
    sys.exit(app.exec_())