"""Ранги по elo (10 уровней) и начисление elo. Не зависит от Kivy."""
import random

START_ELO = 0

# Минимальное elo для каждого ранга: 0-199 — 1-й, 200-399 — 2-й и т.д. до 10-го.
RANK_MIN_ELO = tuple(range(0, 2000, 200))
MAX_RANK = len(RANK_MIN_ELO)


def rank_for_elo(elo):
    """Номер ранга (1..10) по количеству elo."""
    try:
        elo = int(elo)
    except (TypeError, ValueError):
        elo = START_ELO
    rank = 1
    for number, minimum in enumerate(RANK_MIN_ELO, start=1):
        if elo >= minimum:
            rank = number
    return rank


def delta_for_game(net, interactions=0, gambling=0, knockouts=0, rng=None):
    """Сколько elo начислить за соревновательную игру.

    net > 0 — выигрыш денег, net == 0 — ничья, net < 0 — проигрыш.
    interactions — спец-карты, подействовавшие на других игроков;
    gambling — опасные действия (hit 17..20, double 16..20, split/SnC 18/20);
    knockouts — боты, потерявшие все руки из-за хода игрока.
    """
    rng = rng or random.Random()
    if net > 0:
        eps = rng.randint(1, 9)
        return int(round(60 + 20 * interactions + 7 * (1 + gambling / 2) + eps))
    if net == 0:
        return rng.randint(10, 20)
    eps = rng.randint(1, 9)
    return -20 + 10 * knockouts - eps
