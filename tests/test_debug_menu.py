"""Отладочное меню: функции core.debug_tools и окно DebugMenu."""
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from core import debug_tools
from core.storage import HASH_PREFIX, START_BALANCE, Storage
from tests.test_ui_flow import AppCase


class DebugToolsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.now = 1_000_000.0
        self.s = Storage(self.dir.name, clock=lambda: self.now)
        self.s.register('alice', 'secret')

    def test_hashed_password_cannot_be_read(self):
        info = debug_tools.describe_account(self.s, 'alice')
        self.assertIsNone(info['password'])
        self.assertTrue(self.s.users['alice']['password'].startswith(HASH_PREFIX))

    def test_legacy_plain_password_is_shown(self):
        self.s.users['alice']['password'] = 'oldpass'
        self.assertEqual(debug_tools.describe_account(self.s, 'alice')['password'], 'oldpass')

    def test_set_password_then_login(self):
        self.assertIsNotNone(debug_tools.set_password(self.s, 'alice', 'ab'))     # слишком короткий
        self.assertIsNone(debug_tools.set_password(self.s, 'alice', 'newpass'))
        user, error = self.s.authenticate('alice', 'newpass')
        self.assertIsNone(error)
        _, error = self.s.authenticate('alice', 'secret')
        self.assertIsNotNone(error)

    def test_set_balance_validation(self):
        self.assertEqual(debug_tools.set_balance(self.s, 'alice', '5000'), (5000, None))
        self.assertEqual(self.s.users['alice']['balance'], 5000)
        for bad in ('abc', '', '-5', str(debug_tools.MAX_BALANCE + 1), '1.5'):
            amount, error = debug_tools.set_balance(self.s, 'alice', bad)
            self.assertIsNone(amount, bad)
            self.assertTrue(error, bad)
        self.assertEqual(self.s.users['alice']['balance'], 5000)

    def test_zero_balance_locks_and_unlock_gives_start_money(self):
        debug_tools.set_balance(self.s, 'alice', '0')
        self.assertGreater(self.s.lock_remaining(self.s.users['alice']), 0)
        debug_tools.unlock_account(self.s, 'alice')
        user = self.s.users['alice']
        self.assertEqual(self.s.lock_remaining(user), 0)
        self.assertEqual(user['balance'], START_BALANCE)
        self.assertIsNone(self.s.ensure_lock_state(user))         # заново не блокируется

    def test_unlock_keeps_existing_balance(self):
        user = self.s.users['alice']
        user['balance'] = 300
        user['locked_until'] = self.now + 1000
        debug_tools.unlock_account(self.s, 'alice')
        self.assertEqual((user['balance'], user['locked_until']), (300, 0))

    def test_zip_contains_csv_files(self):
        a = os.path.join(self.dir.name, 'a.csv')
        b = os.path.join(self.dir.name, 'b.csv')
        with open(a, 'w') as f:
            f.write('x\n1\n')
        with open(b, 'w') as f:
            f.write('y\n2\n')
        out = os.path.join(self.dir.name, 'out')
        path = debug_tools.make_dataset_zip([a, b, os.path.join(self.dir.name, 'none.csv')], out)
        self.assertTrue(path.endswith('.zip'))
        with zipfile.ZipFile(path) as z:
            self.assertEqual(sorted(z.namelist()), ['a.csv', 'b.csv'])
            self.assertEqual(z.read('a.csv'), b'x\n1\n')

    def test_zip_without_data_raises(self):
        with self.assertRaises(ValueError):
            debug_tools.make_dataset_zip([os.path.join(self.dir.name, 'none.csv')], self.dir.name)


class DebugMenuUITests(AppCase):
    def test_button_exists_and_tap_opens_menu(self):
        from ui.debug_menu import DebugButton
        buttons = [w for w in self.root.children if isinstance(w, DebugButton)]
        self.assertEqual(len(buttons), 1)
        self.assertIs(self.root.children[-1], self.app.fade)       # завеса осталась сверху
        self.assertIsNone(self.app.debug_menu)
        self.app.open_debug_menu()
        self.assertIsNotNone(self.app.debug_menu)
        self.app.debug_menu.dismiss()
        self.assertIsNone(self.app.debug_menu)

    def test_drag_moves_circle_and_tap_opens(self):
        from types import SimpleNamespace
        from ui.debug_menu import DebugButton
        button = [w for w in self.root.children if isinstance(w, DebugButton)][0]

        def touch(x, y, dx=0, dy=0):
            return SimpleNamespace(pos=(x, y), dx=dx, dy=dy, grab_current=button,
                                   grab=lambda w: None, ungrab=lambda w: None)
        self.root.width, self.root.height = 800, 400          # размер «экрана» для границ
        button.pos = (100, 100)
        button.collide_point = lambda x, y: True     # в заглушке Kivy этого метода нет
        t = touch(110, 110)
        self.assertTrue(button.on_touch_down(t))
        button.on_touch_move(touch(110, 110, dx=60, dy=30))
        self.assertEqual(button.pos, (160, 130))
        button.on_touch_up(t)
        self.assertIsNone(self.app.debug_menu)                        # перетащили, меню не открылось
        button.on_touch_move(touch(0, 0, dx=-5000, dy=-5000))
        self.assertEqual(button.pos, (0, 0))                          # за край не уходит
        button.pos = (160, 130)
        t = touch(170, 140)
        button.on_touch_down(t)
        button.on_touch_up(t)
        self.assertIsNotNone(self.app.debug_menu)                     # тап открыл меню
        self.app.debug_menu.dismiss()

    def test_menu_actions(self):
        self.login()
        self.app.open_debug_menu()
        menu = self.app.debug_menu
        name = self.app.username
        self.assertEqual(menu.selected, name)
        self.assertIn(f'Логин: {name}', menu.info_label.text)
        self.assertIn('хэшем', menu.info_label.text)

        menu.balance_input.text = '4321'
        menu.balance_button.press()
        self.assertEqual(self.app.user['balance'], 4321)
        self.assertIn('$4321', menu.info_label.text)

        self.app.user['locked_until'] = self.app.storage.now() + 500
        menu._refresh()
        self.assertIn('(блок)', menu.accounts_box.children[0].text)
        menu.unlock_button.press()
        self.assertEqual(self.app.storage.lock_remaining(self.app.user), 0)

        menu.balance_input.text = 'abc'
        menu.balance_button.press()
        self.assertEqual(self.app.user['balance'], 4321)              # ошибка не меняет баланс
        menu.dismiss()

    def test_zip_button_saves_to_downloads(self):
        self.login()
        with open(self.app.dataset.decisions_path, 'w', encoding='utf-8') as f:
            f.write('a,b\n1,2\n')
        self.app.open_debug_menu()
        menu = self.app.debug_menu
        saved = {}

        def fake_save(path):
            saved['names'] = zipfile.ZipFile(path).namelist()
            return 'Загрузки/test.zip'
        with mock.patch('ui.debug_menu.save_to_downloads', fake_save):
            menu.zip_button.press()
        self.assertEqual(saved['names'], [os.path.basename(self.app.dataset.decisions_path)])
        self.assertIn('Готово', menu.status.text)
        leftovers = [n for n in os.listdir(os.path.dirname(self.app.dataset.decisions_path))
                     if n.endswith('.zip')]
        self.assertEqual(leftovers, [])                              # временный архив удалён
        menu.dismiss()

    def test_zip_without_data_shows_error(self):
        self.login()
        for p in (self.app.dataset.decisions_path, self.app.dataset.rounds_path):
            if os.path.exists(p):
                os.remove(p)
        self.app.open_debug_menu()
        self.app.debug_menu.zip_button.press()
        self.assertIn('Ошибка', self.app.debug_menu.status.text)
        self.app.debug_menu.dismiss()


if __name__ == '__main__':
    unittest.main()
