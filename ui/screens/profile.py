"""Профиль игрока: аватар, имя, логин, статистика."""
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.label import Label

from core.i18n import duration_text, t
from .. import theme
from ..widgets import AvatarImage, Lbl, LimitedInput, Panel, StyledButton, RankIcon
from .base import BaseScreen, make_panel



class RenameDialog(ModalView):
    """Окно смены имени."""

    def __init__(self, current_name, on_save, **kwargs):
        super().__init__(size_hint=(0.6, 0.55), auto_dismiss=True, background='',
                         background_color=(0, 0, 0, 0), overlay_color=(0, 0, 0, 0.65), **kwargs)
        self._on_save = on_save
        panel = Panel()
        panel.add_widget(Lbl(text=t('change_name'), font_size=sp(24), color=theme.GOLD))
        self.input = LimitedInput(text=current_name, hint_text=t('enter_new_name'), max_len=16,
                                  size_hint_y=None, height=theme.INPUT_H)
        self.input.bind(on_text_validate=lambda *a: self.save())
        panel.add_widget(self.input)
        row = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)
        row.add_widget(StyledButton(text=t('save'), on_release=lambda *a: self.save()))
        row.add_widget(StyledButton(text=t('cancel'), base_color=theme.DARK_GRAY,
                                    down_color=theme.GRAY, on_release=lambda *a: self.dismiss()))
        panel.add_widget(row)
        self.add_widget(panel)

    def open(self, *args, **kwargs):
        super().open(*args, **kwargs)
        Clock.schedule_once(lambda dt: setattr(self.input, 'focus', True), 0.1)

    def save(self):
        self._on_save(self.input.text, self)


class ProfileScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        panel = make_panel(theme.WIDE_PANEL_W)
        self.title = Lbl(size_hint_y=None, height=theme.TITLE_H, font_size=theme.TITLE_FS,
                         color=theme.GOLD, outline_width=2, outline_color=theme.BLACK)

        body = BoxLayout(spacing=dp(10))

        # слева: аватар, имя, логин (серым), блокировка
        left = Panel(size_hint_x=0.42, padding=dp(10), spacing=dp(4))
        self.avatar = AvatarImage(size_hint=(None, None), size=(dp(84), dp(84)),
                                  pos_hint={'center_x': 0.5})
        # строка «значок ранга + имя»: ширина по тексту, чтобы значок стоял вплотную к имени
        self.rank_icon = RankIcon(size_hint=(None, 1), width=dp(26))
        self.name_label = Label(font_name=theme.FONT, font_size=sp(22), color=theme.GOLD,
                            size_hint=(None, 1))
        self.name_row = BoxLayout(size_hint=(None, None), height=dp(30), spacing=dp(6),
                                pos_hint={'center_x': 0.5})
        self.name_row.add_widget(self.rank_icon)
        self.name_row.add_widget(self.name_label)
        self.name_label.bind(texture_size=self._fit_name)
        self.login_label = Lbl(size_hint_y=None, height=dp(20), font_size=sp(13),
                               color=theme.GRAY, shorten=True)
        self.lock_label = Lbl(size_hint_y=None, height=dp(20), font_size=sp(13),
                              color=theme.RED_TEXT)
        for widget in (self.avatar, self.name_row, self.login_label, self.lock_label):
            left.add_widget(widget)

        # справа: статистика
        stats = Panel(size_hint_x=0.58, padding=dp(20), spacing=dp(2))
        self.header = Lbl(size_hint_y=None, height=dp(28), font_size=sp(21), color=theme.GOLD)
        stats.add_widget(self.header)
        colors = [theme.WHITE, theme.GREEN_TEXT, theme.RED_TEXT, theme.YELLOW, theme.GOLD]
        self.rows = []
        for color in colors:
            label = Lbl(halign='left', font_size=sp(18), color=color)
            self.rows.append(label)
            stats.add_widget(label)
        self.dataset_label = Lbl(halign='left', font_size=sp(14), color=theme.LIGHT_GRAY)
        stats.add_widget(self.dataset_label)

        body.add_widget(left)
        body.add_widget(stats)

        # кнопки
        actions = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)
        self.rename_button = StyledButton(base_color=theme.BLUE, down_color=theme.LIGHT_BLUE,
                                          font_size=sp(17), on_release=self.open_rename)
        self.avatar_button = StyledButton(base_color=theme.BLUE, down_color=theme.LIGHT_BLUE,
                                          font_size=sp(17), on_release=self.choose_avatar)
        self.reset_button = StyledButton(base_color=theme.DARK_GRAY, down_color=theme.GRAY,
                                         font_size=sp(17), on_release=self.reset_avatar)
        self.back_button = StyledButton(font_size=sp(17),
                                        on_release=lambda *a: self.app.go('menu'))
        for button in (self.rename_button, self.avatar_button, self.reset_button, self.back_button):
            actions.add_widget(button)

        for widget in (self.title, body, actions):
            panel.add_widget(widget)
        self.add_widget(panel)

    # ---------- отображение ----------
    def refresh_texts(self):
        storage = self.app.storage
        user = self.app.user
        if user is None:
            return
        total = user['wins'] + user['losses'] + user['ties']
        rate = user['wins'] / total * 100 if total > 0 else 0.0

        self.title.text = t('my_profile')
        self.avatar.source = self.app.avatar_source(user)
        self.name_label.text = storage.display_name(user)
        self.rank_icon.source = self.app.rank_source(storage.rank(user))
        self.login_label.text = f"{t('login_label')}: {user['username']}"
        remaining = storage.lock_remaining(user)
        self.lock_label.text = (f"{t('locked_short')}: {duration_text(remaining)}"
                                if remaining > 0 else '')

        self.header.text = t('statistics')
        self.rows[0].text = f"{t('balance')}: ${user['balance']}"
        self.rows[1].text = f"{t('wins')}: {user['wins']}"
        self.rows[2].text = f"{t('losses')}: {user['losses']}"
        self.rows[3].text = f"{t('ties')}: {user['ties']}"
        self.rows[4].text = f"{t('win_rate')}: {rate:.1f}%"
        decisions, rounds = self.app.dataset.counts()
        self.dataset_label.text = f"{t('dataset_info')}: {decisions} / {rounds}"

        self.rename_button.text = t('change_name')
        self.avatar_button.text = t('change_avatar')
        self.reset_button.text = t('reset_avatar')
        self.back_button.text = t('back')

    # ---------- имя ----------
    def _fit_name(self, label, size):
        label.width = size[0]
        self.name_row.width = self.rank_icon.width + dp(6) + size[0]
    
    def open_rename(self, *args):
        user = self.app.user
        self._dialog = RenameDialog(self.app.storage.display_name(user), self.save_name)
        self._dialog.open()

    def save_name(self, text, dialog):
        error = self.app.storage.set_display_name(self.app.user, text)
        if error:
            self.app.show_alert(t(error))
            return
        dialog.dismiss()
        self.refresh_texts()

    # ---------- аватар ----------
    def choose_avatar(self, *args):
        self.app.picker.pick(self._avatar_chosen, self._avatar_failed)

    def _avatar_chosen(self, path):
        self.app.storage.set_avatar(self.app.user, path)
        self.refresh_texts()

    def _avatar_failed(self, message):
        self.app.show_alert(message or t('avatar_failed'))

    def reset_avatar(self, *args):
        self.app.storage.clear_avatar(self.app.user)
        self.refresh_texts()
