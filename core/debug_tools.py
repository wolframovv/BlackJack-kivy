"""Инструменты отладочного меню: аккаунты, баланс, блокировка, архив данных. Не зависит от Kivy."""
import os
import time
import zipfile

from .storage import HASH_PREFIX, START_BALANCE, hash_password

MAX_BALANCE = 1_000_000_000


def account_names(storage):
    """Логины всех аккаунтов (по алфавиту)."""
    return sorted(storage.users)


def describe_account(storage, username):
    """Данные аккаунта для показа: логин, пароль (если его можно показать), баланс, блокировка."""
    user = storage.users[username]
    stored = str(user.get('password') or '')
    # Пароли хранятся хэшем (pbkdf2), прочитать их нельзя. Только очень старые сохранения
    # со времён версии на pygame хранят пароль открытым текстом — его показываем как есть.
    readable = stored if stored and not stored.startswith(HASH_PREFIX) else None
    return {
        'username': username,
        'name': storage.display_name(user),
        'password': readable,
        'balance': user['balance'],
        'lock_seconds': storage.lock_remaining(user),
        'elo': user.get('elo', 0),
    }


def unlock_account(storage, username):
    """Снимает блокировку. Если денег нет, выдаёт стартовые, чтобы блокировка не включилась
    снова сразу же."""
    user = storage.users[username]
    user['locked_until'] = 0
    if user['balance'] < 1:
        user['balance'] = START_BALANCE
    storage.save()


def set_balance(storage, username, text):
    """Задаёт баланс. Возвращает (новый баланс или None, текст ошибки или None)."""
    try:
        amount = int(str(text).strip())
    except ValueError:
        return None, 'нужно целое число'
    if amount < 0 or amount > MAX_BALANCE:
        return None, f'от 0 до {MAX_BALANCE}'
    user = storage.users[username]
    user['balance'] = amount
    storage.ensure_lock_state(user)       # 0 денег = блокировка, как в обычной игре
    storage.save()
    return amount, None


def set_password(storage, username, text):
    """Задаёт новый пароль. Возвращает текст ошибки или None."""
    password = str(text).strip()
    if len(password) < 4:
        return 'пароль короче 4 символов'
    storage.users[username]['password'] = hash_password(password)
    storage.save()
    return None


def make_dataset_zip(csv_paths, dest_dir, now=None):
    """Пакует существующие непустые CSV в zip. Возвращает путь к архиву.
    Если данных ещё нет, бросает ValueError."""
    files = [p for p in csv_paths if os.path.exists(p) and os.path.getsize(p) > 0]
    if not files:
        raise ValueError('данных для обучения пока нет')
    os.makedirs(dest_dir, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime(now or time.time()))
    zip_path = os.path.join(dest_dir, f'blackjack_dataset_{stamp}.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, os.path.basename(path))
    return zip_path
