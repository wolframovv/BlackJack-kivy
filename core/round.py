"""Логика одного раунда блэкджека. Не зависит от Kivy.

Раунд меняет состояние мгновенно, а всё, что нужно показать на экране
(раздача, переворот карты, сплит), кладёт в очередь событий. Интерфейс забирает
их через pop_events() и сам решает, как и когда анимировать.

События:
    ('deal_player', hand_index, card_index, card)
    ('deal_dealer', card_index, card, hidden)
    ('flip_dealer', card_index)
    ('split', hand_index)
    ('finished',)

Каждое решение игрока (hit, stand, double, split, surrender, insurance,
no_insurance) записывается в self.decisions вместе с состоянием стола В МОМЕНТ
решения. После конца раунда core.dataset.DecisionLog сохраняет их в CSV.
"""
import uuid
from datetime import datetime, timezone

from .cards import Deck, Hand

DEALING = 'dealing'        # идёт начальная раздача
INSURANCE = 'insurance'    # у дилера туз: игрок решает, страховаться ли
PLAYER = 'player'          # ход игрока
DEALER = 'dealer'          # ход дилера
OVER = 'over'              # раунд закончен


class BlackjackRound:
    MAX_HANDS = 4

    def __init__(self, user, bet, deck=None, player=''):
        """user — словарь игрока (balance, wins, losses, ties), меняется на месте.
        Ставка bet уже списана с баланса до создания раунда."""
        self.user = user
        self.player = player
        self.total_bet = bet
        self.start_bankroll = user['balance'] + bet   # деньги игрока до ставки
        self.deck = deck if deck is not None else Deck()
        self.hands = [Hand(bet=bet)]
        self.dealer = Hand()
        self.current = 0
        self.state = DEALING
        self.split_used = False
        self.dealer_revealed = False
        self.result = None      # 'win' | 'loss' | 'tie'
        self.message = None     # (ключ перевода, число или None)
        self.events = []

        self.insurance_cost = 0     # цена страховки, если она предложена
        self.insurance = 0          # поставленная страховка
        self.insurance_net = 0      # итог страховки: +2*ставка, -ставка или 0
        self.surrendered = False
        self.player_blackjack = False

        self.round_id = uuid.uuid4().hex[:12]
        self.started_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.decisions = []

    # ---------- события ----------
    def pop_events(self):
        events, self.events = self.events, []
        return events

    # ---------- раздача ----------
    def _deal_to_player(self, hand_index):
        card = self.deck.deal()
        hand = self.hands[hand_index]
        hand.add_card(card)
        self.events.append(('deal_player', hand_index, len(hand.cards) - 1, card))

    def _deal_to_dealer(self, hidden=False):
        card = self.deck.deal()
        self.dealer.add_card(card)
        self.events.append(('deal_dealer', len(self.dealer.cards) - 1, card, hidden))

    def start(self):
        """Начальная раздача: игроку, дилеру, игроку, дилеру (закрытая)."""
        self._deal_to_player(0)
        self._deal_to_dealer()
        self._deal_to_player(0)
        self._deal_to_dealer(hidden=True)

    def finish_dealing(self):
        """Вызывается интерфейсом, когда анимация раздачи закончилась."""
        if self.state != DEALING:
            return
        cost = self.hands[0].bet // 2
        if (self.dealer.cards[0].rank == 'A' and cost >= 1
                and self.user['balance'] >= cost):
            self.insurance_cost = cost
            self.state = INSURANCE      # дилер ещё не смотрит закрытую карту
            return
        self._peek()

    # ---------- страховка ----------
    def take_insurance(self):
        if self.state != INSURANCE:
            return False
        self._log('insurance')
        self.user['balance'] -= self.insurance_cost
        self.insurance = self.insurance_cost
        self._peek()
        return True

    def decline_insurance(self):
        if self.state != INSURANCE:
            return False
        self._log('no_insurance')
        self._peek()
        return True

    def _peek(self):
        """Дилер проверяет закрытую карту на блэкджек; здесь же рассчитывается страховка."""
        player_bj = self.hands[0].value == 21
        dealer_bj = self.dealer.value == 21

        if self.insurance:
            if dealer_bj:
                self.insurance_net = self.insurance * 2
                self.user['balance'] += self.insurance * 3   # ставка страховки + выигрыш 2:1
            else:
                self.insurance_net = -self.insurance

        if not (player_bj or dealer_bj):
            self.state = PLAYER
            return

        self._reveal_dealer()
        insured_win = self.insurance_net > 0
        self.player_blackjack = player_bj and not dealer_bj
        if player_bj and dealer_bj:
            self.user['ties'] += 1
            self.user['balance'] += self.total_bet
            self.result = 'tie'
            self.message = (('both_blackjack_insured', self.insurance_net) if insured_win
                            else ('both_blackjack', None))
        elif player_bj:
            self.user['wins'] += 1
            self.user['balance'] += int(self.total_bet * 2.5)
            self.result = 'win'
            self.message = ('player_blackjack', None)
        else:
            self.user['losses'] += 1
            self.result = 'loss'
            self.message = (('dealer_blackjack_insured', self.insurance_net) if insured_win
                            else ('dealer_blackjack', None))
        self._finish()

    # ---------- проверки ----------
    def _active_hand(self):
        if self.state != PLAYER:
            return None
        if not (0 <= self.current < len(self.hands)):
            return None
        hand = self.hands[self.current]
        return hand if hand.is_active else None

    def can_hit(self):
        return self._active_hand() is not None

    can_stand = can_hit

    def can_double(self):
        hand = self._active_hand()
        return (hand is not None and len(hand.cards) == 2
                and not hand.has_doubled
                and self.user['balance'] >= hand.bet)

    def can_split(self):
        hand = self._active_hand()
        return (not self.split_used and hand is not None
                and len(hand.cards) == 2 and hand.can_split()
                and len(self.hands) < self.MAX_HANDS
                and self.user['balance'] >= hand.bet)

    def can_surrender(self):
        """Сдаться можно только первым действием на двух картах (у дилера уже нет блэкджека)."""
        hand = self._active_hand()
        return (hand is not None and self.current == 0 and len(self.hands) == 1
                and not self.split_used and len(hand.cards) == 2
                and not hand.has_doubled and hand.bet >= 2)

    @property
    def total_current_bet(self):
        return sum(hand.bet for hand in self.hands)

    @property
    def dealer_hidden(self):
        return not self.dealer_revealed and len(self.dealer.cards) > 1

    @property
    def net(self):
        """Чистый результат раунда в фишках (страховка включена)."""
        return self.user['balance'] - self.start_bankroll

    @property
    def round_result(self):
        if self.surrendered:
            return 'surrender'
        if self.player_blackjack:
            return 'blackjack'
        return self.result

    # ---------- действия игрока ----------
    def hit(self):
        hand = self._active_hand()
        if hand is None or hand.is_stand:
            return False
        self._log('hit')
        self._deal_to_player(self.current)
        if hand.value > 21:
            hand.is_active = False
            self._next_hand()
        elif hand.value == 21:
            hand.is_stand = True
            self._next_hand()
        return True

    def stand(self):
        hand = self._active_hand()
        if hand is None:
            return False
        self._log('stand')
        hand.is_stand = True
        self._next_hand()
        return True

    def double(self):
        if not self.can_double():
            return False
        self._log('double')
        hand = self.hands[self.current]
        self.user['balance'] -= hand.bet
        hand.bet *= 2
        hand.has_doubled = True
        self._deal_to_player(self.current)
        hand.is_stand = True
        if hand.value > 21:
            hand.is_active = False
        self._next_hand()
        return True

    def split(self):
        """Сплит доступен один раз за раунд."""
        if not self.can_split():
            return False
        self._log('split')
        hand = self.hands[self.current]
        self.user['balance'] -= hand.bet
        new_hand = hand.split()
        if new_hand is None:
            self.user['balance'] += hand.bet
            return False
        self.split_used = True
        self.hands.insert(self.current + 1, new_hand)
        self.events.append(('split', self.current))
        self._deal_to_player(self.current)
        self._deal_to_player(self.current + 1)
        return True

    def surrender(self):
        """Сдаться: половина ставки (с округлением вниз) возвращается, раунд окончен."""
        if not self.can_surrender():
            return False
        self._log('surrender')
        hand = self.hands[0]
        refund = hand.bet // 2
        self.user['balance'] += refund
        self.user['losses'] += 1
        hand.is_active = False
        hand.is_stand = True
        self.surrendered = True
        self.result = 'loss'
        self.message = ('surrendered', refund)
        self._reveal_dealer()
        self._finish()
        return True

    def _next_hand(self):
        self.current += 1
        if self.current >= len(self.hands):
            self._start_dealer()

    # ---------- дилер ----------
    def _reveal_dealer(self):
        if not self.dealer_revealed and len(self.dealer.cards) > 1:
            self.dealer_revealed = True
            self.events.append(('flip_dealer', 1))

    def _start_dealer(self):
        self.state = DEALER
        self._reveal_dealer()

    def dealer_step(self):
        """Один шаг дилера. True — взял карту, False — раунд подсчитан."""
        if self.state != DEALER:
            return False
        if self.dealer.value < 17:
            self._deal_to_dealer()
            return True
        self._settle()
        return False

    # ---------- итоги ----------
    def _finish(self):
        self.state = OVER
        self.events.append(('finished',))

    def _settle(self):
        dealer_value = self.dealer.value
        total_winnings = 0
        total_bet_placed = 0

        for hand in self.hands:
            player_value = hand.value
            total_bet_placed += hand.bet

            if player_value > 21:
                self.user['losses'] += 1
                self.result = 'loss'
            elif dealer_value > 21 or player_value > dealer_value:
                self.user['wins'] += 1
                self.user['balance'] += hand.bet * 2
                total_winnings += hand.bet * 2
                self.result = 'win'
            elif player_value < dealer_value:
                self.user['losses'] += 1
                self.result = 'loss'
            else:
                self.user['ties'] += 1
                self.user['balance'] += hand.bet
                total_winnings += hand.bet
                self.result = 'tie'

        if len(self.hands) == 1:
            if self.result == 'win':
                self.message = ('you_win', total_winnings - total_bet_placed)
            elif self.result == 'loss':
                self.message = ('dealer_wins', None)
            else:
                self.message = ('tie', None)
        else:
            self.message = ('game_completed', self.user['balance'])
        self._finish()

    # ---------- запись решений для обучения ----------
    def _snapshot(self, action):
        """Состояние стола в момент решения (до выполнения действия) + само действие."""
        insuring = self.state == INSURANCE
        hand = self.hands[min(self.current, len(self.hands) - 1)]
        up = self.dealer.cards[0]
        is_pair = hand.can_split()
        return {
            'round_id': self.round_id,
            'decision_idx': len(self.decisions),
            'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'player': self.player,
            'balance': self.user['balance'],
            'bet': hand.bet,
            'bet_pct': round(hand.bet / self.start_bankroll, 4) if self.start_bankroll else 0,
            'player_total': hand.value,
            'player_soft': int(hand.is_soft),
            'n_cards': len(hand.cards),
            'is_pair': int(is_pair),
            'pair_value': hand.cards[0].value if is_pair else 0,
            'hand_index': self.current if not insuring else 0,
            'n_hands': len(self.hands),
            'split_used': int(self.split_used),
            'dealer_up': up.value,
            'dealer_up_ace': int(up.rank == 'A'),
            'can_hit': int(self.can_hit()),
            'can_stand': int(self.can_hit()),
            'can_double': int(self.can_double()),
            'can_split': int(self.can_split()),
            'can_surrender': int(self.can_surrender()),
            'can_insure': int(insuring),
            'action': action,
            'player_cards': ' '.join(_card_code(c) for c in hand.cards),
            'dealer_up_card': _card_code(up),
        }

    def _log(self, action):
        self.decisions.append(self._snapshot(action))


def _card_code(card):
    """Короткая запись карты: AS, 10H, KD..."""
    return f"{card.rank}{card.suit[0].upper()}"
