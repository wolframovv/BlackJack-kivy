"""Ранги по elo (10 уровней). Не зависит от Kivy."""

START_ELO = 0

# Минимальное elo для каждого ранга: RANK_MIN_ELO[0] — для 1-го ранга, [9] — для 10-го.
# ВРЕМЕННЫЕ значения: когда будет понятна система очков, поправьте здесь.
RANK_MIN_ELO = (0, 100, 250, 450, 700, 1000, 1400, 1900, 2500, 3200)
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