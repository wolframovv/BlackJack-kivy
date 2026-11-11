"""Карты, колода и рука игрока. Не зависит от Kivy."""
import random

SUITS = ('hearts', 'diamonds', 'clubs', 'spades')
RANKS = ('2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A')
SUIT_SYMBOLS = {'hearts': '♥', 'diamonds': '♦', 'clubs': '♣', 'spades': '♠'}
RED_SUITS = ('hearts', 'diamonds')


class Card:
    """Одна карта."""

    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    @property
    def value(self):
        """Очки карты (туз считается как 11, понижается в Hand)."""
        if self.rank in ('J', 'Q', 'K'):
            return 10
        if self.rank == 'A':
            return 11
        return int(self.rank)

    @property
    def symbol(self):
        return SUIT_SYMBOLS.get(self.suit, self.suit)

    @property
    def is_red(self):
        return self.suit in RED_SUITS

    def __str__(self):
        return f"{self.rank}{self.symbol}"

    __repr__ = __str__


def cards_value(cards):
    """Сумма очков: туз считается за 11, а при переборе — за 1."""
    total = sum(card.value for card in cards)
    aces = sum(1 for card in cards if card.rank == 'A')
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def cards_is_soft(cards):
    """Мягкая рука: в ней есть туз, который сейчас считается за 11."""
    hard = sum(1 if card.rank == 'A' else card.value for card in cards)
    return any(card.rank == 'A' for card in cards) and hard + 10 <= 21


class Deck:
    """Колода из 52 карт. Карты сдаются с конца списка."""

    def __init__(self, cards=None):
        if cards is not None:
            self.cards = list(cards)
        else:
            self.build()

    def build(self):
        self.cards = [Card(rank, suit) for suit in SUITS for rank in RANKS]
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

    def deal(self):
        if not self.cards:
            self.build()  # колода кончилась — берём новую
        return self.cards.pop()


class Hand:
    """Рука (игрока или дилера)."""

    def __init__(self, bet=0):
        self.cards = []
        self.bet = bet
        self.is_active = True      # False — перебор
        self.is_stand = False
        self.has_doubled = False

    @property
    def value(self):
        return cards_value(self.cards)

    @property
    def is_soft(self):
        return cards_is_soft(self.cards)

    def add_card(self, card):
        self.cards.append(card)

    def can_split(self):
        return len(self.cards) == 2 and self.cards[0].rank == self.cards[1].rank

    def split(self):
        """Забирает вторую карту в новую руку с такой же ставкой."""
        if not self.can_split():
            return None
        new_hand = Hand(bet=self.bet)
        new_hand.add_card(self.cards.pop())
        return new_hand
