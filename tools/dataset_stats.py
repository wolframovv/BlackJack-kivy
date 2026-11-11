"""Быстрая проверка собранных данных (без pandas, работает где угодно).

    python tools/dataset_stats.py путь/к/blackjack_decisions_v1.csv
"""
import csv
import sys
from collections import Counter

ACTION_FLAG = {
    'hit': 'can_hit', 'stand': 'can_stand', 'double': 'can_double', 'split': 'can_split',
    'surrender': 'can_surrender', 'insurance': 'can_insure', 'no_insurance': 'can_insure',
}
MIN_EXAMPLES = 30     # меньше примеров на действие — модель его почти не выучит


def main(path):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print('Файл пуст.')
        return 1

    rounds = {row['round_id'] for row in rows}
    print(f"Решений: {len(rows)}   раундов с решениями: {len(rounds)}   "
          f"игроков: {len({row['player'] for row in rows})}")

    actions = Counter(row['action'] for row in rows)
    print('\nДействия:')
    for action, count in actions.most_common():
        mark = '   <-- мало примеров' if count < MIN_EXAMPLES else ''
        print(f"  {action:<13}{count:>6}  {count / len(rows):6.1%}{mark}")

    baseline = actions.most_common(1)[0][1] / len(rows)
    print(f"\nБазовая точность «всегда {actions.most_common(1)[0][0]}»: {baseline:.1%} "
          f"— модель должна быть заметно лучше.")

    bad = [row for row in rows if row[ACTION_FLAG[row['action']]] != '1']
    print(f"Строк, где действие не разрешено своими флагами: {len(bad)} (должно быть 0)")

    first = {}
    for row in rows:
        first.setdefault(row['round_id'], row)
    results = Counter(row['round_result'] for row in first.values())
    print('\nИсходы раундов:', ', '.join(f"{k}: {v}" for k, v in results.most_common()))
    net = sum(float(row['round_net_per_bet']) for row in first.values()) / len(first)
    print(f"Средний результат раунда: {net:+.3f} ставки")
    return 0 if not bad else 2


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
