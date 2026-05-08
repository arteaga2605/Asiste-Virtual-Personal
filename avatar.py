# avatar.py
import sys
import os
import struct
import random
import socket
import threading
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout,
    QTextEdit, QScrollArea, QMenu, QAction, QSystemTrayIcon
)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QBrush, QIcon
from config import AVATAR_IMAGE_PATH, THINKING_STATE_FILE, ALERT_FILE, COMMUNICATION_PORT


class FloatingAvatar(QWidget):
    response_ready = pyqtSignal(str)
    thinking_changed = pyqtSignal(bool)

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

        self.avatar_width = 150
        self.avatar_height_body = 180
        self.chat_area_width = 320
        self.total_width = self.avatar_width + self.chat_area_width
        self.total_height = 350
        self.setFixedSize(self.total_width, self.total_height)

        self.use_custom_image = False
        if os.path.exists(AVATAR_IMAGE_PATH):
            loaded = QPixmap(AVATAR_IMAGE_PATH)
            if not loaded.isNull():
                self.pixmap = loaded.scaledToWidth(self.avatar_width, Qt.SmoothTransformation)
                self.use_custom_image = True
                self.avatar_height_body = self.pixmap.height()
        else:
            self.pixmap = None

        # Zona de chat
        self.chat_widget = QWidget(self)
        self.chat_widget.setGeometry(self.avatar_width, 10, self.chat_area_width - 20, self.total_height - 20)
        self.chat_widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self.chat_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Burbuja de respuesta
        self.response_scroll = QScrollArea()
        self.response_scroll.setWidgetResizable(True)
        self.response_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.response_scroll.setMaximumHeight(200)

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

        # Campo de entrada
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

        # Bombilla
        self.bulb_label = QLabel("💡", self)
        self.bulb_label.setFont(QFont("Segoe UI", 24))
        self.bulb_label.setAlignment(Qt.AlignCenter)
        self.bulb_label.setStyleSheet("background: transparent;")
        self.bulb_label.setFixedSize(50, 50)
        self.bulb_label.hide()

        self.is_thinking = False
        self.eye_visible = True
        self.movement_enabled = True
        self.user_interacting = False

        self.thinking_changed.connect(self._on_thinking_changed)
        self.response_ready.connect(self._on_response_ready)

        # Parpadeo
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.blink)
        self.schedule_next_blink()

        # Movimiento
        self.target_pos = None
        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self.step_towards_target)
        QTimer.singleShot(2000, self.pick_new_destination)
        self.wander_timer = QTimer(self)
        self.wander_timer.timeout.connect(self.pick_new_destination)
        self.wander_timer.start(10000)

        self.drag_pos = QPoint()

        # Icono en bandeja
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

        # Timer para leer alertas automáticas
        self.alert_timer = QTimer(self)
        self.alert_timer.timeout.connect(self.check_auto_alerts)
        self.alert_timer.start(10000)
        self.last_alert_msg = ""

        self.show()
        self.raise_()

    def check_auto_alerts(self):
        try:
            if os.path.exists(ALERT_FILE):
                with open(ALERT_FILE, "r", encoding="utf-8") as f:
                    msg = f.read().strip()
                if msg and msg != self.last_alert_msg:
                    self.last_alert_msg = msg
                    self.response_bubble.setPlainText(f"🔔 **Alerta automática:**\n{msg}")
                    self.response_scroll.show()
                    os.remove(ALERT_FILE)
        except Exception:
            pass

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

    def pick_new_destination(self):
        if not self.movement_enabled or self.user_interacting:
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
        self.bulb_label.setVisible(state)
        self.update()

    def _on_response_ready(self, text):
        self.response_bubble.setPlainText(text)
        self.response_scroll.show()

    def set_thinking(self, state):
        self.is_thinking = state
        self.bulb_label.setVisible(state)
        self.update()

    def update_bulb_position(self):
        cx = self.avatar_width // 2
        head_top = 90 - 45
        self.bulb_label.move(cx - self.bulb_label.width()//2, head_top - 40)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.avatar_width // 2
        cy = 90
        if self.use_custom_image and self.pixmap:
            x = (self.avatar_width - self.pixmap.width()) // 2
            y = cy - self.pixmap.height()//2
            painter.drawPixmap(x, y, self.pixmap)
        else:
            painter.setPen(QPen(QColor(100, 70, 30), 5, Qt.SolidLine, Qt.RoundCap))
            shoulder_y = cy - 5
            painter.drawLine(cx - 35, shoulder_y, cx - 60, shoulder_y + 20)
            painter.drawLine(cx - 60, shoulder_y + 20, cx - 50, shoulder_y + 30)
            painter.drawLine(cx + 35, shoulder_y, cx + 60, shoulder_y + 20)
            painter.drawLine(cx + 60, shoulder_y + 20, cx + 50, shoulder_y + 30)
            r = 45
            painter.setBrush(QColor(255, 220, 150))
            painter.setPen(QPen(QColor(100, 70, 30), 3))
            painter.drawEllipse(cx - r, cy - r, r*2, r*2)
            eye_y = cy - 5
            if self.eye_visible:
                painter.setBrush(Qt.white)
                painter.setPen(QPen(Qt.black, 2))
                painter.drawEllipse(cx - 20, eye_y - 8, 16, 16)
                painter.drawEllipse(cx + 4,  eye_y - 8, 16, 16)
                painter.setBrush(Qt.black)
                painter.drawEllipse(cx - 16, eye_y - 4, 8, 8)
                painter.drawEllipse(cx + 8,  eye_y - 4, 8, 8)
            else:
                painter.setPen(QPen(Qt.black, 3))
                painter.drawLine(cx - 24, eye_y, cx - 10, eye_y)
                painter.drawLine(cx + 10, eye_y, cx + 24, eye_y)
            painter.setPen(QPen(Qt.black, 3))
            painter.drawArc(cx - 8, cy + 15, 16, 12, 0, -180 * 16)
        self.update_bulb_position()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self.movement_enabled:
            menu.addAction("🛑 No caminar").triggered.connect(self.toggle_movement)
        else:
            menu.addAction("🚶 Caminar").triggered.connect(self.toggle_movement)
        menu.addAction("📰 Noticias del día").triggered.connect(self.show_crypto_gems)
        menu.addAction("🏈 Deporte").triggered.connect(self.show_sports_analysis)
        menu.addAction("📊 Reporte").triggered.connect(self.show_report)
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

    def show_crypto_gems(self):
        self.start_query("__NEWS__")

    def show_sports_analysis(self):
        self.start_query("__SPORTS__")

    def show_report(self):
        self.start_query("__REPORT__")

    def show_history(self):
        self.start_query("__HISTORY__")

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
        """Aumenta la altura máxima de la burbuja en 100 px y la muestra."""
        current = self.response_scroll.maximumHeight()
        new_height = min(current + 100, 500)
        self.response_scroll.setMaximumHeight(new_height)
        self.adjust_window_height(new_height)
        # Mostrar la burbuja aunque estuviera oculta
        self.response_scroll.show()

    def hide_bubble(self):
        self.response_scroll.hide()

    def adjust_window_height(self, bubble_height):
        """Ajusta la altura de la ventana para acomodar la burbuja expandida."""
        base_height = 350
        extra_space = max(0, bubble_height - 200)  # 200 es la altura inicial máxima
        new_total_height = base_height + extra_space
        self.setFixedSize(self.total_width, new_total_height)
        self.chat_widget.setGeometry(
            self.avatar_width, 10,
            self.chat_area_width - 20, new_total_height - 20
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def closeEvent(self, event):
        event.ignore()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    avatar = FloatingAvatar()
    sys.exit(app.exec_())