"""Запись решений игрока в CSV для обучения моделей. Не зависит от Kivy.

Два файла (в имени версия схемы: если колонки изменятся, начнётся новый файл):

  blackjack_decisions_v1.csv — одна строка = одно решение игрока
  blackjack_rounds_v1.csv    — одна строка = один раунд (для модели размера ставки)

Подробное описание колонок — в DATASET.md.
"""
import csv
import os

from .round import OVER

DECISIONS_FILE = 'blackjack_decisions_v1.csv'
ROUNDS_FILE = 'blackjack_rounds_v1.csv'

# Действия-метки. insurance/no_insurance бывают только когда can_insure = 1.
ACTIONS = ('hit', 'stand', 'double', 'split', 'surrender', 'insurance', 'no_insurance')

# Какой флаг разрешает какое действие (для маски допустимых действий у бота)
ACTION_FLAG = {
    'hit': 'can_hit', 'stand': 'can_stand', 'double': 'can_double', 'split': 'can_split',
    'surrender': 'can_surrender', 'insurance': 'can_insure', 'no_insurance': 'can_insure',
}

DECISION_COLUMNS = [
    # идентификаторы (в обучение не берём)
    'round_id', 'decision_idx', 'timestamp', 'player',
    # признаки состояния стола
    'balance', 'bet', 'bet_pct',
    'player_total', 'player_soft', 'n_cards', 'is_pair', 'pair_value',
    'hand_index', 'n_hands', 'split_used',
    'dealer_up', 'dealer_up_ace',
    # какие действия сейчас разрешены
    'can_hit', 'can_stand', 'can_double', 'can_split', 'can_surrender', 'can_insure',
    # метка: что сделал игрок
    'action',
    # исход раунда (для анализа и взвешивания примеров, в признаки не брать!)
    'round_result', 'round_net', 'round_net_per_bet',
    # то же самое в читаемом виде
    'player_cards', 'dealer_up_card',
]

ROUND_COLUMNS = [
    'round_id', 'timestamp', 'player',
    'bankroll_start', 'bet', 'bet_pct', 'prev_net_per_bet',
    'n_decisions', 'insured', 'surrendered',
    'round_result', 'round_net', 'round_net_per_bet',
]


class DecisionLog:
    def __init__(self, directory):
        os.makedirs(directory, exist_ok=True)
        self.decisions_path = os.path.join(directory, DECISIONS_FILE)
        self.rounds_path = os.path.join(directory, ROUNDS_FILE)
        self._prev_net = {}     # результат прошлого раунда по игрокам (только в памяти)

    @staticmethod
    def _append(path, columns, rows):
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            if is_new:
                writer.writeheader()
            writer.writerows(rows)

    def counts(self):
        """(решений, раундов), записанных в файлы."""
        def rows(path):
            try:
                with open(path, encoding='utf-8') as f:
                    return max(0, sum(1 for _ in f) - 1)     # минус строка заголовка
            except OSError:
                return 0
        return rows(self.decisions_path), rows(self.rounds_path)

    def write_round(self, rnd):
        """Записывает законченный раунд. Брошенные посреди игры раунды не пишутся.
        Возвращает True, если запись удалась."""
        if rnd.state != OVER:
            return False
        net = rnd.net
        per_bet = round(net / rnd.total_bet, 4) if rnd.total_bet else 0
        outcome = {'round_result': rnd.round_result, 'round_net': net,
                   'round_net_per_bet': per_bet}
        try:
            if rnd.decisions:
                rows = [dict(decision, **outcome) for decision in rnd.decisions]
                self._append(self.decisions_path, DECISION_COLUMNS, rows)
            prev = self._prev_net.get(rnd.player, '')
            self._append(self.rounds_path, ROUND_COLUMNS, [{
                'round_id': rnd.round_id,
                'timestamp': rnd.started_at,
                'player': rnd.player,
                'bankroll_start': rnd.start_bankroll,
                'bet': rnd.total_bet,
                'bet_pct': round(rnd.total_bet / rnd.start_bankroll, 4) if rnd.start_bankroll else 0,
                'prev_net_per_bet': prev,
                'n_decisions': len(rnd.decisions),
                'insured': int(rnd.insurance > 0),
                'surrendered': int(rnd.surrendered),
                **outcome,
            }])
        except OSError:
            return False
        self._prev_net[rnd.player] = per_bet
        return True
