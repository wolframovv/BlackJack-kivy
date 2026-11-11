"""Выбор режима игры: слева одиночная игра, справа соревновательный (пока в разработке)."""
import os

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image

from core.i18n import t
from .. import theme
from ..widgets import BASE_DIR, Lbl, StyledButton
from .base import BaseScreen, make_panel

MENU_DIR = os.path.join(BASE_DIR, 'etc', 'menu')     # singleplayer.png, multiplayer.png


def mode_picture(name):
    """Иллюстрация режима. Если файла нет, source пустой и место остаётся свободным."""
    path = os.path.join(MENU_DIR, name)
    return Image(source=path if os.path.exists(path) else '', fit_mode='contain', size_hint_y=1)


class ModeScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        panel = make_panel(theme.PANEL_W)
        self.title = Lbl(size_hint_y=None, height=theme.TITLE_H, font_size=theme.TITLE_FS,
                         color=theme.GOLD, outline_width=2, outline_color=theme.BLACK)
        panel.add_widget(self.title)

        button_h = theme.BUTTON_H * 1.4
        self.single_button = StyledButton(size_hint_y=None, height=button_h, font_size=sp(24),
                                          on_release=lambda *a: self.app.go_betting())
        self.competitive_button = StyledButton(
            size_hint_y=None, height=button_h, font_size=sp(24),
            on_release=lambda *a: self.app.go_betting('competitive'))
        self.single_picture = mode_picture('singleplayer.png')
        self.competitive_picture = mode_picture('multiplayer.png')

        # два столбца по горизонтали: картинка сверху, кнопка снизу
        columns = BoxLayout(spacing=dp(14))
        for picture, button in ((self.single_picture, self.single_button),
                                (self.competitive_picture, self.competitive_button)):
            column = BoxLayout(orientation='vertical', spacing=dp(8))
            column.add_widget(picture)
            column.add_widget(button)
            columns.add_widget(column)
        panel.add_widget(columns)

        self.back_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                        base_color=theme.DARK_GRAY, down_color=theme.GRAY,
                                        on_release=lambda *a: self.app.go('menu'))
        panel.add_widget(self.back_button)
        self.add_widget(panel)

    def refresh_texts(self):
        self.title.text = t('play_mode_title')
        self.single_button.text = t('mode_single')
        self.competitive_button.text = t('mode_competitive')
        self.back_button.text = t('back')
