"""Боты для соревновательного режима. Не зависят от Kivy.

Обычные ходы идут по основной стратегии блэкджека (таблица ниже) с шансом ошибки. Решения по
спец-картам бот принимает по оценке выигрыша: насколько изменится ожидаемый результат его руки
и (с весом rivalry) рук соперников. Оценки считаются точно, из вероятностей карт, обучения нет.

rivalry: 0 = бот думает только о своей руке, 1 = чужой проигрыш для него так же ценен, как свой
выигрыш. Пока игроки получают деньги от дилера по отдельности, пакостить другим невыгодно, и
rivalry моделирует «вредность» человека.
"""
from collections import defaultdict
from functools import lru_cache

from .cards import RANKS
from .competitive import Controller, min_key

_STEPS = [(1, True) if r == 'A' else (10 if r in ('J', 'Q', 'K') else int(r), False)
          for r in RANKS]
BUST = 22


def _value(hard, ace):
    return hard + 10 if ace and hard + 10 <= 21 else hard


def state_of(cards):
    """Рука как (сумма с тузами за 1, есть ли туз)."""
    hard, ace = 0, False
    for card in cards:
        if card.rank == 'A':
            hard += 1
            ace = True
        else:
            hard += card.value
    return hard, ace


def up_value(card):
    return 11 if card.rank == 'A' else card.value


# ---------- ожидаемый результат руки против дилера ----------
@lru_cache(maxsize=None)
def _dealer_final(hard, ace):
    value = _value(hard, ace)
    if value >= 17:
        return ((value if value <= 21 else BUST, 1.0),)
    out = defaultdict(float)
    for add, is_ace in _STEPS:
        for final, p in _dealer_final(hard + add, ace or is_ace):
            out[final] += p / len(_STEPS)
    return tuple(sorted(out.items()))


@lru_cache(maxsize=None)
def stand_ev(total, up):
    """Ожидаемый результат (в ставках), если остановиться на total при открытой карте дилера up."""
    if total > 21:
        return -1.0
    start = (1, True) if up == 11 else (up, False)
    win = lose = 0.0
    for final, p in _dealer_final(*start):
        if final == BUST or final < total:
            win += p
        elif final > total:
            lose += p
    return win - lose


@lru_cache(maxsize=None)
def _forced(hard, ace, up):
    return sum(stand_ev(_value(hard + add, ace or is_ace), up) for add, is_ace in _STEPS) / len(_STEPS)


def forced_score(cards, up):
    """Оценка руки, если сейчас придётся взять одну обычную карту и остановиться."""
    hard, ace = state_of(cards)
    return _forced(hard, ace, up)


def hand_ev(cards, up):
    """Оценка руки при разумной игре: остановиться или взять ещё одну карту."""
    hard, ace = state_of(cards)
    value = _value(hard, ace)
    if value > 21:
        return -1.0
    return max(stand_ev(value, up), _forced(hard, ace, up))


# ---------- основная стратегия (дилер стоит на любом 17) ----------
def basic_action(hard, ace, up, can_double):
    total = _value(hard, ace)
    soft = ace and hard + 10 <= 21
    if soft:
        if total >= 19:
            return 'stand'
        if total == 18:
            if up in (3, 4, 5, 6):
                return 'double' if can_double else 'stand'
            return 'stand' if up in (2, 7, 8) else 'hit'
        if total == 17:
            return 'double' if can_double and up in (3, 4, 5, 6) else 'hit'
        if total in (15, 16):
            return 'double' if can_double and up in (4, 5, 6) else 'hit'
        return 'double' if can_double and up in (5, 6) else 'hit'
    if total >= 17:
        return 'stand'
    if total >= 13:
        return 'stand' if up <= 6 else 'hit'
    if total == 12:
        return 'stand' if 4 <= up <= 6 else 'hit'
    if total == 11:
        return 'double' if can_double and up <= 10 else 'hit'
    if total == 10:
        return 'double' if can_double and up <= 9 else 'hit'
    if total == 9:
        return 'double' if can_double and 3 <= up <= 6 else 'hit'
    return 'hit'


def should_split(rank, up):
    """Когда делить пару (основная стратегия): тузы и восьмёрки всегда, десятки и пятёрки никогда."""
    if rank in ('A', '8'):
        return True
    if rank == '9':
        return up not in (7, 10, 11)
    if rank in ('2', '3', '7'):
        return up <= 7
    if rank == '6':
        return up <= 6
    if rank == '4':
        return up in (5, 6)
    return False


def should_surrender(hard, ace, up):
    """Сдаваться стоит жёсткими 16 против 9, 10 и туза и жёсткими 15 против 10."""
    if ace and hard + 10 <= 21:
        return False                                  # мягкая рука
    return (hard == 16 and up in (9, 10, 11)) or (hard == 15 and up == 10)


class Bot(Controller):
    """err: шанс ошибки (ошибается на пограничных ходах); style: куда тянет ошибки
    ('neutral', 'cautious' чаще стоит, 'reckless' чаще берёт и удваивает)."""

    def __init__(self, name, rng, err=0.1, style='neutral', rivalry=0.3, bet=100):
        self.name = name
        self.rng = rng
        self.err = err
        self.style = style
        self.rivalry = rivalry
        self.bet_amount = bet

    def bet(self, view):
        return self.bet_amount

    # ---------- обычные ходы ----------
    def action(self, view, hand_index, allowed):
        hand = view.players[view.me].hands[hand_index]
        hard, ace = state_of(hand.cards)
        total = _value(hard, ace)
        can_double = 'double' in allowed
        up = up_value(view.dealer_up)
        if 'split' in allowed and should_split(hand.cards[0].rank, up) and \
                self.rng.random() >= self.err:
            return 'split'
        if 'surrender' in allowed and should_surrender(hard, ace, up) and \
                self.rng.random() >= self.err:
            return 'surrender'
        best = basic_action(hard, ace, up, can_double)
        choice = best
        if self.rng.random() < self.err:
            choice = self._mistake(best, total, can_double)
        if choice in allowed:
            return choice
        return best if best in allowed else 'stand'

    def _mistake(self, best, total, can_double):
        if self.style == 'cautious':
            if best == 'hit' and total >= 12:
                return 'stand'
            if best == 'double':
                return 'hit'
        elif self.style == 'reckless':
            if best == 'stand' and 12 <= total <= 16:
                return 'hit'
            if best == 'hit' and can_double and 12 <= total <= 14:
                return 'double'
        else:
            if best in ('hit', 'stand') and 12 <= total <= 16:
                return 'stand' if best == 'hit' else 'hit'
            if best == 'double':
                return 'hit'
        return best

    # ---------- спец-карты ----------
    def _others(self, view):
        """Чужие живые руки: [(игрок, рука, HandView)]."""
        return [(i, j, h) for i, p in enumerate(view.players) if i != view.me
                for j, h in enumerate(p.hands) if h.status == 'live']

    def _random_choice(self):
        return self.rng.random() < self.err

    def use_snc(self, view, hand_index):
        if self._random_choice():
            return self.rng.random() < 0.5
        hand = view.players[view.me].hands[hand_index]
        return hand_ev(hand.cards, up_value(view.dealer_up)) > 0.0     # вторая рука с плюсом

    def min_choice(self, view, hand_index, plus):
        others = self._others(view)
        if not others:
            return None
        if self._random_choice():
            return self.rng.choice([None] + [(i, j) for i, j, _ in others])
        up = up_value(view.dealer_up)
        mine = view.players[view.me].hands[hand_index].cards
        own_card = min(mine, key=min_key)
        best_choice = None
        best_value = forced_score(list(mine) + [own_card], up) - forced_score(mine, up)
        for i, j, hand in others:
            card = min(hand.cards if plus else mine, key=min_key)
            harm = hand_ev(hand.cards, up) - hand_ev(list(hand.cards) + [card], up)
            if self.rivalry * harm > best_value:
                best_choice, best_value = (i, j), self.rivalry * harm
        return best_choice

    def one_for_all(self, view, hand_index):
        if self._random_choice():
            return self.rng.choice(('hit', 'stand'))
        up = up_value(view.dealer_up)
        mine = view.players[view.me].hands[hand_index].cards
        others = [h.cards for _, _, h in self._others(view)]
        hard, ace = state_of(mine)
        scores = {
            'stand': stand_ev(_value(hard, ace), up)
                     - self.rivalry * sum(hand_ev_stand(c, up) for c in others),
            'hit': forced_score(mine, up)
                   - self.rivalry * sum(forced_score(c, up) for c in others),
        }
        return max(scores, key=scores.get)

    def swap(self, view, hand_index):
        others = self._others(view)
        if not others:
            return None
        if self._random_choice():
            return self.rng.choice([None] + [(i, j) for i, j, _ in others])
        up = up_value(view.dealer_up)
        mine = view.players[view.me].hands[hand_index].cards
        best_choice, best_value = None, 0.15
        for i, j, hand in others:
            gain = forced_score(hand.cards, up) - forced_score(mine, up)
            harm = hand_ev(hand.cards, up) - hand_ev(mine, up)
            if gain + self.rivalry * harm > best_value:
                best_choice, best_value = (i, j), gain + self.rivalry * harm
        return best_choice

    def dealer_card(self, view, hand_index):
        if self._random_choice():
            return self.rng.randrange(len(view.players[view.me].hands[hand_index].cards))
        mine = list(view.players[view.me].hands[hand_index].cards)
        taken = view.dealer_up
        best_index, best_score = 0, None
        for index, card in enumerate(mine):
            after = mine[:index] + mine[index + 1:] + [taken]
            score = forced_score(after, up_value(card))     # дилер получит эту карту
            if best_score is None or score > best_score:
                best_index, best_score = index, score
        return best_index


def hand_ev_stand(cards, up):
    hard, ace = state_of(cards)
    return stand_ev(_value(hard, ace), up)


PROFILES = {
    'эксперт': dict(err=0.02, style='neutral', rivalry=0.3),
    'обычный': dict(err=0.12, style='neutral', rivalry=0.3),
    'новичок': dict(err=0.35, style='neutral', rivalry=0.3),
    'осторожный': dict(err=0.15, style='cautious', rivalry=0.1),
    'азартный': dict(err=0.20, style='reckless', rivalry=0.6),
}


def make_bot(profile, rng, bet=100):
    return Bot(profile, rng, bet=bet, **PROFILES[profile])
