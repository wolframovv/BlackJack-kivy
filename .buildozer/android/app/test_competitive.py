"""Соревновательный режим: спец-карты, раунды, боты."""
import random
import unittest

from core import bots
from core.cards import Card
from core.competitive import (Config, Controller, FixedCard, HandView, Player, PlayerView,
                              SPECIAL_KINDS, SpecialCard, Table, TableHand, View)

SUITS = {'H': 'hearts', 'D': 'diamonds', 'C': 'clubs', 'S': 'spades'}
LETTERS = {name: letter for letter, name in SUITS.items()}


def card(text):
    return Card(text[:-1], SUITS[text[-1]])


def hand(text, bet=100, **flags):
    h = TableHand(bet)
    h.cards = [card(c) for c in text.split()]
    for key, value in flags.items():
        setattr(h, key, value)
    return h


class Scripted(Controller):
    """Контроллер с заранее заданными ответами."""

    def __init__(self, snc=False, min_target=None, ofa='stand', swap_target=None,
                 dealer_index=0, actions=(), bet=100):
        self.snc, self.min_target, self.ofa = snc, min_target, ofa
        self.swap_target, self.dealer_index = swap_target, dealer_index
        self.actions, self._bet = list(actions), bet

    def bet(self, view):
        return self._bet

    def action(self, view, hand_index, allowed):
        return self.actions.pop(0) if self.actions else 'stand'

    def use_snc(self, view, hand_index):
        return self.snc

    def min_choice(self, view, hand_index, plus):
        return self.min_target

    def one_for_all(self, view, hand_index):
        return self.ofa

    def swap(self, view, hand_index):
        return self.swap_target

    def dealer_card(self, view, hand_index):
        return self.dealer_index


def make_table(count=3, config=None, controllers=None, seed=1):
    controllers = controllers or [Scripted() for _ in range(count)]
    players = [Player(f'P{i}', c, 1000) for i, c in enumerate(controllers)]
    table = Table(players, config or Config(1, ()), random.Random(seed))
    table.dealer = hand('KH 7D')
    return table


def code(c):
    """Карта в виде '10H' (для сравнения в тестах); «среднее» как '~8'."""
    return f'~{c.value}' if isinstance(c, FixedCard) else c.rank + LETTERS[c.suit]


def texts(cards):
    return sorted(code(c) for c in cards)


class DeckTests(unittest.TestCase):
    def test_deck_composition(self):
        table = make_table(config=Config(2, SPECIAL_KINDS * 2))
        table.build_deck()
        specials = [c for c in table.deck if isinstance(c, SpecialCard)]
        self.assertEqual(len(table.deck), 104 + 18)
        self.assertEqual(len(specials), 18)
        for kind in SPECIAL_KINDS:
            self.assertEqual(sum(1 for c in specials if c.kind == kind), 2)

    def test_specials_never_dealt_as_normal_cards(self):
        table = make_table()
        table.deck = [card('2C'), SpecialCard('troll'), SpecialCard('swap'), SpecialCard('dealer')]
        drawn = table._draw_normal()
        self.assertIsInstance(drawn, Card)
        self.assertEqual(drawn.rank, '2')
        self.assertEqual(sum(isinstance(c, SpecialCard) for c in table.deck), 3)   # вернулись в колоду


class SpecialEffectTests(unittest.TestCase):
    def test_troll_keeps_cards_counts_bets_and_shield(self):
        for seed in range(30):
            table = make_table(seed=seed)
            table.players[0].hands = [hand('10H 5S', 100)]
            table.players[1].hands = [hand('9C 9D 2S', 50)]
            table.players[2].hands = [hand('10C 10D', 70, is_stand=True)]      # встал: защищён
            before = texts(table.players[0].hands[0].cards + table.players[1].hands[0].cards)
            table._sp_troll(0, 0)
            hands = [p.hands[0] for p in table.players]
            self.assertEqual(texts(hands[2].cards), ['10C', '10D'])
            self.assertEqual(texts(hands[0].cards + hands[1].cards), before)
            self.assertEqual((len(hands[0].cards), len(hands[1].cards)), (2, 3))
            self.assertEqual([h.bet for h in hands], [100, 50, 70])
            for h in hands:
                self.assertEqual(h.value > 21, not h.is_active)               # перебор отмечен
            self.assertEqual(table.events[-1].targets, (1,))

    def test_snc_used_declined_and_no_money(self):
        table = make_table(controllers=[Scripted(snc=True), Scripted(), Scripted()])
        player = table.players[0]
        player.hands = [hand('7H 7S', 100)]
        table._sp_snc(0, 0)
        self.assertEqual(len(player.hands), 2)
        self.assertEqual(texts(player.hands[1].cards), ['7H', '7S'])
        self.assertEqual((player.hands[1].bet, player.balance), (100, 900))
        self.assertIsNot(player.hands[0], player.hands[1])

        table = make_table()                                      # отказ
        table.players[0].hands = [hand('7H 7S', 100)]
        table._sp_snc(0, 0)
        self.assertEqual((len(table.players[0].hands), table.players[0].balance), (1, 1000))

        table = make_table(controllers=[Scripted(snc=True), Scripted(), Scripted()])
        table.players[0].balance = 50                              # не хватает денег
        table.players[0].hands = [hand('7H 7S', 100)]
        table._sp_snc(0, 0)
        self.assertEqual((len(table.players[0].hands), table.players[0].balance), (1, 50))

    def test_average(self):
        table = make_table()
        player = table.players[0]
        player.hands = [hand('10H 9S 5C', 90)]
        table._sp_average(0, 0)
        h = player.hands[0]
        self.assertEqual(len(h.cards), 1)
        self.assertIsInstance(h.cards[0], FixedCard)
        self.assertEqual((h.value, h.bet, player.balance), (8, 30, 1060))     # 24/3 = 8, 90/3 = 30

        player.hands = [hand('AH KS', 100)]                        # туз считается за 1: (1+10)/2 = 5,5 -> 6
        table._sp_average(0, 0)
        self.assertEqual((player.hands[0].value, player.hands[0].bet), (6, 50))

        player.hands = [hand('7H', 100)]                           # одна карта не меняется
        table._sp_average(0, 0)
        self.assertEqual((player.hands[0].value, player.hands[0].bet), (7, 100))

    def test_min_self_and_other(self):
        table = make_table()
        table.players[0].hands = [hand('2H 9S')]
        table.players[1].hands = [hand('9C 10D')]
        table._sp_min(0, 0)                                        # себе: копия двойки
        self.assertEqual(texts(table.players[0].hands[0].cards), ['2H', '2H', '9S'])

        table = make_table(controllers=[Scripted(min_target=(1, 0)), Scripted(), Scripted()])
        table.players[0].hands = [hand('2H 9S')]
        table.players[1].hands = [hand('9C 10D')]
        table._sp_min(0, 0)                                        # другому: копия МОЕЙ минимальной (2)
        self.assertEqual(texts(table.players[1].hands[0].cards), ['10D', '2H', '9C'])
        self.assertTrue(table.players[1].hands[0].is_active)       # 21

    def test_min_plus_uses_targets_min_card(self):
        table = make_table(controllers=[Scripted(min_target=(1, 0)), Scripted(), Scripted()])
        table.players[0].hands = [hand('2H 3S')]
        table.players[1].hands = [hand('9C 10D')]
        table._sp_min_plus(0, 0)                                   # копия карты получателя: 9
        self.assertEqual(texts(table.players[1].hands[0].cards), ['10D', '9C', '9C'])
        self.assertFalse(table.players[1].hands[0].is_active)      # перебор 28
        self.assertEqual(table.events[-1].targets, (1,))

    def test_min_ignores_shielded_and_invalid_targets(self):
        table = make_table(controllers=[Scripted(min_target=(1, 0)), Scripted(), Scripted()])
        table.players[0].hands = [hand('2H 9S')]
        table.players[1].hands = [hand('9C 10D', is_stand=True)]    # встал: защищён
        table.players[2].hands = [hand('KC 5D', is_active=False)]    # перебрал
        table._sp_min(0, 0)
        self.assertEqual(texts(table.players[1].hands[0].cards), ['10D', '9C'])
        self.assertEqual(len(table.players[0].hands[0].cards), 3)    # досталось себе
        self.assertEqual(table.events[-1].info, 'self')

    def test_one_for_all_stand_and_hit(self):
        table = make_table(controllers=[Scripted(ofa='stand'), Scripted(), Scripted()])
        table.players[0].hands = [hand('8H 3S')]
        table.players[1].hands = [hand('9C 4D')]
        table.players[2].hands = [hand('10C 4D', is_stand=True)]
        self.assertTrue(table._sp_one_for_all(0, 0))
        self.assertTrue(table.players[0].hands[0].is_stand)
        self.assertTrue(table.players[1].hands[0].is_stand)
        self.assertEqual(len(table.players[2].hands[0].cards), 2)

        table = make_table(controllers=[Scripted(ofa='hit'), Scripted(), Scripted()])
        table.players[0].hands = [hand('8H 3S')]
        table.players[1].hands = [hand('9C 4D')]
        table.players[2].hands = [hand('10C 4D', is_stand=True)]
        table.deck = [card('2C'), card('3C'), card('KC')]           # сдаются с конца: K, 3, 2
        self.assertTrue(table._sp_one_for_all(0, 0))
        self.assertEqual(texts(table.players[0].hands[0].cards), ['3S', '8H', 'KC'])
        self.assertTrue(table.players[0].hands[0].is_active)         # 8+3+10 = 21: не перебор
        self.assertEqual(texts(table.players[1].hands[0].cards), ['3C', '4D', '9C'])
        self.assertEqual(len(table.players[2].hands[0].cards), 2)    # кто встал, тот не берёт

    def test_loser(self):
        table = make_table()
        table.players[0].hands = [hand('5H 6S')]
        table.players[1].hands = [hand('10C 9D')]
        table.players[2].hands = [hand('3C')]                         # одна карта: пропускается
        table.players.append(Player('P3', Scripted(), 1000))
        table.players[3].hands = [hand('KC 2D', is_stand=True)]       # встал: защищён
        table._sp_loser(0, 0)
        self.assertEqual(texts(table.players[1].hands[0].cards), ['9D'])
        self.assertEqual(texts(table.players[2].hands[0].cards), ['3C'])
        self.assertEqual(texts(table.players[3].hands[0].cards), ['2D', 'KC'])
        self.assertEqual(texts(table.players[0].hands[0].cards), ['10C', '5H', '6S'])
        self.assertEqual(table.events[-1].targets, (1,))

    def test_loser_ace_counts_as_max(self):
        table = make_table()
        table.players[0].hands = [hand('2H 3S')]
        table.players[1].hands = [hand('AC 9D')]
        table._sp_loser(0, 0)
        self.assertEqual(texts(table.players[1].hands[0].cards), ['9D'])
        self.assertEqual(texts(table.players[0].hands[0].cards), ['2H', '3S', 'AC'])

    def test_dealer_swap(self):
        table = make_table(controllers=[Scripted(dealer_index=1), Scripted(), Scripted()])
        table.players[0].hands = [hand('5H 6S')]
        table.players[1].hands = [hand('9C 9D')]
        table.dealer = hand('KH 7D')
        table._sp_dealer(0, 0)
        self.assertEqual(texts(table.dealer.cards), ['6S', '7D'])
        self.assertEqual(texts(table.players[0].hands[0].cards), ['5H', 'KH'])
        self.assertEqual(table.dealer.cards[0].rank, '6')            # открытая карта дилера заменена
        self.assertEqual(table.events[-1].targets, (1,))

        table = make_table(controllers=[Scripted(dealer_index='bad'), Scripted(), Scripted()])
        table.players[0].hands = [hand('5H 6S')]
        table._sp_dealer(0, 0)                                       # плохой ответ: отдаём самую маленькую
        self.assertEqual(texts(table.dealer.cards), ['5H', '7D'])

    def test_swap(self):
        table = make_table(controllers=[Scripted(swap_target=(1, 0)), Scripted(), Scripted()])
        table.players[0].hands = [hand('2H 3S', 100)]
        table.players[1].hands = [hand('10C 9D', 40)]
        table._sp_swap(0, 0)
        self.assertEqual(texts(table.players[0].hands[0].cards), ['10C', '9D'])
        self.assertEqual(texts(table.players[1].hands[0].cards), ['2H', '3S'])
        self.assertEqual((table.players[0].hands[0].bet, table.players[1].hands[0].bet), (100, 40))

        table = make_table()                                          # отказ
        table.players[0].hands = [hand('2H 3S')]
        table.players[1].hands = [hand('10C 9D')]
        table._sp_swap(0, 0)
        self.assertEqual(texts(table.players[0].hands[0].cards), ['2H', '3S'])
        self.assertEqual(table.events[-1].info, 'declined')

        table = make_table()                                          # некому менять
        table.players[0].hands = [hand('2H 3S')]
        table.players[1].hands = [hand('10C 9D', is_stand=True)]
        table._sp_swap(0, 0)
        self.assertEqual(table.events[-1].info, 'no_target')

    def test_targets_exclude_shielded_own_and_natural(self):
        table = make_table()
        table.players[0].hands = [hand('5H 6S')]
        table.players[1].hands = [hand('9C 9D'), hand('2C 3D', is_stand=True)]
        table.players[2].hands = [hand('AC KD', natural=True)]
        self.assertEqual(table._live_targets(0), [(1, 0)])
        self.assertEqual(table._live_slots(), [(0, 0), (1, 0)])

    def test_special_then_normal_card_and_chain(self):
        table = make_table()
        table.players[0].hands = [hand('10H 9S', 100)]
        table.deck = [card('2C'), SpecialCard('average')]             # сначала Average, затем 2C
        table._hit(0, 0)
        h = table.players[0].hands[0]
        self.assertEqual([code(c) for c in h.cards], ['~10', '2C'])
        self.assertEqual((h.value, h.bet, table.specials_drawn), (12, 50, 1))

    def test_one_for_all_replaces_the_normal_card(self):
        table = make_table(controllers=[Scripted(ofa='stand'), Scripted(), Scripted()])
        table.players[0].hands = [hand('10H 4S')]
        table.deck = [card('2C'), SpecialCard('one_for_all')]
        table._hit(0, 0)
        self.assertEqual(len(table.players[0].hands[0].cards), 2)     # обычная карта не выдана
        self.assertEqual(len(table.deck), 1)
        self.assertTrue(table.players[0].hands[0].is_stand)

    def test_busted_by_special_stops_the_hit(self):
        table = make_table(controllers=[Scripted(), Scripted(), Scripted()])
        table.players[0].hands = [hand('10H 6S 5C')]                  # 21
        table.players[1].hands = [hand('KC 9D')]
        table.deck = [card('2C'), SpecialCard('loser')]               # Loser дарит 10 -> перебор
        table._hit(0, 0)
        self.assertFalse(table.players[0].hands[0].is_active)
        self.assertEqual(len(table.deck), 1)                          # 2C не выдавалась


class RoundTests(unittest.TestCase):
    def play(self, deck_text, controllers, config=None):
        table = make_table(controllers=controllers, config=config)
        deck = [card(c) for c in deck_text.split()]
        table.build_deck = lambda: setattr(table, 'deck', list(deck))
        return table, table.play_round()

    def test_dealer_blackjack(self):
        # порядок сдачи: P0, P1, дилер, P0, P1, дилер; карты берутся с конца списка
        table, report = self.play('QD KS 8S AS AH 10H', [Scripted(), Scripted()])
        self.assertEqual(report.nets, {0: -100, 1: 0})                # у P1 тоже блэкджек: ничья
        self.assertEqual(report.circles, 0)

    def test_player_blackjack_pays_3_to_2(self):
        table, report = self.play('7C 8S KS 10D 10H AH', [Scripted(), Scripted()])
        self.assertEqual(report.nets, {0: 150, 1: 100})               # дилер 17, у P1 18

    def test_hit_bust_and_double(self):
        # P0: 10+6 берёт 9 -> 25, перебор. P1: 5+5 удваивает, берёт 10 -> 20 против 17 у дилера
        table, report = self.play('10C 9C 7C 5S 6S 10D 5H 10H', [Scripted(actions=['hit']),
                                                                   Scripted(actions=['double'])])
        self.assertEqual(report.nets[0], -100)
        self.assertEqual(report.nets[1], 200)

    def test_loss_when_everyone_busts_dealer_does_not_play(self):
        # P0: 10+6 берёт 9 -> перебор; дилер (10+5 = 15) мог бы брать, но не играет
        table, report = self.play('9C 5C 6S 10D 10H', [Scripted(actions=['hit'])])
        self.assertEqual(report.nets[0], -100)
        self.assertEqual(len(table.dealer.cards), 2)

    def test_full_random_rounds_keep_invariants(self):
        for decks, copies in ((1, 1), (2, 2), (1, 2)):
            rng = random.Random(decks * 10 + copies)
            players = [Player(name, bots.make_bot(name, random.Random(rng.random())), 10_000)
                       for name in bots.PROFILES]
            table = Table(players, Config(decks, SPECIAL_KINDS * copies), random.Random(5))
            for _ in range(400):
                for p in players:
                    p.balance = 10_000
                report = table.play_round()
                self.assertLessEqual(report.circles, Table.MAX_CIRCLES)
                self.assertLessEqual(len(report.events), report.specials)
                for p in players:
                    self.assertIsInstance(p.balance, int)
                    self.assertGreaterEqual(p.balance, 0)
                    for h in p.hands:
                        self.assertFalse(h.live)                     # все руки закончены
                        self.assertGreater(h.bet, 0)

    def test_same_seed_same_result(self):
        def run():
            rng = random.Random(3)
            players = [Player(n, bots.make_bot(n, random.Random(rng.random())), 10_000)
                       for n in bots.PROFILES]
            table = Table(players, Config(2, SPECIAL_KINDS * 2), random.Random(4))
            out = []
            for _ in range(50):
                for p in players:
                    p.balance = 10_000
                out.append(sorted(table.play_round().nets.items()))
            return out
        self.assertEqual(run(), run())

    def test_button_moves_every_round(self):
        table = make_table(controllers=[Scripted(), Scripted(), Scripted()])
        buttons = [table.play_round().button for _ in range(4)]
        self.assertEqual(buttons, [0, 1, 2, 0])

    def test_player_without_money_sits_out(self):
        table = make_table(controllers=[Scripted(), Scripted()])
        table.players[0].balance = 0
        report = table.play_round()
        self.assertEqual(list(report.nets), [1])
        self.assertEqual(table.players[0].hands, [])


class BotTests(unittest.TestCase):
    def action(self, text, up, can_double=True):
        hard, ace = bots.state_of([card(c) for c in text.split()])
        return bots.basic_action(hard, ace, up, can_double)

    def test_basic_strategy(self):
        self.assertEqual(self.action('10H 6S', 10), 'hit')
        self.assertEqual(self.action('10H 6S', 6), 'stand')
        self.assertEqual(self.action('10H 2S', 4), 'stand')
        self.assertEqual(self.action('10H 2S', 3), 'hit')
        self.assertEqual(self.action('10H 7S', 11), 'stand')
        self.assertEqual(self.action('6H 5S', 6), 'double')
        self.assertEqual(self.action('6H 5S', 6, can_double=False), 'hit')
        self.assertEqual(self.action('6H 4S', 10), 'hit')                 # 10 против 10: не удваиваем
        self.assertEqual(self.action('5H 4S', 5), 'double')
        self.assertEqual(self.action('AH 7S', 9), 'hit')                  # мягкие 18
        self.assertEqual(self.action('AH 7S', 6), 'double')
        self.assertEqual(self.action('AH 7S', 6, can_double=False), 'stand')
        self.assertEqual(self.action('AH 7S', 7), 'stand')
        self.assertEqual(self.action('AH 9S', 6), 'stand')

    def test_dealer_distribution_and_ev(self):
        for up in range(2, 12):
            start = (1, True) if up == 11 else (up, False)
            self.assertAlmostEqual(sum(p for _, p in bots._dealer_final(*start)), 1.0, places=9)
        bust = lambda up: dict(bots._dealer_final(*((1, True) if up == 11 else (up, False)))).get(22, 0)
        self.assertAlmostEqual(bust(6), 0.42, delta=0.02)
        self.assertAlmostEqual(bust(10), 0.21, delta=0.02)
        self.assertAlmostEqual(bust(11), 0.12, delta=0.02)
        values = [bots.stand_ev(total, 10) for total in range(12, 22)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(bots.stand_ev(22, 10), -1.0)

    def test_bot_returns_only_allowed_actions_and_valid_targets(self):
        rng = random.Random(9)
        for name in bots.PROFILES:
            bot = bots.make_bot(name, random.Random(1))
            for _ in range(300):
                text = ' '.join(rng.choice(['2H', '5S', '9C', 'KD', 'AH', '7S', '3D'])
                                for _ in range(rng.randint(1, 4)))
                cards = tuple(card(c) for c in text.split())
                other = tuple(card(c) for c in ('10H', '6S'))
                players = [PlayerView('me', 1000, [HandView(cards, 100, 'live')]),
                           PlayerView('x', 1000, [HandView(other, 100, 'live')])]
                view = View(0, players, card('9D'))
                allowed = rng.choice([('hit', 'stand'), ('hit', 'stand', 'double')])
                self.assertIn(bot.action(view, 0, allowed), allowed)
                self.assertIn(bot.one_for_all(view, 0), ('hit', 'stand'))
                self.assertIn(bot.min_choice(view, 0, rng.random() < 0.5), (None, (1, 0)))
                self.assertIn(bot.swap(view, 0), (None, (1, 0)))
                self.assertIn(bot.dealer_card(view, 0), range(len(cards)))
                self.assertIsInstance(bot.use_snc(view, 0), bool)

    def test_snc_only_when_second_hand_is_worth_it(self):
        bot = bots.Bot('b', random.Random(1), err=0.0)
        def view(text, up):
            cards = tuple(card(c) for c in text.split())
            return View(0, [PlayerView('me', 1000, [HandView(cards, 100, 'live')])], card(up))
        self.assertTrue(bot.use_snc(view('5H 5S', '6C'), 0))
        self.assertFalse(bot.use_snc(view('10H 6S', 'KC'), 0))


if __name__ == '__main__':
    unittest.main()
