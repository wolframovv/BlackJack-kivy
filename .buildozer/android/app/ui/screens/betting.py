"""Экран ставки."""
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout

from core.i18n import t
from .. import theme
from ..widgets import Lbl, LimitedInput, StyledButton
from .base import BaseScreen, make_panel

CHIPS = (10, 50, 100, 500)
DEFAULT_BET = 10


class BettingScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self.bet = DEFAULT_BET

        panel = make_panel(theme.PANEL_W)
        self.title = Lbl(font_size=theme.TITLE_FS, color=theme.GOLD,
                         outline_width=2, outline_color=theme.BLACK)
        self.balance_label = Lbl(size_hint_y=None, height=dp(26), font_size=sp(22))
        self.bet_label = Lbl(size_hint_y=None, height=dp(34), font_size=sp(28),
                             color=theme.GOLD)
        self.input = LimitedInput(size_hint_y=None, height=theme.INPUT_H, max_len=12,
                                  input_filter='int', input_type='number')
        self.input.bind(on_text_validate=self.apply_input)

        chips = BoxLayout(size_hint_y=None, height=dp(36), spacing=theme.SPACING)
        self.chip_buttons = []
        for amount in CHIPS:
            button = StyledButton(text=f"${amount}", base_color=theme.BLUE,
                                  down_color=theme.LIGHT_BLUE,
                                  on_release=lambda b, a=amount: self.set_bet(a))
            self.chip_buttons.append((amount, button))
            chips.add_widget(button)

        self.start_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                         on_release=self.start)
        self.back_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                        base_color=theme.BLUE, down_color=theme.LIGHT_BLUE,
                                        on_release=lambda *a: self.app.go('mode'))
        for widget in (self.title, self.balance_label, self.bet_label, self.input, chips,
                       self.start_button, self.back_button):
            panel.add_widget(widget)
        self.add_widget(panel)

    def on_pre_enter(self, *args):
        balance = self.app.user['balance']
        self.bet = max(1, min(self.bet, balance))
        self.input.text = ''
        super().on_pre_enter(*args)

    def refresh_texts(self):
        balance = self.app.user['balance']
        self.title.text = t('place_bet')
        self.balance_label.text = f"{t('balance')}: ${balance}"
        self.bet_label.text = f"{t('bet')}: ${self.bet}"
        self.input.hint_text = t('enter_bet')
        self.start_button.text = t('start_game')
        self.back_button.text = t('back')
        for amount, button in self.chip_buttons:
            button.disabled = amount > balance

    def set_bet(self, amount):
        self.bet = amount
        self.input.text = ''
        self.refresh_texts()

    def _read_input(self):
        """Возвращает ставку из поля (или текущую), либо None, если показана ошибка."""
        text = self.input.text.strip()
        if not text:
            return self.bet
        try:
            return int(text)
        except ValueError:
            self.app.show_alert(t('invalid_number'))
            return None

    def _validate(self, bet):
        if bet <= 0:
            self.app.show_alert(t('bet_must_be_positive'))
            return False
        if bet > self.app.user['balance']:
            self.app.show_alert(t('insufficient_funds'))
            return False
        return True

    def apply_input(self, *args):
        bet = self._read_input()
        if bet is not None and self._validate(bet):
            self.set_bet(bet)

    def start(self, *args):
        bet = self._read_input()
        if bet is not None and self._validate(bet):
            self.bet = bet
            self.app.start_game(bet)
