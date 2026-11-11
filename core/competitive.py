"""Соревновательный режим: стол на несколько игроков со спец-картами. Не зависит от Kivy.

Правила (как договорились):
  * Спец-карта не входит в руку: срабатывает сразу при вытягивании (при «взять» или «удвоить»),
    после чего игрок получает обычную карту. Если выпала ещё одна спец-карта, срабатывает и она.
  * В начальной раздаче и у дилера спец-карт нет: выпавшая карта возвращается в колоду.
  * Раунд идёт кругами: за круг каждая живая рука делает одно действие (взять / стоп / удвоить).
    Кто встал или перебрал, из кругов выбывает и защищён от пакостей других игроков.
    Первым в круге ходит «кнопка», она сдвигается каждый раунд.
  * Когда живых рук не осталось, дилер добирает до 17 и все считаются с ним по отдельности.
  * Блэкджек (21 с двух карт) платит 3:2, дилер стоит на любом 17. Сплит, сдача и страховка
    в этом режиме пока не реализованы (сплит заменяет карта SnC).

Решения игрока принимает «контроллер» (человек, бот или в будущем сетевой игрок): стол сам
не знает, кто ходит. Контроллер видит только то, что видит игрок: все открытые руки и
открытую карту дилера, но не колоду и не закрытую карту дилера.

Раунд идёт по шагам (iter_round — генератор), чтобы экран мог делать паузы и играть анимации:
  * Notice(kind, info)  — «что произошло» (раздали карту, вытянули спец-карту...), отвечать не нужно;
  * Request(kind, ...)  — «нужно решение игрока»; ответ передаётся в generator.send(ответ).
Table.play_round() проходит все шаги сразу, спрашивая контроллеров (для симуляции и тестов).
"""
import random
from collections import namedtuple

from .cards import Card, Hand, RANKS, SUITS, cards_value

SPECIAL_KINDS = ('troll', 'snc', 'min', 'min_plus', 'average',
                 'one_for_all', 'loser', 'dealer', 'swap')
SPECIAL_TITLES = {
    'troll': 'Troll face', 'snc': 'SnC', 'min': 'Min', 'min_plus': 'Min+',
    'average': 'Average', 'one_for_all': 'One for all', 'loser': 'Loser',
    'dealer': 'Dealer', 'swap': 'Swap',
}


class SpecialCard:
    """Спец-карта. В руку не попадает, только срабатывает."""

    def __init__(self, kind):
        self.kind = kind

    def __str__(self):
        return SPECIAL_TITLES[self.kind]

    __repr__ = __str__


class FixedCard:
    """Карта «среднее»: после Average вся рука состоит из одной такой карты."""
    rank = 'avg'
    suit = ''

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return f"~{self.value}"

    __repr__ = __str__


def min_key(card):
    """Для Min / Min+: туз считается за 1."""
    return 1 if card.rank == 'A' else card.value


def max_key(card):
    """Для Loser: туз считается за 11."""
    return card.value


class TableHand(Hand):
    """Рука за столом: к обычной руке добавлены блэкджек и статус."""

    def __init__(self, bet=0):
        super().__init__(bet)
        self.natural = False
        self.surrendered = False      # игрок сдался: половина ставки уже вернулась
        self.refund = 0

    @property
    def live(self):
        """Живая рука: ещё играет (не встала, не перебрала и не блэкджек)."""
        return self.is_active and not self.is_stand and not self.natural

    @property
    def status(self):
        if self.natural:
            return 'natural'
        if self.surrendered:
            return 'surrender'
        if not self.is_active:
            return 'bust'
        return 'stand' if self.is_stand else 'live'


class Config:
    """Состав колоды: сколько обычных колод по 52 и какие спец-карты (kinds повторяются)."""

    def __init__(self, decks=1, specials=()):
        self.decks = decks
        self.specials = tuple(specials)


class Player:
    def __init__(self, name, controller, balance=1000):
        self.name = name
        self.controller = controller
        self.balance = balance
        self.hands = []


DEALER = -1      # «номер игрока» дилера в уведомлениях

HandView = namedtuple('HandView', 'cards bet status')
PlayerView = namedtuple('PlayerView', 'name balance hands')
View = namedtuple('View', 'me players dealer_up')
Event = namedtuple('Event', 'kind actor targets info')
Notice = namedtuple('Notice', 'kind info')
Request = namedtuple('Request', 'kind player hand args view')
RoundReport = namedtuple('RoundReport', 'nets base_bets circles specials events hits button')


class Controller:
    """Тот, кто принимает решения за игрока. Эти значения по умолчанию безопасны."""

    def bet(self, view):
        return 10

    def action(self, view, hand_index, allowed):
        return 'stand'

    def use_snc(self, view, hand_index):
        return False

    def min_choice(self, view, hand_index, plus):
        """None — взять копию минимальной карты себе, (игрок, рука) — отдать её другому."""
        return None

    def one_for_all(self, view, hand_index):
        return 'stand'

    def swap(self, view, hand_index):
        """None — отказаться, (игрок, рука) — поменяться руками."""
        return None

    def dealer_card(self, view, hand_index):
        """Номер своей карты, которую отдаём дилеру."""
        return 0


class Table:
    MAX_CIRCLES = 60     # защита от бесконечной игры
    MAX_CHAIN = 6        # сколько спец-карт подряд срабатывает за одно «взять»
    MAX_HANDS = 4        # больше рук у одного игрока быть не может

    def __init__(self, players, config, rng=None):
        self.players = players
        self.config = config
        self.rng = rng or random.Random()
        self.button = 0
        self.deck = []
        self.dealer = TableHand()
        self.events = []
        self.specials_drawn = 0
        self.hit_counts = {}
        self.hole_hidden = False        # закрыта ли вторая карта дилера
        self.split_used = set()         # кто уже делал сплит в этом раунде (один раз за раунд)
        self.acted = set()              # кто уже ходил (сдаться можно только первым действием)

    # ---------- колода ----------
    def build_deck(self):
        cards = [Card(rank, suit) for _ in range(self.config.decks)
                 for suit in SUITS for rank in RANKS]
        cards += [SpecialCard(kind) for kind in self.config.specials]
        self.rng.shuffle(cards)
        self.deck = cards

    def _draw_any(self):
        if not self.deck:
            self.build_deck()            # колода кончилась: берём новую
        return self.deck.pop()

    def _draw_normal(self):
        """Обычная карта. Выпавшие спец-карты возвращаются в случайное место колоды."""
        if all(isinstance(c, SpecialCard) for c in self.deck):
            self.build_deck()            # в колоде остались одни спец-карты (или она пуста)
        while True:
            card = self._draw_any()
            if not isinstance(card, SpecialCard):
                return card
            self.deck.insert(self.rng.randrange(len(self.deck) + 1), card)

    # ---------- что видит игрок ----------
    def view(self, me):
        players = [PlayerView(p.name, p.balance,
                              [HandView(tuple(h.cards), h.bet, h.status) for h in p.hands])
                   for p in self.players]
        up = self.dealer.cards[0] if self.dealer.cards else None
        return View(me, players, up)

    def _event(self, kind, actor, targets=(), info='', hands=(), origin=None):
        """Записывает событие и возвращает уведомление «сработала спец-карта» для экрана."""
        self.events.append(Event(kind, actor, tuple(targets), info))
        return Notice('effect', {'kind': kind, 'actor': actor, 'targets': tuple(targets),
                                 'info': info, 'hands': tuple(hands), 'origin': origin})

    def answer(self, request):
        """Ответ контроллера игрока на запрос решения."""
        controller = self.players[request.player].controller
        view, hand, kind = request.view, request.hand, request.kind
        if kind == 'bet':
            return controller.bet(view)
        if kind == 'action':
            return controller.action(view, hand, request.args)
        if kind == 'snc':
            return controller.use_snc(view, hand)
        if kind == 'min':
            return controller.min_choice(view, hand, request.args)
        if kind == 'one_for_all':
            return controller.one_for_all(view, hand)
        if kind == 'swap':
            return controller.swap(view, hand)
        return controller.dealer_card(view, hand)

    def drive(self, generator):
        """Проходит все шаги генератора, отвечая на запросы контроллерами игроков.
        Возвращает то, что вернул генератор."""
        answer = None
        while True:
            try:
                step = generator.send(answer)
            except StopIteration as stop:
                return stop.value
            answer = self.answer(step) if isinstance(step, Request) else None

    # ---------- раунд ----------
    def seat_order(self, seated):
        n = len(self.players)
        return [i for i in ((self.button + k) % n for k in range(n)) if i in seated]

    def _live_slots(self):
        return [(i, j) for i, p in enumerate(self.players)
                for j, h in enumerate(p.hands) if h.live]

    def _live_targets(self, actor):
        """Чужие живые руки: те, на кого можно подействовать (кто встал, тот защищён)."""
        return [(i, j) for i, j in self._live_slots() if i != actor]

    def play_round(self):
        """Весь раунд сразу (решения принимают контроллеры). Возвращает RoundReport."""
        return self.drive(self.iter_round())

    def iter_round(self):
        """Раунд по шагам: генератор отдаёт Notice и Request, а в конце возвращает RoundReport."""
        self.events = []
        self.specials_drawn = 0
        self.hit_counts = {}
        self.split_used = set()
        self.acted = set()
        self.build_deck()
        for p in self.players:
            p.hands = []
        yield Notice('start', {})
        seated = [i for i, p in enumerate(self.players) if p.balance > 0]
        start = {i: self.players[i].balance for i in seated}
        base_bets = {}
        for i in seated:
            p = self.players[i]
            answer = yield Request('bet', i, 0, None, self.view(i))
            bet = max(1, min(int(answer), p.balance))
            p.balance -= bet
            p.hands = [TableHand(bet)]
            base_bets[i] = bet
            self.hit_counts[i] = 0
        yield Notice('bets', {'bets': dict(base_bets)})

        self.dealer = TableHand()
        self.hole_hidden = False
        order = self.seat_order(seated)
        for number in range(2):
            for i in order:
                card = self._draw_normal()
                self.players[i].hands[0].add_card(card)
                yield Notice('deal', {'player': i, 'hand': 0, 'card': card, 'hidden': False})
            card = self._draw_normal()
            self.dealer.add_card(card)
            self.hole_hidden = number == 1
            yield Notice('deal', {'player': DEALER, 'hand': 0, 'card': card,
                                  'hidden': number == 1})
        for i in order:
            hand = self.players[i].hands[0]
            hand.natural = hand.value == 21

        circles = 0
        dealer_natural = self.dealer.value == 21
        if dealer_natural:
            for p in self.players:                       # раунд закончен сразу
                for hand in p.hands:
                    hand.is_stand = True
        else:
            while circles < self.MAX_CIRCLES and self._live_slots():
                circles += 1
                for i in order:
                    player = self.players[i]
                    j = 0
                    while j < len(player.hands):          # SnC может добавить руку по ходу
                        if player.hands[j].live:
                            yield from self._act(i, j)
                        j += 1
            for i, j in self._live_slots():               # аварийно: круги кончились
                self.players[i].hands[j].is_stand = True
        if self.hole_hidden:
            self.hole_hidden = False
            yield Notice('reveal', {})
        if not dealer_natural and any(h.is_active and not h.natural
                                      for p in self.players for h in p.hands):
            while self.dealer.value < 17:
                card = self._draw_normal()
                self.dealer.add_card(card)
                yield Notice('deal', {'player': DEALER, 'hand': 0, 'card': card,
                                      'hidden': False})
        results = self._settle(dealer_natural)
        yield Notice('settle', {'results': results})

        report = RoundReport(
            nets={i: self.players[i].balance - start[i] for i in seated},
            base_bets=base_bets, circles=circles, specials=self.specials_drawn,
            events=list(self.events), hits=dict(self.hit_counts), button=self.button)
        self.button = (self.button + 1) % len(self.players)
        return report

    def _settle(self, dealer_natural):
        """Расчёт с дилером. Возвращает список результатов по рукам."""
        dealer_value = self.dealer.value
        results = []
        for i, p in enumerate(self.players):
            for j, hand in enumerate(p.hands):
                if dealer_natural:
                    payout = hand.bet if hand.natural else 0
                elif hand.natural:
                    payout = hand.bet * 5 // 2
                elif hand.surrendered or not hand.is_active:
                    payout = 0
                elif dealer_value > 21 or hand.value > dealer_value:
                    payout = hand.bet * 2
                elif hand.value == dealer_value:
                    payout = hand.bet
                else:
                    payout = 0
                p.balance += payout
                if hand.surrendered:
                    payout = hand.refund               # для показа: половина ставки вернулась раньше
                if hand.natural and not dealer_natural:
                    outcome = 'blackjack'
                elif hand.surrendered:
                    outcome = 'surrender'
                elif not hand.is_active:
                    outcome = 'bust'
                elif payout > hand.bet:
                    outcome = 'win'
                elif payout == hand.bet:
                    outcome = 'push'
                else:
                    outcome = 'lose'
                results.append({'player': i, 'hand': j, 'bet': hand.bet, 'payout': payout,
                                'outcome': outcome})
        return results

    # ---------- действия игрока ----------
    def _act(self, pi, hi):
        player = self.players[pi]
        hand = player.hands[hi]
        yield Notice('turn', {'player': pi, 'hand': hi})
        allowed = ['hit', 'stand']
        if len(hand.cards) == 2 and not hand.has_doubled and player.balance >= hand.bet:
            allowed.append('double')
        if self._can_split(pi, hi):
            allowed.append('split')
        if self._can_surrender(pi, hi):
            allowed.append('surrender')
        choice = yield Request('action', pi, hi, tuple(allowed), self.view(pi))
        if choice not in allowed:
            choice = 'stand'
        yield Notice('action', {'player': pi, 'hand': hi, 'action': choice})
        if choice == 'stand':
            hand.is_stand = True
            return
        self.acted.add(pi)
        if choice == 'surrender':
            refund = hand.bet // 2
            player.balance += refund
            hand.is_active = False
            hand.is_stand = True
            hand.surrendered = True
            hand.refund = refund
            yield Notice('surrender', {'player': pi, 'hand': hi, 'refund': refund})
            return
        if choice == 'split':
            yield from self._split(pi, hi)
            return
        if choice == 'double':
            player.balance -= hand.bet
            hand.bet *= 2
            hand.has_doubled = True
        yield from self._hit(pi, hi)
        if hand.has_doubled and hand.is_active:
            hand.is_stand = True                          # после удвоения рука закончена

    def _can_split(self, pi, hi):
        """Сплит: две карты одного достоинства, хватает денег на вторую ставку,
        один раз за раунд на игрока и не больше MAX_HANDS рук."""
        player = self.players[pi]
        hand = player.hands[hi]
        return (pi not in self.split_used and hand.can_split()
                and len(player.hands) < self.MAX_HANDS and player.balance >= hand.bet)

    def _can_surrender(self, pi, hi):
        """Сдаться можно только первым действием на двух картах, одной рукой и без сплита
        (как в обычной игре). Возвращается половина ставки."""
        player = self.players[pi]
        hand = player.hands[hi]
        return (pi not in self.acted and pi not in self.split_used and len(player.hands) == 1
                and len(hand.cards) == 2 and not hand.has_doubled and hand.bet >= 2)

    def _split(self, pi, hi):
        """Вторая карта уходит в новую руку с такой же ставкой, каждая рука получает по карте."""
        player = self.players[pi]
        hand = player.hands[hi]
        player.balance -= hand.bet
        new_hand = TableHand(hand.bet)
        new_hand.cards = [hand.cards.pop()]
        player.hands.insert(hi + 1, new_hand)
        self.split_used.add(pi)
        yield Notice('split', {'player': pi, 'hand': hi})
        for index in (hi, hi + 1):
            card = self._draw_normal()
            player.hands[index].add_card(card)
            self._check_bust(player.hands[index])
            yield Notice('hit_card', {'player': pi, 'hand': index, 'card': card})

    def _check_bust(self, hand):
        if hand.is_active and cards_value(hand.cards) > 21:
            hand.is_active = False

    def _hit(self, pi, hi):
        hand = self.players[pi].hands[hi]
        self.hit_counts[pi] = self.hit_counts.get(pi, 0) + 1
        chain = 0
        while True:
            card = self._draw_normal() if chain >= self.MAX_CHAIN else self._draw_any()
            if not isinstance(card, SpecialCard):
                hand.add_card(card)
                yield Notice('hit_card', {'player': pi, 'hand': hi, 'card': card})
                break
            chain += 1
            self.specials_drawn += 1
            yield Notice('special', {'player': pi, 'hand': hi, 'kind': card.kind})
            replaced = yield from getattr(self, '_sp_' + card.kind)(pi, hi)
            if replaced or not hand.is_active:
                break
        self._check_bust(hand)

    def _add_copy(self, hand, card):
        copy = FixedCard(card.value) if isinstance(card, FixedCard) else Card(card.rank, card.suit)
        hand.add_card(copy)
        self._check_bust(hand)

    @staticmethod
    def _clone_cards(cards):
        """Независимые копии карт (чтобы у экрана каждая карта была отдельным объектом)."""
        return [FixedCard(c.value) if isinstance(c, FixedCard) else Card(c.rank, c.suit)
                for c in cards]

    # ---------- спец-карты (каждая возвращает True, если заменила обычную карту) ----------
    def _sp_troll(self, pi, hi):
        """Карты всех живых рук перемешиваются и раздаются заново (столько же каждой руке)."""
        slots = self._live_slots()
        counts, pool = [], []
        for i, j in slots:
            hand = self.players[i].hands[j]
            counts.append(len(hand.cards))
            pool.extend(hand.cards)
            hand.cards = []
        self.rng.shuffle(pool)
        for (i, j), count in zip(slots, counts):
            hand = self.players[i].hands[j]
            hand.cards, pool = pool[:count], pool[count:]
            self._check_bust(hand)
        yield self._event('troll', pi, sorted({i for i, _ in slots if i != pi}),
                          f'hands={len(slots)}', hands=slots)
        return False

    def _sp_snc(self, pi, hi):
        """Рука превращается в две одинаковые (вторая со ставкой такого же размера). Можно отказаться."""
        player = self.players[pi]
        hand = player.hands[hi]
        if player.balance < hand.bet:
            yield self._event('snc', pi, (), 'no_money')
            return False
        use = yield Request('snc', pi, hi, None, self.view(pi))
        if not use:
            yield self._event('snc', pi, (), 'declined')
            return False
        player.balance -= hand.bet
        copy = TableHand(hand.bet)
        copy.cards = self._clone_cards(hand.cards)
        player.hands.insert(hi + 1, copy)
        yield self._event('snc', pi, (), 'used', hands=[(pi, hi), (pi, hi + 1)],
                          origin=(pi, hi))
        return False

    def _sp_min(self, pi, hi):
        return (yield from self._min_effect('min', pi, hi, plus=False))

    def _sp_min_plus(self, pi, hi):
        return (yield from self._min_effect('min_plus', pi, hi, plus=True))

    def _min_effect(self, kind, pi, hi, plus):
        """Копия минимальной карты: себе или другому. У Min+ при передаче берётся
        минимальная карта получателя, а не своя."""
        player = self.players[pi]
        hand = player.hands[hi]
        targets = self._live_targets(pi)
        choice = None
        if targets:
            choice = yield Request('min', pi, hi, plus, self.view(pi))
        if choice is not None and tuple(choice) not in targets:
            choice = None
        if choice is None:
            if hand.cards:
                self._add_copy(hand, min(hand.cards, key=min_key))
            yield self._event(kind, pi, (), 'self', hands=[(pi, hi)], origin=(pi, hi))
        else:
            ti, tj = choice
            target = self.players[ti].hands[tj]
            source = target.cards if plus else hand.cards
            self._add_copy(target, min(source, key=min_key))
            yield self._event(kind, pi, [ti], 'other', hands=[(ti, tj)],
                              origin=(ti, tj) if plus else (pi, hi))
        return False

    def _sp_average(self, pi, hi):
        """Рука превращается в одну карту со средним значением (вверх, туз = 1),
        ставка делится на число карт, остаток возвращается на баланс."""
        player = self.players[pi]
        hand = player.hands[hi]
        count = len(hand.cards)
        if count == 0:
            yield self._event('average', pi, (), 'empty')
            return False
        total = sum(1 if c.rank == 'A' else c.value for c in hand.cards)
        average = -(-total // count)
        new_bet = max(1, hand.bet // count)
        player.balance += hand.bet - new_bet
        hand.bet = new_bet
        hand.cards = [FixedCard(average)]
        yield self._event('average', pi, (), f'{count}->{average}', hands=[(pi, hi)])
        return False

    def _sp_one_for_all(self, pi, hi):
        """Выбранное действие (взять или стоп) делают все живые руки, включая свою.
        Оно заменяет обычное «взять» вытянувшего."""
        action = yield Request('one_for_all', pi, hi, None, self.view(pi))
        if action not in ('hit', 'stand'):
            action = 'stand'
        slots = self._live_slots()
        for i, j in slots:
            hand = self.players[i].hands[j]
            if action == 'stand':
                hand.is_stand = True
            else:
                hand.add_card(self._draw_normal())
                self._check_bust(hand)
        yield self._event('one_for_all', pi, sorted({i for i, _ in slots if i != pi}),
                          action, hands=slots)
        return True

    def _sp_loser(self, pi, hi):
        """У остальных живых рук (минимум 2 карты) убирается самая большая карта,
        самую большую из убранных получает вытянувший."""
        removed, affected, slots = [], set(), []
        for i, j in self._live_targets(pi):
            hand = self.players[i].hands[j]
            if len(hand.cards) < 2:
                continue
            card = max(hand.cards, key=max_key)
            hand.cards.remove(card)
            removed.append(card)
            affected.add(i)
            slots.append((i, j))
        if removed:
            mine = self.players[pi].hands[hi]
            mine.add_card(max(removed, key=max_key))
            self._check_bust(mine)
        yield self._event('loser', pi, sorted(affected), f'removed={len(removed)}',
                          hands=slots + [(pi, hi)])
        return False

    def _sp_dealer(self, pi, hi):
        """Обмен с дилером: отдаём свою карту, берём его открытую."""
        player = self.players[pi]
        hand = player.hands[hi]
        if not hand.cards or not self.dealer.cards:
            yield self._event('dealer', pi, (), 'empty')
            return False
        index = yield Request('dealer_card', pi, hi, None, self.view(pi))
        if not isinstance(index, int) or not 0 <= index < len(hand.cards):
            index = min(range(len(hand.cards)), key=lambda k: min_key(hand.cards[k]))
        given = hand.cards.pop(index)
        taken = self.dealer.cards[0]
        self.dealer.cards[0] = given
        hand.add_card(taken)
        self._check_bust(hand)
        others = sorted({i for i, p in enumerate(self.players) if i != pi
                         and any(h.is_active for h in p.hands)})
        yield self._event('dealer', pi, others, f'give={given} take={taken}',
                          hands=[(pi, hi)])
        return False

    def _sp_swap(self, pi, hi):
        """Обмен руками с выбранной чужой живой рукой (ставки остаются на местах). Можно отказаться."""
        player = self.players[pi]
        hand = player.hands[hi]
        targets = self._live_targets(pi)
        if not targets:
            yield self._event('swap', pi, (), 'no_target')
            return False
        choice = yield Request('swap', pi, hi, None, self.view(pi))
        if choice is None or tuple(choice) not in targets:
            yield self._event('swap', pi, (), 'declined')
            return False
        ti, tj = choice
        target = self.players[ti].hands[tj]
        hand.cards, target.cards = target.cards, hand.cards
        yield self._event('swap', pi, [ti], 'used', hands=[(pi, hi), (ti, tj)])
        return False
