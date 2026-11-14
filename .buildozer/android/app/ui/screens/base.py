"""Базовый класс экранов."""
from kivy.uix.screenmanager import Screen

from ..widgets import Panel


def make_panel(width_hint=0.5, height_hint=0.94):
    """Главная панель экрана по центру."""
    return Panel(size_hint=(width_hint, height_hint),
                 pos_hint={'center_x': 0.5, 'center_y': 0.5})


class BaseScreen(Screen):
    animated_background = True   # крутить ли частицы фона на этом экране
    game_background = False      # True — за игровым столом показывать etc/game_bg.jpg

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app

    def on_pre_enter(self, *args):
        self.refresh_texts()
        self.app.set_game_background(self.game_background)
        self.app.background.set_animated(self.animated_background)

    def refresh_texts(self):
        """Обновляет переводимые тексты (вызывается при входе и смене языка)."""
