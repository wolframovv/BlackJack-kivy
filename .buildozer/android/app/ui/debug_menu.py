"""Отладочное меню: круглая кнопка поверх игры, аккаунты, баланс, блокировка, архив данных.

Включается флагом theme.DEBUG_MENU. Кружок можно перетаскивать, тап открывает меню.
"""
import os

from kivy.core.window import Window  # noqa: F401  (нужен, чтобы окно было создано)
from kivy.graphics import Color, Ellipse
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from core import debug_tools
from core.i18n import duration_text
from . import theme
from .downloads import save_to_downloads
from .widgets import Lbl, LimitedInput, Panel, StyledButton

TAP_LIMIT = dp(8)        # сдвиг пальца меньше этого считается нажатием, а не перетаскиванием
ROW_H = dp(34)


class DebugButton(Widget):
    """Полупрозрачный кружок поверх всего интерфейса."""

    def __init__(self, app, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(46), dp(46)))
        kwargs.setdefault('pos_hint', {'right': 0.99, 'center_y': 0.5})
        super().__init__(**kwargs)
        self.app = app
        self._moved = 0
        with self.canvas:
            Color(1, 0.25, 0.25, 0.6)
            self._circle = Ellipse(pos=self.pos, size=self.size)
        self._label = Lbl(text='D', font_size=sp(22), color=theme.WHITE)
        self.add_widget(self._label)
        self.bind(pos=self._relayout, size=self._relayout)
        self._relayout()

    def _relayout(self, *args):
        self._circle.pos = self.pos
        self._circle.size = self.size
        self._label.pos = self.pos
        self._label.size = self.size

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False                     # мимо кружка: пусть нажимается то, что под ним
        touch.grab(self)
        self._moved = 0
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        self._moved += abs(touch.dx) + abs(touch.dy)
        self.pos_hint = {}                   # дальше положение задаёт палец, а не FloatLayout
        x, y = self.x + touch.dx, self.y + touch.dy
        if self.parent is not None and self.parent.width and self.parent.height:
            x = max(0, min(x, self.parent.width - self.width))
            y = max(0, min(y, self.parent.height - self.height))
        self.pos = (x, y)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        if self._moved <= TAP_LIMIT:
            self.app.open_debug_menu()
        return True


class DebugMenu(ModalView):
    def __init__(self, app, **kwargs):
        super().__init__(size_hint=(0.94, 0.94), auto_dismiss=True, background='',
                         background_color=(0, 0, 0, 0), overlay_color=(0, 0, 0, 0.65),
                         **kwargs)
        self.app = app
        self.storage = app.storage
        self.selected = None

        panel = Panel()
        panel.add_widget(Lbl(text='DEBUG', size_hint_y=None, height=dp(30), font_size=sp(24),
                             color=theme.GOLD))

        body = BoxLayout(spacing=dp(8))
        # слева: список аккаунтов
        self.accounts_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        self.accounts_box.bind(minimum_height=self.accounts_box.setter('height'))
        accounts_scroll = ScrollView(size_hint_x=0.34)
        accounts_scroll.add_widget(self.accounts_box)
        body.add_widget(accounts_scroll)

        # справа: данные и действия для выбранного аккаунта
        self.details_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        self.details_box.bind(minimum_height=self.details_box.setter('height'))
        self.info_label = Lbl(text='', halign='left', valign='top', font_size=sp(16),
                              size_hint_y=None, height=dp(96))
        self.details_box.add_widget(self.info_label)

        self.balance_input = LimitedInput(hint_text='новый баланс', input_filter='int',
                                          max_len=10, size_hint_y=None, height=ROW_H)
        self.balance_button = StyledButton(text='Задать баланс', size_hint_y=None,
                                           height=ROW_H, on_release=self._apply_balance)
        self.details_box.add_widget(self._row(self.balance_input, self.balance_button))

        self.unlock_button = StyledButton(text='Снять блокировку', size_hint_y=None,
                                          height=ROW_H, on_release=self._unlock)
        self.details_box.add_widget(self.unlock_button)

        self.password_input = LimitedInput(hint_text='новый пароль', max_len=32,
                                           size_hint_y=None, height=ROW_H)
        self.password_button = StyledButton(text='Сменить пароль', size_hint_y=None,
                                            height=ROW_H, on_release=self._apply_password)
        self.details_box.add_widget(self._row(self.password_input, self.password_button))

        details_scroll = ScrollView()
        details_scroll.add_widget(self.details_box)
        body.add_widget(details_scroll)
        panel.add_widget(body)

        self.status = Lbl(text='', size_hint_y=None, height=dp(24), font_size=sp(15))
        panel.add_widget(self.status)

        bottom = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)
        self.zip_button = StyledButton(text='Данные для обучения: ZIP в Загрузки',
                                       on_release=self._make_zip)
        self.close_button = StyledButton(text='Закрыть', base_color=theme.DARK_GRAY,
                                         down_color=theme.GRAY,
                                         on_release=lambda *a: self.dismiss())
        bottom.add_widget(self.zip_button)
        bottom.add_widget(self.close_button)
        panel.add_widget(bottom)
        self.add_widget(panel)

        names = debug_tools.account_names(self.storage)
        self.selected = app.username if app.username in names else (names[0] if names else None)
        self._refresh()

    @staticmethod
    def _row(*widgets):
        row = BoxLayout(size_hint_y=None, height=ROW_H, spacing=theme.SPACING)
        for widget in widgets:
            row.add_widget(widget)
        return row

    # ---------- отображение ----------
    def _say(self, text, ok=True):
        self.status.text = text
        self.status.color = theme.GREEN_TEXT if ok else theme.RED_TEXT

    def _refresh(self):
        names = debug_tools.account_names(self.storage)
        if self.selected not in names:
            self.selected = names[0] if names else None
        self.accounts_box.clear_widgets()
        for name in names:
            info = debug_tools.describe_account(self.storage, name)
            mark = '  (блок)' if info['lock_seconds'] else ''
            chosen = name == self.selected
            button = StyledButton(text=name + mark, size_hint_y=None, height=ROW_H,
                                  base_color=theme.DARK_GREEN if chosen else theme.DARK_GRAY,
                                  down_color=theme.GREEN if chosen else theme.GRAY,
                                  on_release=lambda b, n=name: self._select(n))
            self.accounts_box.add_widget(button)
        self.info_label.text = self._info_text()
        has_account = self.selected is not None
        for widget in (self.balance_button, self.unlock_button, self.password_button):
            widget.disabled = not has_account

    def _info_text(self):
        if self.selected is None:
            return 'Аккаунтов нет'
        info = debug_tools.describe_account(self.storage, self.selected)
        if info['password'] is not None:
            password = info['password']
        else:
            password = 'хранится хэшем, прочитать нельзя (можно задать новый)'
        lock = duration_text(info['lock_seconds']) if info['lock_seconds'] else 'нет'
        return (f"Логин: {info['username']}\n"
                f"Пароль: {password}\n"
                f"Баланс: ${info['balance']}\n"
                f"Блокировка: {lock}   Elo: {info['elo']}")

    def _select(self, name):
        self.selected = name
        self.status.text = ''
        self._refresh()

    # ---------- действия ----------
    def _apply_balance(self, *args):
        amount, error = debug_tools.set_balance(self.storage, self.selected,
                                                self.balance_input.text)
        if error:
            return self._say(error, ok=False)
        self.balance_input.text = ''
        self._refresh()
        self._say(f'Баланс {self.selected}: ${amount}')

    def _unlock(self, *args):
        debug_tools.unlock_account(self.storage, self.selected)
        self._refresh()
        self._say(f'Блокировка {self.selected} снята')

    def _apply_password(self, *args):
        error = debug_tools.set_password(self.storage, self.selected, self.password_input.text)
        if error:
            return self._say(error, ok=False)
        new_password = self.password_input.text.strip()
        self.password_input.text = ''
        self._refresh()
        self._say(f'Новый пароль {self.selected}: {new_password}')

    def _make_zip(self, *args):
        dataset = self.app.dataset
        try:
            zip_path = debug_tools.make_dataset_zip(
                [dataset.decisions_path, dataset.rounds_path],
                os.path.dirname(dataset.decisions_path))
            place = save_to_downloads(zip_path)
        except Exception as error:
            return self._say(f'Ошибка: {error}', ok=False)
        try:
            os.remove(zip_path)               # временный архив рядом с данными больше не нужен
        except OSError:
            pass
        decisions, rounds = dataset.counts()
        self._say(f'Готово: {place} (решений {decisions}, раундов {rounds})')
