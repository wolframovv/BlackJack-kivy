"""Минимальная заглушка Kivy для проверки кода приложения без Kivy.

Проверяет Python-логику (создание экранов, переходы, последовательность анимаций),
но не внешний вид: файл style.kv и отрисовка в ней не участвуют.
"""
import os
import sys
import tempfile
import types

MISSING = object()


# ----------------------------------------------------------------- свойства
class Property:
    def __init__(self, default=None, **kw):
        self.default = default

    def __set_name__(self, owner, name):
        self.name = name

    def _values(self, obj):
        return obj.__dict__.setdefault('_pv', {})

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        values = self._values(obj)
        if self.name not in values:
            default = self.default
            values[self.name] = list(default) if isinstance(default, (list, tuple)) else default
        return values[self.name]

    def __set__(self, obj, value):
        values = self._values(obj)
        old = values.get(self.name, MISSING)
        values[self.name] = value
        if old is MISSING or old != value:
            obj._notify(self.name, value)


class StringProperty(Property): pass
class NumericProperty(Property): pass
class BooleanProperty(Property): pass
class ListProperty(Property):
    def __init__(self, default=None, **kw):
        super().__init__(default if default is not None else [])


# ----------------------------------------------------------------- часы
class _Event:
    def __init__(self, fn, when, interval=None):
        self.fn, self.when, self.interval, self.cancelled = fn, when, interval, False

    def cancel(self):
        self.cancelled = True


class _Clock:
    def __init__(self):
        self.reset()

    def reset(self):
        self.now = 0.0
        self.queue = []

    def schedule_once(self, fn, timeout=0):
        ev = _Event(fn, self.now + timeout)
        self.queue.append(ev)
        return ev

    def schedule_interval(self, fn, interval):
        ev = _Event(fn, self.now + interval, interval)
        self.queue.append(ev)
        return ev

    def advance(self, dt):
        target = self.now + dt
        while True:
            due = [e for e in self.queue if not e.cancelled and e.when <= target]
            if not due:
                break
            ev = min(due, key=lambda e: e.when)
            self.now = max(self.now, ev.when)
            if ev.interval:
                ev.when += ev.interval
            else:
                self.queue.remove(ev)
            ev.fn(ev.interval or 0)
        self.now = target
        self.queue = [e for e in self.queue if not e.cancelled]

    def pending_once(self):
        return [e for e in self.queue if not e.cancelled and not e.interval]

    def settle(self, max_time=60.0, step=0.02):
        t = 0.0
        while t < max_time:
            self.advance(step)
            t += step
            if not self.pending_once():
                return t
        raise AssertionError('анимации не закончились за %s с' % max_time)


Clock = _Clock()


# ----------------------------------------------------------------- виджеты
class Canvas:
    def __init__(self):
        self.before = self
        self.after = self
        self.items = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def add(self, item):
        self.items.append(item)

    def remove(self, item):
        self.items.remove(item)


class Instruction:
    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)


class InstructionGroup(Instruction):
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)


class Widget:
    x = NumericProperty(0)
    y = NumericProperty(0)
    width = NumericProperty(100)
    height = NumericProperty(100)
    opacity = NumericProperty(1)
    disabled = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._binds = {}
        self.children = []
        self.parent = None
        self.canvas = Canvas()
        for key, value in kwargs.items():
            if key.startswith('on_') and callable(value):
                self.bind(**{key: value})
            else:
                setattr(self, key, value)

    # pos / size ведут себя как в Kivy: вычисляются из x,y,width,height
    @property
    def pos(self):
        return (self.x, self.y)

    @pos.setter
    def pos(self, value):
        self.x, self.y = value
        self._notify('pos', value)

    @property
    def size(self):
        return (self.width, self.height)

    @size.setter
    def size(self, value):
        self.width, self.height = value
        self._notify('size', value)

    center_x = property(lambda s: s.x + s.width / 2)
    center_y = property(lambda s: s.y + s.height / 2)
    top = property(lambda s: s.y + s.height)
    right = property(lambda s: s.x + s.width)

    def bind(self, **kwargs):
        for name, cb in kwargs.items():
            self._binds.setdefault(name, []).append(cb)

    def unbind(self, **kwargs):
        pass

    def setter(self, name):
        return lambda obj, value: setattr(self, name, value)

    def _notify(self, name, value):
        for cb in list(self.__dict__.get('_binds', {}).get(name, [])):
            cb(self, value)

    def dispatch(self, event, *args):
        for cb in list(self._binds.get(event, [])):
            cb(self, *args)

    def add_widget(self, widget):
        widget.parent = self
        self.children.append(widget)

    def remove_widget(self, widget):
        self.children.remove(widget)

    def clear_widgets(self):
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


class Label(Widget):
    text = StringProperty('')
    color = ListProperty([1, 1, 1, 1])
    font_size = NumericProperty(15)


class Button(Label):
    state = StringProperty('normal')

    def press(self):
        """Имитация нажатия в тестах."""
        assert not self.disabled, 'кнопка недоступна: %r' % self.text
        self.dispatch('on_release')


class Image(Widget):
    source = StringProperty('')


class TextInput(Label):
    hint_text = StringProperty('')
    password = BooleanProperty(False)
    focus = BooleanProperty(False)

    def insert_text(self, substring, from_undo=False):
        self.text = self.text + substring

    def type(self, text):
        """Имитация ввода с клавиатуры."""
        for ch in text:
            self.insert_text(ch)


class BoxLayout(Widget): pass
class FloatLayout(Widget): pass
class GridLayout(Widget):
    minimum_height = NumericProperty(0)
class ScrollView(Widget): pass
class StencilView(Widget): pass


class ModalView(Widget):
    def open(self):
        self.is_open = True

    def dismiss(self):
        if getattr(self, 'is_open', False):
            self.is_open = False
            self.dispatch('on_dismiss')


class Screen(Widget):
    name = StringProperty('')
    manager = None

    def on_pre_enter(self, *a): pass
    def on_enter(self, *a): pass
    def on_leave(self, *a): pass


class FadeTransition:
    def __init__(self, **kw):
        pass


class NoTransition:
    def __init__(self, **kw):
        pass


class ScreenManager(Widget):
    SIZE_BEFORE_PRE_ENTER = True   # в тестах переключается, чтобы проверить оба порядка

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.screens = {}
        self._current = None
        self.size = (2128, 996)

    def add_widget(self, screen):
        screen.manager = self
        self.screens[screen.name] = screen

    @property
    def current(self):
        return self._current.name if self._current else None

    @current.setter
    def current(self, name):
        old, new = self._current, self.screens[name]
        if old is new:
            return
        self._current = new
        if self.SIZE_BEFORE_PRE_ENTER:
            new.size = self.size
        new.on_pre_enter()
        if not self.SIZE_BEFORE_PRE_ENTER:
            new.size = self.size

        def finish(dt):
            if old is not None:
                old.on_leave()
            new.on_enter()

        Clock.schedule_once(finish, 0.12)

    @property
    def current_screen(self):
        return self._current


class Animation:
    running = []

    def __init__(self, **kwargs):
        self.duration = kwargs.pop('duration', kwargs.pop('d', 1.0))
        kwargs.pop('t', None)
        kwargs.pop('transition', None)
        self.props = kwargs
        self._binds = []
        self._event = None

    def bind(self, **kwargs):
        if 'on_complete' in kwargs:
            self._binds.append(kwargs['on_complete'])

    def start(self, widget):
        self.widget = widget

        def finish(dt):
            for name, value in self.props.items():
                setattr(widget, name, value)
            if self in Animation.running:
                Animation.running.remove(self)
            for cb in self._binds:
                cb(self, widget)

        Animation.running.append(self)
        self._event = Clock.schedule_once(finish, self.duration)

    @staticmethod
    def cancel_all(widget, *names):
        for anim in list(Animation.running):
            if anim.widget is widget:
                anim._event.cancel()
                Animation.running.remove(anim)


# ----------------------------------------------------------------- установка
def install():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    existing = sys.modules.get('kivy')
    if existing is not None and getattr(existing, '_is_stub', False):
        return sys.modules          # уже установлена: второй раз классы подменять нельзя

    kivy = mod('kivy')
    kivy.__path__ = []
    kivy._is_stub = True

    class _Config:
        @staticmethod
        def set(*a): pass

    class _Window:
        softinput_mode = ''
        clearcolor = (0, 0, 0, 1)
        callbacks = {}

        @classmethod
        def bind(cls, **kw):
            cls.callbacks.update(kw)

    class _LabelBase:
        registered = {}

        @classmethod
        def register(cls, name, fn_regular=None, fn_bold=None, **kw):
            cls.registered[name] = fn_regular

    class _App:
        title = ''

        def __init__(self, **kw):
            self._tmp = tempfile.mkdtemp()
            self.stopped = False

        @property
        def user_data_dir(self):
            return self._tmp

        def run(self):
            pass

        def stop(self):
            self.stopped = True

    class _Builder:
        loaded = []

        @classmethod
        def load_file(cls, path):
            cls.loaded.append(path)

    mod('kivy.config', Config=_Config)
    mod('kivy.app', App=_App)
    mod('kivy.core')
    mod('kivy.core.window', Window=_Window)
    mod('kivy.core.text', LabelBase=_LabelBase)
    mod('kivy.resources', resource_find=lambda p: p)
    mod('kivy.lang', Builder=_Builder)
    mod('kivy.metrics', dp=lambda v: v * 2.625, sp=lambda v: v * 2.625)
    mod('kivy.clock', Clock=Clock)
    mod('kivy.animation', Animation=Animation)
    mod('kivy.properties', StringProperty=StringProperty, NumericProperty=NumericProperty,
        BooleanProperty=BooleanProperty, ListProperty=ListProperty)
    mod('kivy.graphics', Color=Instruction, Ellipse=Instruction, Rectangle=Instruction,
        Line=Instruction, InstructionGroup=InstructionGroup)

    class TextureStub:
        def __init__(self, size):
            self.size = size

        @classmethod
        def create(cls, size=(1, 1), colorfmt='rgba'):
            return cls(size)

        def blit_buffer(self, data, colorfmt='rgba', bufferfmt='ubyte'):
            self.data = data

    mod('kivy.graphics.texture', Texture=TextureStub)

    class _Texture:
        def __init__(self, size):
            self.size = size
            self.tex_coords = (0, 1, 1, 1, 1, 0, 0, 0)

    class _CoreImage:
        sizes = {}                       # путь -> (ширина, высота); по умолчанию 256×256

        def __init__(self, filename, **kw):
            if not os.path.exists(filename):
                raise FileNotFoundError(filename)
            self.texture = _Texture(self.sizes.get(filename, (256, 256)))

    core_image = mod('kivy.core.image', Image=_CoreImage)
    mod('kivy.uix')
    mod('kivy.uix.widget', Widget=Widget)
    mod('kivy.uix.label', Label=Label)
    mod('kivy.uix.button', Button=Button)
    mod('kivy.uix.image', Image=Image)
    mod('kivy.uix.textinput', TextInput=TextInput)
    mod('kivy.uix.boxlayout', BoxLayout=BoxLayout)
    mod('kivy.uix.floatlayout', FloatLayout=FloatLayout)
    mod('kivy.uix.gridlayout', GridLayout=GridLayout)
    mod('kivy.uix.scrollview', ScrollView=ScrollView)
    mod('kivy.uix.stencilview', StencilView=StencilView)
    mod('kivy.uix.modalview', ModalView=ModalView)
    mod('kivy.uix.screenmanager', Screen=Screen, ScreenManager=ScreenManager,
        FadeTransition=FadeTransition, NoTransition=NoTransition)
    return sys.modules
