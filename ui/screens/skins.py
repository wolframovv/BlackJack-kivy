"""Магазин скинов карт."""
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout

from core.i18n import t
from core.skins import SKINS
from .. import theme
from ..widgets import Lbl, StyledButton
from .base import BaseScreen, make_panel


class SkinsScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        panel = make_panel(theme.PANEL_W)
        self.title = Lbl(size_hint_y=None, height=theme.TITLE_H, font_size=theme.TITLE_FS, color=theme.GOLD,
                         outline_width=2, outline_color=theme.BLACK)
        self.balance_label = Lbl(size_hint_y=None, height=dp(28), font_size=sp(22))
        self.list_box = BoxLayout(orientation='vertical', spacing=dp(6))
        self.back_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                        on_release=lambda *a: self.app.go('menu'))
        for widget in (self.title, self.balance_label, self.list_box, self.back_button):
            panel.add_widget(widget)
        self.add_widget(panel)

    def refresh_texts(self):
        user = self.app.user
        self.title.text = t('skins')
        self.balance_label.text = f"{t('balance')}: ${user['balance']}"
        self.back_button.text = t('back')

        self.list_box.clear_widgets()
        for skin in SKINS:
            owned = skin['id'] in user['skins']
            current = user.get('current_skin') == skin['id']

            row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
            info = BoxLayout(orientation='vertical')
            info.add_widget(Lbl(text=t(skin['name_key']), halign='left', font_size=sp(21),
                                color=theme.GOLD))
            if owned:
                info.add_widget(Lbl(text=t('purchased'), halign='left', font_size=sp(16),
                                    color=theme.GREEN_TEXT))
            else:
                info.add_widget(Lbl(text=f"${skin['price']}", halign='left', font_size=sp(16),
                                    color=theme.YELLOW))
            row.add_widget(info)

            if owned:
                button = StyledButton(text=t('selected') if current else t('select'),
                                      size_hint_x=None, width=dp(120), disabled=current,
                                      on_release=lambda b, s=skin: self.select(s))
            else:
                button = StyledButton(text=t('buy'), size_hint_x=None, width=dp(120),
                                      base_color=theme.BLUE, down_color=theme.LIGHT_BLUE,
                                      on_release=lambda b, s=skin: self.buy(s))
            row.add_widget(button)
            self.list_box.add_widget(row)

    def buy(self, skin):
        user = self.app.user
        if user['balance'] < skin['price']:
            self.app.show_alert(t('not_enough_money'))
            return
        user['balance'] -= skin['price']
        user['skins'].append(skin['id'])
        self.app.storage.save()
        self.refresh_texts()

    def select(self, skin):
        user = self.app.user
        if skin['id'] in user['skins']:
            user['current_skin'] = skin['id']
            self.app.storage.save()
            self.refresh_texts()
