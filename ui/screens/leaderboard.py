"""Таблица лидеров: аватар, имя (крупно) и логин (мелко, серым), прокрутка пальцем."""
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView

from core.i18n import t
from .. import theme
from ..widgets import AvatarImage, LeaderRow, Lbl, StyledButton, RankIcon
from .base import BaseScreen, make_panel

COLUMNS = (0.1, 0.46, 0.2, 0.24)   # место, игрок (аватар+имя+логин), процент побед, баланс
ALIGN = ('center', 'left', 'center', 'center')
ROW_H = dp(46)
AVATAR_SIZE = dp(34)
RANK_SIZE = dp(26)


class LeaderboardScreen(BaseScreen):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        panel = make_panel(theme.WIDE_PANEL_W)
        self.title = Lbl(size_hint_y=None, height=theme.TITLE_H, font_size=theme.TITLE_FS,
                         color=theme.GOLD, outline_width=2, outline_color=theme.BLACK)
        self.header = LeaderRow(bg=[0, 0, 0, 0])
        self.header_labels = []
        for index, width in enumerate(COLUMNS):
            label = Lbl(size_hint_x=width, font_size=sp(17), color=theme.GOLD,
                        halign=ALIGN[index])
            self.header_labels.append(label)
            self.header.add_widget(label)

        self.grid = GridLayout(cols=1, spacing=dp(3), size_hint_y=None)
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
        self.scroll.add_widget(self.grid)

        self.back_button = StyledButton(size_hint_y=None, height=theme.BUTTON_H,
                                        on_release=lambda *a: self.app.go('menu'))
        for widget in (self.title, self.header, self.scroll, self.back_button):
            panel.add_widget(widget)
        self.add_widget(panel)

    def _player_cell(self, entry, rank):
        cell = BoxLayout(size_hint_x=COLUMNS[1], spacing=dp(8))
        cell.add_widget(AvatarImage(size_hint=(None, None), size=(AVATAR_SIZE, AVATAR_SIZE),
                                    pos_hint={'center_y': 0.5},
                                    source=entry['avatar'] or self.app.default_avatar))
        cell.add_widget(RankIcon(size_hint=(None, None), size=(RANK_SIZE, RANK_SIZE),
                         pos_hint={'center_y': 0.5},
                         source=self.app.rank_source(entry['rank'])))
        texts = BoxLayout(orientation='vertical')
        texts.add_widget(Lbl(text=entry['name'], halign='left', font_size=sp(16), shorten=True,
                             color=theme.GOLD if rank <= 3 else theme.WHITE))
        texts.add_widget(Lbl(text=entry['username'], halign='left', font_size=sp(11),
                             shorten=True, color=theme.GRAY))     # логин: мелко и серым
        cell.add_widget(texts)
        return cell

    def refresh_texts(self):
        self.title.text = t('leaderboard_title')
        for label, key in zip(self.header_labels,
                              ('rank', 'username_col', 'win_rate_col', 'balance')):
            label.text = t(key)
        self.back_button.text = t('back')

        self.grid.clear_widgets()
        rows = self.app.storage.leaderboard()
        if not rows:
            self.grid.add_widget(Lbl(text=t('no_data'), size_hint_y=None, height=dp(40),
                                     color=theme.GRAY))
            return
        for rank, entry in enumerate(rows, start=1):
            bg = [1, 1, 1, 0.08] if rank % 2 else [1, 1, 1, 0.03]
            row = LeaderRow(bg=bg, height=ROW_H)
            row.add_widget(Lbl(text=str(rank), size_hint_x=COLUMNS[0], font_size=sp(17),
                               halign=ALIGN[0], color=theme.WHITE))
            row.add_widget(self._player_cell(entry, rank))
            row.add_widget(Lbl(text=f"{entry['win_rate']:.1f}%", size_hint_x=COLUMNS[2],
                               font_size=sp(17), halign=ALIGN[2], color=theme.GREEN_TEXT))
            row.add_widget(Lbl(text=f"${entry['balance']}", size_hint_x=COLUMNS[3],
                               font_size=sp(17), halign=ALIGN[3], color=theme.GOLD))
            self.grid.add_widget(row)
