"""Соревновательный режим: стол на пять игроков (ты и четыре бота) со спец-картами.

Правила живут в core.competitive.Table: раунд там генератор шагов. Этот экран берёт у
генератора следующий шаг и показывает его анимациями:
  * Notice (раздали карту, вытянули спец-карту...): играем анимацию, ждём и берём следующий шаг;
  * Request (нужно решение): у бота экран «думает» случайное время (THINK_*), у игрока
    показывает кнопки или подсвечивает тех, кого можно выбрать, и ждёт нажатия.
Все карты на экране приводятся в соответствие со столом функцией _sync: что появилось, то
вылетает из колоды, что переехало, то плавно едет на новое место.
"""
import random
from functools import partial

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from core.bots import PROFILES, make_bot
from core.cards import cards_value
from core.competitive import (Config, Controller, DEALER, FixedCard, Player, Request,
                              SPECIAL_KINDS, SPECIAL_TITLES, Table)
from core.i18n import duration_text, t
from .. import theme
from ..sound import sounds
from ..widgets import (AvatarImage, CardWidget, ConfirmDialog, DimOverlay, HighlightBox, Lbl,
                       OverlayPanel, SpecialCardWidget, StyledButton, TargetZone, TurnBoard,
                       VerticalShade)
from .base import BaseScreen

CONFIG = Config(decks=1, specials=SPECIAL_KINDS * 2)    # вариант C: 52 карты + 18 спец-карт
SEATS = 5                                               # место 0 — игрок, 1..4 — боты
BOT_NAMES = ('Макс', 'Лиза', 'Артём', 'Соня', 'Дима', 'Катя')
CARD_RATIO = 120.0 / 168.0       # ширина / высота карты

THINK_ACTION = (0.6, 1.4)        # сколько бот «думает» над обычным ходом, с
THINK_SPECIAL = (1.0, 3.0)       # и над решением по спец-карте (выбор жертвы и т.п.), с
DEAL_PAUSE = 0.28                # пауза после каждой розданной карты
CARD_MOVE = 0.38                 # полёт и перестановка карты
SPECIAL_GROW = 1.0               # спец-карта медленно растёт в центре
SPECIAL_HOLD = 0.3               # пауза после того, как она выросла
EFFECT_HOLD = 1.0                # сколько показывается результат эффекта
SPECIAL_ASKS = ('snc', 'min', 'one_for_all', 'swap', 'dealer_card')   # запросы по спец-картам
ACTION_KEYS = ('hit', 'stand', 'double', 'split', 'surrender')   # кнопки действий слева направо
OFFSCREEN = -100000              # куда уезжают спрятанные кнопки (см. _place_buttons)

GOLD_HEX = 'ffd700'


class TableScreen(BaseScreen):
    animated_background = theme.PARTICLES_IN_GAME
    game_background = True               # etc/game_bg.jpg
    rng_factory = random.Random          # источник случайности стола (в тестах подменяется)

    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self.next_bet = None
        self.bet = 0
        self.engine = None              # core.competitive.Table
        self.players = []
        self._iter = None               # генератор раунда
        self._run = 0                   # номер запуска: старые отложенные вызовы игнорируются
        self._skin = 'default'
        self._cards = {}                # id(карта) -> (карта, виджет, ключ порядка)
        self._special = None            # большая спец-карта в центре
        self._turn = None               # (игрок, рука), чей сейчас ход
        self._request = None            # запрос, который ждёт ответа игрока
        self._choice_actions = []
        self._mode = 'actions'          # что показано внизу: кнопки действий или выбора
        self._choice_count = 0
        self._outcomes = {}
        self._mirror = False            # переносить ли баланс стола в профиль игрока
        self._over = False
        self._leave_dialog = None
        self._m = {}
        self._name_widths = {}          # место -> (текст, шрифт, ширина подписи)

        # слои: затемнения по краям, колода и карты, уходящие карты, большая спец-карта
        self.layer = Widget()
        self.fade_layer = Widget()
        self.spec_layer = Widget()
        self.deck_widgets = [CardWidget(face_up=False) for _ in range(5)]
        self.shade = VerticalShade(size_hint=(None, None))      # затемнение сверху экрана
        self.shade_bottom = VerticalShade(size_hint=(None, None), bottom=True)   # и снизу
        for widget in (self.shade, self.shade_bottom, self.layer, self.fade_layer):
            self.add_widget(widget)

        # подписи мест: 0 — игрок, 1..4 — боты
        self.seat_avatar = [AvatarImage(size_hint=(None, None)) for _ in range(SEATS)]
        self.seat_name = [Lbl(size_hint=(None, None), halign='center', font_size=sp(16),
                              color=theme.WHITE, shorten=True) for _ in range(SEATS)]
        self.seat_info = [Lbl(size_hint=(None, None), markup=True, font_size=sp(13),
                              color=theme.WHITE) for _ in range(SEATS)]
        self.dealer_label = Lbl(size_hint=(None, None), markup=True, font_size=sp(17),
                                color=theme.GOLD)
        for widget in (*self.seat_avatar, *self.seat_name, *self.seat_info, self.dealer_label):
            self.add_widget(widget)

        self.board = TurnBoard(size_hint=(None, None))      # табло «кто ходит»
        self.add_widget(self.board)
        self.turn_box = HighlightBox(size_hint=(None, None), opacity=0)
        self.add_widget(self.turn_box)
        self.flashes = [HighlightBox(size_hint=(None, None), opacity=0) for _ in range(8)]
        self.zones = [TargetZone(size_hint=(None, None), opacity=0) for _ in range(12)]
        for widget in (*self.flashes, *self.zones):
            self.add_widget(widget)

        self.add_widget(self.spec_layer)
        self.caption = Lbl(size_hint=(None, None), markup=True, font_size=sp(15),
                           color=theme.WHITE)
        self.add_widget(self.caption)

        # кнопки: действия, выбор по спец-карте и выход
        self.buttons = {}
        for key, color, down in (('hit', theme.DARK_GREEN, theme.GREEN),
                                 ('stand', theme.DARK_RED, theme.RED),
                                 ('double', theme.BLUE, theme.LIGHT_BLUE),
                                 ('split', [0.78, 0.59, 0, 1], theme.YELLOW),
                                 ('surrender', [0.55, 0.27, 0.07, 1], [0.75, 0.4, 0.1, 1])):
            button = StyledButton(size_hint=(None, None), base_color=color, down_color=down,
                                  font_size=sp(18), on_release=partial(self._press_action, key))
            self.buttons[key] = button
            self.add_widget(button)
        self.choice_buttons = []
        for index in range(3):
            button = StyledButton(size_hint=(None, None), font_size=sp(17), opacity=0,
                                  disabled=True,
                                  on_release=partial(self._press_choice, index))
            self.choice_buttons.append(button)
            self.add_widget(button)
        self.menu_button = StyledButton(size_hint=(None, None), base_color=theme.DARK_GRAY,
                                        down_color=theme.GRAY, font_size=sp(18),
                                        on_release=self.ask_leave)
        self.add_widget(self.menu_button)

        # затемнение и панель результата лежат выше всего
        self.dim = DimOverlay(size_hint=(None, None), opacity=0)
        self.add_widget(self.dim)
        self.result_panel = OverlayPanel(size_hint=(None, None), opacity=0, padding=dp(14))
        self.result_label = Lbl(font_size=sp(24), color=theme.GOLD)
        self.result_balance = Lbl(size_hint_y=None, height=dp(30), font_size=sp(20),
                                  color=theme.WHITE)
        self.result_note = Lbl(size_hint_y=None, height=dp(26), font_size=sp(16),
                               color=theme.RED_TEXT)
        row = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)
        self.result_buttons = {}
        for key, color, down, handler in (
            ('new_game', theme.DARK_GREEN, theme.GREEN,
             lambda *a: self.app.go_betting('competitive')),
            ('menu', theme.DARK_GRAY, theme.GRAY, lambda *a: self.app.go('menu')),
        ):
            button = StyledButton(base_color=color, down_color=down, on_release=handler)
            self.result_buttons[key] = button
            row.add_widget(button)
        for widget in (self.result_label, self.result_balance, self.result_note, row):
            self.result_panel.add_widget(widget)
        self.add_widget(self.result_panel)

        self._build_deck()
        self.bind(size=self._on_size)

    # ------------------------------------------------------------ жизненный цикл
    def begin(self, bet):
        """Вызывается перед переходом на экран: раунд стартует в on_enter."""
        self.next_bet = bet

    def on_pre_enter(self, *args):
        super().on_pre_enter(*args)
        if self.next_bet is not None:
            self._reset()
        self._relayout()

    def on_enter(self, *args):
        if self.next_bet is None:
            return
        bet, self.next_bet = self.next_bet, None
        self._start_round(bet)

    def on_leave(self, *args):
        if self._leave_dialog is not None:
            self._leave_dialog.dismiss()
        self._run += 1
        self._iter = None
        self._request = None
        self.app.storage.save()

    def refresh_texts(self):
        for key, button in self.buttons.items():
            button.text = t(key)
        self.menu_button.text = t('menu')
        for key, button in self.result_buttons.items():
            button.text = t(key)
        if self.engine is not None:
            self._refresh_labels()

    def _reset(self):
        self._run += 1
        self._iter = None
        self._request = None
        self._over = False
        self._mirror = False
        self._turn = None
        self._outcomes = {}
        self._name_widths = {}
        self.engine = None
        self.players = []
        for _, widget, _ in self._cards.values():
            Animation.cancel_all(widget)
        self._cards = {}
        self.layer.clear_widgets()
        self.fade_layer.clear_widgets()
        self._remove_special()
        self._build_deck()
        for widget in (self.dim, self.result_panel, self.turn_box):
            widget.opacity = 0
        self.caption.text = ''
        self.result_note.text = ''
        self._hide_zones()
        self._set_actions(())
        self.board.set_text('', animate=False)
        for index in range(SEATS):
            self.seat_info[index].text = ''
            self.seat_name[index].text = ''
        self.dealer_label.text = t('dealer')

    def _build_deck(self):
        for widget in self.deck_widgets:
            self.layer.add_widget(widget)

    def _start_round(self, bet):
        user = self.app.user
        self._skin = user.get('current_skin', 'default')
        self.bet = bet
        rng = self.rng_factory()
        names = rng.sample(BOT_NAMES, SEATS - 1)
        profiles = rng.sample(list(PROFILES), SEATS - 1)
        human = Player(self.app.storage.display_name(user), Controller(),
                       user['balance'] + bet)          # ставка уже списана: стол спишет её сам
        bots = [Player(name, make_bot(profile, random.Random(rng.random()), bet), bet * 100)
                for name, profile in zip(names, profiles)]
        self.players = [human] + bots
        self.engine = Table(self.players, CONFIG, rng)
        self.engine.button = rng.randrange(SEATS)
        for index in range(SEATS):
            self.seat_name[index].text = self.players[index].name
            self.seat_avatar[index].source = (self.app.avatar_source(user) if index == 0
                                              else self.app.default_avatar)
        self._relayout()
        self._iter = self.engine.iter_round()
        self._resume(None)

    # ------------------------------------------------------------ геометрия
    def _on_size(self, *args):
        self._relayout()

    @staticmethod
    def _place(widget, x, y, w, h):
        widget.pos = (x, y)
        widget.size = (w, h)

    def _metrics(self):
        W, H = self.width, self.height
        seats = []
        gap = dp(4)
        # игрок: внизу по центру, карты крупнее всех. Над веером по центру — одна строка
        # «аватар + имя» (выше неё итог руки и ставка).
        ch = 0.17 * H
        d = 0.055 * H
        x, w, fan_y = 0.29 * W, 0.42 * W, 0.135 * H
        header_y = fan_y + ch + 0.004 * H
        seats.append({'x': x, 'y': fan_y, 'w': w, 'cw': ch * CARD_RATIO, 'ch': ch,
                      'header_y': header_y, 'header_h': d, 'avatar_d': d,
                      'name_gap': gap, 'name_cap': 0.36 * W,
                      'info': (x, header_y + d + 0.004 * H, w, 0.04 * H)})
        # боты: по два слева и справа по дуге (места 1 и 2 слева, 3 и 4 справа)
        ch = 0.115 * H
        d = 0.055 * H
        for cx, y0 in ((0.115 * W, 0.20 * H), (0.16 * W, 0.56 * H),
                       (0.84 * W, 0.56 * H), (0.885 * W, 0.20 * H)):
            w = 0.2 * W
            x = cx - w / 2
            fan_y = y0 + 0.05 * H
            header_y = fan_y + ch + 0.008 * H
            seats.append({'x': x, 'y': fan_y, 'w': w, 'cw': ch * CARD_RATIO, 'ch': ch,
                          'header_y': header_y, 'header_h': d, 'avatar_d': d,
                          'name_gap': gap, 'name_cap': max(dp(20), w - d - dp(12)),
                          'info': (x, y0, w, 0.048 * H)})
        dealer_ch = 0.145 * H
        deck_w = dealer_ch * CARD_RATIO
        big_h = 0.26 * H
        return {
            'W': W, 'H': H, 'seats': seats, 'bar_top': 0.105 * H,
            'dealer': {'x': 0.35 * W, 'y': 0.725 * H, 'w': 0.30 * W, 'cw': dealer_ch * CARD_RATIO,
                       'ch': dealer_ch},
            'deck': (W / 2 - deck_w / 2, 0.42 * H), 'deck_size': (deck_w, dealer_ch),
            'big': (big_h * CARD_RATIO, big_h), 'big_center': (W / 2, 0.59 * H),
        }

    def _relayout(self):
        m = self._m = self._metrics()
        W, H = m['W'], m['H']
        if not W or not H:
            return
        for index in range(len(m['seats'])):
            self._place_seat(index)
        dealer = m['dealer']
        self._place(self.dealer_label, dealer['x'], 0.872 * H, dealer['w'], 0.045 * H)
        self._place(self.board, 0.33 * W, 0.92 * H, 0.34 * W, 0.07 * H)
        self._place(self.caption, 0.15 * W, 0.405 * H, 0.7 * W, 0.05 * H)
        self._place(self.dim, 0, 0, W, H)
        self._place(self.result_panel, W * 0.25, H * 0.25, W * 0.5, H * 0.5)

        self._place(self.shade, 0, 0.72 * H, W, 0.28 * H)
        self._place(self.shade_bottom, 0, 0, W, 0.28 * H)
        self._place(self.menu_button, 0.015 * W, 0.915 * H, 0.1 * W, 0.07 * H)
        self._place_buttons()

        dw, dh = m['deck_size']
        for index, widget in enumerate(self.deck_widgets):
            widget.size = (dw, dh)
            widget.pos = (m['deck'][0] + index * dp(1.5), m['deck'][1] + index * dp(1.5))
        if self.engine is not None:
            self._sync(animate=False)
            self._refresh_labels()
            self._place_turn_box()

    def _place_seat(self, index):
        """Ставит аватар и имя одной строкой, отцентрованной над веером карт."""
        if not self._m:
            return
        seat = self._m['seats'][index]
        d, gap, height = seat['avatar_d'], seat['name_gap'], seat['header_h']
        width, shortened = self._measure_name(index, seat['name_cap'])
        left = seat['x'] + seat['w'] / 2 - (d + gap + width) / 2
        self._place(self.seat_avatar[index], left, seat['header_y'], d, height)
        name = self.seat_name[index]
        self._place(name, left + d + gap, seat['header_y'], width, height)
        name.text_size = (width, height)      # текст по центру строки, по высоте тоже
        name.shorten = shortened
        self._place(self.seat_info[index], *seat['info'])

    def _measure_name(self, index, cap):
        """Ширина подписи по её тексту. В настоящем Kivy — из текстуры, в тестах — оценка.

        Подпись не должна разъезжаться на всю ширину места: иначе аватар и имя снова
        окажутся далеко друг от друга. Слишком длинное имя подрезается многоточием."""
        name = self.seat_name[index]
        key = (name.text, name.font_size)
        cached = self._name_widths.get(index)
        if cached is not None and cached[0] == key:
            width = cached[1]
        else:
            width = 0
            update = getattr(name, 'texture_update', None)
            if update is not None:              # настоящий Kivy: меряем текстуру
                name.text_size = (None, None)
                name.shorten = False
                update()
                width = name.texture_size[0]
            if width <= 0:                      # заглушка Kivy или пустая подпись
                width = len(name.text) * name.font_size * 0.4
            width = max(width, dp(12))
            self._name_widths[index] = (key, width)
        return min(width, cap), width > cap

    def _row_rects(self, count):
        """Ряд из count одинаковых кнопок по центру экрана внизу."""
        W, H = self._m['W'], self._m['H']
        width, gap, height = 0.15 * W, 0.01 * W, 0.09 * H
        x0 = W / 2 - (count * width + (count - 1) * gap) / 2
        return [(x0 + i * (width + gap), 0.015 * H, width, height) for i in range(count)]

    def _place_buttons(self):
        """Показанный набор кнопок стоит по центру, спрятанный уезжает за экран. Нельзя
        просто делать его прозрачным и отключённым: в Kivy отключённая кнопка поглощает
        нажатия в своих границах и закрыла бы кнопки под собой."""
        if not self._m or not self._m['W']:
            return
        actions = self._row_rects(len(ACTION_KEYS))
        choices = self._row_rects(max(1, self._choice_count))
        for index, key in enumerate(ACTION_KEYS):
            rect = actions[index] if self._mode == 'actions' else None
            self._place_or_hide(self.buttons[key], rect)
        for index, button in enumerate(self.choice_buttons):
            shown = self._mode == 'choices' and index < self._choice_count
            self._place_or_hide(button, choices[index] if shown else None)

    def _place_or_hide(self, button, rect):
        if rect is None:
            button.pos = (OFFSCREEN, OFFSCREEN)
        else:
            self._place(button, *rect)

    def _geom(self, seat):
        return self._m['dealer'] if seat == DEALER else self._m['seats'][seat]

    def _hands_of(self, seat):
        return [self.engine.dealer] if seat == DEALER else self.engine.players[seat].hands

    def _slot(self, seat, hand, hand_count, index, count):
        """Где лежит карта: (x, y, угол). Карты руки лежат веером."""
        g = self._geom(seat)
        region_w = g['w'] / max(1, hand_count)
        x0 = g['x'] + hand * region_w
        cw = g['cw']
        step = min(cw * 0.55, (region_w - cw) / (count - 1)) if count > 1 else 0.0
        left = x0 + (region_w - (cw + step * (count - 1))) / 2
        mid = (count - 1) / 2.0
        x = left + index * step
        y = g['y'] - (index - mid) ** 2 * g['ch'] * 0.012     # края веера чуть ниже
        angle = (mid - index) * 5.0 if count > 1 else 0.0
        return x, y, angle

    def _hand_rect(self, seat, hand):
        """Прямоугольник вокруг руки (для рамок и нажатий)."""
        hands = self._hands_of(seat)
        g = self._geom(seat)
        count = max(1, len(hands[hand].cards))
        first = self._slot(seat, hand, len(hands), 0, count)
        last = self._slot(seat, hand, len(hands), count - 1, count)
        pad = dp(4)
        y = min(first[1], last[1])
        return self._clamp_rect((first[0] - pad, y - pad, last[0] + g['cw'] - first[0] + 2 * pad,
                                 g['ch'] + 2 * pad))

    def _clamp_rect(self, rect):
        """Рамки не должны заезжать на ряд кнопок: нижний край не ниже верха кнопок."""
        x, y, w, h = rect
        floor = self._m['bar_top'] + dp(4)
        if y < floor:
            h -= floor - y
            y = floor
        return x, y, w, h

    # ------------------------------------------------------------ карты на столе
    def _make_widget(self, card, hidden):
        if isinstance(card, FixedCard):                 # карта «среднее»: число и подпись AVG
            widget = CardWidget(rank='avg', suit='', skin=self._skin, face_up=True)
            widget.fallback_text = f"{card.value}\nAVG"
            return widget
        return CardWidget(rank=card.rank, suit=card.suit, skin=self._skin,
                          face_up=not hidden)

    def _sync(self, animate=True, spawn=None):
        """Приводит карты на экране в соответствие со столом: новые вылетают из колоды
        (или из руки spawn), лишние исчезают, остальные плавно переезжают."""
        eng = self.engine
        if eng is None or not self._m:
            return
        wanted = {}
        for seat in [DEALER] + list(range(len(eng.players))):
            hands = self._hands_of(seat)
            for j, hand in enumerate(hands):
                count = len(hand.cards)
                for k, card in enumerate(hand.cards):
                    wanted[id(card)] = (card, seat, j, len(hands), k, count)
        for key in [k for k in self._cards if k not in wanted]:
            _, widget, _ = self._cards.pop(key)
            self._fade_out(widget)

        origin = None
        if spawn is not None and spawn[0] < len(eng.players) and \
                spawn[1] < len(eng.players[spawn[0]].hands) and \
                eng.players[spawn[0]].hands[spawn[1]].cards:
            rect = self._hand_rect(*spawn)
            origin = (rect[0] + rect[2] / 2, rect[1])
        for key, (card, seat, j, hands_count, k, count) in wanted.items():
            x, y, angle = self._slot(seat, j, hands_count, k, count)
            g = self._geom(seat)
            hidden = seat == DEALER and k == 1 and eng.hole_hidden
            entry = self._cards.get(key)
            if entry is None:
                widget = self._make_widget(card, hidden)
                widget.pos = origin if (origin and animate) else (
                    self._m['deck'] if animate else (x, y))
                self.layer.add_widget(widget)
            else:
                widget = entry[1]
            widget.size = (g['cw'], g['ch'])
            self._cards[key] = (card, widget, (seat if seat != DEALER else -1, j, k))
            Animation.cancel_all(widget)
            if animate:
                Animation(x=x, y=y, angle=angle, duration=CARD_MOVE, t='out_cubic').start(widget)
            else:
                widget.pos = (x, y)
                widget.angle = angle
        self._restack()

    def _restack(self):
        """Порядок отрисовки: карты правее лежат выше (как в веере)."""
        ordered = sorted(self._cards.values(), key=lambda entry: entry[2])
        self.layer.clear_widgets()
        for widget in self.deck_widgets:
            self.layer.add_widget(widget)
        for _, widget, _ in ordered:
            self.layer.add_widget(widget)

    def _fade_out(self, widget):
        if widget.parent is not None:
            widget.parent.remove_widget(widget)
        self.fade_layer.add_widget(widget)
        Animation.cancel_all(widget)
        animation = Animation(opacity=0, duration=0.35)
        animation.bind(on_complete=lambda *a: self._drop(widget))
        animation.start(widget)

    def _drop(self, widget):
        if widget.parent is not None:
            widget.parent.remove_widget(widget)

    # ------------------------------------------------------------ большая спец-карта
    def _show_special(self, kind):
        self._remove_special()
        m = self._m
        widget = SpecialCardWidget(kind=kind, face_up=False, skin=self._skin)
        widget.size = m['deck_size']
        widget.pos = m['deck']
        self.spec_layer.add_widget(widget)
        self._special = widget
        big_w, big_h = m['big']
        cx, cy = m['big_center']
        Animation(x=cx - big_w / 2, y=cy - big_h / 2, width=big_w, height=big_h,
                  duration=SPECIAL_GROW, t='out_cubic').start(widget)
        run = self._run
        Clock.schedule_once(lambda dt: widget.flip_to(True) if run == self._run else None,
                            SPECIAL_GROW * 0.45)
        sounds.play('card')

    def _hide_special(self, *args):
        widget = self._special
        if widget is None:
            return
        self._special = None
        Animation.cancel_all(widget)
        animation = Animation(opacity=0, duration=0.35)
        animation.bind(on_complete=lambda *a: self._drop(widget))
        animation.start(widget)
        self.caption.text = ''

    def _remove_special(self):
        if self._special is not None:
            Animation.cancel_all(self._special)
            self._drop(self._special)
            self._special = None
        self.spec_layer.clear_widgets()

    # ------------------------------------------------------------ подписи и рамки
    def _name(self, seat):
        return t('dealer') if seat == DEALER else self.players[seat].name

    def _set_turn(self, text, animate=True):
        self.board.set_text(text, animate)

    def _place_turn_box(self):
        if self._turn is None or self.engine is None:
            self.turn_box.opacity = 0
            return
        seat, hand = self._turn
        hands = self._hands_of(seat)
        if hand >= len(hands) or not hands[hand].cards:
            self.turn_box.opacity = 0
            return
        self._place(self.turn_box, *self._hand_rect(seat, hand))
        self.turn_box.opacity = 1

    def _refresh_labels(self):
        eng = self.engine
        if eng is None:
            return
        for index, player in enumerate(eng.players):
            parts = []
            for j, hand in enumerate(player.hands):
                text = f"{cards_value(hand.cards)} | ${hand.bet}"
                result = self._outcomes.get((index, j))
                if result is not None:
                    if result['outcome'] == 'blackjack':
                        text += f"  [color={GOLD_HEX}]BLACKJACK[/color]"
                    elif result['outcome'] == 'surrender':
                        text += f"  [color=ffa050]{t('surrender_badge')}[/color]"
                    text += '  ' + self._outcome_text(result)
                elif hand.natural:
                    text += f"  [color={GOLD_HEX}]BLACKJACK[/color]"
                elif hand.surrendered:
                    text += f"  [color=ffa050]{t('surrender_badge')}[/color]"
                elif not hand.is_active:
                    text += "  [color=ff4040]BUST[/color]"
                elif hand.is_stand:
                    text += f"  [color=a0a0a0]{t('stand').upper()}[/color]"
                parts.append(text)
            self.seat_info[index].text = '   '.join(parts)
        self.seat_name[0].text = f"{eng.players[0].name}   ${eng.players[0].balance}"
        self._place_seat(0)             # у игрока в подписи ещё и баланс: ширина меняется
        dealer = eng.dealer
        if not dealer.cards:
            self.dealer_label.text = t('dealer')
        elif eng.hole_hidden:
            self.dealer_label.text = f"{t('dealer')}   {t('visible')}: {dealer.cards[0].value}"
        else:
            self.dealer_label.text = f"{t('dealer')}   {t('total')}: {dealer.value}"

    @staticmethod
    def _outcome_text(result):
        net = result['payout'] - result['bet']
        if result['outcome'] in ('win', 'blackjack'):
            return f"[color=50dc50]+${net}[/color]"
        if result['outcome'] == 'push':
            return "[color=ffff00]=[/color]"
        return f"[color=ff5050]-${result['bet'] - result['payout']}[/color]"

    def _flash(self, seat, hand):
        """Короткая вспышка рамки вокруг руки, на которую подействовала карта."""
        hands = self._hands_of(seat)
        if hand >= len(hands) or not hands[hand].cards:
            return
        for box in self.flashes:
            if box.opacity <= 0.01:
                self._place(box, *self._hand_rect(seat, hand))
                box.opacity = 1
                Animation.cancel_all(box)
                Animation(opacity=0, duration=EFFECT_HOLD, t='in_quad').start(box)
                return

    def _effect_text(self, info):
        kind, detail = info['kind'], info['info']
        extra = ''
        note = {'declined': 'eff_declined', 'no_target': 'eff_no_target',
                'no_money': 'eff_no_money'}.get(detail)
        names = ', '.join(self._name(i) for i in info['targets'])
        if note:
            extra = t(note)
        elif kind in ('min', 'min_plus'):
            extra = t('eff_self') if detail == 'self' else f"{t('eff_other')}: {names}"
        elif kind == 'swap':
            extra = names
        elif kind == 'one_for_all':
            extra = t(detail)
        text = f"[color={GOLD_HEX}]{SPECIAL_TITLES[kind]}[/color]  {self._name(info['actor'])}"
        return text + (f": {extra}" if extra else '')

    # ------------------------------------------------------------ ход раунда
    def _resume(self, answer=None):
        """Берёт у раунда следующий шаг и показывает его."""
        if self._iter is None:
            return
        try:
            step = self._iter.send(answer)
        except StopIteration as stop:
            self._iter = None
            self._finish(stop.value)
            return
        if isinstance(step, Request):
            self._on_request(step)
        else:
            handler = getattr(self, '_n_' + step.kind)
            delay = handler(step.info) or 0.0
            if self._mirror:
                self.app.user['balance'] = self.players[0].balance
            self._after(delay)

    def _after(self, delay, answer=None):
        run = self._run
        Clock.schedule_once(lambda dt: self._tick(run, answer), delay)

    def _tick(self, run, answer):
        if run == self._run:
            self._resume(answer)

    # ---- уведомления ----
    def _n_start(self, info):
        self._set_turn(t('dealing_cards'), animate=False)
        return 0.3

    def _n_bets(self, info):
        self._mirror = True
        self._refresh_labels()
        return 0.2

    def _n_deal(self, info):
        sounds.play('card')
        self._sync()
        self._refresh_labels()
        return DEAL_PAUSE

    def _n_turn(self, info):
        seat, hand = info['player'], info['hand']
        name = self._name(seat)
        count = len(self.engine.players[seat].hands)
        if count > 1:
            name += f" ({hand + 1}/{count})"
        self._set_turn(name)
        self._turn = (seat, hand)
        self._place_turn_box()
        self._refresh_labels()
        return 0.55

    def _n_action(self, info):
        self._refresh_labels()
        return 0.12 if info['action'] == 'hit' else 0.4

    def _n_surrender(self, info):
        self._refresh_labels()
        self._place_turn_box()
        return 0.5

    def _n_split(self, info):
        sounds.play('card')
        self._sync()
        self._refresh_labels()
        self._place_turn_box()
        return 0.55

    def _n_hit_card(self, info):
        sounds.play('card')
        self._sync()
        self._refresh_labels()
        self._place_turn_box()
        return 0.5

    def _n_special(self, info):
        self._show_special(info['kind'])
        self.caption.text = (f"{self._name(info['player'])}: [color={GOLD_HEX}]"
                             f"{SPECIAL_TITLES[info['kind']]}[/color]  "
                             f"{t('spec_desc_' + info['kind'])}")
        return SPECIAL_GROW + SPECIAL_HOLD

    def _n_effect(self, info):
        self._sync(spawn=info['origin'])
        self._refresh_labels()
        self._place_turn_box()
        self.caption.text = self._effect_text(info)
        for seat, hand in info['hands']:
            self._flash(seat, hand)
        run = self._run
        Clock.schedule_once(lambda dt: self._hide_special() if run == self._run else None,
                            EFFECT_HOLD)
        return EFFECT_HOLD + 0.4

    def _n_reveal(self, info):
        self._turn = None
        self.turn_box.opacity = 0
        self._set_turn(t('dealer'))
        entry = self._cards.get(id(self.engine.dealer.cards[1])) if \
            len(self.engine.dealer.cards) > 1 else None
        if entry is not None:
            entry[1].flip_to(True)
        self._refresh_labels()
        return 0.7

    def _n_settle(self, info):
        self._outcomes = {(r['player'], r['hand']): r for r in info['results']}
        self._turn = None
        self.turn_box.opacity = 0
        self._refresh_labels()
        return 1.3

    # ---- запросы решения ----
    def _think_delay(self, kind):
        low, high = THINK_SPECIAL if kind in SPECIAL_ASKS else THINK_ACTION
        return random.uniform(low, high)

    def _on_request(self, step):
        if step.kind == 'bet':
            answer = self.bet if step.player == 0 else self.engine.answer(step)
            self._after(0, answer)
        elif step.player == 0:
            self._request = step
            getattr(self, '_h_' + step.kind)(step)
        else:
            if step.kind in SPECIAL_ASKS:
                self.caption.text = f"{self._name(step.player)} {t('bot_thinking')}"
            self._after(self._think_delay(step.kind), self.engine.answer(step))

    def _answer(self, value):
        """Ответ игрока на запрос: убираем кнопки и рамки и продолжаем раунд."""
        if self._request is None:
            return
        self._request = None
        self._hide_zones()
        self._set_actions(())
        self._after(0, value)

    # ---- кнопки игрока ----
    def _set_actions(self, allowed):
        self._mode = 'actions'
        for key, button in self.buttons.items():
            button.opacity = 1
            button.disabled = key not in allowed
        for button in self.choice_buttons:
            button.opacity = 0
            button.disabled = True
        self._place_buttons()

    def _set_choices(self, options):
        """options: [(текст, цвет, цвет нажатой, действие)]. Кнопки действий прячутся."""
        self._mode = 'choices'
        self._choice_count = len(options)
        for button in self.buttons.values():
            button.opacity = 0
            button.disabled = True
        self._choice_actions = [option[3] for option in options]
        for index, button in enumerate(self.choice_buttons):
            if index < len(options):
                text, color, down, _ = options[index]
                button.text = text
                button.base_color = color
                button.down_color = down
                button.opacity = 1
                button.disabled = False
            else:
                button.opacity = 0
                button.disabled = True
        self._place_buttons()

    def _press_action(self, key, *args):
        if self._request is not None and self._request.kind == 'action' and \
                key in self._request.args:
            self._answer(key)

    def _press_choice(self, index, *args):
        if index < len(self._choice_actions):
            self._choice_actions[index]()

    def _ask(self, question, options):
        self.caption.text = question
        self._hide_zones()
        self._set_choices(options)

    def _yes_no(self, step, yes_text, question, yes_value, no_value):
        self._ask(question, [
            (yes_text, theme.DARK_GREEN, theme.GREEN, lambda: self._answer(yes_value)),
            (t('decline'), theme.DARK_GRAY, theme.GRAY, lambda: self._answer(no_value)),
        ])

    def _h_action(self, step):
        self._set_actions(step.args)

    def _h_snc(self, step):
        self._yes_no(step, t('snc_yes'), t('snc_ask'), True, False)

    def _h_one_for_all(self, step):
        self._ask(t('ofa_ask'), [
            (t('hit'), theme.DARK_GREEN, theme.GREEN, lambda: self._answer('hit')),
            (t('stand'), theme.DARK_RED, theme.RED, lambda: self._answer('stand')),
        ])

    def _h_min(self, step):
        self._ask(t('min_ask'), [
            (t('min_self'), theme.DARK_GREEN, theme.GREEN, lambda: self._answer(None)),
            (t('min_other'), theme.BLUE, theme.LIGHT_BLUE,
             lambda: self._pick_target(step, lambda: self._h_min(step))),
        ])

    def _h_swap(self, step):
        self._ask(t('swap_ask'), [
            (t('swap_yes'), theme.DARK_GREEN, theme.GREEN,
             lambda: self._pick_target(step, lambda: self._h_swap(step))),
            (t('decline'), theme.DARK_GRAY, theme.GRAY, lambda: self._answer(None)),
        ])

    def _h_dealer_card(self, step):
        """Выбор своей карты, которую получит дилер: нажатие на нужную карту."""
        hand = self.engine.players[0].hands[step.hand]
        seat = self._geom(0)
        items = []
        for index in range(len(hand.cards)):
            x, y, _ = self._slot(0, step.hand, len(self.engine.players[0].hands), index,
                                 len(hand.cards))
            items.append((self._clamp_rect((x, y, seat['cw'], seat['ch'])),
                          partial(self._answer, index)))
        self.caption.text = t('pick_card')
        self._set_choices([])
        self._show_zones(items)

    def _pick_target(self, step, go_back):
        """Выбор игрока: рамка вокруг каждой руки, на которую можно подействовать."""
        view = step.view
        targets = [(i, j) for i, p in enumerate(view.players) if i != view.me
                   for j, h in enumerate(p.hands) if h.status == 'live']
        self.caption.text = t('pick_target')
        self._set_choices([(t('back'), theme.DARK_GRAY, theme.GRAY, go_back)])
        self._show_zones([(self._hand_rect(i, j), partial(self._answer, (i, j)))
                          for i, j in targets])

    def _show_zones(self, items):
        self._hide_zones()
        for zone, (rect, action) in zip(self.zones, items):
            self._place(zone, *rect)
            zone.on_pick = action
            zone.opacity = 1

    def _hide_zones(self):
        for zone in self.zones:
            zone.opacity = 0
            zone.on_pick = None

    # ------------------------------------------------------------ конец раунда и выход
    def _finish(self, report):
        user = self.app.user
        user['balance'] = self.players[0].balance
        self._over = True
        self._set_actions(())
        self.caption.text = ''
        net = report.nets.get(0, 0)
        if net > 0:
            self.result_label.text = t('you_win') + str(net)
            self.result_label.color = theme.GREEN_TEXT
            sounds.play('win')
        elif net < 0:
            self.result_label.text = t('dealer_wins')
            self.result_label.color = theme.RED_TEXT
            sounds.play('lose')
        else:
            self.result_label.text = t('tie')
            self.result_label.color = theme.YELLOW
        self.result_balance.text = f"{t('new_balance')}{user['balance']}"
        self.app.storage.ensure_lock_state(user)
        remaining = self.app.storage.lock_remaining(user)
        self.result_note.text = (t('bankrupt_note') + duration_text(remaining)
                                 if remaining > 0 else '')
        self.app.storage.save()
        self.dim.opacity = 1
        self.result_panel.opacity = 1

    def ask_leave(self, *args):
        """«Меню» и клавиша «Назад»: во время раунда переспрашиваем, потому что поставленные
        деньги при выходе пропадают."""
        if self._leave_dialog is not None:
            self._leave_dialog.dismiss()
            return
        if self._over:
            self.app.go('menu')
            return
        if self._iter is None:
            return
        dialog = ConfirmDialog(t('leave_confirm'), on_confirm=lambda: self.app.go('menu'))
        dialog.bind(on_dismiss=self._leave_dismissed)
        self._leave_dialog = dialog
        dialog.open()

    def _leave_dismissed(self, *args):
        self._leave_dialog = None
