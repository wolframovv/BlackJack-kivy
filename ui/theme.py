"""Цвета, размеры и шрифты."""
import os

from kivy.core.text import LabelBase
from kivy.metrics import dp, sp
from kivy.resources import resource_find


def rgb(r, g, b, a=255):
    return [r / 255.0, g / 255.0, b / 255.0, a / 255.0]


WHITE = rgb(255, 255, 255)
BLACK = rgb(0, 0, 0)
GOLD = rgb(255, 215, 0)
GREEN = rgb(11, 102, 35)
DARK_GREEN = rgb(0, 80, 0)
GREEN_TEXT = rgb(80, 220, 80)
RED = rgb(220, 20, 60)
DARK_RED = rgb(139, 0, 0)
RED_TEXT = rgb(255, 80, 80)
BLUE = rgb(0, 100, 200)
LIGHT_BLUE = rgb(0, 150, 255)
YELLOW = rgb(255, 255, 0)
GRAY = rgb(128, 128, 128)
DARK_GRAY = rgb(70, 70, 70)
LIGHT_GRAY = rgb(200, 200, 200)

# Размеры рассчитаны на телефон в ландшафте (~380 dp по высоте)
BUTTON_H = dp(40)
INPUT_H = dp(40)
SPACING = dp(6)

# Единые размеры, чтобы экраны выглядели одинаково
TITLE_H = dp(44)
TITLE_FS = sp(32)
PANEL_W = 0.56          # ширина главной панели
WIDE_PANEL_W = 0.8      # ширина панели с таблицей

# Затемнение при переходе между экранами (лежит поверх всего интерфейса)
FADE_PEAK = 0.55
FADE_IN = 0.14
FADE_OUT = 0.2

PARTICLES_IN_GAME = False   # True — частицы фона видны и за игровым столом

FONT = 'Bebas'

DEBUG_MENU = True


def register_fonts(base_dir):
    """Регистрирует шрифт Bebas Neue (с кириллицей). Если файла нет — берёт Roboto."""
    path = os.path.join(base_dir, 'etc', 'Bebas_Neue_Cyrillic.ttf')
    if not os.path.exists(path):
        path = resource_find('data/fonts/Roboto-Regular.ttf')
    LabelBase.register(name=FONT, fn_regular=path, fn_bold=path)
