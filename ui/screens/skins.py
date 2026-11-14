"""Магазин скинов карт: прокручиваемый список и выдвижное превью пака."""
import os

from kivy.animation import Animation
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.uix.stencilview import StencilView

from core.i18n import t
from core.skins import SKINS
from .. import theme
from ..widgets import CARDS_DIR, Lbl, StyledButton, TouchBlocker
from .base import BaseScreen, make_panel

SLIDE_TIME = 0.32       # список уезжает влево и возвращается
PREVIEW_TIME = 0.38     # превью выезжает справа и проявляется
EXIT_FADE = 0.18        # превью гаснет перед возвратом списка
EXIT_SLIDE = 0.26       # превью уезжает вправо уже невидимым
ROW_H = dp(58)
ACTION_W = dp(120)


class SkinsScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        panel = make_panel(theme.PANEL_W)
        self.title = Lbl(size_hint_y=None, height=theme.TITLE_H, font_size=theme.TITLE_FS,
                         color=theme.GOLD, outline_width=2, outline_color=theme.BLACK)
        self.balance_label = Lbl(size_hint_y=None, height=dp(28), font_size=sp(22))

        # список скинов с вертикальной прокруткой
        self.list_box = BoxLayout(orientation='vertical', spacing=dp(6),
                                  size_hint_y=None, padding=(0, 0, 0, dp(4)))
        self.list_box.bind(minimum_height=self.list_box.setter('height'))
        self.list_scroll = ScrollView(size_hint=(None, None), do_scroll_x=False,
                                      bar_width=dp(4), scroll_type=['bars', 'content'])
        self.list_scroll.add_widget(self.list_box)

        # превью: картинка preview.png, название и описание пака
        self.preview = BoxLayout(orientation='vertical', size_hint=(None, None),
                                 padding=dp(4), spacing=dp(4), opacity=0)
        self.preview_name = Lbl(size_hint_y=None, height=dp(30), font_size=sp(24),
                                color=theme.GOLD)
        self.preview_image = Image(fit_mode='contain')
        self.preview_desc = Lbl(size_hint_y=None, height=dp(44), font_size=sp(16),
                                color=theme.LIGHT_GRAY)
        for widget in (self.preview_name, self.preview_image, self.preview_desc):
            self.preview.add_widget(widget)

        # сцена с обрезкой: список и превью ездят внутри неё, не выходя за панель
        self.content = StencilView(size_hint_y=1)
        self.content.add_widget(self.list_scroll)
        # блокируем касания, не выключая кнопки: disabled у ScrollView красит всех детей
        self.blocker = TouchBlocker(size_hint=(None, None), opacity=0)
        self.content.add_widget(self.blocker)
        self.content.add_widget(self.preview)
        self.content.bind(size=self._layout_content, pos=self._layout_content)

        self.back_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                        on_release=self.go_back)
        for widget in (self.title, self.balance_label, self.content, self.back_button):
            panel.add_widget(widget)
        self.add_widget(panel)

        self.preview_skin = None
        self._animating = False
        self.rows = []
        self.open_buttons = {}
        self.action_buttons = {}

    # ------------------------------------------------------------ список и превью
    def on_pre_enter(self, *args):
        super().on_pre_enter(*args)
        self._reset_view()

    def refresh_texts(self):
        user = self.app.user
        self.title.text = t('skins')
        self.balance_label.text = f"{t('balance')}: ${user['balance']}"
        self.back_button.text = t('back')

        self.rows = []
        self.open_buttons = {}
        self.action_buttons = {}
        self.list_box.clear_widgets()
        for skin in SKINS:
            owned = skin['id'] in user['skins']
            current = user.get('current_skin') == skin['id']
            row, open_button = self._make_row(skin, owned, current)
            self.rows.append((skin, row))
            self.open_buttons[skin['id']] = open_button
            self.list_box.add_widget(row)

        self.list_scroll.scroll_y = 1
        if self.preview_skin is not None:
            self._fill_preview(self.preview_skin)

    def _make_row(self, skin, owned, current):
        """Строка скина: слева название/цена, справа кнопка, поверх — зона просмотра."""
        row = FloatLayout(size_hint_y=None, height=ROW_H)
        info = BoxLayout(orientation='vertical', size_hint=(1, 1),
                         pos_hint={'x': 0, 'center_y': 0.5},
                         padding=(dp(6), 0, ACTION_W + dp(8), 0))
        info.add_widget(Lbl(text=t(skin['name_key']), halign='left', font_size=sp(21),
                            color=theme.GOLD, shorten=True))
        if owned:
            info.add_widget(Lbl(text=t('purchased'), halign='left', font_size=sp(16),
                                color=theme.GREEN_TEXT))
        else:
            info.add_widget(Lbl(text=f"${skin['price']}", halign='left', font_size=sp(16),
                                color=theme.YELLOW))
        row.add_widget(info)

        # прозрачная кнопка на всю строку: по ней открывается превью
        open_button = StyledButton(size_hint=(1, 1), pos_hint={'x': 0, 'y': 0},
                                   base_color=[0, 0, 0, 0],
                                   down_color=[1, 1, 1, 0.08],
                                   on_release=lambda *a, s=skin: self.open_preview(s))
        row.add_widget(open_button)

        # кнопка покупки/выбора лежит выше зоны просмотра
        if owned:
            action = StyledButton(text=t('selected') if current else t('select'),
                                  size_hint=(None, 1), width=ACTION_W,
                                  pos_hint={'right': 1, 'center_y': 0.5},
                                  disabled=current,
                                  on_release=lambda b, s=skin: self.select(s))
        else:
            action = StyledButton(text=t('buy'), size_hint=(None, 1), width=ACTION_W,
                                  pos_hint={'right': 1, 'center_y': 0.5},
                                  base_color=theme.BLUE, down_color=theme.LIGHT_BLUE,
                                  on_release=lambda b, s=skin: self.buy(s))
        row.add_widget(action)
        self.action_buttons[skin['id']] = action
        return row, open_button

    def _fill_preview(self, skin):
        self.preview_name.text = t(skin['name_key'])
        self.preview_desc.text = t(skin.get('desc_key', 'skin_desc_' + skin['id']))
        path = os.path.join(CARDS_DIR, skin['id'], 'preview.png')
        self.preview_image.source = path if os.path.exists(path) else ''

    def _layout_content(self, *args):
        w, h = self.content.size
        x, y = self.content.pos
        self.list_scroll.size = (w, h)
        self.preview.size = (w, h)
        self.blocker.size = (w, h)
        self.blocker.pos = (x, y)
        if self.preview_skin is None:
            self.list_scroll.pos = (x, y)
            self.preview.pos = (x + w, y)
        else:
            self.list_scroll.pos = (x - w, y)
            self.preview.pos = (x, y)

    def _reset_view(self):
        Animation.cancel_all(self.list_scroll)
        Animation.cancel_all(self.preview)
        self.preview_skin = None
        self._animating = False
        self.preview.opacity = 0
        self.blocker.opacity = 0
        self._layout_content()

    def open_preview(self, skin, *args):
        if self._animating or self.preview_skin is not None:
            return
        self._fill_preview(skin)
        self.preview_skin = skin
        w = self.content.width
        self.preview.pos = (self.content.x + w, self.content.y)
        self.preview.opacity = 0
        self.blocker.opacity = 1
        self._animating = True
        show = Animation(x=self.content.x, opacity=1,
                         duration=PREVIEW_TIME, t='out_cubic')
        show.bind(on_complete=self._opened)
        show.start(self.preview)
        Animation(x=self.content.x - w, duration=SLIDE_TIME,
                  t='out_cubic').start(self.list_scroll)

    def close_preview(self, *args):
        if self.preview_skin is None or self._animating:
            return
        self._animating = True
        self.blocker.opacity = 1
        w = self.content.width
        # сначала превью гаснет, и только потом список возвращается:
        # так картинка превью не накладывается на кнопки строк
        fade = Animation(opacity=0, duration=EXIT_FADE, t='in_quad')
        fade.bind(on_complete=self._start_list_return)
        fade.start(self.preview)
        Animation(x=self.content.x + w, duration=EXIT_SLIDE,
                  t='in_cubic').start(self.preview)

    def _start_list_return(self, *args):
        if self.preview_skin is None:
            return
        back = Animation(x=self.content.x, duration=SLIDE_TIME, t='out_cubic')
        back.bind(on_complete=self._closed)
        back.start(self.list_scroll)

    def _opened(self, *args):
        self._animating = False

    def _closed(self, *args):
        self.preview_skin = None
        self.preview.opacity = 0
        self.blocker.opacity = 0
        self._animating = False
        self._layout_content()

    # ------------------------------------------------------------ действия
    def go_back(self, *args):
        if self.preview_skin is not None:
            self.close_preview()
        else:
            self.app.go('menu')

    def handle_back(self):
        """Esc/«Назад»: если открыто превью — сначала закрываем его."""
        if self.preview_skin is None:
            return False
        if not self._animating:
            self.close_preview()
        return True

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
