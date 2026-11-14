"""Игровой стол.

Логика раунда живёт в core.round.BlackjackRound и меняется мгновенно. Этот экран
забирает из неё события и проигрывает их анимациями Kivy (полёт карт из колоды,
переворот карты дилера), а следующий шаг делает, когда все анимации закончились.
"""
from functools import partial

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from core.cards import cards_is_soft, cards_value
from core.i18n import duration_text, t
from core.round import BlackjackRound, DEALING, INSURANCE, PLAYER, DEALER, OVER
from .. import theme
from ..sound import sounds
from ..widgets import (AvatarImage, CardWidget, DimOverlay, HighlightBox, Lbl, OverlayPanel,
                       Panel, StyledButton, ConfirmDialog)
from .base import BaseScreen

CARD_RATIO = 120.0 / 168.0   # ширина / высота карты
DEAL_STEP = 0.22             # пауза между раздаваемыми картами, с
MOVE_TIME = 0.40             # полёт карты, с
DEALER_PAUSE = 0.5           # пауза перед следующей картой дилера, с
MAX_ROWS = 2                 # сплит доступен один раз, значит рук не больше двух


class GameScreen(BaseScreen):
    animated_background = theme.PARTICLES_IN_GAME
    game_background = True       # etc/game_bg.jpg

    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self.round = None
        self.next_bet = None
        self._skin = 'default'
        self._gen = 0                   # номер раунда: старые отложенные вызовы игнорируются
        self._pending = 0               # сколько анимаций ещё идёт
        self._cards = {}                # Card -> CardWidget
        self._deck_widgets = []
        self._advance_scheduled = False
        self._dealer_scheduled = False
        self._over_shown = False
        self._leave_dialog = None       # окно «Вы точно хотите выйти?», пока оно открыто
        self._dirty = False
        self._m = self._metrics()

        # слой карт (колода и карты добавляются сюда)
        self.table = Widget()
        self.add_widget(self.table)

        self.highlight = HighlightBox(size_hint=(None, None), opacity=0)
        self.add_widget(self.highlight)

        self.dealer_label = Lbl(size_hint=(None, None), halign='left', markup=True,
                                padding_x=0, font_size=sp(19), color=theme.GOLD)
        self.avatar = AvatarImage(size_hint=(None, None))
        self.user_label = Lbl(size_hint=(None, None), halign='left', font_size=sp(17),
                              color=theme.WHITE, shorten=True)
        self.info_label = Lbl(size_hint=(None, None), halign='right', font_size=sp(16),
                              color=theme.WHITE)
        self.hand_labels = [Lbl(size_hint=(None, None), halign='left', markup=True,
                                padding_x=0, font_size=sp(15), color=theme.WHITE)
                            for _ in range(MAX_ROWS)]
        for widget in (self.dealer_label, self.avatar, self.user_label, self.info_label,
                       *self.hand_labels):
            self.add_widget(widget)

        # плашка «Раздача карт... / Ход дилера...»
        self.banner = Panel(size_hint=(None, None), opacity=0, padding=dp(4))
        self.banner_label = Lbl(font_size=sp(20), color=theme.GOLD)
        self.banner.add_widget(self.banner_label)
        self.add_widget(self.banner)

        # предложение страховки (когда у дилера туз): панель справа от карт
        self.insurance_panel = OverlayPanel(size_hint=(None, None), opacity=0, padding=dp(12))
        self.insurance_label = Lbl(font_size=sp(19), color=theme.GOLD)
        insurance_row = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)
        self.insurance_buttons = {}
        for key, color, down, handler in (
            ('insurance_take', theme.BLUE, theme.LIGHT_BLUE, self.do_insure),
            ('insurance_decline', theme.DARK_GRAY, theme.GRAY, self.do_no_insure),
        ):
            button = StyledButton(base_color=color, down_color=down, font_size=sp(17),
                                  on_release=handler)
            self.insurance_buttons[key] = button
            insurance_row.add_widget(button)
        self.insurance_panel.add_widget(self.insurance_label)
        self.insurance_panel.add_widget(insurance_row)
        self.add_widget(self.insurance_panel)

        # нижняя панель кнопок
        self.buttons = {}
        spec = [
            ('hit', theme.DARK_GREEN, theme.GREEN, self.do_hit),
            ('stand', theme.DARK_RED, theme.RED, self.do_stand),
            ('double', theme.BLUE, theme.LIGHT_BLUE, self.do_double),
            ('split', [0.78, 0.59, 0, 1], theme.YELLOW, self.do_split),
            ('surrender', [0.55, 0.27, 0.07, 1], [0.75, 0.4, 0.1, 1], self.do_surrender),
            ('menu', theme.DARK_GRAY, theme.GRAY, self.ask_leave),
        ]
        for key, color, down, handler in spec:
            button = StyledButton(size_hint=(None, None), base_color=color, down_color=down,
                                  font_size=sp(18), on_release=handler)
            self.buttons[key] = button
            self.add_widget(button)

        # затемнение и панель результата лежат выше ВСЕГО, включая нижние кнопки
        self.dim = DimOverlay(size_hint=(None, None), opacity=0)
        self.add_widget(self.dim)
        self.result_panel = OverlayPanel(size_hint=(None, None), opacity=0, padding=dp(14))
        self.result_label = Lbl(font_size=sp(24), color=theme.GOLD)
        self.result_balance = Lbl(size_hint_y=None, height=dp(30), font_size=sp(20),
                                  color=theme.WHITE)
        self.result_note = Lbl(size_hint_y=None, height=dp(26), font_size=sp(16),
                               color=theme.RED_TEXT)
        result_row = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)
        self.result_buttons = {}
        for key, color, down, handler in (
            ('new_game', theme.DARK_GREEN, theme.GREEN, lambda *a: self.app.go_betting()),
            ('menu', theme.DARK_GRAY, theme.GRAY, lambda *a: self.app.go('menu')),
        ):
            button = StyledButton(base_color=color, down_color=down, on_release=handler)
            self.result_buttons[key] = button
            result_row.add_widget(button)
        for widget in (self.result_label, self.result_balance, self.result_note, result_row):
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
        user = self.app.user
        self._skin = user.get('current_skin', 'default')
        self.round = BlackjackRound(user, bet, player=self.app.username)
        self.round.start()
        self._process_events()
        self._refresh_ui()

    def on_leave(self, *args):
        if self._leave_dialog is not None:
            self._leave_dialog.dismiss()
        self._gen += 1
        self.round = None

    def refresh_texts(self):
        for key, button in self.buttons.items():
            button.text = t(key)
        for key, button in self.result_buttons.items():
            button.text = t(key)
        for key, button in self.insurance_buttons.items():
            button.text = t(key)
        if self.round:
            self._refresh_ui()

    def _reset(self):
        self._gen += 1
        self._pending = 0
        self._advance_scheduled = False
        self._dealer_scheduled = False
        self._over_shown = False
        self._dirty = False
        self.round = None
        for widget in self._cards.values():
            Animation.cancel_all(widget)
        self._cards = {}
        self.table.clear_widgets()
        self._build_deck()
        self.dim.opacity = 0
        self.result_panel.opacity = 0
        self.insurance_panel.opacity = 0
        self.result_note.text = ''
        self.banner.opacity = 0
        self.highlight.opacity = 0
        for label in self.hand_labels:
            label.text = ''
        self.dealer_label.text = t('dealer')

    def _build_deck(self):
        self._deck_widgets = []
        for _ in range(5):
            widget = CardWidget(face_up=False)
            self.table.add_widget(widget)
            self._deck_widgets.append(widget)

    # ------------------------------------------------------------ геометрия
    def _metrics(self):
        height, width = self.height, self.width
        card_h = 0.19 * height
        card_w = card_h * CARD_RATIO
        top_h = 0.075 * height
        gap = 0.012 * height
        label_h = 0.06 * height
        dealer_y = height - top_h - card_h
        rows = []
        y_top = dealer_y - gap
        for _ in range(MAX_ROWS):
            label_y = y_top - label_h
            cards_y = label_y - card_h
            rows.append((label_y, cards_y))
            y_top = cards_y - gap
        x0 = 0.02 * width
        step = min(card_w * 1.12, (0.78 * width - card_w) / 6.0)
        return {
            'W': width, 'H': height, 'card_w': card_w, 'card_h': card_h,
            'top_h': top_h, 'label_h': label_h, 'dealer_y': dealer_y,
            'rows': rows, 'x0': x0, 'step': step,
            'deck': (width - card_w * 1.4, height * 0.45),
        }

    def _target(self, who, hand_index, card_index):
        m = self._m
        x = m['x0'] + card_index * m['step']
        if who == 'dealer':
            return x, m['dealer_y']
        row = min(hand_index, MAX_ROWS - 1)
        return x, m['rows'][row][1]

    def _on_size(self, *args):
        if self._pending == 0:
            self._relayout()
        else:
            self._dirty = True

    def _relayout(self):
        m = self._m = self._metrics()
        width, height = m['W'], m['H']
        if not width or not height:
            return

        top_y = height - m['top_h']
        self._place(self.dealer_label, m['x0'], top_y, 0.36 * width, m['top_h'])
        avatar_size = m['top_h'] * 0.88
        gap = dp(6)
        self._place(self.avatar, 0.4 * width, top_y + (m['top_h'] - avatar_size) / 2,
                    avatar_size, avatar_size)
        self._place(self.user_label, 0.4 * width + avatar_size + gap, top_y,
                    0.2 * width - avatar_size - gap, m['top_h'])
        self._place(self.info_label, 0.6 * width, top_y, 0.38 * width, m['top_h'])
        for index, label in enumerate(self.hand_labels):
            self._place(label, m['x0'], m['rows'][index][0], 0.8 * width, m['label_h'])

        self._place(self.banner, width * 0.3, height * 0.125, width * 0.4, height * 0.075)
        self._place(self.dim, 0, 0, width, height)
        self._place(self.result_panel, width * 0.25, height * 0.25, width * 0.5, height * 0.5)
        self._place(self.insurance_panel, width * 0.4, height * 0.3, width * 0.4, height * 0.34)

        bar_h = height * 0.095
        gap = width * 0.008
        button_w = (width * 0.96 - gap * 5) / 6.0
        for index, key in enumerate(('hit', 'stand', 'double', 'split', 'surrender', 'menu')):
            self._place(self.buttons[key], width * 0.02 + index * (button_w + gap),
                        height * 0.012, button_w, bar_h)

        deck_x, deck_y = m['deck']
        for index, widget in enumerate(self._deck_widgets):
            widget.size = (m['card_w'], m['card_h'])
            widget.pos = (deck_x + index * dp(1.5), deck_y + index * dp(1.5))

        if self.round:
            for who, hand_index, card_index, card in self._iter_cards():
                widget = self._cards.get(card)
                if widget is not None:
                    widget.size = (m['card_w'], m['card_h'])
                    widget.pos = self._target(who, hand_index, card_index)
            self._refresh_ui()

    @staticmethod
    def _place(widget, x, y, w, h):
        widget.pos = (x, y)
        widget.size = (w, h)

    def _iter_cards(self):
        for index, card in enumerate(self.round.dealer.cards):
            yield 'dealer', 0, index, card
        for hand_index, hand in enumerate(self.round.hands):
            for index, card in enumerate(hand.cards):
                yield 'player', hand_index, index, card

    # ------------------------------------------------------------ анимации
    def _start_anim(self, delay, action):
        """Планирует анимацию; action(done) обязан вызвать done() по окончании."""
        self._pending += 1
        gen = self._gen
        done = partial(self._anim_done, gen)

        def run(dt):
            if gen == self._gen and self.round is not None:
                action(done)

        Clock.schedule_once(run, delay)

    def _anim_done(self, gen, *args):
        if gen != self._gen:
            return
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self._schedule_advance()

    def _move(self, widget, target, duration, done, appear=False):
        if appear:
            widget.visible = True
            sounds.play('card')
        animation = Animation(x=target[0], y=target[1], duration=duration, t='out_cubic')

        def arrived(*args):
            widget.landed = True
            self._refresh_labels()     # сумма меняется, когда карта легла на стол
            done()

        animation.bind(on_complete=arrived)
        animation.start(widget)

    def _deal_card(self, card, target, face_up, delay):
        m = self._m
        widget = CardWidget(rank=card.rank, suit=card.suit, skin=self._skin, face_up=face_up)
        widget.size = (m['card_w'], m['card_h'])
        widget.pos = m['deck']
        widget.visible = False          # появится в момент вылета из колоды
        self.table.add_widget(widget)
        self._cards[card] = widget
        self._start_anim(delay, lambda done: self._move(widget, target, MOVE_TIME, done, True))
        return delay + DEAL_STEP

    def _flip_card(self, card, delay):
        widget = self._cards.get(card)
        if widget is None:
            return
        self._start_anim(delay, lambda done: widget.flip_to(True, on_done=done))

    def _animate_relayout(self, delay):
        """После сплита плавно переставляем уже лежащие карты."""
        for who, hand_index, card_index, card in self._iter_cards():
            widget = self._cards.get(card)
            if widget is not None:
                target = self._target(who, hand_index, card_index)
                self._start_anim(delay, lambda done, w=widget, tg=target:
                                 self._move(w, tg, 0.3, done))

    def _process_events(self):
        delay = 0.0
        for event in self.round.pop_events():
            kind = event[0]
            if kind == 'deal_player':
                _, hand_index, card_index, card = event
                delay = self._deal_card(card, self._target('player', hand_index, card_index),
                                        True, delay)
            elif kind == 'deal_dealer':
                _, card_index, card, hidden = event
                delay = self._deal_card(card, self._target('dealer', 0, card_index),
                                        not hidden, delay)
            elif kind == 'flip_dealer':
                self._flip_card(self.round.dealer.cards[event[1]], delay)
                delay += 0.2
            elif kind == 'split':
                self._animate_relayout(delay)
                delay += 0.35
        if self._pending == 0:
            self._schedule_advance()

    # ------------------------------------------------------------ ход игры
    def _schedule_advance(self):
        if self._advance_scheduled:
            return
        self._advance_scheduled = True
        gen = self._gen

        def run(dt):
            self._advance_scheduled = False
            if gen == self._gen:
                self._advance()

        Clock.schedule_once(run, 0.05)

    def _advance(self):
        """Вызывается, когда все анимации закончились: делает следующий шаг раунда."""
        r = self.round
        if r is None or self._pending > 0:
            return
        if self._dirty:
            self._dirty = False
            self._relayout()

        if r.state == DEALING:
            r.finish_dealing()          # проверка блэкджека
            self._process_events()
        elif r.state == DEALER:
            self._schedule_dealer_step()
        elif r.state == OVER:
            self._on_over()
        self._refresh_ui()

    def _schedule_dealer_step(self):
        if self._dealer_scheduled:
            return
        self._dealer_scheduled = True
        gen = self._gen

        def run(dt):
            self._dealer_scheduled = False
            if gen != self._gen or self.round is None:
                return
            self.round.dealer_step()
            self._process_events()
            self._refresh_ui()

        Clock.schedule_once(run, DEALER_PAUSE)

    def _on_over(self):
        if self._over_shown:
            return
        self._over_shown = True
        r = self.round
        self.app.storage.save()
        self.app.dataset.write_round(r)        # решения этого раунда — в CSV для обучения
        key, number = r.message
        self.result_label.text = t(key) + (str(number) if number is not None else '')
        net = r.net
        self.result_label.color = (theme.GREEN_TEXT if net > 0 else
                                   theme.RED_TEXT if net < 0 else theme.YELLOW)
        if net > 0:
            sounds.play('win')
        elif net < 0:
            sounds.play('lose')
        balance_text = f"{t('new_balance')}{self.app.user['balance']}"
        if r.insurance:
            sign = '+' if r.insurance_net >= 0 else '-'
            balance_text += f"   {t('insurance')}: {sign}${abs(r.insurance_net)}"
        self.result_balance.text = balance_text

        # деньги кончились: игра блокируется на 24 часа
        user = self.app.user
        self.app.storage.ensure_lock_state(user)
        remaining = self.app.storage.lock_remaining(user)
        self.result_note.text = (t('bankrupt_note') + duration_text(remaining)
                                 if remaining > 0 else '')
        self.dim.opacity = 1
        self.result_panel.opacity = 1

    def ask_leave(self, *args):
        """Кнопка «Меню» и клавиша «Назад» во время партии: переспрашиваем, потому что
        поставленные деньги при выходе пропадают. Если окно уже открыто — закрываем его."""
        if self._leave_dialog is not None:
            self._leave_dialog.dismiss()
            return
        r = self.round
        if r is None or self._pending > 0 or r.state not in (PLAYER, INSURANCE, OVER):
            return                      # идёт раздача или ход дилера: выходить рано
        if r.state == OVER:             # раунд закончен, ставка уже разыграна
            self.app.go('menu')
            return
        dialog = ConfirmDialog(t('leave_confirm'), on_confirm=lambda: self.app.go('menu'))
        dialog.bind(on_dismiss=self._leave_dismissed)
        self._leave_dialog = dialog
        dialog.open()

    def _leave_dismissed(self, *args):
        self._leave_dialog = None

    # ------------------------------------------------------------ действия игрока
    def _busy(self):
        r = self.round
        return r is None or self._pending > 0 or r.state in (DEALING, DEALER)

    def _act(self, method_name):
        if self._busy():
            return
        if getattr(self.round, method_name)():
            self._process_events()
            self._refresh_ui()

    def do_hit(self, *args):
        self._act('hit')

    def do_stand(self, *args):
        self._act('stand')

    def do_double(self, *args):
        self._act('double')

    def do_split(self, *args):
        self._act('split')

    def do_surrender(self, *args):
        self._act('surrender')

    def do_insure(self, *args):
        self._act('take_insurance')

    def do_no_insure(self, *args):
        self._act('decline_insurance')

    # ------------------------------------------------------------ интерфейс
    def _landed_cards(self, cards):
        """Карты, которые уже лежат на столе: сумму показываем только по ним."""
        shown = []
        for card in cards:
            widget = self._cards.get(card)
            if widget is not None and widget.landed:
                shown.append(card)
        return shown

    def _total_text(self, cards):
        shown = self._landed_cards(cards)
        text = f"{t('total')}: {cards_value(shown)}"
        if cards_is_soft(shown):
            text += f" ({t('soft')})"     # туз считается за 11, сумма может уменьшиться
        return cards_value(shown), text

    def _refresh_labels(self):
        r = self.round
        if r is None:
            return
        user = self.app.user
        self.user_label.text = self.app.storage.display_name(user)
        self.avatar.source = self.app.avatar_source(user)
        self.info_label.text = (f"{t('balance')}: ${user['balance']}    "
                                f"{t('total_bet')}{r.total_current_bet}")

        # дилер
        if r.state == DEALING or not r.dealer.cards:
            self.dealer_label.text = t('dealer')
        else:
            hole = self._cards.get(r.dealer.cards[1]) if len(r.dealer.cards) > 1 else None
            if hole is not None and not hole.face_up:
                shown = self._landed_cards(r.dealer.cards[:1])
                visible = shown[0].value if shown else 0
                self.dealer_label.text = f"{t('dealer')}   {t('visible')}: {visible}"
            else:
                self.dealer_label.text = f"{t('dealer')}   {self._total_text(r.dealer.cards)[1]}"

        # руки игрока
        for index, label in enumerate(self.hand_labels):
            if index < len(r.hands) and r.state != DEALING:
                hand = r.hands[index]
                value, total = self._total_text(hand.cards)
                text = f"{total} | {t('bet')}: ${hand.bet}"
                if value > 21:
                    text += "   [color=ff4040]BUST![/color]"
                label.text = text
            else:
                label.text = ''

    def _refresh_ui(self):
        r = self.round
        if r is None:
            return
        m = self._m
        busy = self._busy()
        self._refresh_labels()

        # перебравшие руки приглушаем
        for hand in r.hands:
            for card in hand.cards:
                widget = self._cards.get(card)
                if widget is not None:
                    widget.dim = not hand.is_active

        # рамка вокруг активной руки
        active = r.hands[r.current] if (r.state == PLAYER and r.current < len(r.hands)) else None
        if active is not None and active.is_active and active.cards:
            pad = dp(4)
            row = min(r.current, MAX_ROWS - 1)
            count = len(active.cards)
            self._place(self.highlight, m['x0'] - pad, m['rows'][row][1] - pad,
                        m['card_w'] + (count - 1) * m['step'] + 2 * pad, m['card_h'] + 2 * pad)
            self.highlight.opacity = 1
        else:
            self.highlight.opacity = 0

        # плашка со статусом
        if r.state == DEALING:
            self.banner_label.text = t('dealing_cards')
            self.banner.opacity = 1
        elif r.state == DEALER:
            self.banner_label.text = t('dealer_turn')
            self.banner.opacity = 1
        else:
            self.banner.opacity = 0

        # предложение страховки
        offer = r.state == INSURANCE and self._pending == 0
        self.insurance_panel.opacity = 1 if offer else 0
        if offer:
            self.insurance_label.text = f"{t('insurance_offer')}{r.insurance_cost}"

        # кнопки
        self.buttons['hit'].disabled = busy or not r.can_hit()
        self.buttons['stand'].disabled = busy or not r.can_stand()
        self.buttons['double'].disabled = busy or not r.can_double()
        self.buttons['split'].disabled = busy or not r.can_split()
        self.buttons['surrender'].disabled = busy or not r.can_surrender()
        leave_ok = self._pending == 0 and r.state in (PLAYER, INSURANCE, OVER)
        self.buttons['menu'].disabled = not leave_ok
