"""Имя и логин, аватар, блокировка на 24 часа, запрет регистрации во время блокировки."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.i18n import duration_text, i18n
from core.storage import LOCK_SECONDS, NAME_MAX, START_BALANCE, Storage


class FakeClock:
    def __init__(self, start=1_700_000_000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class StorageCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.s = Storage(self.dir.name, clock=self.clock)

    def tearDown(self):
        self.dir.cleanup()

    def add(self, login='alice'):
        user, err = self.s.register(login, 'secret')
        self.assertIsNone(err)
        return user

    def bankrupt(self, user):
        user['balance'] = 0
        return self.s.ensure_lock_state(user)


class NameTests(StorageCase):
    def test_name_defaults_to_login_and_is_separate(self):
        user = self.add('alice')
        self.assertEqual((user['username'], self.s.display_name(user)), ('alice', 'alice'))
        self.assertIsNone(self.s.set_display_name(user, '  Алиса   Прекрасная '))
        self.assertEqual(self.s.display_name(user), 'Алиса Прекрасная')   # пробелы схлопнуты
        self.assertEqual(user['username'], 'alice')                         # логин не меняется
        # входить по-прежнему нужно по логину
        self.assertIsNone(self.s.authenticate('alice', 'secret')[1])
        self.assertEqual(self.s.authenticate('Алиса Прекрасная', 'secret')[1], 'user_not_found')

    def test_name_rules(self):
        user = self.add()
        self.assertEqual(self.s.set_display_name(user, ' a '), 'name_short')
        self.assertEqual(self.s.set_display_name(user, ''), 'name_short')
        self.assertEqual(self.s.set_display_name(user, 'x' * (NAME_MAX + 1)), 'name_long')
        self.assertIsNone(self.s.set_display_name(user, 'x' * NAME_MAX))
        self.assertEqual(self.s.display_name(user), 'x' * NAME_MAX)

    def test_name_persists_and_two_users_may_share_a_name(self):
        a, b = self.add('alice'), self.add('bobby')
        self.s.set_display_name(a, 'Макс')
        self.s.set_display_name(b, 'Макс')
        s2 = Storage(self.dir.name, clock=self.clock)
        self.assertEqual([s2.display_name(s2.users[k]) for k in ('alice', 'bobby')], ['Макс', 'Макс'])
        rows = s2.leaderboard()
        self.assertEqual({r['username'] for r in rows}, {'alice', 'bobby'})   # логины различают
        self.assertEqual({r['name'] for r in rows}, {'Макс'})


class AvatarTests(StorageCase):
    def make_file(self, ext='.jpg', data=b'x'):
        path = self.s.new_avatar_path(ext)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def test_default_avatar_has_no_file(self):
        user = self.add()
        self.assertEqual(self.s.avatar_file(user), '')
        self.assertEqual(self.s.leaderboard()[0]['avatar'], '')

    def test_set_replace_and_clear(self):
        user = self.add()
        first = self.make_file('.png')
        self.s.set_avatar(user, first)
        self.assertEqual(self.s.avatar_file(user), first)
        second = self.make_file('.JPG')
        self.assertNotEqual(first, second)                    # новое имя файла каждый раз
        self.s.set_avatar(user, second)
        self.assertEqual(self.s.avatar_file(user), second)
        self.assertFalse(os.path.exists(first))               # старый файл удалён
        self.assertTrue(second.endswith('.jpg'))
        self.s.clear_avatar(user)
        self.assertEqual(self.s.avatar_file(user), '')
        self.assertFalse(os.path.exists(second))
        self.assertEqual(user['avatar'], '')

    def test_avatar_persists_and_missing_file_falls_back(self):
        user = self.add()
        path = self.make_file()
        self.s.set_avatar(user, path)
        s2 = Storage(self.dir.name, clock=self.clock)
        self.assertEqual(s2.avatar_file(s2.users['alice']), path)
        os.remove(path)                                        # файл пропал с диска
        self.assertEqual(s2.avatar_file(s2.users['alice']), '')

    def test_leaderboard_contains_avatar_path(self):
        user = self.add()
        path = self.make_file()
        self.s.set_avatar(user, path)
        self.assertEqual(self.s.leaderboard()[0]['avatar'], path)

    def test_avatar_path_cannot_escape_folder(self):
        user = self.add()
        user['avatar'] = '../game_save.json'
        self.assertEqual(self.s.avatar_file(user), '')         # берётся только имя файла


class LockTests(StorageCase):
    def test_no_lock_while_money_remains(self):
        user = self.add()
        user['balance'] = 1
        self.assertIsNone(self.s.ensure_lock_state(user))
        self.assertEqual(self.s.lock_remaining(user), 0)

    def test_bankrupt_locks_for_24_hours(self):
        user = self.add()
        self.assertEqual(self.bankrupt(user), 'locked')
        self.assertEqual(self.s.lock_remaining(user), LOCK_SECONDS)
        self.clock.advance(3600)
        self.assertEqual(self.s.lock_remaining(user), LOCK_SECONDS - 3600)
        self.assertIsNone(self.s.ensure_lock_state(user))      # повторный вызов ничего не меняет
        self.assertEqual(self.s.lock_remaining(user), LOCK_SECONDS - 3600)

    def test_lock_lifts_after_24_hours_and_gives_start_money(self):
        user = self.add()
        self.bankrupt(user)
        self.clock.advance(LOCK_SECONDS - 1)
        self.assertGreater(self.s.lock_remaining(user), 0)
        self.assertIsNone(self.s.ensure_lock_state(user))
        self.assertEqual(user['balance'], 0)
        self.clock.advance(1)
        self.assertEqual(self.s.lock_remaining(user), 0)
        self.assertEqual(self.s.ensure_lock_state(user), 'unlocked')
        self.assertEqual((user['balance'], user['locked_until']), (START_BALANCE, 0))

    def test_lock_survives_restart_and_clock_keeps_running(self):
        user = self.add()
        self.bankrupt(user)
        self.clock.advance(7200)
        s2 = Storage(self.dir.name, clock=self.clock)
        self.assertEqual(s2.lock_remaining(s2.users['alice']), LOCK_SECONDS - 7200)

    def test_legacy_zero_balance_gets_locked_on_check(self):
        user = self.add()
        user['balance'] = 0                       # старый аккаунт без блокировки
        self.assertEqual(self.s.ensure_lock_state(user), 'locked')

    def test_new_bankruptcy_after_unlock_locks_again(self):
        user = self.add()
        self.bankrupt(user)
        self.clock.advance(LOCK_SECONDS)
        self.s.ensure_lock_state(user)
        self.assertEqual(self.bankrupt(user), 'locked')


class RegistrationBlockTests(StorageCase):
    def test_cannot_register_while_any_account_is_locked(self):
        a = self.add('alice')
        self.bankrupt(a)
        user, err = self.s.register('newbie', 'secret')
        self.assertEqual((user, err), (None, 'register_locked'))
        self.assertNotIn('newbie', self.s.users)
        self.assertEqual(self.s.register_block_remaining(), LOCK_SECONDS)

    def test_waits_for_the_longest_lock(self):
        a, b = self.add('alice'), self.add('bobby')
        self.bankrupt(a)
        self.clock.advance(3600)
        self.bankrupt(b)                           # у bobby блокировка закончится позже
        self.assertEqual(self.s.register_block_remaining(), LOCK_SECONDS)
        self.clock.advance(LOCK_SECONDS - 3600)    # у alice уже прошла, у bobby ещё нет
        self.assertEqual(self.s.register_block_remaining(), 3600)
        self.assertEqual(self.s.register('newbie', 'secret')[1], 'register_locked')
        self.assertEqual(self.s.lock_remaining(a), 0)           # alice разблокирована
        self.assertEqual(a['balance'], START_BALANCE)

    def test_can_register_once_all_locks_are_gone(self):
        a = self.add('alice')
        self.bankrupt(a)
        self.clock.advance(LOCK_SECONDS)
        user, err = self.s.register('newbie', 'secret')
        self.assertIsNone(err)
        self.assertEqual(user['display_name'], 'newbie')

    def test_login_to_existing_accounts_is_still_possible(self):
        a = self.add('alice')
        self.bankrupt(a)
        user, err = self.s.authenticate('alice', 'secret')
        self.assertIsNone(err)                      # войти в заблокированный аккаунт можно

    def test_no_block_without_locks(self):
        self.add('alice')
        self.assertEqual(self.s.register_block_remaining(), 0)
        self.assertIsNone(self.s.register('bobby', 'secret')[1])


class DurationTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language('russian')

    def test_format(self):
        self.assertEqual(duration_text(0), 'меньше минуты')
        self.assertEqual(duration_text(1), '1 мин')
        self.assertEqual(duration_text(3600), '1 ч')
        self.assertEqual(duration_text(86399), '24 ч')
        self.assertEqual(duration_text(5400), '1 ч 30 мин')
        i18n.set_language('english')
        self.assertEqual(duration_text(5400), '1 h 30 min')
        i18n.set_language('russian')


if __name__ == '__main__':
    unittest.main()
