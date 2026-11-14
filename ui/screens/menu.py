"""Главное меню."""
import os

from kivy.metrics import dp
from kivy.uix.image import Image

from core.i18n import i18n, t
from .. import theme
from ..widgets import BASE_DIR, StyledButton
from .base import BaseScreen, make_panel

LOGO_PATH = os.path.join(BASE_DIR, 'etc', 'menu', 'logo.png')


class MenuScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        panel = make_panel(theme.PANEL_W, 0.98)
        panel.padding = dp(8)
        panel.spacing = dp(4)
        # вместо текстового заголовка — картинка-логотип
        self.logo = Image(source=LOGO_PATH if os.path.exists(LOGO_PATH) else '',
                          fit_mode='contain')
        panel.add_widget(self.logo)

        spec = [
            ('play', theme.DARK_GREEN, theme.GREEN, lambda *a: self.app.go_play()),
            ('profile', theme.DARK_GREEN, theme.GREEN, lambda *a: self.app.go('profile')),
            ('leaderboard', theme.DARK_GREEN, theme.GREEN, lambda *a: self.app.go('leaderboard')),
            ('skins', theme.DARK_GREEN, theme.GREEN, lambda *a: self.app.go('skins')),
            ('logout', theme.BLUE, theme.LIGHT_BLUE, lambda *a: self.app.logout()),
            ('exit', theme.RED, [1, 0.27, 0, 1], lambda *a: self.app.stop()),
        ]
        self.buttons = {}
        for key, color, down, handler in spec:
            button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                  base_color=color, down_color=down, on_release=handler)
            self.buttons[key] = button
            panel.add_widget(button)
        self.add_widget(panel)

        # переключатель языка — в углу, только в меню
        self.lang_button = StyledButton(size_hint=(None, None), size=(dp(56), dp(34)),
                                        pos_hint={'right': 0.985, 'top': 0.975},
                                        base_color=theme.LIGHT_GRAY, down_color=theme.WHITE,
                                        text_color=theme.BLACK,
                                        on_release=lambda *a: self.app.toggle_language())
        self.add_widget(self.lang_button)

    def refresh_texts(self):
        for key, button in self.buttons.items():
            button.text = t(key)
        self.lang_button.text = i18n.short
