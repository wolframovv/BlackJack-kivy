"""Фон: картинка с лёгким дрейфом и движущиеся частицы."""
import math
import os
import random

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, InstructionGroup, Rectangle
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image

from . import theme


class ParticleBackground(FloatLayout):
    PARTICLE_COUNT = 50
    TICK = 1 / 30.0          # частицы медленные, 30 обновлений в секунду достаточно
    DRIFT = 0.012            # амплитуда дрейфа фона (доля размера окна)
    MARGIN = 0.03            # запас картинки за краями экрана под дрейф

    def __init__(self, image_path, **kwargs):
        super().__init__(**kwargs)
        self._time = 0.0
        self._event = None
        self._animated = False
        self._group_added = False
        self._image_path = None

        # запасной зелёный фон, если картинки нет
        with self.canvas.before:
            Color(*theme.GREEN)
            self._fill = Rectangle()

        self.image = Image(source='', fit_mode='fill', size_hint=(None, None))
        self.add_widget(self.image)
        self.set_image(image_path)

        self._group = InstructionGroup()
        self._particles = []
        self._build_particles()

        self.bind(size=self._layout, pos=self._layout)
        self._layout()
        self.set_animated(True)

    def set_image(self, image_path):
        """Меняет картинку фона: в меню одна, за игровым столом другая."""
        source = image_path if image_path and os.path.exists(image_path) else ''
        if source == self._image_path:
            return
        self._image_path = source
        self.image.source = source

    # ---------- частицы ----------
    def _build_particles(self):
        for _ in range(self.PARTICLE_COUNT):
            alpha = random.randint(50, 150) / 255.0
            tint = random.choice([(1, 1, 1), (1, 0.84, 0.3), (0.7, 0.85, 1)])
            color = Color(tint[0], tint[1], tint[2], alpha)
            ellipse = Ellipse(size=(2, 2), segments=10)
            self._group.add(color)
            self._group.add(ellipse)
            self._particles.append({
                'ellipse': ellipse,
                'x': random.random(), 'y': random.random(),     # доли экрана
                'radius': random.uniform(1.0, 3.0),
                'speed': random.uniform(0.1, 0.5) * 60 / 1080.0,  # доля высоты в секунду
                'dir': random.uniform(0, math.pi * 2),
            })

    def _layout(self, *args):
        w, h = self.size
        self._fill.pos = self.pos
        self._fill.size = self.size
        pad_x, pad_y = w * self.MARGIN, h * self.MARGIN
        self.image.size = (w + 2 * pad_x, h + 2 * pad_y)
        self._apply_drift()
        self._place_particles()

    def _apply_drift(self):
        w, h = self.size
        dx = math.sin(self._time * 0.5) * w * self.DRIFT
        dy = math.cos(self._time * 0.3) * h * self.DRIFT
        self.image.pos = (self.x - w * self.MARGIN + dx, self.y - h * self.MARGIN + dy)

    def _place_particles(self):
        w, h = self.size
        scale = max(h / 1080.0, 0.8) * 1.6
        for p in self._particles:
            r = p['radius'] * scale
            p['ellipse'].size = (r * 2, r * 2)
            p['ellipse'].pos = (self.x + p['x'] * w - r, self.y + p['y'] * h - r)

    def _tick(self, dt):
        w, h = self.size
        if not w or not h:
            return
        self._time += dt
        step = dt * h  # скорость задана долей высоты в секунду
        for p in self._particles:
            p['x'] += math.cos(p['dir']) * p['speed'] * step / w
            p['y'] += math.sin(p['dir']) * p['speed'] * step / h
            # уходят за край — появляются с противоположной стороны
            if p['x'] < -0.02:
                p['x'] = 1.02
            elif p['x'] > 1.02:
                p['x'] = -0.02
            if p['y'] < -0.02:
                p['y'] = 1.02
            elif p['y'] > 1.02:
                p['y'] = -0.02
            # слегка меняем направление, как в старой версии
            p['dir'] += random.uniform(-0.05, 0.05)
        self._apply_drift()
        self._place_particles()

    # ---------- управление ----------
    def set_animated(self, enabled):
        """Включает или выключает частицы и дрейф (на игровом столе выключаем)."""
        if enabled == self._animated:
            return
        self._animated = enabled
        if enabled:
            if not self._group_added:
                self.canvas.add(self._group)
                self._group_added = True
            self._event = Clock.schedule_interval(self._tick, self.TICK)
        else:
            if self._event is not None:
                self._event.cancel()
                self._event = None
            if self._group_added:
                self.canvas.remove(self._group)
                self._group_added = False
