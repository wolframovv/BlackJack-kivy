"""Экран входа и регистрации."""
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout

from core.i18n import duration_text, t
from .. import theme
from ..widgets import Lbl, LimitedInput, StyledButton
from .base import BaseScreen, make_panel


class LoginScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self.register_mode = False

        panel = make_panel(theme.PANEL_W)
        self.title = Lbl(text='BLACKJACK', font_size=sp(40), color=theme.GOLD,
                         outline_width=2, outline_color=theme.BLACK)
        self.mode_label = Lbl(size_hint_y=None, height=dp(26), font_size=sp(22),
                              color=theme.GOLD)
        self.user_input = LimitedInput(size_hint_y=None, height=theme.INPUT_H, max_len=20)

        row = BoxLayout(size_hint_y=None, height=theme.INPUT_H, spacing=theme.SPACING)
        self.pass_input = LimitedInput(max_len=20, password=True)
        self.eye_button = StyledButton(text='***', size_hint_x=None, width=dp(56),
                                       base_color=theme.LIGHT_GRAY, down_color=theme.WHITE,
                                       text_color=theme.BLACK, on_release=self.toggle_password)
        row.add_widget(self.pass_input)
        row.add_widget(self.eye_button)

        self.action_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                          on_release=self.submit)
        self.switch_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                          base_color=theme.BLUE, down_color=theme.LIGHT_BLUE,
                                          on_release=self.switch_mode)
        self.exit_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                        base_color=theme.RED, down_color=[1, 0.27, 0, 1],
                                        on_release=lambda *a: self.app.stop())

        self.user_input.bind(on_text_validate=lambda *a: setattr(self.pass_input, 'focus', True))
        self.pass_input.bind(on_text_validate=self.submit)

        for widget in (self.title, self.mode_label, self.user_input, row,
                       self.action_button, self.switch_button, self.exit_button):
            panel.add_widget(widget)
        self.add_widget(panel)

    def on_pre_enter(self, *args):
        self.register_mode = False
        self.pass_input.text = ''
        self.pass_input.password = True
        self.eye_button.text = '***'
        super().on_pre_enter(*args)

    def refresh_texts(self):
        self.title.text = t('blackjack')
        self.mode_label.text = t('register') if self.register_mode else t('login')
        self.user_input.hint_text = t('username')
        self.pass_input.hint_text = t('password')
        self.action_button.text = t('register_btn') if self.register_mode else t('login_btn')
        self.switch_button.text = t('back_to_login') if self.register_mode else t('register')
        self.exit_button.text = t('exit')

    def toggle_password(self, *args):
        self.pass_input.password = not self.pass_input.password
        self.eye_button.text = '***' if self.pass_input.password else 'abc'

    def switch_mode(self, *args):
        self.register_mode = not self.register_mode
        self.refresh_texts()

    def submit(self, *args):
        storage = self.app.storage
        name, password = self.user_input.text, self.pass_input.text
        if self.register_mode:
            wait = storage.register_block_remaining()
            if wait > 0:      # у какого-то аккаунта действует блокировка — ждём, пока снимется
                self.app.show_alert(t('register_locked') + duration_text(wait))
                return
            user, error = storage.register(name, password)
        else:
            user, error = storage.authenticate(name, password)
        if error:
            self.app.show_alert(t(error))
            return
        self.pass_input.text = ''
        self.app.login_success(user['username'])
