"""Симуляция соревновательного режима в терминале (без интерфейса).

Запуск из папки проекта:
    python simulate_competitive.py                 # три варианта колоды, по 50000 раундов
    python simulate_competitive.py --rounds 50000  # точнее, но дольше
    python simulate_competitive.py --variants B    # только один вариант
    python simulate_competitive.py --players 3     # меньше игроков (первые N профилей)

За столом 5 ботов разных «характеров». В каждом раунде у всех баланс сбрасывается, а ставка
одинаковая, поэтому результаты (в ставках) можно сравнивать.
Чтобы добавить свой вариант колоды, допишите строку в VARIANTS. Например, 8 спец-карт без Swap:
    ('D', '52 карты + 8 спец', Config(decks=1, specials=SPECIAL_KINDS[:8])),
"""
import argparse
import random
import time
from collections import defaultdict

from core.bots import PROFILES, make_bot
from core.competitive import Config, Player, SPECIAL_KINDS, SPECIAL_TITLES, Table

VARIANTS = (
    ('A', '52 карты + 9 спец-карт (по одной)', Config(decks=1, specials=SPECIAL_KINDS)),
    ('B', '104 карты + 18 спец-карт (по две)', Config(decks=2, specials=SPECIAL_KINDS * 2)),
    ('C', '52 карты + 18 спец-карт (по две)', Config(decks=1, specials=SPECIAL_KINDS * 2)),
)
BET = 100
BANKROLL = BET * 100


def mean(total, count):
    return total / count if count else float('nan')


def run_variant(config, rounds, seed, players_count):
    rng = random.Random(seed)
    names = list(PROFILES)[:players_count]
    players = [Player(name, make_bot(name, random.Random(rng.random()), BET), BANKROLL)
               for name in names]
    table = Table(players, config, random.Random(rng.random()))
    n = len(players)

    s = defaultdict(float)
    hist = defaultdict(int)
    kind_draw = defaultdict(int)                  # сколько раз карта выпала
    kind_drawer = defaultdict(lambda: [0.0, 0])   # результат того, кто вытянул
    kind_target = defaultdict(lambda: [0.0, 0])   # результат тех, на кого подействовало
    kind_info = defaultdict(lambda: defaultdict(int))
    base_drawer = [0.0, 0]    # игроки, бравшие карту, но не вытянувшие спец-карт
    base_target = [0.0, 0]    # игроки, на которых ничего не подействовало
    by_profile = defaultdict(lambda: [0.0, 0])
    by_position = defaultdict(lambda: [0.0, 0])
    pranks = defaultdict(int)

    started = time.time()
    for _ in range(rounds):
        for p in players:
            p.balance = BANKROLL
        report = table.play_round()
        net = {i: report.nets[i] / report.base_bets[i] for i in report.nets}

        s['rounds'] += 1
        s['specials'] += report.specials
        s['circles'] += report.circles
        s['hits'] += sum(report.hits.values())
        hist[min(report.specials, 3)] += 1

        drew, hit_by, hit_on = defaultdict(set), defaultdict(set), defaultdict(set)
        for event in report.events:
            kind_draw[event.kind] += 1
            kind_info[event.kind][event.info.split('=')[0].split('->')[0]] += 1
            drew[event.actor].add(event.kind)
            for target in event.targets:
                hit_on[target].add(event.kind)
            if (event.kind in ('min', 'min_plus') and event.info == 'other') or \
                    (event.kind == 'swap' and event.info == 'used'):
                pranks[players[event.actor].name] += 1      # выбранные пакости, не автоматические
        for i, value in net.items():
            for kind in drew[i]:
                kind_drawer[kind][0] += value
                kind_drawer[kind][1] += 1
            for kind in hit_on[i]:
                kind_target[kind][0] += value
                kind_target[kind][1] += 1
            if not drew[i] and report.hits.get(i, 0) > 0:
                base_drawer[0] += value
                base_drawer[1] += 1
            if not drew[i] and not hit_on[i]:
                base_target[0] += value
                base_target[1] += 1
            by_profile[players[i].name][0] += value
            by_profile[players[i].name][1] += 1
            position = (i - report.button) % n
            by_position[position][0] += value
            by_position[position][1] += 1
            s['net'] += value
            s['player_rounds'] += 1

    return dict(s=s, hist=hist, kind_draw=kind_draw, kind_drawer=kind_drawer,
                kind_target=kind_target, kind_info=kind_info, base_drawer=base_drawer,
                base_target=base_target, by_profile=by_profile, by_position=by_position,
                pranks=pranks, seconds=time.time() - started, rounds=rounds, n=n)


def print_variant(code, title, config, r):
    s, rounds = r['s'], r['rounds']
    print('=' * 78)
    print(f"Вариант {code}: {title}  (спец-карт в колоде: {len(config.specials)}, "
          f"игроков: {r['n']}, раундов: {rounds}, {r['seconds']:.1f} с)")
    print('=' * 78)
    print(f"Спец-карт за раунд: {s['specials'] / rounds:.2f}   "
          f"кругов за раунд: {s['circles'] / rounds:.2f}   "
          f"«взять» за раунд: {s['hits'] / rounds:.1f}")
    hist = r['hist']
    print("Раундов с N спец-картами:  " + "   ".join(
        f"{label}: {hist[k] / rounds * 100:4.1f}%"
        for k, label in ((0, '0'), (1, '1'), (2, '2'), (3, '3+'))))
    print(f"Средний результат игрока за раунд: {mean(s['net'], s['player_rounds']):+.3f} ставки")
    bd, bt = r['base_drawer'], r['base_target']
    print(f"\nКарты (результат в ставках за раунд; базовые уровни без спец-карт: "
          f"брал карты {mean(*bd):+.3f}, не затронут {mean(*bt):+.3f})")
    print(f"{'карта':<12}{'выпало/1000':>12}{'у вытянувшего':>15}{'у пострадавших':>16}"
          f"{'на других':>11}   что делали")
    for kind in SPECIAL_KINDS:
        draws = r['kind_draw'][kind]
        if not config.specials.count(kind):
            continue
        drawer, target = r['kind_drawer'][kind], r['kind_target'][kind]
        info = r['kind_info'][kind]
        details = ', '.join(f"{k} {v / draws * 100:.0f}%" for k, v in sorted(info.items())) if draws else ''
        target_text = f"{mean(*target):+.3f}" if target[1] else '    —'
        print(f"{SPECIAL_TITLES[kind]:<12}{draws / rounds * 1000:>12.0f}"
              f"{mean(*drawer):>+15.3f}{target_text:>16}{target[1] / rounds * 1000:>11.0f}   {details}")
    print("\nРезультат по характеру бота (в ставках за раунд) и сколько раз он выбрал пакость (Min, Min+ или Swap на другого):")
    for name in PROFILES:
        if name in r['by_profile']:
            total, count = r['by_profile'][name]
            print(f"  {name:<12}{mean(total, count):+.3f}   пакостей: {r['pranks'].get(name, 0)}")
    print("Результат по месту в круге (1 = ходит первым, место сдвигается каждый раунд):")
    print("  " + "   ".join(f"{pos + 1}: {mean(*r['by_position'][pos]):+.3f}"
                            for pos in range(r['n'])))
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--rounds', type=int, default=50000)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--players', type=int, default=5, choices=range(2, 6))
    parser.add_argument('--variants', default='ABC', help='буквы вариантов, например AB')
    args = parser.parse_args()

    results = []
    for code, title, config in VARIANTS:
        if code not in args.variants.upper():
            continue
        result = run_variant(config, args.rounds, args.seed, args.players)
        print_variant(code, title, config, result)
        results.append((code, title, result))

    if results:
        control = run_variant(Config(decks=1, specials=()), args.rounds, args.seed, args.players)
        print('=' * 78)
        print('Сравнение вариантов (результат игрока в ставках за раунд)')
        print('=' * 78)
        print(f"{'вариант':<10}{'спец/раунд':>11}{'есть спец':>10}{'2+ спец':>9}{'кругов':>8}"
              f"{'результат':>11}")
        for code, title, r in results + [('контроль', 'без спец-карт', control)]:
            s, rounds = r['s'], r['rounds']
            print(f"{code:<10}{s['specials'] / rounds:>11.2f}"
                  f"{(1 - r['hist'][0] / rounds) * 100:>9.0f}%"
                  f"{(r['hist'][2] + r['hist'][3]) / rounds * 100:>8.0f}%"
                  f"{s['circles'] / rounds:>8.2f}{mean(s['net'], s['player_rounds']):>+11.3f}")
        print("«контроль»: те же боты без спец-карт, чтобы видеть, сколько проигрывают сами боты.")


if __name__ == '__main__':
    main()
