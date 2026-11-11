"""Сохранения, пользователи и настройки. Не зависит от Kivy.

Формат файлов совместим со старой версией на pygame (game_save.json и
game_settings.json), поэтому при установке поверх старой версии прогресс
сохраняется. Старые пароли в открытом виде принимаются и при первом входе
автоматически заменяются на хэш.
"""
import hashlib
import hmac
import json
import os
import time
import uuid
from .ranks import START_ELO, rank_for_elo

SAVE_NAME = 'game_save.json'
SETTINGS_NAME = 'game_settings.json'
HASH_PREFIX = 'pbkdf2$'
HASH_ITERATIONS = 60000
START_BALANCE = 1000
LOCK_SECONDS = 24 * 3600     # блокировка игры после проигрыша всех денег
NAME_MIN, NAME_MAX = 2, 16   # допустимая длина отображаемого имени
AVATAR_DIR = 'avatars'

USER_DEFAULTS = {
    'balance': START_BALANCE,
    'wins': 0,
    'losses': 0,
    'ties': 0,
    'skins': ['default'],
    'current_skin': 'default',
    'avatar': '',          # имя файла в папке avatars/ ('' — аватар по умолчанию)
    'locked_until': 0,     # до какого времени (unix) игра заблокирована, 0 — нет блокировки
      'elo': START_ELO,
}


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, HASH_ITERATIONS)
    return f"{HASH_PREFIX}{salt.hex()}${digest.hex()}"


def check_password(stored, password):
    """Возвращает (совпал ли пароль, нужно ли заменить на хэш)."""
    if not stored:
        return False, False
    if stored.startswith(HASH_PREFIX):
        try:
            _, salt_hex, digest_hex = stored.split('$')
            digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                         bytes.fromhex(salt_hex), HASH_ITERATIONS)
            return hmac.compare_digest(digest.hex(), digest_hex), False
        except ValueError:
            return False, False
    # старый формат: пароль в открытом виде
    return hmac.compare_digest(stored.encode('utf-8'), password.encode('utf-8')), True


class Storage:
    def __init__(self, directory, clock=time.time):
        os.makedirs(directory, exist_ok=True)
        self.save_path = os.path.join(directory, SAVE_NAME)
        self.settings_path = os.path.join(directory, SETTINGS_NAME)
        self.avatar_dir = os.path.join(directory, AVATAR_DIR)
        self._clock = clock                 # подменяется в тестах
        self.users = self._load_users()
        self.settings = self._load_settings()

    def now(self):
        return self._clock()

    # ---------- файлы ----------
    @staticmethod
    def _read_json(path):
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            # повреждённый файл не затираем, а откладываем в сторону
            try:
                os.replace(path, path + '.bak')
            except OSError:
                pass
            return None

    @staticmethod
    def _write_json(path, data):
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # запись атомарная: приложение могут убить в любой момент

    # ---------- пользователи ----------
    def _load_users(self):
        data = self._read_json(self.save_path) or {}
        users = {}
        for name, info in data.items():
            if not isinstance(info, dict) or name == 'Guest':   # гостевой игрок удалён
                continue
            user = dict(USER_DEFAULTS)
            user['skins'] = list(USER_DEFAULTS['skins'])
            user.update(info)
            user['username'] = name                              # логин
            if not str(user.get('display_name') or '').strip():
                user['display_name'] = name                      # имя по умолчанию = логин
            users[name] = user
        return users

    @staticmethod
    def _new_user(name, password_hash):
        user = dict(USER_DEFAULTS)
        user['skins'] = list(USER_DEFAULTS['skins'])
        user['username'] = name            # логин (по нему входят)
        user['display_name'] = name        # имя (его видят другие игроки)
        user['password'] = password_hash
        return user

    def save(self):
        self._write_json(self.save_path, self.users)
        self._write_json(self.settings_path, self.settings)

    def get_user(self, name):
        return self.users.get(name)

    def register(self, username, password):
        """Возвращает (пользователь или None, ключ ошибки или None)."""
        username, password = username.strip(), password.strip()
        if not username or not password:
            return None, 'fill_all_fields'
        if self.register_block_remaining() > 0:
            return None, 'register_locked'     # у кого-то действует блокировка
        if username in self.users:
            return None, 'username_taken'
        if len(username) < 3:
            return None, 'username_short'
        if len(password) < 4:
            return None, 'password_short'
        user = self._new_user(username, hash_password(password))
        self.users[username] = user
        self.save()
        return user, None

    def authenticate(self, username, password):
        """Возвращает (пользователь или None, ключ ошибки или None)."""
        username, password = username.strip(), password.strip()
        if not username or not password:
            return None, 'fill_all_fields'
        user = self.users.get(username)
        if user is None:
            return None, 'user_not_found'
        ok, needs_upgrade = check_password(user.get('password'), password)
        if not ok:
            return None, 'wrong_password'
        if needs_upgrade:
            user['password'] = hash_password(password)
            self.save()
        return user, None

    def leaderboard(self):
        """Все игроки, по убыванию процента побед."""
        self.refresh_all_locks()
        rows = []
        for login, user in self.users.items():
            total = user['wins'] + user['losses'] + user['ties']
            rate = user['wins'] / total * 100 if total > 0 else 0
            rows.append({'username': login, 'name': self.display_name(user),
                         'avatar': self.avatar_file(user), 'win_rate': rate,
                         'balance': user['balance'], 'games': total, 'elo' : user['elo'], 'rank' : self.rank(user)})
        rows.sort(key=lambda row: row['win_rate'], reverse=True)
        return rows

    # ---------- имя и аватар ----------
    @staticmethod
    def rank(user):
        """Ранг игрока (1..10) по его elo."""
        return rank_for_elo(user.get('elo', START_ELO))
    
    @staticmethod
    def display_name(user):
        return str(user.get('display_name') or '').strip() or user['username']

    def set_display_name(self, user, name):
        """Меняет имя (логин не меняется). Возвращает ключ ошибки или None."""
        name = ' '.join(str(name).split())          # лишние пробелы убираем
        if len(name) < NAME_MIN:
            return 'name_short'
        if len(name) > NAME_MAX:
            return 'name_long'
        user['display_name'] = name
        self.save()
        return None

    def new_avatar_path(self, ext='.jpg'):
        """Свободный путь для нового файла аватара (имя уникально, чтобы не мешал кэш картинок)."""
        os.makedirs(self.avatar_dir, exist_ok=True)
        ext = ext if ext.startswith('.') else '.' + ext
        return os.path.join(self.avatar_dir, f"avatar_{uuid.uuid4().hex[:10]}{ext.lower()}")

    def avatar_file(self, user):
        """Полный путь к аватару игрока или '', если используется аватар по умолчанию."""
        name = os.path.basename(user.get('avatar') or '')
        if not name:
            return ''
        path = os.path.join(self.avatar_dir, name)
        return path if os.path.exists(path) else ''

    def set_avatar(self, user, path):
        """Назначает аватаром файл из папки avatars/ и удаляет прежний."""
        old = self.avatar_file(user)
        user['avatar'] = os.path.basename(path)
        self.save()
        if old and os.path.abspath(old) != os.path.abspath(path):
            self._remove(old)

    def clear_avatar(self, user):
        old = self.avatar_file(user)
        user['avatar'] = ''
        self.save()
        if old:
            self._remove(old)

    @staticmethod
    def _remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

    # ---------- блокировка после проигрыша всех денег ----------
    def lock_remaining(self, user):
        """Сколько секунд игра ещё заблокирована (0 — можно играть)."""
        until = user.get('locked_until') or 0
        return max(0, int(until - self.now() + 0.999)) if until else 0

    def ensure_lock_state(self, user):
        """Приводит блокировку в порядок. Возвращает:
        'locked'   — деньги кончились, игра заблокирована на 24 часа (только что);
        'unlocked' — срок прошёл: блокировка снята, начислено стартовое количество денег;
        None       — ничего не изменилось."""
        now = self.now()
        until = user.get('locked_until') or 0
        if until and now >= until:
            user['locked_until'] = 0
            if user['balance'] < 1:
                user['balance'] = START_BALANCE
            self.save()
            return 'unlocked'
        if not until and user['balance'] < 1:
            user['locked_until'] = now + LOCK_SECONDS
            self.save()
            return 'locked'
        return None

    def refresh_all_locks(self):
        """Снимает истёкшие блокировки у всех аккаунтов."""
        changed = False
        for user in self.users.values():
            until = user.get('locked_until') or 0
            if until and self.now() >= until:
                user['locked_until'] = 0
                if user['balance'] < 1:
                    user['balance'] = START_BALANCE
                changed = True
        if changed:
            self.save()

    def register_block_remaining(self):
        """Сколько секунд нельзя создавать новые аккаунты: пока действует блокировка
        хотя бы у одного — ждём, пока она снимется со всех."""
        self.refresh_all_locks()
        return max([self.lock_remaining(u) for u in self.users.values()] or [0])

    # ---------- настройки ----------
    def _load_settings(self):
        data = self._read_json(self.settings_path) or {}
        data.setdefault('language', 'russian')
        return data

    @property
    def language(self):
        return self.settings.get('language', 'russian')

    @language.setter
    def language(self, value):
        self.settings['language'] = value
        self._write_json(self.settings_path, self.settings)

    @property
    def last_user(self):
        return self.settings.get('last_user')

    @last_user.setter
    def last_user(self, value):
        self.settings['last_user'] = value
        self._write_json(self.settings_path, self.settings)
