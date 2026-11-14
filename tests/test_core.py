import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

from core.cards import Card, Deck, Hand, cards_is_soft, cards_value
from core.ranks import RANK_MIN_ELO, delta_for_game, rank_for_elo
from core.round import BlackjackRound, DEALING, INSURANCE, PLAYER, DEALER, OVER
from core.storage import Storage, hash_password, check_password


def C(text):
    """'AS' -> туз пик, '10H' -> десятка червей"""
    suits = {'H': 'hearts', 'D': 'diamonds', 'C': 'clubs', 'S': 'spades'}
    return Card(text[:-1], suits[text[-1]])


def stacked(*names):
    """Колода, из которой карты сдаются ровно в указанном порядке."""
    return Deck(cards=[C(n) for n in reversed(names)])


def new_user(balance=900):
    return {'balance': balance, 'wins': 0, 'losses': 0, 'ties': 0}


def play(deck_cards, bet=100, balance=900, insurance='decline'):
    """Раздача и проверка блэкджека. Если предложена страховка — по умолчанию отказ."""
    user = new_user(balance)
    r = BlackjackRound(user, bet, deck=stacked(*deck_cards), player='tester')
    r.start()
    r.finish_dealing()
    if r.state == INSURANCE:
        if insurance == 'take':
            r.take_insurance()
        elif insurance == 'decline':
            r.decline_insurance()
    return r, user


def run_dealer(r):
    while r.state == DEALER:
        r.dealer_step()


class HandTests(unittest.TestCase):
    def value(self, *names):
        h = Hand()
        for n in names:
            h.add_card(C(n))
        return h.value

    def test_values(self):
        self.assertEqual(self.value('AS', 'KH'), 21)
        self.assertEqual(self.value('AS', 'AH', '9C'), 21)
        self.assertEqual(self.value('AS', 'AH'), 12)
        self.assertEqual(self.value('KS', 'QH', '5C'), 25)
        self.assertEqual(self.value('AS', '5H', 'KC'), 16)

    def test_split_moves_second_card(self):
        h = Hand(bet=50)
        h.add_card(C('8S'))
        h.add_card(C('8H'))
        new = h.split()
        self.assertEqual(len(h.cards), 1)
        self.assertEqual(len(new.cards), 1)
        self.assertEqual(new.bet, 50)
        self.assertEqual(h.value, 8)

    def test_cannot_split_different_ranks(self):
        h = Hand()
        h.add_card(C('KS'))
        h.add_card(C('QH'))
        self.assertFalse(h.can_split())
        self.assertIsNone(h.split())


def reference_value(cards):
    """Независимый эталон подсчёта очков."""
    hard = sum(1 if c.rank == 'A' else c.value for c in cards)
    if any(c.rank == 'A' for c in cards) and hard + 10 <= 21:
        return hard + 10
    return hard


class ValueFuzzTests(unittest.TestCase):
    def test_matches_reference_and_drops_only_for_soft_hands(self):
        rng = random.Random(7)
        for _ in range(5000):
            deck = Deck()
            rng.shuffle(deck.cards)
            hand = Hand()
            previous = None
            for _ in range(rng.randint(2, 8)):
                hand.add_card(deck.deal())
                self.assertEqual(hand.value, reference_value(hand.cards))
                if previous is not None and hand.value < previous[0]:
                    # сумма может упасть только если туз был за 11 и стал за 1
                    self.assertTrue(previous[1], 'сумма упала у жёсткой руки')
                previous = (hand.value, hand.is_soft)
                if hand.value > 21:
                    break

    def test_soft_flag(self):
        self.assertTrue(cards_is_soft([C('AS'), C('9H')]))        # 20 мягкая
        self.assertFalse(cards_is_soft([C('AS'), C('9H'), C('5C')]))  # 15 жёсткая
        self.assertFalse(cards_is_soft([C('KS'), C('9H')]))
        self.assertTrue(cards_is_soft([C('AS'), C('AH')]))        # 12 мягкая
        self.assertEqual(cards_value([C('AS'), C('7H')]), 18)
        self.assertEqual(cards_value([C('AS'), C('7H'), C('9C')]), 17)


class DeckTests(unittest.TestCase):
    def test_full_unique(self):
        d = Deck()
        self.assertEqual(len(d.cards), 52)
        self.assertEqual(len({str(c) for c in d.cards}), 52)

    def test_rebuild_when_empty(self):
        d = Deck(cards=[C('2S')])
        d.deal()
        self.assertTrue(d.deal())  # не падает, колода пересоздана
        self.assertEqual(len(d.cards), 51)


class RoundTests(unittest.TestCase):
    def test_initial_deal_events(self):
        r = BlackjackRound(new_user(), 100, deck=stacked('5S', '6H', '7C', '8D'))
        r.start()
        ev = r.pop_events()
        self.assertEqual([e[0] for e in ev],
                         ['deal_player', 'deal_dealer', 'deal_player', 'deal_dealer'])
        self.assertFalse(ev[1][3])   # первая карта дилера открыта
        self.assertTrue(ev[3][3])    # вторая закрыта
        self.assertEqual(r.state, DEALING)
        self.assertEqual(r.pop_events(), [])

    def test_player_blackjack(self):
        r, u = play(['AS', '9H', 'KC', '7D'])
        self.assertEqual(r.state, OVER)
        self.assertEqual((u['wins'], u['balance']), (1, 900 + 250))
        self.assertEqual(r.message, ('player_blackjack', None))
        kinds = [e[0] for e in r.pop_events()]
        self.assertIn('flip_dealer', kinds)
        self.assertIn('finished', kinds)

    def test_dealer_blackjack(self):
        r, u = play(['9S', 'AH', '7C', 'KD'])
        self.assertEqual(r.state, OVER)
        self.assertEqual((u['losses'], u['balance']), (1, 900))
        self.assertEqual(r.message, ('dealer_blackjack', None))

    def test_both_blackjack(self):
        r, u = play(['AS', 'AH', 'KC', 'KD'])
        self.assertEqual((u['ties'], u['balance']), (1, 1000))
        self.assertEqual(r.message, ('both_blackjack', None))

    def test_no_blackjack_goes_to_player(self):
        r, _ = play(['9S', '9H', '8C', '7D'])
        self.assertEqual(r.state, PLAYER)
        self.assertTrue(r.can_hit())
        self.assertTrue(r.dealer_hidden)

    def test_hit_bust_then_dealer_plays_and_loses(self):
        # игрок 10+6, дилер 10+7; игрок берёт 10 -> перебор
        r, u = play(['10S', '10H', '6C', '7D', 'KS'])
        self.assertTrue(r.hit())
        self.assertFalse(r.hands[0].is_active)
        self.assertEqual(r.state, DEALER)
        run_dealer(r)
        self.assertEqual(r.state, OVER)
        self.assertEqual((u['losses'], u['balance']), (1, 900))
        self.assertEqual(r.message, ('dealer_wins', None))

    def test_hit_to_21_auto_stands(self):
        # 5+6=11, берёт 10 -> 21
        r, u = play(['5S', '9H', '6C', '8D', 'KS'])
        r.hit()
        self.assertTrue(r.hands[0].is_stand)
        self.assertEqual(r.state, DEALER)
        run_dealer(r)
        self.assertEqual((u['wins'], u['balance']), (1, 1100))
        self.assertEqual(r.message, ('you_win', 100))

    def test_stand_dealer_draws_to_17(self):
        # игрок 10+9=19; дилер 10+6=16 берёт 2 -> 18; выигрыш игрока
        r, u = play(['10S', '10H', '9C', '6D', '2S'])
        self.assertTrue(r.stand())
        self.assertEqual(r.state, DEALER)
        steps = 0
        while r.state == DEALER:
            r.dealer_step()
            steps += 1
        self.assertEqual(len(r.dealer.cards), 3)
        self.assertEqual(r.dealer.value, 18)
        self.assertEqual((u['wins'], u['balance']), (1, 1100))

    def test_dealer_bust_pays_player(self):
        # дилер 10+6, берёт K -> 26
        r, u = play(['10S', '10H', '8C', '6D', 'KS'])
        r.stand()
        run_dealer(r)
        self.assertEqual((u['wins'], u['balance']), (1, 1100))

    def test_push(self):
        r, u = play(['10S', '10H', '8C', '8D'])
        r.stand()
        run_dealer(r)
        self.assertEqual((u['ties'], u['balance']), (1, 1000))
        self.assertEqual(r.message, ('tie', None))

    def test_dealer_wins_higher(self):
        r, u = play(['10S', '10H', '7C', '9D'])
        r.stand()
        run_dealer(r)
        self.assertEqual((u['losses'], u['balance']), (1, 900))

    def test_double(self):
        # 5+6=11, удвоение: берёт 10 -> 21; ставка 200
        r, u = play(['5S', '9H', '6C', '8D', 'KS'], bet=100, balance=900)
        self.assertTrue(r.can_double())
        self.assertTrue(r.double())
        self.assertEqual(u['balance'], 800)
        self.assertEqual(r.hands[0].bet, 200)
        self.assertEqual(len(r.hands[0].cards), 3)
        self.assertEqual(r.state, DEALER)
        run_dealer(r)
        self.assertEqual(u['balance'], 800 + 400)
        self.assertEqual(r.message, ('you_win', 200))

    def test_double_bust_marks_hand_inactive(self):
        # 6+6=12, удвоение: берёт K -> 22
        r, u = play(['6S', '9H', '6C', '8D', 'KS'], bet=100, balance=900)
        self.assertTrue(r.double())
        self.assertGreater(r.hands[0].value, 21)
        self.assertFalse(r.hands[0].is_active)
        run_dealer(r)
        self.assertEqual((u['losses'], u['balance']), (1, 800))

    def test_double_needs_money(self):
        r, _ = play(['5S', '9H', '6C', '8D', 'KS'], bet=100, balance=50)
        self.assertFalse(r.can_double())
        self.assertFalse(r.double())

    def test_split_once(self):
        # 8+8, дилер 9+7; после сплита каждая рука получает карту
        r, u = play(['8S', '9H', '8C', '7D', '3S', '2H', 'KC', 'QD'])
        self.assertTrue(r.can_split())
        self.assertTrue(r.split())
        self.assertEqual(u['balance'], 800)
        self.assertEqual(len(r.hands), 2)
        self.assertEqual([len(h.cards) for h in r.hands], [2, 2])
        self.assertEqual(r.hands[0].value, 11)   # 8+3
        self.assertEqual(r.hands[1].value, 10)   # 8+2
        kinds = [e[0] for e in r.pop_events()]
        self.assertIn('split', kinds)
        self.assertFalse(r.can_split())          # второй сплит запрещён

    def test_split_two_hands_settlement(self):
        r, u = play(['8S', '10H', '8C', '8D', '3S', '2H', 'KC', 'QD'])
        r.split()
        # рука 0: 8+3 -> берёт K = 21 (автостенд), рука 1: 8+2 -> берёт Q = 20
        r.hit()
        self.assertEqual(r.current, 1)
        r.hit()
        self.assertEqual(r.state, PLAYER)   # 20 — не автостенд
        r.stand()
        self.assertEqual(r.state, DEALER)
        run_dealer(r)
        # дилер 10+8=18, обе руки выигрывают
        self.assertEqual(u['wins'], 2)
        self.assertEqual(u['balance'], 800 + 200 + 200)
        self.assertEqual(r.message, ('game_completed', u['balance']))

    def test_cannot_act_when_not_player_turn(self):
        r = BlackjackRound(new_user(), 100, deck=stacked('5S', '6H', '7C', '8D'))
        r.start()
        self.assertFalse(r.hit())      # ещё идёт раздача
        self.assertFalse(r.stand())
        r.finish_dealing()
        r.stand()
        self.assertFalse(r.hit())      # ход дилера

    def test_total_current_bet(self):
        r, _ = play(['8S', '9H', '8C', '7D', '3S', '2H'])
        r.split()
        self.assertEqual(r.total_current_bet, 200)



class EloTests(unittest.TestCase):
    class FixedRng:
        def __init__(self, value):
            self.value = value

        def randint(self, low, high):
            self.assert_low, self.assert_high = low, high
            return self.value

    def test_rank_thresholds_every_200(self):
        self.assertEqual(RANK_MIN_ELO, tuple(range(0, 2000, 200)))
        for elo, expected in ((0, 1), (199, 1), (200, 2), (399, 2), (400, 3),
                              (1599, 8), (1600, 9), (1800, 10), (5000, 10)):
            self.assertEqual(rank_for_elo(elo), expected, elo)

    def test_win_delta_uses_interactions_and_gambling(self):
        rng = self.FixedRng(5)
        # 60 + 20*2 + 7*(1 + 2/2) + 5 = 119
        self.assertEqual(delta_for_game(100, interactions=2, gambling=2, rng=rng), 119)
        self.assertEqual((rng.assert_low, rng.assert_high), (1, 9))

    def test_tie_delta_is_10_to_20(self):
        rng = self.FixedRng(17)
        self.assertEqual(delta_for_game(0, rng=rng), 17)
        self.assertEqual((rng.assert_low, rng.assert_high), (10, 20))

    def test_loss_delta_uses_knockouts(self):
        rng = self.FixedRng(3)
        # -20 + 10*2 - 3 = -3
        self.assertEqual(delta_for_game(-100, knockouts=2, rng=rng), -3)
        self.assertEqual((rng.assert_low, rng.assert_high), (1, 9))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = self.dir.name

    def tearDown(self):
        self.dir.cleanup()

    def test_no_guest_user(self):
        self.assertEqual(Storage(self.path).users, {})

    def test_register_and_login(self):
        s = Storage(self.path)
        user, err = s.register('alice', 'secret')
        self.assertIsNone(err)
        self.assertTrue(user['password'].startswith('pbkdf2$'))
        self.assertEqual(s.authenticate('alice', 'secret')[1], None)
        self.assertEqual(s.authenticate('alice', 'wrong')[1], 'wrong_password')
        self.assertEqual(s.authenticate('bob', 'secret')[1], 'user_not_found')
        self.assertEqual(s.authenticate('', '')[1], 'fill_all_fields')

    def test_register_errors(self):
        s = Storage(self.path)
        self.assertEqual(s.register('', 'abcd')[1], 'fill_all_fields')
        self.assertEqual(s.register('ab', 'abcd')[1], 'username_short')
        self.assertEqual(s.register('abc', 'abc')[1], 'password_short')
        s.register('abc', 'abcd')
        self.assertEqual(s.register('abc', 'abcd')[1], 'username_taken')

    def test_persistence(self):
        s = Storage(self.path)
        user, _ = s.register('alice', 'secret')
        user['balance'] = 4321
        s.save()
        s2 = Storage(self.path)
        self.assertEqual(s2.users['alice']['balance'], 4321)
        self.assertEqual(s2.authenticate('alice', 'secret')[1], None)

    def test_legacy_plaintext_password_upgrades(self):
        legacy = {'Guest': {'balance': 1000, 'wins': 0, 'losses': 0, 'ties': 0,
                            'password': None, 'username': 'Guest'},
                  'old': {'balance': 77, 'wins': 3, 'losses': 1, 'ties': 0,
                          'password': 'plain1', 'username': 'old'}}
        with open(os.path.join(self.path, 'game_save.json'), 'w', encoding='utf-8') as f:
            json.dump(legacy, f)
        s = Storage(self.path)
        self.assertEqual(s.users['old']['skins'], ['default'])   # новые поля дополнены
        self.assertNotIn('Guest', s.users)                         # гостя из старого файла убираем
        self.assertEqual(s.users['old']['display_name'], 'old')     # имя по умолчанию = логин
        self.assertEqual((s.users['old']['avatar'], s.users['old']['locked_until']), ('', 0))
        user, err = s.authenticate('old', 'plain1')
        self.assertIsNone(err)
        self.assertTrue(user['password'].startswith('pbkdf2$'))
        self.assertEqual(Storage(self.path).authenticate('old', 'plain1')[1], None)

    def test_corrupt_file_is_kept_as_backup(self):
        with open(os.path.join(self.path, 'game_save.json'), 'w') as f:
            f.write('{ это не json')
        s = Storage(self.path)
        self.assertEqual(s.users, {})
        self.assertTrue(os.path.exists(os.path.join(self.path, 'game_save.json.bak')))

    def test_leaderboard_sorted(self):
        s = Storage(self.path)
        a, _ = s.register('aaa', 'pass1')
        b, _ = s.register('bbb', 'pass2')
        a.update(wins=1, losses=3)
        b.update(wins=3, losses=1)
        rows = s.leaderboard()
        self.assertEqual(rows[0]['username'], 'bbb')
        self.assertAlmostEqual(rows[0]['win_rate'], 75.0)

    def test_settings(self):
        s = Storage(self.path)
        s.language = 'english'
        s.last_user = 'alice'
        s2 = Storage(self.path)
        self.assertEqual((s2.language, s2.last_user), ('english', 'alice'))

    def test_hash_helpers(self):
        h = hash_password('x1y2')
        self.assertEqual(check_password(h, 'x1y2'), (True, False))
        self.assertEqual(check_password(h, 'nope'), (False, False))
        self.assertEqual(check_password('abc', 'abc'), (True, True))
        self.assertEqual(check_password(None, 'abc'), (False, False))


if __name__ == '__main__':
    unittest.main()
