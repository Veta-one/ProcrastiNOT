# ProcrastiNOT.py (версия на PyQt6)

import sys
import os
import configparser
import threading
from datetime import datetime, time as dt_time
import time
import platform

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QSystemTrayIcon, QMenu, QGroupBox, QSpinBox, QCheckBox,
    QLineEdit, QFileDialog, QMessageBox
)
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QColor, QFont, QBrush, QPen, QAction, QPainterPath
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QPoint, QSize, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QSoundEffect 

# --- Вспомогательные функции и константы (в основном без изменений) ---

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

APP_ICON_PNG = resource_path('assets/app_icon.png')
DEFAULT_ICON_PATH = APP_ICON_PNG
NOTIFICATION_APP_ICON_PATH = APP_ICON_PNG
DEFAULT_SOUND_PATH = resource_path('assets/notification.wav')
CONFIG_FILE = 'settings.ini'

APP_FONT_FAMILY = "Montserrat"
FALLBACK_FONT_FAMILY = "Segoe UI" # Более подходящий для Windows

# Стилевые конфиги для логики, а не для прямого рендеринга
STYLE_CONFIGS = {
    "work": {"timer_fg": "#f3a500"},
    "rest": {"timer_fg": "#f33100"},
    "postponed": {"timer_fg": "#ffffff"},
    "rest_prompt": {"timer_fg": "#ffffff"},
}

TRAY_ICON_WORK_BG = "#1e1e1e"
TRAY_ICON_WORK_FG = STYLE_CONFIGS["work"]["timer_fg"]
TRAY_ICON_REST_BG = "#E0E0E0"
TRAY_ICON_REST_FG = STYLE_CONFIGS["rest"]["timer_fg"]
TRAY_ICON_PROMPT_BG = "#64bc64"
TRAY_ICON_PROMPT_FG = "#000000"
TRAY_ICON_POSTPONED_BG = "#f3a500"
TRAY_ICON_POSTPONED_FG = "#ffffff"
TRAY_ICON_IDLE_BG = "#1c1c1c"
TRAY_ICON_IDLE_FG = "#777777"


# Класс ConfigManager остается практически без изменений
class ConfigManager:
    def __init__(self, filename):
        self.filename = filename
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self):
        if not os.path.exists(self.filename):
            self.create_default_config()
        self.config.read(self.filename)
        self.work_minutes = self.config.getint('Timers', 'work_minutes', fallback=75)
        self.rest_minutes = self.config.getint('Timers', 'rest_minutes', fallback=33)
        self.postpone_minutes = self.config.getint('Timers', 'postpone_minutes', fallback=5)
        if self.postpone_minutes < 1: self.postpone_minutes = 1
        self.sound_enabled = self.config.getboolean('Timers', 'sound_enabled', fallback=True)
        self.sound_file = self.config.get('Timers', 'sound_file', fallback=DEFAULT_SOUND_PATH)
        self.active_start_hour = self.config.getint('Schedule', 'active_start_hour', fallback=9)
        self.active_end_hour = self.config.getint('Schedule', 'active_end_hour', fallback=18)
        self.icon_update_rate = self.config.getint('Timers', 'icon_update_rate_seconds', fallback=1)
        if self.icon_update_rate < 1: self.icon_update_rate = 1
        self.notif_timeout = self.config.getint('Timers', 'notif_timeout', fallback=5)

    def create_default_config(self):
        self.config['Timers'] = {
            'work_minutes': '75',
            'rest_minutes': '33',
            'postpone_minutes': '5',
            'sound_enabled': 'True',
            'sound_file': DEFAULT_SOUND_PATH,
            'icon_update_rate_seconds': '1',
            'notif_timeout': '5'
        }
        self.config['Schedule'] = {
            'active_start_hour': '9',
            'active_end_hour': '18'
        }
        # Записываем созданный конфиг напрямую в файл
        with open(self.filename, 'w') as cf:
            self.config.write(cf)

    def save_config(self):
        self.config['Timers'] = {
            'work_minutes': str(self.work_minutes), 'rest_minutes': str(self.rest_minutes),
            'postpone_minutes': str(self.postpone_minutes), 'sound_enabled': str(self.sound_enabled),
            'sound_file': self.sound_file, 'icon_update_rate_seconds': str(self.icon_update_rate),
            'notif_timeout': str(self.notif_timeout)
        }
        self.config['Schedule'] = {
            'active_start_hour': str(self.active_start_hour), 'active_end_hour': str(self.active_end_hour)
        }
        with open(self.filename, 'w') as cf: self.config.write(cf)

# --- Новые классы на PyQt6 ---

class CustomNotification(QWidget):
    """
    Новое уведомление на PyQt6.
    С поддержкой нативных эффектов Windows (Mica/Blur), скругленных углов и анимаций.
    """
    # Сигнал, который будет отправлен при закрытии окна
    closed = pyqtSignal()

    def __init__(self, parent_app, mode_key, title_text, timer_text, buttons_config=None, is_persistent=False, timeout_ms=7000):
        super().__init__()
        self.parent_app = parent_app
        self.is_persistent = is_persistent
        self.timeout_ms = timeout_ms
        self.mode_key = mode_key
        self.animation = QPropertyAnimation(self, b"windowOpacity")

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose) # Важно! Объект будет удаляться при закрытии

        # --- ГЛАВНОЕ ИСПРАВЛЕНИЕ ---
        # 1. УДАЛЯЕМ вызов Mica-эффекта, который вызывает конфликт рендеринга
        # self._enable_mica_effect() 

        # 2. ДОБАВЛЯЕМ два самых важных атрибута для кастомных окон
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True) # Приказ НЕ рисовать системный фон
        # ---------------------------
        self.setup_ui(title_text, timer_text, buttons_config)
        self.set_stylesheet() # Теперь вызывается без аргументов

        self.reposition()
        self.fade_in()

        self.mouse_over = False
        if not self.is_persistent:
            QTimer.singleShot(self.timeout_ms, self._check_timeout)
    
    def closeEvent(self, event):
        """ Переопределяем стандартный метод закрытия, чтобы отправить сигнал """
        self.closed.emit()
        super().closeEvent(event)
        
    def enterEvent(self, event):
        self.mouse_over = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.mouse_over = False
        super().leaveEvent(event)

    def _check_timeout(self):
        if self.mouse_over and self.isVisible(): # Добавлена проверка isVisible()
            QTimer.singleShot(1000, self._check_timeout)
        else:
            self.fade_out()

    def _enable_mica_effect(self):
        if platform.system() == "Windows":
            try:
                from ctypes import windll, c_int, byref
                hwnd = int(self.winId())
                value = c_int(2)
                windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, byref(value), 4)
            except Exception as e:
                print(f"Не удалось применить Mica-эффект: {e}")

    def setup_ui(self, title_text, timer_text, buttons_config):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.container_widget = QWidget()
        self.container_widget.setObjectName("ContainerWidget") # Присваиваем имя для стилизации
        self.main_layout.addWidget(self.container_widget)
        
        layout = QVBoxLayout(self.container_widget)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(5)

        header_layout = QHBoxLayout()
        icon_label = QLabel()
        pixmap = QPixmap(NOTIFICATION_APP_ICON_PATH).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        icon_label.setPixmap(pixmap)
        header_layout.addWidget(icon_label)

        self.title_label = QLabel(title_text)
        self.title_label.setObjectName("TitleLabel")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        close_button = QPushButton("✕")
        close_button.setObjectName("CloseButton")
        close_button.setFixedSize(22, 22)
        close_button.clicked.connect(self.fade_out)
        header_layout.addWidget(close_button)
        layout.addLayout(header_layout)

        content_layout = QHBoxLayout()
        self.timer_label = QLabel(timer_text)
        self.timer_label.setObjectName("TimerLabel")
        content_layout.addWidget(self.timer_label, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if buttons_config:
            button_layout = QVBoxLayout()
            button_layout.setSpacing(4)
            for btn_conf in buttons_config:
                button = QPushButton(btn_conf["text"])
                button.setObjectName(f"ActionButton{btn_conf.get('style', '')}")
                button.clicked.connect(btn_conf["command"])
                button_layout.addWidget(button)
            content_layout.addLayout(button_layout)
        
        layout.addLayout(content_layout)

    def set_stylesheet(self):
        style_data = {
            "work":        {"bg": "rgba(30, 30, 30, 0.85)", "fg": "#ffffff", "timer": "#f3a500", "btn_bg": "#ffffff", "btn_fg": "#1e1e1e"},
            "rest":        {"bg": "rgba(240, 240, 240, 0.9)", "fg": "#1e1e1e", "timer": "#f33100", "btn_bg": "#1e1e1e", "btn_fg": "#ffffff"},
            "rest_prompt": {"bg": "rgba(100, 188, 100, 0.9)", "fg": "#ffffff", "timer": "#ffffff", "btn_bg": "#ffffff", "btn_fg": "#1e1e1e", "btn_primary_bg": "#1e1e1e", "btn_primary_fg": "#ffffff"},
            "postponed":   {"bg": "rgba(243, 165, 0, 0.9)", "fg": "#ffffff", "timer": "#ffffff", "btn_bg": "#ffffff", "btn_fg": "#1e1e1e"},
            "idle_inactive_hours": {"bg": "rgba(28, 28, 28, 0.85)", "fg": "#777777", "timer": "#777777", "btn_bg": "#444444", "btn_fg": "#aaaaaa"}
        }
        
        colors = style_data.get(self.mode_key, style_data["work"])

        base_style = f"""
            CustomNotification {{
                background: transparent;
            }}
            #ContainerWidget {{
                background-color: {colors['bg']};
                border-radius: 12px;
            }}
            #TitleLabel, #CloseButton {{
                color: {colors['fg']};
            }}
            #TimerLabel {{
                color: {colors['timer']};
            }}
            #ActionButton {{
                background-color: {colors['btn_bg']};
                color: {colors['btn_fg']};
                border: 1px solid {colors['btn_bg']};
            }}
            #ActionButton:hover {{
                background-color: #e0e0e0;
                border-color: #e0e0e0;
                color: #1e1e1e;
            }}
            #ActionButtonPrimary {{
                background-color: {colors.get('btn_primary_bg', colors['btn_bg'])};
                color: {colors.get('btn_primary_fg', colors['btn_fg'])};
                border: 1px solid {colors.get('btn_primary_bg', colors['btn_bg'])};
            }}
            #ActionButtonPrimary:hover {{
                background-color: #444;
                border-color: #444;
                color: #ffffff;
            }}
            
            #CloseButton {{
                background-color: transparent;
                border: none; 
                font-size: 12pt; 
                font-weight: bold;
                padding: 0px;
                margin: 0px;
                min-width: 22px;
                max-width: 22px;
            }}
            #CloseButton:hover {{
                color: #ff4d4d;
            }}

            QPushButton {{
                font-family: "{APP_FONT_FAMILY}", "{FALLBACK_FONT_FAMILY}";
                font-weight: bold; 
                font-size: 9pt; 
                padding: 6px 14px;
                border-radius: 8px;
                min-width: 100px;
            }}
            #TitleLabel {{
                font-family: "{APP_FONT_FAMILY}", "{FALLBACK_FONT_FAMILY}";
                font-size: 11pt; 
                font-weight: bold;
            }}
            #TimerLabel {{
                font-family: "{APP_FONT_FAMILY}", "{FALLBACK_FONT_FAMILY}";
                font-size: 30pt; 
                font-weight: bold; 
                padding-right: 20px;
            }}
        """
        self.setStyleSheet(base_style)

    def update_timer(self, new_time_text):
        if self.isVisible():
            self.timer_label.setText(new_time_text)
    
    def fade_in(self):
        self.animation.stop()
        self.animation.setDuration(300)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.show()
        self.animation.start()

    def fade_out(self):
        self.animation.stop()
        self.animation.setDuration(300)
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.Type.InCubic)
        # Убеждаемся, что close() вызовется только один раз
        try: self.animation.finished.disconnect() 
        except TypeError: pass
        self.animation.finished.connect(self.close)
        self.animation.start()

    def reposition(self):
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        self.setFixedSize(380, 130)
        x = screen_geometry.right() - self.width() - 15
        y = screen_geometry.bottom() - self.height() - 15
        self.move(x, y)

class SettingsWindow(QWidget):
    """ Красивое окно настроек на PyQt6 """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.config_manager = parent_app.config_manager
        
        self.setWindowTitle("Настройки")
        self.setWindowIcon(QIcon(DEFAULT_ICON_PATH))
        self.setGeometry(0, 0, 450, 500)
        self.center()
        self.setStyleSheet(self.get_stylesheet())

        self.setup_ui()
        self.load_settings()

    def center(self):
        qr = self.frameGeometry()
        cp = self.screen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def get_stylesheet(self):
        return """
            QWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
                font-family: "Segoe UI", "Montserrat", sans-serif;
                font-size: 10pt;
            }
            
            QGroupBox {
                font-weight: bold;
                font-size: 11pt;
                border: 2px solid #444;
                border-radius: 12px;
                margin-top: 15px;
                padding: 15px;
                background-color: #2a2a2a;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px 10px;
                left: 15px;
                background-color: #f3a500;
                color: #1e1e1e;
                border-radius: 6px;
                font-weight: bold;
            }
            
            QLabel {
                background-color: transparent;
                font-size: 10pt;
                color: #d0d0d0;
                padding: 2px;
            }
            
            QSpinBox, QLineEdit {
                background-color: #3a3a3a;
                border: 2px solid #555;
                border-radius: 8px;
                padding: 8px 12px;
                color: #ffffff;
                font-size: 10pt;
                min-height: 20px;
            }
            
            QSpinBox:focus, QLineEdit:focus {
                border-color: #f3a500;
                background-color: #404040;
            }
            
            QSpinBox:hover, QLineEdit:hover {
                border-color: #666;
                background-color: #353535;
            }
            
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #555;
                border: none;
                width: 20px;
                border-radius: 4px;
            }
            
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #f3a500;
            }
            
            QSpinBox::up-arrow, QSpinBox::down-arrow {
                width: 8px;
                height: 8px;
            }
            
            QCheckBox {
                font-size: 10pt;
                color: #d0d0d0;
                spacing: 8px;
            }
            
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 2px solid #555;
                border-radius: 6px;
                background-color: #3a3a3a;
            }
            
            QCheckBox::indicator:checked {
                background-color: #f3a500;
                border-color: #f3a500;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOSIgdmlld0JveD0iMCAwIDEyIDkiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDQuNUw0LjUgOEwxMSAxIiBzdHJva2U9IiMxZTFlMWUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }
            
            QCheckBox::indicator:hover {
                border-color: #f3a500;
            }
            
            QPushButton {
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 10pt;
                min-width: 100px;
                border: none;
            }
            
            QPushButton#SaveButton {
                background-color: #f3a500;
                color: #1e1e1e;
            }
            
            QPushButton#SaveButton:hover {
                background-color: #ffb733;
            }
            
            QPushButton#SaveButton:pressed {
                background-color: #e09400;
            }
            
            QPushButton#CancelButton {
                background-color: #555;
                color: #e0e0e0;
            }
            
            QPushButton#CancelButton:hover {
                background-color: #666;
            }
            
            QPushButton#CancelButton:pressed {
                background-color: #444;
            }
            
            QPushButton#BrowseButton {
                background-color: #444;
                color: #e0e0e0;
                padding: 8px 15px;
                min-width: 50px;
            }
            
            QPushButton#BrowseButton:hover {
                background-color: #555;
            }
            
            QPushButton#BrowseButton:pressed {
                background-color: #333;
            }
        """
    
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # Timers Group
        timers_group = QGroupBox("Таймеры")
        timers_layout = QGridLayout(timers_group)
        self.work_spin = QSpinBox()
        self.rest_spin = QSpinBox()
        self.postpone_spin = QSpinBox()
        for spin in [self.work_spin, self.rest_spin, self.postpone_spin]:
            spin.setRange(1, 180)
        timers_layout.addWidget(QLabel("Работа (мин):"), 0, 0)
        timers_layout.addWidget(self.work_spin, 0, 1)
        timers_layout.addWidget(QLabel("Отдых (мин):"), 1, 0)
        timers_layout.addWidget(self.rest_spin, 1, 1)
        timers_layout.addWidget(QLabel("Отложить (мин):"), 2, 0)
        timers_layout.addWidget(self.postpone_spin, 2, 1)
        main_layout.addWidget(timers_group)

        # Schedule Group
        schedule_group = QGroupBox("Расписание")
        schedule_layout = QGridLayout(schedule_group)
        self.start_hour_spin = QSpinBox()
        self.end_hour_spin = QSpinBox()
        for spin in [self.start_hour_spin, self.end_hour_spin]:
            spin.setRange(0, 23)
        schedule_layout.addWidget(QLabel("Начало (час):"), 0, 0)
        schedule_layout.addWidget(self.start_hour_spin, 0, 1)
        schedule_layout.addWidget(QLabel("Конец (час):"), 1, 0)
        schedule_layout.addWidget(self.end_hour_spin, 1, 1)
        main_layout.addWidget(schedule_group)

        # Other Group
        other_group = QGroupBox("Прочее")
        other_layout = QGridLayout(other_group)
        self.icon_rate_spin = QSpinBox()
        self.icon_rate_spin.setRange(1, 10)
        self.notif_timeout_spin = QSpinBox()
        self.notif_timeout_spin.setRange(1, 30)
        other_layout.addWidget(QLabel("Иконка (сек):"), 0, 0)
        other_layout.addWidget(self.icon_rate_spin, 0, 1)
        other_layout.addWidget(QLabel("Автозакрытие (сек):"), 1, 0)
        other_layout.addWidget(self.notif_timeout_spin, 1, 1)
        self.sound_check = QCheckBox("Звук уведомлений")
        other_layout.addWidget(self.sound_check, 2, 0, 1, 2)
        sound_file_layout = QHBoxLayout()
        self.sound_file_edit = QLineEdit()
        browse_button = QPushButton("...")
        browse_button.setObjectName("BrowseButton")
        browse_button.clicked.connect(self.browse_sound_file)
        sound_file_layout.addWidget(self.sound_file_edit)
        sound_file_layout.addWidget(browse_button)
        other_layout.addWidget(QLabel("Файл звука:"), 3, 0)
        other_layout.addLayout(sound_file_layout, 3, 1)
        main_layout.addWidget(other_group)

        main_layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        cancel_button = QPushButton("Отмена")
        cancel_button.setObjectName("CancelButton")
        cancel_button.clicked.connect(self.close)
        save_button = QPushButton("Сохранить")
        save_button.setObjectName("SaveButton")
        save_button.clicked.connect(self.save_settings)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)
        main_layout.addLayout(button_layout)
        
    def load_settings(self):
        self.work_spin.setValue(self.config_manager.work_minutes)
        self.rest_spin.setValue(self.config_manager.rest_minutes)
        self.postpone_spin.setValue(self.config_manager.postpone_minutes)
        self.start_hour_spin.setValue(self.config_manager.active_start_hour)
        self.end_hour_spin.setValue(self.config_manager.active_end_hour)
        self.icon_rate_spin.setValue(self.config_manager.icon_update_rate)
        self.notif_timeout_spin.setValue(self.config_manager.notif_timeout)
        self.sound_check.setChecked(self.config_manager.sound_enabled)
        self.sound_file_edit.setText(self.config_manager.sound_file)

    def save_settings(self):
        try:
            self.config_manager.work_minutes = self.work_spin.value()
            self.config_manager.rest_minutes = self.rest_spin.value()
            self.config_manager.postpone_minutes = self.postpone_spin.value()
            self.config_manager.active_start_hour = self.start_hour_spin.value()
            self.config_manager.active_end_hour = self.end_hour_spin.value()
            self.config_manager.icon_update_rate = self.icon_rate_spin.value()
            self.config_manager.notif_timeout = self.notif_timeout_spin.value()
            self.config_manager.sound_enabled = self.sound_check.isChecked()
            self.config_manager.sound_file = self.sound_file_edit.text()
            
            self.config_manager.save_config()
            self.parent_app.load_settings()

            QMessageBox.information(self, "Сохранено", "Настройки сохранены и применены.")
            self.close()
            
            timer_was_running = self.parent_app.main_timer.isActive()
            if self.parent_app.active_notification:
                self.parent_app.active_notification.fade_out()
            if timer_was_running:
                self.parent_app.start_main_timer()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки: {e}")

    def browse_sound_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Выберите файл звука", "", "WAV Files (*.wav);;All Files (*)")
        if filename:
            self.sound_file_edit.setText(filename)


class ProductivityApp:
    def __init__(self, app_instance):
        self.app = app_instance
        self.config_manager = ConfigManager(CONFIG_FILE)
        
        self.sound_effect = QSoundEffect()
        self.load_settings()

        self.current_mode = "work"
        self.last_icon_update_time = 0
        self.current_phase_end_time = 0
        self.overtime_start_time = 0

        self.active_notification = None
        self.settings_window = None


        
        self.main_timer = QTimer()
        self.main_timer.setInterval(1000)
        self.main_timer.timeout.connect(self.update_timer_tick)
        
        self.setup_tray_icon()
        self.start_main_timer()

    def load_settings(self):
        self.config_manager.load_config()
        self.work_duration_sec = self.config_manager.work_minutes * 60
        self.rest_duration_sec = self.config_manager.rest_minutes * 60
        self.postpone_duration_sec = self.config_manager.postpone_minutes * 60
        if os.path.exists(self.config_manager.sound_file):
            self.sound_effect.setSource(QUrl.fromLocalFile(self.config_manager.sound_file))

    def _generate_icon_image(self, text, bg_color, fg_color):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, 64, 64, 12, 12)
        painter.fillPath(path, QBrush(QColor(bg_color)))

        font = QFont(APP_FONT_FAMILY, 28, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor(fg_color)))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return QIcon(pixmap)
    
    def play_sound(self):
        if self.config_manager.sound_enabled and self.sound_effect.isLoaded():
            self.sound_effect.play()

    def is_within_active_hours(self):
        n = datetime.now().time()
        s = dt_time(self.config_manager.active_start_hour, 0)
        e = dt_time(self.config_manager.active_end_hour, 0)
        if e < s: return n >= s or n <= e
        return s <= n <= e

    def start_main_timer(self):
        self.main_timer.stop()
        if not self.is_within_active_hours():
            if self.current_mode != "idle_inactive_hours":
                self.current_mode = "idle_inactive_hours"
                if self.active_notification: self.active_notification.fade_out()
                self.current_phase_end_time = time.time()
                self.show_notification()
            self.tray_icon.setToolTip("Спит (вне часов)")
            self.tray_icon.setIcon(self._generate_icon_image("Zzz", TRAY_ICON_IDLE_BG, TRAY_ICON_IDLE_FG))
            QTimer.singleShot(60 * 1000, self.start_main_timer)
            return

        if self.current_mode == "idle_inactive_hours":
            self.current_mode = "work"

        duration_sec = {
            "work": self.work_duration_sec,
            "rest": self.rest_duration_sec,
            "postponed": self.postpone_duration_sec
        }.get(self.current_mode, 0)

        self.current_phase_end_time = time.time() + duration_sec
        self.show_notification()
        self.update_display_elements()
        self.main_timer.start()

    def update_timer_tick(self):
        if not self.is_within_active_hours():
            self.start_main_timer()
            return
        
        if self.current_mode == "rest_prompt":
            # В режиме переработки просто обновляем дисплей
            self.update_display_elements()
        else:
            remaining_seconds = max(0, int(self.current_phase_end_time - time.time()))
            self.update_display_elements(current_remaining_seconds=remaining_seconds)
    
            if remaining_seconds <= 0:
                if self.current_mode in ["work", "postponed", "rest"]:
                    self.play_sound()
                    self.current_mode = "rest_prompt"
                    self.overtime_start_time = time.time()
                    self.update_display_elements()
                    self.show_notification(is_rest_prompt=True)
    
    def update_display_elements(self, current_remaining_seconds=None):
        # --- ИСПРАВЛЕНИЕ RuntimeError ---
        # Теперь эта проверка безопасна
        is_prompt_active = self.active_notification and self.active_notification.is_persistent
        mode = "rest_prompt" if is_prompt_active else self.current_mode
    
        if current_remaining_seconds is None:
            if mode == "rest_prompt":
                current_remaining_seconds = int(time.time() - self.overtime_start_time)
            else:
                current_remaining_seconds = max(0, int(self.current_phase_end_time - time.time()))
        
        now = time.time()
        needs_icon_update = (now - self.last_icon_update_time >= self.config_manager.icon_update_rate) or \
                            (mode not in ["rest_prompt", "idle_inactive_hours"] and current_remaining_seconds <= 5)
        
        m, s = divmod(current_remaining_seconds, 60)
        icon_text = str(m if m > 0 else current_remaining_seconds)
        timer_text = self.format_time(current_remaining_seconds)
    
        tray_bg, tray_fg, tray_title = TRAY_ICON_IDLE_BG, TRAY_ICON_IDLE_FG, "Таймер"
        
        if mode == "work":
            tray_bg, tray_fg = TRAY_ICON_WORK_BG, TRAY_ICON_WORK_FG
            tray_title = f"Работа: {timer_text}"
        elif mode == "rest":
            tray_bg, tray_fg = TRAY_ICON_REST_BG, TRAY_ICON_REST_FG
            tray_title = f"Отдых: {timer_text}"
        elif mode == "rest_prompt":
            overtime_seconds = int(time.time() - self.overtime_start_time)
            m, s = divmod(overtime_seconds, 60)
            icon_text = str(m if m > 0 else overtime_seconds)
            tray_bg, tray_fg = TRAY_ICON_PROMPT_BG, TRAY_ICON_PROMPT_FG
            tray_title = f"Переработка: {self.format_time(overtime_seconds)}"
            timer_text = self.format_time(overtime_seconds)
        elif mode == "postponed":
            tray_bg, tray_fg = TRAY_ICON_POSTPONED_BG, TRAY_ICON_POSTPONED_FG
            tray_title = f"Отложено: {timer_text}"
        elif mode == "idle_inactive_hours":
            icon_text = "Zzz"
            tray_title = "Спит (вне часов)"
            timer_text = "--:--"
        
        self.tray_icon.setToolTip(tray_title)
        if needs_icon_update and icon_text:
            self.tray_icon.setIcon(self._generate_icon_image(icon_text, tray_bg, tray_fg))
            self.last_icon_update_time = now
    
        if self.active_notification:
            self.active_notification.update_timer(timer_text)
    
    def format_time(self, seconds):
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"
    
    def show_notification(self, is_rest_prompt=False, from_tray_click=False):
        current_eval_mode = "rest_prompt" if is_rest_prompt else self.current_mode
        
        if self.active_notification:
            if self.active_notification.mode_key == current_eval_mode and not from_tray_click:
                self.active_notification.activateWindow()
                return
            # Закрываем старое уведомление, если тип не совпадает
            self.active_notification.fade_out()
        
        title, timer_text, buttons = "", "", []
        persistent = False
        
        if current_eval_mode == "rest_prompt":
            title = "Пора отдохнуть!"
            timer_text = self.format_time(self.rest_duration_sec)
            buttons = [
                {"text": f"Отложить ({self.config_manager.postpone_minutes}м)", "command": self.postpone_rest_action, "style": ""},
                {"text": "Начать отдых", "command": self.start_rest_action, "style": "Primary"}
            ]
            persistent = False
        elif current_eval_mode == "work":
            title = "Работаем"
            timer_text = self.format_time(max(0, int(self.current_phase_end_time - time.time())))
            buttons = [{"text": "Завершить работу", "command": self.force_start_rest_action, "style": ""}]
        elif current_eval_mode == "rest":
            title = "Отдыхаем"
            timer_text = self.format_time(max(0, int(self.current_phase_end_time - time.time())))
            buttons = [{"text": "Вернуться к работе", "command": self.force_start_work_action, "style": ""}]
        elif current_eval_mode == "postponed":
            title = "Отдых отложен"
            timer_text = self.format_time(max(0, int(self.current_phase_end_time - time.time())))
            buttons = [{"text": "Начать отдых", "command": self.force_start_rest_from_postponed_action, "style": ""}]
        elif current_eval_mode == "idle_inactive_hours":
            title = "Приложение спит"
            timer_text = "--:--"
        else:
            return
    
        self.active_notification = CustomNotification(
            self, current_eval_mode, title, timer_text, buttons, persistent, self.config_manager.notif_timeout * 1000
        )
        # --- ИСПРАВЛЕНИЕ RuntimeError ---
        # Подписываемся на сигнал закрытия, чтобы обнулить ссылку
        self.active_notification.closed.connect(self._on_notification_closed)
        
        self.update_display_elements()
    
    def _on_notification_closed(self):
        """ Этот слот вызывается, когда уведомление закрывается. """
        self.active_notification = None
    
    def _handle_action(self, action_func):
        if self.active_notification: self.active_notification.fade_out()
        action_func()
    
    def start_rest_action(self): self._handle_action(lambda: self._set_mode_and_start("rest"))
    def postpone_rest_action(self): self._handle_action(lambda: self._set_mode_and_start("postponed"))
    def force_start_rest_action(self): self._handle_action(lambda: self._set_mode_and_start("rest"))
    def force_start_work_action(self): self._handle_action(lambda: self._set_mode_and_start("work"))
    def force_start_rest_from_postponed_action(self): self._handle_action(lambda: self._set_mode_and_start("rest"))
    
    def _set_mode_and_start(self, mode):
        self.current_mode = mode
        if mode != 'postponed': # Не проигрываем звук при откладывании
             self.play_sound()
        self.start_main_timer()
    
    def show_settings_window(self):
        if not self.settings_window or not self.settings_window.isVisible():
            self.settings_window = SettingsWindow(self)
            self.settings_window.show()
        self.settings_window.activateWindow()
    
    def setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(QIcon(DEFAULT_ICON_PATH))
        self.tray_icon.setToolTip("Таймер продуктивности")
        
        menu = QMenu()
        show_action = QAction("Показать уведомление", self.app)
        show_action.triggered.connect(lambda: self.show_notification(from_tray_click=True))
        menu.addAction(show_action)
    
        settings_action = QAction("Настройки", self.app)
        settings_action.triggered.connect(self.show_settings_window)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction("Выход", self.app)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
    
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(lambda reason: self.show_notification(from_tray_click=True) if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    
    def quit_app(self):
        if self.active_notification: self.active_notification.close()
        if self.settings_window: self.settings_window.close()
        self.tray_icon.hide()
        self.app.quit()

if __name__ == "__main__":
    if not os.path.exists("assets"): os.makedirs("assets")
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) # Приложение не закрывается, если закрыть все окна
    
    prod_app = ProductivityApp(app)
    
    sys.exit(app.exec())