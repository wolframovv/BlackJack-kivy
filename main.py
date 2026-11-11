"""BlackJack на Kivy: точка входа."""
import os

ANDROID = 'ANDROID_ARGUMENT' in os.environ
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if not ANDROID:
    # На ПК имитируем телефон: плотность и размер окна, как у ландшафтного экрана ~380 dp
    os.environ.setdefault('KIVY_METRICS_DENSITY', '1.3')

from kivy.config import Config  # noqa: E402

if not ANDROID:
    Config.set('input', 'mouse', 'mouse,disable_multitouch')
    Config.set('graphics', 'width', '1064')
    Config.set('graphics', 'height', '498')

from kivy.animation import Animation  # noqa: E402
from kivy.app import App  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.lang import Builder  # noqa: E402
from kivy.uix.floatlayout import FloatLayout  # noqa: E402
from kivy.uix.screenmanager import NoTransition, ScreenManager  # noqa: E402

from core.dataset import DecisionLog  # noqa: E402
from core.i18n import duration_text, i18n, t  # noqa: E402
from core.storage import Storage  # noqa: E402
from ui import theme  # noqa: E402
from ui.avatar_picker import AvatarPicker  # noqa: E402
from ui.debug_menu import DebugButton, DebugMenu  # noqa: E402
from ui.background import ParticleBackground  # noqa: E402
from ui.sound import sounds  # noqa: E402
from ui.screens.betting import BettingScreen  # noqa: E402
from ui.screens.competitive import TableScreen  # noqa: E402
from ui.screens.game import GameScreen  # noqa: E402
from ui.screens.leaderboard import LeaderboardScreen  # noqa: E402
from ui.screens.login import LoginScreen  # noqa: E402
from ui.screens.menu import MenuScreen  # noqa: E402
from ui.screens.mode import ModeScreen  # noqa: E402
from ui.screens.profile import ProfileScreen  # noqa: E402
from ui.screens.skins import SkinsScreen  # noqa: E402
from ui.widgets import AlertPopup, FadeOverlay  # noqa: E402

# куда возвращает кнопка «Назад» с каждого экрана
BACK_TARGETS = {
    'profile': 'menu', 'leaderboard': 'menu', 'skins': 'menu',
    'mode': 'menu', 'betting': 'mode',
}


class BlackjackApp(App):
    title = 'BlackJack'

    def build(self):
        theme.register_fonts(BASE_DIR)
        Builder.load_file(os.path.join(BASE_DIR, 'ui', 'style.kv'))

        Window.clearcolor = (0, 0, 0, 1)
        # чтобы экранная клавиатура не закрывала поле ввода
        Window.softinput_mode = 'below_target'

        self.storage = Storage(self.user_data_dir)
        i18n.set_language(self.storage.language)
        self.dataset = DecisionLog(self._dataset_dir())   # CSV с решениями для обучения
        print('Датасет решений:', self.dataset.decisions_path)
        self.username = None           # логин вошедшего игрока (гостя больше нет)
        self.default_avatar = os.path.join(BASE_DIR, 'etc', 'default_pic.png')
        self.picker = AvatarPicker(self)
        sounds.load(os.path.join(BASE_DIR, 'etc', 'sounds'))
        self.alert = None
        self.debug_menu = None
        self.mode = 'single'           # 'single' или 'competitive' (после экрана ставки)
        self._fading = False
        self._target = None

        root = FloatLayout()
        self.background = ParticleBackground(os.path.join(BASE_DIR, 'etc', 'background.jpg'))
        root.add_widget(self.background)

        self.sm = ScreenManager(transition=NoTransition())
        self.game = GameScreen(self, name='game')
        self.table_screen = TableScreen(self, name='table')
        for screen in (
            LoginScreen(self, name='login'),
            MenuScreen(self, name='menu'),
            ProfileScreen(self, name='profile'),
            ModeScreen(self, name='mode'),
            LeaderboardScreen(self, name='leaderboard'),
            SkinsScreen(self, name='skins'),
            BettingScreen(self, name='betting'),
            self.game,
            self.table_screen,
        ):
            self.sm.add_widget(screen)
        root.add_widget(self.sm)
        if theme.DEBUG_MENU:
            root.add_widget(DebugButton(self))     # кружок отладочного меню (над экранами)
        # завеса для переходов лежит последней, то есть поверх всего интерфейса
        self.fade = FadeOverlay(opacity=0)
        root.add_widget(self.fade)

        # автоматический вход под последним пользователем
        last = self.storage.last_user
        if last and last in self.storage.users:
            self.username = last
            self.storage.ensure_lock_state(self.user)     # снять истёкшую блокировку
            self.sm.current = 'menu'
        else:
            self.sm.current = 'login'

        Window.bind(on_keyboard=self._on_keyboard)
        return root

    # ---------- данные ----------
    def _dataset_dir(self):
        """Где лежат CSV для обучения: переменная BLACKJACK_DATA_DIR, на ПК — папка data/
        рядом с main.py, на Android — папка данных приложения."""
        custom = os.environ.get('BLACKJACK_DATA_DIR')
        if custom:
            return custom
        return self.user_data_dir if ANDROID else os.path.join(BASE_DIR, 'data')

    @property
    def user(self):
        return self.storage.get_user(self.username)

    def avatar_source(self, user):
        """Путь к аватару игрока или к картинке по умолчанию (etc/default_pic.png)."""
        return self.storage.avatar_file(user) or self.default_avatar

    def rank_source(self, rank):
        """Путь к картинке ранга etc/elo/elo<N>.png или '', если файла нет."""
        path = os.path.join(BASE_DIR, 'etc', 'elo', f'elo{rank}.png')
        return path if os.path.exists(path) else ''

    # ---------- навигация ----------
    def go(self, name):
        """Переход на экран: интерфейс затемняется целиком, экран меняется, затемнение уходит."""
        self._target = name
        if self._fading or name == self.sm.current:
            return
        self._fading = True
        animation = Animation(opacity=theme.FADE_PEAK, duration=theme.FADE_IN, t='out_quad')
        animation.bind(on_complete=self._fade_swap)
        animation.start(self.fade)

    def _fade_swap(self, *args):
        self.sm.current = self._target
        animation = Animation(opacity=0, duration=theme.FADE_OUT, t='in_quad')
        animation.bind(on_complete=self._fade_done)
        animation.start(self.fade)

    def _fade_done(self, *args):
        self._fading = False

    def _can_play(self):
        """True, если можно играть. Если деньги кончились — игра заблокирована на 24 часа,
        и игроку показывается, сколько ждать."""
        user = self.user
        if self.storage.ensure_lock_state(user) == 'unlocked':
            self.show_alert(t('lock_lifted'))
        remaining = self.storage.lock_remaining(user)
        if remaining > 0:
            self.show_alert(t('locked_play') + duration_text(remaining))
            return False
        return True

    def go_play(self):
        """Кнопка «Играть»: выбор режима."""
        if self._can_play():
            self.go('mode')

    def go_betting(self, mode='single'):
        """Переход к ставке: mode 'single' (одиночная игра) или 'competitive' (стол с ботами)."""
        if self._can_play():
            self.mode = mode
            self.go('betting')

    def start_game(self, bet):
        user = self.user
        if self._fading or bet <= 0 or bet > user['balance'] or self.storage.lock_remaining(user) > 0:
            return   # во время перехода повторное нажатие не должно списать ставку дважды
        user['balance'] -= bet
        self.storage.save()
        if self.mode == 'competitive':
            self.table_screen.begin(bet)
            self.go('table')
        else:
            self.game.begin(bet)
            self.go('game')

    def login_success(self, username):
        self.username = username
        self.storage.last_user = username
        if self.storage.ensure_lock_state(self.user) == 'unlocked':
            self.show_alert(t('lock_lifted'))
        self.go('menu')

    def logout(self):
        self.username = None
        self.storage.last_user = None
        self.go('login')

    def toggle_language(self):
        i18n.next_language()
        self.storage.language = i18n.language
        self.sm.current_screen.refresh_texts()

    def show_alert(self, text):
        if self.alert is not None:
            self.alert.dismiss()
        self.alert = AlertPopup(text, on_close=self._alert_closed)
        self.alert.open()

    def _alert_closed(self):
        self.alert = None

    def open_debug_menu(self):
        if self.debug_menu is not None:
            return
        self.debug_menu = DebugMenu(self)
        self.debug_menu.bind(on_dismiss=self._debug_closed)
        self.debug_menu.open()

    def _debug_closed(self, *args):
        self.debug_menu = None
        # баланс или блокировка могли измениться: обновляем тексты текущего экрана
        if self.sm.current in ('menu', 'profile', 'mode', 'betting', 'leaderboard', 'skins'):
            self.sm.current_screen.refresh_texts()

    # ---------- кнопка «Назад» (на ПК — Esc) ----------
    def _on_keyboard(self, window, key, *args):
        if key != 27:
            return False
        if self.debug_menu is not None:
            self.debug_menu.dismiss()
            return True
        if self.alert is not None:
            self.alert.dismiss()
            return True
        current = self.sm.current
        if current in BACK_TARGETS:
            self.go(BACK_TARGETS[current])
            return True
        if current == 'game':
            self.game.ask_leave()   # во время партии «Назад» спрашивает подтверждение
            return True
        if current == 'table':
            self.table_screen.ask_leave()
            return True
        return False             # меню и вход: стандартное поведение — выход

    # ---------- жизненный цикл ----------
    def on_pause(self):
        self.storage.save()
        return True              # разрешаем свернуть приложение

    def on_stop(self):
        self.storage.save()


if __name__ == '__main__':
    BlackjackApp().run()
