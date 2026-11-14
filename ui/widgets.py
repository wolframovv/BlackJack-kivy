"""Общие виджеты: надписи, кнопки, панели, поля ввода, карты, окно-предупреждение."""
import os
from functools import lru_cache

from kivy.animation import Animation
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from core.cards import SUIT_SYMBOLS
from core.competitive import SPECIAL_TITLES
from core.i18n import t
from . import theme
from .sound import sounds

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(BASE_DIR, 'cards')
SPECIAL_DIR = os.path.join(CARDS_DIR, 'spec')      # картинки спец-карт: <вид>.png


class Lbl(Label):
    """Надпись шрифтом игры (стиль — в style.kv)."""


class StyledButton(Button):
    """Кнопка со скруглёнными углами и цветом, меняющимся при нажатии."""
    base_color = ListProperty(theme.DARK_GREEN)
    down_color = ListProperty(theme.GREEN)
    text_color = ListProperty(theme.WHITE)
    current_color = ListProperty(theme.DARK_GREEN)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(state=self._update_color, disabled=self._update_color,
                  base_color=self._update_color, down_color=self._update_color)
        self._update_color()

    def on_press(self):
        sounds.play('click')

    def _update_color(self, *args):
        if self.disabled:
            self.current_color = theme.DARK_GRAY
        elif self.state == 'down':
            self.current_color = self.down_color
        else:
            self.current_color = self.base_color


class Panel(BoxLayout):
    """Полупрозрачная панель с золотой рамкой (стиль — в style.kv)."""


class OverlayPanel(Panel):
    """Панель, которая появляется и исчезает через opacity (результат, страховка).

    Невидимая панель НЕ перехватывает нажатия. Раньше для скрытия использовался disabled,
    а в Kivy отключённый виджет поглощает все касания в своих границах, из-за чего скрытая
    панель результата закрывала кнопки страховки, лежащие под ней."""
    passes_touch_when_hidden = True

    def on_touch_down(self, touch):
        return False if self.opacity < 0.01 else super().on_touch_down(touch)

    def on_touch_move(self, touch):
        return False if self.opacity < 0.01 else super().on_touch_move(touch)

    def on_touch_up(self, touch):
        return False if self.opacity < 0.01 else super().on_touch_up(touch)


class LimitedInput(TextInput):
    """Поле ввода с ограничением длины."""
    max_len = NumericProperty(0)

    def insert_text(self, substring, from_undo=False):
        if self.max_len:
            room = max(0, self.max_len - len(self.text))
            substring = substring[:room]
        return super().insert_text(substring, from_undo=from_undo)


class RankIcon(Image):
    """Картинка ранга (etc/elo/eloN.png). Если файла нет, source пустой и ничего не рисуется."""

    def __init__(self, **kwargs):
        kwargs.setdefault('fit_mode', 'contain')      # сохраняем пропорции картинки
        super().__init__(**kwargs)


class LeaderRow(BoxLayout):
    bg = ListProperty([1, 1, 1, 0.06])


class HighlightBox(Widget):
    """Жёлтая рамка вокруг активной руки."""


class TouchBlocker(Widget):
    """Пока виден, перехватывает все нажатия: то, что под ним, не нажимается."""

    def on_touch_down(self, touch):
        return self.opacity > 0.01

    def on_touch_move(self, touch):
        return self.opacity > 0.01

    def on_touch_up(self, touch):
        return self.opacity > 0.01


class DimOverlay(TouchBlocker):
    """Затемнение экрана (полупрозрачное)."""


class FadeOverlay(TouchBlocker):
    """Чёрная завеса поверх всего интерфейса; прозрачность задаёт opacity."""


# ---------------------------------------------------------------- аватар

def _center_crop_coords(texture):
    """Координаты текстуры для вырезания квадрата из центра (если картинка не квадратная)."""
    width, height = texture.size
    if not width or not height or abs(width - height) / max(width, height) < 0.01:
        return None
    base = list(texture.tex_coords)
    us, vs = base[0::2], base[1::2]
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    if width > height:
        shift = (umax - umin) * (1 - height / width) / 2
        umin, umax = umin + shift, umax - shift
    else:
        shift = (vmax - vmin) * (1 - width / height) / 2
        vmin, vmax = vmin + shift, vmax - shift
    coords = []
    for u, v in zip(us, vs):
        coords += [umax if u == max(us) else umin, vmax if v == max(vs) else vmin]
    return coords


class AvatarImage(Widget):
    """Аватар в форме круга. source — путь к картинке; если файла нет, рисуется серая
    «фигурка человека» (как аватар по умолчанию)."""
    source = StringProperty('')
    gray = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            Color(0.55, 0.55, 0.55, 1)
            self._bg = Ellipse()
            self._person_color = Color(0.83, 0.83, 0.83, 1)
            self._head = Ellipse()
            self._body = Ellipse()
            self._image_color = Color(1, 1, 1, 0)
            self._image = Ellipse()
            self._ring_color = Color(theme.GOLD[0], theme.GOLD[1], theme.GOLD[2], 0.9)
            self._ring = Line(width=dp(1.2))
            self._gray_color = Color(0.4, 0.4, 0.4, 0)
            self._gray = Ellipse()
        self.bind(pos=self._update, size=self._update, source=self._load,
                  gray=self._update)
        self._update()
        self._load()

    def _update(self, *args):
        diameter = min(self.width, self.height)
        radius = diameter / 2.0
        cx, cy = self.center_x, self.center_y
        for ellipse in (self._bg, self._image, self._gray):
            ellipse.pos = (cx - radius, cy - radius)
            ellipse.size = (diameter, diameter)
        self._head.pos = (cx - 0.2 * radius, cy + 0.05 * radius)
        self._head.size = (0.4 * radius, 0.4 * radius)
        self._body.pos = (cx - 0.5 * radius, cy - 0.78 * radius)
        self._body.size = (radius, radius)
        self._ring.circle = (cx, cy, radius)
        self._gray_color.rgba = ((0.38, 0.38, 0.38, 0.70) if self.gray
                                 else (0, 0, 0, 0))
        self._ring_color.rgba = ((0.5, 0.5, 0.5, 0.9) if self.gray
                                 else (*theme.GOLD[:3], 0.9))

    def _load(self, *args):
        texture = None
        if self.source and os.path.exists(self.source):
            try:
                texture = CoreImage(self.source).texture
            except Exception:
                texture = None
        if texture is None:
            self._image_color.a = 0
            self._person_color.a = 1
            return
        self._image.texture = texture
        coords = _center_crop_coords(texture)
        if coords:
            self._image.tex_coords = coords
        self._image_color.a = 1
        self._person_color.a = 0


# ---------------------------------------------------------------- карты

@lru_cache(maxsize=None)
def _exists(path):
    return os.path.exists(path)


def face_path(skin, rank, suit):
    for folder in (skin, 'default'):
        path = os.path.join(CARDS_DIR, folder, f"{rank}_of_{suit}.png")
        if _exists(path):
            return path
    return ''


def special_path(kind):
    path = os.path.join(SPECIAL_DIR, f"{kind}.png")
    return path if _exists(path) else ''


def back_path():
    path = os.path.join(CARDS_DIR, 'card_back.png')
    return path if _exists(path) else ''


class CardWidget(Widget):
    """Карта: картинка из cards/ или, если файла нет, нарисованная запасная."""
    rank = StringProperty('')
    suit = StringProperty('')
    skin = StringProperty('default')
    face_up = BooleanProperty(True)
    sx = NumericProperty(1)          # масштаб по X (для анимации переворота)
    angle = NumericProperty(0)       # поворот в градусах (карты в веере)
    font_scale = NumericProperty(0.3)    # размер запасной надписи относительно высоты карты
    visible = BooleanProperty(True)
    dim = BooleanProperty(False)
    wasted = BooleanProperty(False)  # серый фильтр: перебор или сдача
    landed = False                   # карта уже долетела до своего места

    img_source = StringProperty('')
    has_image = BooleanProperty(False)
    fallback_bg = ListProperty([1, 1, 1, 1])
    fallback_text = StringProperty('')
    fallback_color = ListProperty([0, 0, 0, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._wasted_widget = Widget(size_hint=(None, None), disabled=True)
        with self._wasted_widget.canvas:
            self._wasted_color = Color(0.38, 0.38, 0.38, 0)
            self._wasted_rect = RoundedRectangle(radius=[dp(8)])
        self.add_widget(self._wasted_widget)
        self.bind(rank=self._refresh, suit=self._refresh, skin=self._refresh,
                  face_up=self._refresh, visible=self._opacity, dim=self._opacity,
                  pos=self._refresh_wasted, size=self._refresh_wasted,
                  wasted=self._refresh_wasted)
        self._refresh()
        self._opacity()
        self._refresh_wasted()

    def _refresh_wasted(self, *args):
        self._wasted_widget.pos = self.pos
        self._wasted_widget.size = self.size
        self._wasted_rect.pos = self.pos
        self._wasted_rect.size = self.size
        self._wasted_color.rgba = ((0.38, 0.38, 0.38, 0.70) if self.wasted
                                   else (0, 0, 0, 0))

    def _opacity(self, *args):
        self.opacity = (0.5 if self.dim else 1.0) if self.visible else 0.0

    def _refresh(self, *args):
        if self.face_up:
            path = face_path(self.skin, self.rank, self.suit)
            if path:
                self._set_image(path)
            else:
                self.img_source = ''
                self.has_image = False
                self.fallback_bg = [1, 1, 1, 1]
                symbol = SUIT_SYMBOLS.get(self.suit, '')
                self.fallback_text = f"{self.rank}\n{symbol}"
                red = self.suit in ('hearts', 'diamonds')
                self.fallback_color = [0.85, 0.1, 0.1, 1] if red else [0, 0, 0, 1]
        else:
            path = back_path()
            if path:
                self._set_image(path)
            else:
                self.img_source = ''
                self.has_image = False
                self.fallback_bg = [0.1, 0.3, 0.8, 1]
                self.fallback_text = ''

    def _set_image(self, path):
        self.img_source = path
        self.has_image = True
        self.fallback_bg = [0, 0, 0, 0]
        self.fallback_text = ''

    def flip_to(self, face_up, on_done=None, duration=0.16):
        """Переворот карты: сжимаем по X до нуля, меняем сторону, разжимаем."""
        if self.face_up == face_up:
            if on_done:
                on_done()
            return
        shrink = Animation(sx=0, duration=duration, t='in_quad')
        grow = Animation(sx=1, duration=duration, t='out_quad')

        def middle(*args):
            self.face_up = face_up
            grow.start(self)

        shrink.bind(on_complete=middle)
        if on_done:
            grow.bind(on_complete=lambda *args: on_done())
        shrink.start(self)


class SpecialCardWidget(CardWidget):
    """Спец-карта: картинка cards/spec/<вид>.png, а если файла нет, фиолетовая карта с названием."""
    kind = StringProperty('')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(kind=self._refresh)
        self._refresh()

    def _refresh(self, *args):
        if not self.face_up:
            return super()._refresh()                # рубашка колоды
        path = special_path(self.kind)
        if path:
            self._set_image(path)
            return
        self.img_source = ''
        self.has_image = False
        self.fallback_bg = [0.42, 0.12, 0.62, 1]
        self.fallback_text = SPECIAL_TITLES.get(self.kind, self.kind)
        self.fallback_color = [1, 1, 1, 1]
        self.font_scale = 0.11


class VerticalShade(Widget):
    """Затемнение-полоска: сверху тёмное, вниз плавно становится прозрачным.

    bottom=True переворачивает полоску: тёмное внизу, вверх прозрачно.
    """

    def __init__(self, strength=0.88, steps=64, bottom=False, **kwargs):
        super().__init__(**kwargs)
        # alphas[0] у нижнего края, alphas[-1] у верхнего
        self.alphas = [int(255 * strength * (row / (steps - 1)) ** 1.4) for row in range(steps)]
        if bottom:
            self.alphas.reverse()      # теперь внизу самое тёмное, вверху прозрачно
        texture = Texture.create(size=(1, steps), colorfmt='rgba')
        data = b''.join(bytes((0, 0, 0, alpha)) for alpha in self.alphas)
        texture.blit_buffer(data, colorfmt='rgba', bufferfmt='ubyte')
        texture.mag_filter = 'linear'
        texture.min_filter = 'linear'
        with self.canvas:
            Color(1, 1, 1, 1)
            self._rect = Rectangle(texture=texture, pos=self.pos, size=self.size)
        self.bind(pos=self._update, size=self._update)

    def _update(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class TurnBoard(StencilView):
    """Чёрное табло с белым текстом: имя меняется «барабаном», старое уезжает вверх,
    новое выезжает снизу (всё, что вышло за рамку табло, обрезается)."""
    text = StringProperty('')
    SPEED = 0.45

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._front = Lbl(size_hint=(None, None), color=theme.WHITE, font_size=sp(19))
        self._back = Lbl(size_hint=(None, None), color=theme.WHITE, font_size=sp(19))
        self.add_widget(self._front)
        self.add_widget(self._back)
        self.bind(pos=self._layout, size=self._layout)
        self._layout()

    def _layout(self, *args):
        for label in (self._front, self._back):
            label.size = self.size
            label.x = self.x
        self._front.y = self.y
        self._back.y = self.y - self.height          # ждёт под табло

    def set_text(self, text, animate=True):
        if text == self.text:
            return
        self.text = text
        Animation.cancel_all(self._front)
        Animation.cancel_all(self._back)
        old, new = self._front, self._back
        new.text = text
        self._front, self._back = new, old
        if not animate:
            old.y = self.y + self.height
            new.y = self.y
            return
        new.y = self.y - self.height
        Animation(y=self.y, duration=self.SPEED, t='out_cubic').start(new)
        Animation(y=self.y + self.height, duration=self.SPEED, t='out_cubic').start(old)


class TargetZone(HighlightBox):
    """Рамка-кнопка: подсвечивает того, кого можно выбрать, и принимает нажатие."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.on_pick = None

    def on_touch_down(self, touch):
        if self.opacity > 0.01 and self.on_pick and self.collide_point(*touch.pos):
            self.on_pick()
            return True
        return False


# ------------------------------------------------------- окно-предупреждение

class ConfirmDialog(ModalView):
    """Окно подтверждения: текст и две кнопки в ряд — «Назад» (закрыть) и «Меню» (подтвердить)."""

    def __init__(self, message, on_confirm, **kwargs):
        super().__init__(size_hint=(0.6, 0.55), auto_dismiss=True, background='',
                         background_color=(0, 0, 0, 0), overlay_color=(0, 0, 0, 0.65),
                         **kwargs)
        self._on_confirm = on_confirm
        panel = Panel()
        panel.add_widget(Lbl(text=message, color=theme.RED_TEXT, font_size=sp(22),
                             size_hint_y=1))
        row = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)
        self.back_button = StyledButton(text=t('back'), base_color=theme.DARK_GRAY,
                                        down_color=theme.GRAY)
        self.back_button.bind(on_release=lambda *args: self.dismiss())
        self.confirm_button = StyledButton(text=t('menu'), base_color=theme.DARK_RED,
                                           down_color=theme.RED)
        self.confirm_button.bind(on_release=self._confirm)
        row.add_widget(self.back_button)
        row.add_widget(self.confirm_button)
        panel.add_widget(row)
        self.add_widget(panel)

    def _confirm(self, *args):
        self.dismiss()
        self._on_confirm()


class AlertPopup(ModalView):
    def __init__(self, message, on_close=None, **kwargs):
        super().__init__(size_hint=(0.55, 0.5), auto_dismiss=True, background='',
                         background_color=(0, 0, 0, 0), overlay_color=(0, 0, 0, 0.65),
                         **kwargs)
        self._on_close = on_close
        panel = Panel()
        panel.add_widget(Lbl(text=message, color=theme.RED_TEXT, font_size=sp(22),
                             size_hint_y=1))
        button = StyledButton(text=t('close'), size_hint_y=None, height=theme.BUTTON_H,
                              base_color=theme.DARK_RED, down_color=theme.RED)
        button.bind(on_release=lambda *args: self.dismiss())
        panel.add_widget(button)
        self.add_widget(panel)
        self.bind(on_dismiss=self._dismissed)

    def _dismissed(self, *args):
        if self._on_close:
            self._on_close()
