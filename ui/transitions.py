"""Переходы между экранами меню/режима/ставки."""
from kivy.graphics import InstructionGroup, PopMatrix, PushMatrix, Rotate, Scale
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.screenmanager import TransitionBase


def _ease_out_cubic(p):
    return 1.0 - (1.0 - p) ** 3


def _ease_in_out(p):
    return p * p * (3.0 - 2.0 * p)


class ArcTransition(TransitionBase):
    """Меню уменьшается и уходит вниз, выбор режима прилетает сверху.

    При reverse анимация проигрывается назад: выбор режима уходит вверх,
    а меню возвращается снизу.
    """

    reverse = BooleanProperty(False)
    duration = NumericProperty(0.52)

    def __init__(self, **kwargs):
        self._groups = {}
        self._scales = {}
        self._rotates = {}
        super().__init__(**kwargs)

    def start(self, manager):
        self.manager = manager
        for screen in (self.screen_in, self.screen_out):
            screen.pos = manager.pos
            screen.size = manager.size
            screen.opacity = 1
            group = InstructionGroup()
            group.add(PushMatrix())
            scale = Scale(origin=screen.center)
            rotate = Rotate(origin=screen.center, axis=(1, 0, 0), angle=0)
            group.add(scale)
            group.add(rotate)
            group.add(PopMatrix())
            screen.canvas.before.add(group)
            self._groups[screen] = group
            self._scales[screen] = scale
            self._rotates[screen] = rotate
        super().start(manager)

    def on_progress(self, progression):
        if not self.screen_in or not self.screen_out:
            return
        p = _ease_in_out(progression)
        x, y = self.manager.pos
        w, h = self.manager.size
        if not self.reverse:
            out_y = y - h * 0.38 * p
            in_y = y + h * 0.55 * (1 - p)
            out_angle = -28.0 * p
            in_angle = 28.0 * (1 - p)
        else:
            out_y = y + h * 0.55 * p
            in_y = y - h * 0.38 * (1 - p)
            out_angle = 28.0 * p
            in_angle = -28.0 * (1 - p)
        scale = 1.0 - 0.45 * p
        self._apply(self.screen_out, x, out_y, scale, out_angle, 1.0 - p)
        self._apply(self.screen_in, x, in_y, 0.55 + 0.45 * p, in_angle, p)

    def _apply(self, screen, x, y, scale, angle, opacity):
        screen.x = x
        screen.y = y
        screen.opacity = opacity
        origin = (screen.center_x, screen.center_y, 0)
        inst_scale = self._scales[screen]
        inst_scale.origin = origin
        inst_scale.x = scale
        inst_scale.y = scale
        inst_scale.z = 1.0
        inst_rotate = self._rotates[screen]
        inst_rotate.origin = origin
        inst_rotate.axis = (1, 0, 0)
        inst_rotate.angle = angle

    def _cleanup(self):
        for screen, group in self._groups.items():
            try:
                screen.canvas.before.remove(group)
            except (ValueError, AttributeError):
                pass
        self._groups.clear()
        self._scales.clear()
        self._rotates.clear()
        if self.screen_in is not None and self.manager is not None:
            self.screen_in.opacity = 1
            self.screen_in.pos = self.manager.pos
            self.screen_in.size = self.manager.size
        if self.screen_out is not None and self.manager is not None:
            self.screen_out.opacity = 1
            self.screen_out.pos = self.manager.pos
            self.screen_out.size = self.manager.size

    def on_complete(self):
        self._cleanup()
        super().on_complete()

    def stop(self):
        self._cleanup()
        super().stop()


class SlideTransition(TransitionBase):
    """Смена экрана сдвигом: direction='left' — новый приезжает справа,
    direction='right' — новый приезжает слева."""

    direction = StringProperty('left')
    duration = NumericProperty(0.34)

    def start(self, manager):
        self.manager = manager
        for screen in (self.screen_in, self.screen_out):
            screen.pos = manager.pos
            screen.size = manager.size
            screen.opacity = 1
        super().start(manager)

    def on_progress(self, progression):
        if not self.screen_in or not self.screen_out:
            return
        p = _ease_out_cubic(progression)
        x, y = self.manager.pos
        w, h = self.manager.size
        a, b = self.screen_in, self.screen_out
        a.y = b.y = y
        if self.direction == 'left':
            a.x = x + w * (1 - p)
            b.x = x - w * p
        else:
            a.x = x - w * (1 - p)
            b.x = x + w * p

    def on_complete(self):
        for screen in (self.screen_in, self.screen_out):
            if screen is not None:
                screen.pos = self.manager.pos
                screen.size = self.manager.size
                screen.opacity = 1
        super().on_complete()
