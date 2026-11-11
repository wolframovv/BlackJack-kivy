"""Страховка, сдача, запись решений и CSV-датасет."""
import csv
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cards import Card, Deck
from core.dataset import (ACTION_FLAG, ACTIONS, DECISION_COLUMNS, ROUND_COLUMNS,
                          DecisionLog)
from core.round import BlackjackRound, DEALER, INSURANCE, OVER, PLAYER
from tests.test_core import C, new_user, play, run_dealer, stacked


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


class InsuranceTests(unittest.TestCase):
    def test_offered_when_dealer_shows_ace(self):
        r, u = play(['9S', 'AH', '7C', '5D'], insurance=None)
        self.assertEqual(r.state, INSURANCE)
        self.assertEqual(r.insurance_cost, 50)
        self.assertFalse(r.dealer_revealed)            # дилер ещё не смотрел карту
        self.assertFalse(r.hit())                      # пока не решили — играть нельзя
        self.assertFalse(r.can_surrender())

    def test_take_and_dealer_has_blackjack_breaks_even(self):
        r, u = play(['9S', 'AH', '7C', 'KD'], insurance='take')
        self.assertEqual(r.state, OVER)
        self.assertEqual(r.insurance_net, 100)         # 2:1 на ставку 50
        self.assertEqual(u['balance'], 900 - 50 + 150)
        self.assertEqual(r.net, 0)                     # основную ставку проиграли, страховка вернула
        self.assertEqual(u['losses'], 1)
        self.assertEqual(r.message, ('dealer_blackjack_insured', 100))

    def test_take_and_no_dealer_blackjack_loses_insurance(self):
        r, u = play(['9S', 'AH', '7C', '5D'], insurance='take')
        self.assertEqual(r.state, PLAYER)
        self.assertEqual(r.insurance_net, -50)
        self.assertEqual(u['balance'], 850)
        r.stand()
        run_dealer(r)
        self.assertEqual(r.state, OVER)
        # 16 у игрока, дилер A+5 = 16 мягкие -> берёт карту; результат не важен,
        # важно что страховка уже учтена в net
        self.assertEqual(r.net, u['balance'] - 1000)

    def test_decline_and_dealer_blackjack_loses_bet(self):
        r, u = play(['9S', 'AH', '7C', 'KD'], insurance='decline')
        self.assertEqual((u['balance'], r.net), (900, -100))
        self.assertEqual(r.message, ('dealer_blackjack', None))

    def test_player_blackjack_is_even_money_with_insurance(self):
        # у игрока блэкджек, у дилера нет: БД 250 - страховка 50 = +100 (как «1 к 1»)
        r, u = play(['AS', 'AH', 'KC', '5D'], insurance='take')
        self.assertEqual(r.state, OVER)
        self.assertEqual(r.net, 100)
        # блэкджек у обоих: ничья по основной ставке + страховка 2:1 = те же +100
        r2, u2 = play(['AS', 'AH', 'KC', 'KD'], insurance='take')
        self.assertEqual(r2.net, 100)
        self.assertEqual(r2.message, ('both_blackjack_insured', 100))

    def test_not_offered_without_money_or_for_tiny_bet(self):
        r, _ = play(['9S', 'AH', '7C', '5D'], bet=100, balance=20, insurance=None)
        self.assertEqual(r.state, PLAYER)              # 50 > 20: страховку не предлагаем
        r, _ = play(['9S', 'AH', '7C', '5D'], bet=1, balance=900, insurance=None)
        self.assertEqual(r.state, PLAYER)              # половина от 1 — это 0

    def test_not_offered_for_ten_up_card(self):
        r, u = play(['9S', 'KH', '7C', 'AD'], insurance=None)
        self.assertEqual(r.state, OVER)                # блэкджек дилера виден сразу
        self.assertEqual(r.message, ('dealer_blackjack', None))

    def test_decisions_outside_offer_are_ignored(self):
        r, _ = play(['9S', '9H', '7C', '5D'])
        self.assertFalse(r.take_insurance())
        self.assertFalse(r.decline_insurance())


class SurrenderTests(unittest.TestCase):
    def test_surrender_returns_half(self):
        r, u = play(['10S', '10H', '6C', '7D'])
        self.assertTrue(r.can_surrender())
        self.assertTrue(r.surrender())
        self.assertEqual(r.state, OVER)
        self.assertEqual(u['balance'], 950)
        self.assertEqual((u['losses'], u['wins']), (1, 0))
        self.assertEqual(r.message, ('surrendered', 50))
        self.assertEqual(r.net, -50)
        self.assertEqual(r.round_result, 'surrender')
        self.assertIn('flip_dealer', [e[0] for e in r.pop_events()])

    def test_odd_bet_rounds_down(self):
        r, u = play(['10S', '10H', '6C', '7D'], bet=15, balance=985)
        r.surrender()
        self.assertEqual(r.net, -8)                    # вернули 7 из 15

    def test_bet_of_one_cannot_surrender(self):
        r, _ = play(['10S', '10H', '6C', '7D'], bet=1)
        self.assertFalse(r.can_surrender())
        self.assertFalse(r.surrender())

    def test_only_as_first_action(self):
        r, _ = play(['5S', '10H', '6C', '7D', '2S'])
        r.hit()
        self.assertFalse(r.can_surrender())            # уже три карты
        r2, _ = play(['8S', '10H', '8C', '7D', '3S', '2H'])
        r2.split()
        self.assertFalse(r2.can_surrender())
        r3, _ = play(['5S', '10H', '6C', '7D', '2S'])
        r3.double()
        self.assertFalse(r3.can_surrender())

    def test_after_declining_insurance(self):
        r, _ = play(['10S', 'AH', '6C', '5D'], insurance=None)
        self.assertEqual(r.state, INSURANCE)
        self.assertFalse(r.can_surrender())
        r.decline_insurance()
        self.assertTrue(r.can_surrender())


class DecisionLoggingTests(unittest.TestCase):
    def test_stand_decision_features(self):
        r, u = play(['10S', '9H', '7C', '6D'])
        r.stand()
        self.assertEqual(len(r.decisions), 1)
        d = r.decisions[0]
        expected = dict(action='stand', player_total=17, player_soft=0, n_cards=2,
                        is_pair=0, pair_value=0, dealer_up=9, dealer_up_ace=0,
                        bet=100, balance=900, bet_pct=0.1, hand_index=0, n_hands=1,
                        split_used=0, can_hit=1, can_stand=1, can_double=1, can_split=0,
                        can_surrender=1, can_insure=0, decision_idx=0,
                        player_cards='10S 7C', dealer_up_card='9H', player='tester')
        for key, value in expected.items():
            self.assertEqual(d[key], value, key)

    def test_insurance_then_hit(self):
        r, _ = play(['5S', 'AH', '6C', '9D', '3S'], insurance='decline')
        r.hit()
        actions = [d['action'] for d in r.decisions]
        self.assertEqual(actions, ['no_insurance', 'hit'])
        ins, hit = r.decisions
        self.assertEqual((ins['can_insure'], ins['can_hit'], ins['can_stand'], ins['can_double'],
                          ins['can_split'], ins['can_surrender']), (1, 0, 0, 0, 0, 0))
        self.assertEqual((ins['dealer_up'], ins['dealer_up_ace']), (11, 1))
        self.assertEqual(hit['can_insure'], 0)
        self.assertEqual([d['decision_idx'] for d in r.decisions], [0, 1])

    def test_forced_moves_are_not_logged(self):
        # 5+6=11, берёт 10 -> 21: автостенд не является решением; ход дилера тоже
        r, _ = play(['5S', '9H', '6C', '8D', 'KS'])
        r.hit()
        run_dealer(r)
        self.assertEqual([d['action'] for d in r.decisions], ['hit'])

    def test_bust_is_not_a_decision(self):
        r, _ = play(['10S', '10H', '6C', '7D', 'KS'])
        r.hit()
        self.assertEqual(len(r.decisions), 1)

    def test_split_and_second_hand(self):
        r, _ = play(['8S', '9H', '8C', '7D', '3S', '2H', 'KC'])
        r.split()
        first = r.decisions[0]
        self.assertEqual((first['action'], first['is_pair'], first['pair_value'],
                          first['can_split']), ('split', 1, 8, 1))
        r.stand()                                        # рука 0
        r.stand()                                        # рука 1
        hands = [(d['action'], d['hand_index'], d['n_hands']) for d in r.decisions]
        self.assertEqual(hands, [('split', 0, 1), ('stand', 0, 2), ('stand', 1, 2)])
        self.assertEqual(r.decisions[-1]['split_used'], 1)

    def test_double_logs_balance_before_deduction(self):
        r, _ = play(['5S', '9H', '6C', '8D', 'KS'])
        r.double()
        d = r.decisions[0]
        self.assertEqual((d['action'], d['balance'], d['bet']), ('double', 900, 100))

    def test_pair_of_aces_value(self):
        r, _ = play(['AS', '9H', 'AC', '7D'])
        r.stand()
        d = r.decisions[0]
        self.assertEqual((d['is_pair'], d['pair_value'], d['player_total'], d['player_soft']),
                         (1, 11, 12, 1))

    def test_invalid_actions_are_not_logged(self):
        r, _ = play(['10S', '9H', '7C', '6D'])
        r.split()                                        # нельзя: не пара
        self.assertEqual(r.decisions, [])


class DatasetFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.log = DecisionLog(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def finish(self, cards, actions, **kw):
        r, u = play(cards, **kw)
        for name in actions:
            getattr(r, name)()
        run_dealer(r)
        return r

    def test_unfinished_round_is_not_written(self):
        r, _ = play(['10S', '9H', '7C', '6D'])
        r.stand()
        r.state = PLAYER                                   # имитируем брошенный раунд
        self.assertFalse(self.log.write_round(r))
        self.assertFalse(os.path.exists(self.log.decisions_path))
        self.assertFalse(os.path.exists(self.log.rounds_path))

    def test_rows_and_outcome(self):
        r = self.finish(['10S', '10H', '9C', '6D', '2S'], ['stand'])   # выигрыш +100
        self.assertTrue(self.log.write_round(r))
        rows = read_csv(self.log.decisions_path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(list(row.keys()), DECISION_COLUMNS)
        self.assertEqual((row['action'], row['round_result'], row['round_net'],
                          row['round_net_per_bet']), ('stand', 'win', '100', '1.0'))
        rounds = read_csv(self.log.rounds_path)
        self.assertEqual(list(rounds[0].keys()), ROUND_COLUMNS)
        self.assertEqual((rounds[0]['bet'], rounds[0]['bankroll_start'], rounds[0]['bet_pct'],
                          rounds[0]['prev_net_per_bet'], rounds[0]['n_decisions']),
                         ('100', '1000', '0.1', '', '1'))

    def test_header_once_and_prev_result(self):
        r1 = self.finish(['10S', '10H', '9C', '6D', '2S'], ['stand'])        # +1.0
        r2 = self.finish(['10S', '10H', '7C', '9D'], ['stand'])              # -1.0
        self.log.write_round(r1)
        self.log.write_round(r2)
        with open(self.log.decisions_path, encoding='utf-8') as f:
            text = f.read()
        self.assertEqual(text.count('round_id'), 1)
        rounds = read_csv(self.log.rounds_path)
        self.assertEqual([x['prev_net_per_bet'] for x in rounds], ['', '1.0'])
        self.assertEqual([x['round_net_per_bet'] for x in rounds], ['1.0', '-1.0'])

    def test_special_outcomes(self):
        cases = [
            (['AS', '9H', 'KC', '7D'], [], 'blackjack', '1.5'),
            (['10S', '10H', '6C', '7D'], ['surrender'], 'surrender', '-0.5'),
            (['9S', 'AH', '7C', 'KD'], [], 'loss', '0.0'),   # страховка (take) вернула ставку
        ]
        for cards, actions, result, per_bet in cases:
            r, _ = play(cards, insurance='take')
            for name in actions:
                getattr(r, name)()
            self.assertTrue(self.log.write_round(r))
            rounds = read_csv(self.log.rounds_path)[-1]
            self.assertEqual((rounds['round_result'], rounds['round_net_per_bet']),
                             (result, per_bet), cards)

    def test_round_without_decisions_still_in_rounds_file(self):
        r, _ = play(['9S', 'KH', '7C', 'AD'])               # блэкджек дилера сразу
        self.assertEqual(r.decisions, [])
        self.assertTrue(self.log.write_round(r))
        self.assertFalse(os.path.exists(self.log.decisions_path))
        self.assertEqual(len(read_csv(self.log.rounds_path)), 1)


class SimulationTests(unittest.TestCase):
    """1500 раундов со случайными допустимыми действиями: файл должен быть согласован."""

    def test_random_play_produces_consistent_csv(self):
        rng = random.Random(3)
        random.seed(5)                                       # перетасовка колоды
        with tempfile.TemporaryDirectory() as directory:
            log = DecisionLog(directory)
            user = new_user(10_000_000)
            expected_rows = 0
            seen = set()
            nets = []
            for n in range(1500):
                bet = rng.choice([1, 2, 10, 15, 50, 100, 333])
                user['balance'] -= bet
                r = BlackjackRound(user, bet, player='sim')
                r.start()
                r.finish_dealing()
                guard = 0
                while r.state not in (OVER, DEALER):
                    guard += 1
                    self.assertLess(guard, 50)
                    if r.state == INSURANCE:
                        getattr(r, rng.choice(['take_insurance', 'decline_insurance']))()
                        continue
                    legal = [name for name, ok in (
                        ('hit', r.can_hit()), ('stand', r.can_stand()),
                        ('double', r.can_double()), ('split', r.can_split()),
                        ('surrender', r.can_surrender())) if ok]
                    self.assertTrue(legal)
                    self.assertTrue(getattr(r, rng.choice(legal))())
                run_dealer(r)
                self.assertEqual(r.state, OVER)
                bets = sum(h.bet for h in r.hands)
                self.assertGreaterEqual(r.net, -(bets + r.insurance))
                self.assertLessEqual(r.net, 1.5 * bets + 2 * r.insurance)
                self.assertTrue(log.write_round(r))
                expected_rows += len(r.decisions)
                nets.append((r.round_id, r.net))
                seen.update(d['action'] for d in r.decisions)

            rows = read_csv(log.decisions_path)
            self.assertEqual(len(rows), expected_rows)
            self.assertEqual(seen, set(ACTIONS))             # все 7 действий встретились
            for row in rows:
                self.assertIn(row['action'], ACTIONS)
                self.assertEqual(row[ACTION_FLAG[row['action']]], '1',
                                 'действие не разрешено своими же флагами: %r' % row)
                if row['can_insure'] == '1':
                    self.assertIn(row['action'], ('insurance', 'no_insurance'))
                else:
                    self.assertNotIn(row['action'], ('insurance', 'no_insurance'))
                self.assertGreaterEqual(int(row['player_total']), 2)
                self.assertLessEqual(int(row['player_total']), 21)
                self.assertTrue(2 <= int(row['dealer_up']) <= 11)
            # индексы решений идут подряд в каждом раунде
            by_round = {}
            for row in rows:
                by_round.setdefault(row['round_id'], []).append(int(row['decision_idx']))
            for ids in by_round.values():
                self.assertEqual(ids, list(range(len(ids))))
            rounds = read_csv(log.rounds_path)
            self.assertEqual(len(rounds), 1500)
            self.assertEqual({x['round_id'] for x in rounds}, {rid for rid, _ in nets})
            for row in rounds:
                expected = dict(nets)[row['round_id']]
                self.assertEqual(int(row['round_net']), expected)


if __name__ == '__main__':
    unittest.main()
