"""Интерфейс: профиль (имя, логин, аватар), таблица, шапка игры, блокировка, выбор режима."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_ui_flow import AppCase, Clock, center, touch_owner  # noqa: E402
from tests import kivy_stub  # noqa: E402
from core.i18n import duration_text, t  # noqa: E402
from core.storage import LOCK_SECONDS, START_BALANCE  # noqa: E402
from ui import theme  # noqa: E402
from ui.widgets import AvatarImage  # noqa: E402


class ProfileCase(AppCase):
    def make_avatar_file(self, ext='.png'):
        path = self.app.storage.new_avatar_path(ext)
        with open(path, 'wb') as f:
            f.write(b'img')
        return path

    def fake_picker(self, path=None, error=None):
        """Подменяет галерею: сразу «выбирает» файл (или сообщает об ошибке)."""
        def pick(on_done, on_error):
            if error:
                on_error(error)
            else:
                on_done(path or self.make_avatar_file())
        self.app.picker.pick = pick

    def open_profile(self):
        self.login()
        self.app.go('profile')
        Clock.settle()
        return self.screen('profile')


class ProfileTests(ProfileCase):
    def test_shows_name_login_and_default_avatar(self):
        p = self.open_profile()
        self.assertEqual(p.name_label.text, 'alice')
        self.assertEqual(p.login_label.text, f"{t('login_label')}: alice")
        self.assertEqual(p.avatar.source, self.app.default_avatar)
        self.assertTrue(self.app.default_avatar.endswith(os.path.join('etc', 'default_pic.png')))
        self.assertEqual(p.login_label.color, theme.GRAY)             # логин серый
        self.assertLess(p.login_label.font_size, p.name_label.font_size)   # и мелкий

    def test_rename_through_dialog(self):
        p = self.open_profile()
        p.rename_button.press()
        dialog = p._dialog
        self.assertEqual(dialog.input.text, 'alice')                    # в окне текущее имя
        dialog.input.text = '  Алиса   Первая '
        dialog.save()
        self.assertEqual(self.app.user['display_name'], 'Алиса Первая')
        self.assertEqual(p.name_label.text, 'Алиса Первая')
        self.assertEqual(self.app.user['username'], 'alice')              # логин прежний
        self.assertFalse(dialog.is_open)
        self.assertIsNone(self.app.alert)

    def test_invalid_name_keeps_dialog_open_and_shows_alert(self):
        p = self.open_profile()
        p.rename_button.press()
        p._dialog.input.text = 'a'
        p._dialog.save()
        self.assertIsNotNone(self.app.alert)
        self.assertTrue(p._dialog.is_open)
        self.assertEqual(self.app.user['display_name'], 'alice')

    def test_login_still_works_after_rename(self):
        p = self.open_profile()
        p.rename_button.press()
        p._dialog.input.text = 'Другое Имя'
        p._dialog.save()
        user, err = self.app.storage.authenticate('alice', 'secret')
        self.assertIsNone(err)
        self.assertEqual(self.app.storage.authenticate('Другое Имя', 'secret')[1], 'user_not_found')

    def test_choose_replace_and_reset_avatar(self):
        p = self.open_profile()
        first = self.make_avatar_file()
        self.fake_picker(first)
        p.avatar_button.press()
        self.assertEqual(p.avatar.source, first)
        self.assertEqual(self.app.user['avatar'], os.path.basename(first))
        second = self.make_avatar_file('.jpg')
        self.fake_picker(second)
        p.avatar_button.press()
        self.assertEqual(p.avatar.source, second)
        self.assertFalse(os.path.exists(first))                          # старый файл удалён
        p.reset_button.press()
        self.assertEqual(p.avatar.source, self.app.default_avatar)
        self.assertFalse(os.path.exists(second))

    def test_picker_error_shows_alert_and_keeps_avatar(self):
        p = self.open_profile()
        self.fake_picker(error='boom')
        p.avatar_button.press()
        self.assertIsNotNone(self.app.alert)
        self.assertEqual(self.app.user['avatar'], '')
        self.assertEqual(p.avatar.source, self.app.default_avatar)

    def test_avatar_survives_restart(self):
        p = self.open_profile()
        path = self.make_avatar_file()
        self.fake_picker(path)
        p.avatar_button.press()
        import main
        app2 = main.BlackjackApp()
        app2._tmp = self.app.user_data_dir
        app2.build()
        self.assertEqual(app2.avatar_source(app2.user), path)


class AvatarImageTests(AppCase):
    def make_png(self, name='x.png'):
        path = os.path.join(self._data_tmp.name, name)
        with open(path, 'wb') as f:
            f.write(b'img')
        return path

    def test_missing_file_shows_grey_person(self):
        avatar = AvatarImage(size=(40, 40), source='/нет/такого.png')
        self.assertEqual(avatar._image_color.a, 0)
        self.assertEqual(avatar._person_color.a, 1)

    def test_existing_file_shows_image_in_circle(self):
        avatar = AvatarImage(size=(40, 40), source=self.make_png())
        self.assertEqual(avatar._image_color.a, 1)
        self.assertEqual(avatar._person_color.a, 0)
        self.assertEqual(avatar._ring.circle, (20, 20, 20))               # круг по размеру виджета

    def test_source_change_reloads(self):
        avatar = AvatarImage(size=(40, 40))
        self.assertEqual(avatar._image_color.a, 0)
        avatar.source = self.make_png()
        self.assertEqual(avatar._image_color.a, 1)
        avatar.source = ''
        self.assertEqual(avatar._image_color.a, 0)

    def test_circle_uses_shorter_side(self):
        avatar = AvatarImage(size=(60, 40))
        self.assertEqual(avatar._bg.size, (40, 40))

    def test_non_square_image_is_cropped_from_center(self):
        path = self.make_png('wide.png')
        kivy_stub.sys.modules['kivy.core.image'].Image.sizes[path] = (400, 200)
        avatar = AvatarImage(size=(40, 40), source=path)
        coords = avatar._image.tex_coords
        us = sorted(set(coords[0::2]))
        self.assertAlmostEqual(us[0], 0.25)       # вырезана центральная половина по ширине
        self.assertAlmostEqual(us[1], 0.75)
        self.assertEqual(sorted(set(coords[1::2])), [0, 1])


class LeaderboardUITests(ProfileCase):
    def test_rows_show_avatar_name_and_small_grey_login(self):
        self.login('alice')
        user = self.app.user
        self.app.storage.set_display_name(user, 'Королева')
        avatar = self.make_avatar_file()
        self.app.storage.set_avatar(user, avatar)
        bob, _ = self.app.storage.register('bobby', 'secret')
        self.app.go('leaderboard')
        Clock.settle()
        rows = self.screen('leaderboard').grid.children
        self.assertEqual(len(rows), 2)
        found = {}
        for row in rows:
            cell = row.children[1]
            avatar_widget, rank_icon, texts = cell.children
            self.assertTrue(rank_icon.source in ('', self.app.rank_source(1)))   # у всех 1-й ранг
            name, login = texts.children
            found[login.text] = (name.text, avatar_widget.source, login.color, login.font_size,
                                 name.font_size)
        name, source, color, small, big = found['alice']
        self.assertEqual((name, source), ('Королева', avatar))
        self.assertEqual(color, theme.GRAY)
        self.assertLess(small, big)
        self.assertEqual(found['bobby'][:2], ('bobby', self.app.default_avatar))   # без аватара — по умолчанию

    def test_no_guest_in_table(self):
        self.login()
        self.app.go('leaderboard')
        Clock.settle()
        names = [row.children[1].children[2].children[1].text
                 for row in self.screen('leaderboard').grid.children]
        self.assertNotIn('Guest', names)


class GameHudTests(ProfileCase):
    def test_game_shows_player_name_and_avatar(self):
        self.login('alice')
        self.app.storage.set_display_name(self.app.user, 'Королева')
        path = self.make_avatar_file()
        self.app.storage.set_avatar(self.app.user, path)
        self.stack('10S', '10H', '9C', '6D', '2S')
        self.app.go_betting()
        Clock.settle()
        betting = self.screen('betting')
        betting.input.type('50')
        betting.start()
        Clock.settle()
        g = self.game
        self.assertEqual(g.user_label.text, 'Королева')                    # имя, а не логин
        self.assertEqual(g.avatar.source, path)
        self.assertGreater(g.avatar.width, 0)

    def test_dataset_still_uses_login(self):
        self.login('alice')
        self.app.storage.set_display_name(self.app.user, 'Королева')
        self.stack('10S', '10H', '9C', '6D', '2S')
        self.app.go_betting()
        Clock.settle()
        self.screen('betting').input.type('50')
        self.screen('betting').start()
        Clock.settle()
        self.press('stand')
        import csv
        with open(self.app.dataset.decisions_path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]['player'], 'alice')                        # в датасете стабильный логин


class LockUITests(ProfileCase):
    def go_bankrupt(self):
        """Игрок ставит все 100 и проигрывает."""
        self.login('alice')
        self.app.user['balance'] = 100
        self.stack('10S', '10H', '6C', '7D', 'KS')
        self.app.go_betting()
        Clock.settle()
        self.screen('betting').input.type('100')
        self.screen('betting').start()
        Clock.settle()
        self.press('hit')                                   # 16 + K = перебор
        self.assertEqual(self.app.user['balance'], 0)

    def test_losing_everything_locks_for_24h_and_shows_note(self):
        self.go_bankrupt()
        user = self.app.user
        self.assertEqual(self.app.storage.lock_remaining(user), LOCK_SECONDS)
        self.assertIn(duration_text(LOCK_SECONDS), self.game.result_note.text)
        self.assertIn(t('bankrupt_note'), self.game.result_note.text)

    def test_cannot_start_new_round_while_locked(self):
        self.go_bankrupt()
        self.game.result_buttons['new_game'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'game')            # на ставку не пустило
        self.assertIsNotNone(self.app.alert)
        self.app.alert.dismiss()
        self.game.result_buttons['menu'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')
        self.screen('menu').buttons['play'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')            # и в выбор режима тоже
        self.assertIsNotNone(self.app.alert)
        self.app.alert.dismiss()
        self.app.start_game(10)                               # даже прямой вызов не списывает ставку
        self.assertEqual(self.app.user['balance'], 0)

    def test_profile_shows_lock_timer(self):
        self.go_bankrupt()
        self.app.go('profile')
        Clock.settle()
        self.assertIn(t('locked_short'), self.screen('profile').lock_label.text)
        self.clock.advance(3600)
        self.screen('profile').refresh_texts()
        self.assertIn(duration_text(LOCK_SECONDS - 3600), self.screen('profile').lock_label.text)

    def test_play_again_after_24h_with_start_money(self):
        self.go_bankrupt()
        self.game.result_buttons['menu'].press()
        Clock.settle()
        self.clock.advance(LOCK_SECONDS)
        self.screen('menu').buttons['play'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'mode')
        self.assertEqual(self.app.user['balance'], START_BALANCE)
        self.assertIsNotNone(self.app.alert)                  # «Ограничение снято»
        self.assertEqual(self.app.storage.lock_remaining(self.app.user), 0)

    def test_lock_lifts_on_login_too(self):
        self.go_bankrupt()
        self.app.logout()
        Clock.settle()
        self.clock.advance(LOCK_SECONDS + 5)
        login = self.screen('login')
        login.user_input.text, login.pass_input.text = 'alice', 'secret'
        login.submit()
        Clock.settle()
        self.assertEqual(self.app.user['balance'], START_BALANCE)
        self.assertIsNotNone(self.app.alert)

    def test_can_log_in_to_locked_account_and_browse(self):
        self.go_bankrupt()
        self.app.logout()
        Clock.settle()
        login = self.screen('login')
        login.user_input.text, login.pass_input.text = 'alice', 'secret'
        login.submit()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')
        self.app.go('leaderboard')
        Clock.settle()
        self.assertEqual(self.sm.current, 'leaderboard')

    def test_registration_blocked_while_any_account_locked(self):
        self.go_bankrupt()
        self.app.logout()
        Clock.settle()
        login = self.screen('login')
        login.switch_mode()
        login.user_input.text, login.pass_input.text = 'newbie', 'secret'
        login.submit()
        Clock.settle()
        self.assertEqual(self.sm.current, 'login')
        self.assertNotIn('newbie', self.app.storage.users)
        self.assertIsNotNone(self.app.alert)
        message = self.app.alert.children[0].children[0].text         # текст окна-предупреждения
        self.assertIn(t('register_locked'), message)
        self.assertIn(duration_text(LOCK_SECONDS), message)           # и сколько ждать
        self.app.alert.dismiss()
        # блокировка у alice закончилась — регистрация снова возможна
        self.clock.advance(LOCK_SECONDS)
        login.submit()
        Clock.settle()
        self.assertIn('newbie', self.app.storage.users)
        self.assertEqual(self.sm.current, 'menu')
        self.assertEqual(self.app.storage.display_name(self.app.user), 'newbie')

    def test_registration_free_when_nobody_is_locked(self):
        self.login('alice')
        self.app.logout()
        Clock.settle()
        login = self.screen('login')
        login.switch_mode()
        login.user_input.text, login.pass_input.text = 'newbie', 'secret'
        login.submit()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')


class ModeTests(ProfileCase):
    def test_play_opens_mode_choice(self):
        self.login()
        self.screen('menu').buttons['play'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'mode')
        mode = self.screen('mode')
        self.assertEqual(mode.single_button.text, 'Одиночная игра')
        self.assertEqual(mode.competitive_button.text, 'Соревновательный режим')

    def test_single_goes_to_betting(self):
        self.login()
        self.app.go('mode')
        Clock.settle()
        self.screen('mode').single_button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'betting')

    def test_competitive_leads_to_betting_then_table(self):
        self.login()
        self.app.go('mode')
        Clock.settle()
        button = self.screen('mode').competitive_button
        self.assertFalse(button.disabled)
        button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'betting')
        self.assertEqual(self.app.mode, 'competitive')
        self.screen('betting').start_button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'table')
        self.assertEqual(self.app.user['balance'], 1000 - self.screen('betting').bet)

    def test_single_player_resets_mode(self):
        self.login()
        self.app.go_betting('competitive')
        Clock.settle()
        self.app.go('mode')
        Clock.settle()
        self.screen('mode').single_button.press()
        Clock.settle()
        self.assertEqual(self.app.mode, 'single')

    def test_modes_are_side_by_side_with_pictures(self):
        mode = self.screen('mode')
        columns = [w for w in mode.walk()
                   if mode.single_button in w.children or mode.competitive_button in w.children]
        self.assertEqual(len(columns), 2)
        left, right = columns
        self.assertIn(mode.single_picture, left.children)             # слева одиночная игра
        self.assertIn(mode.competitive_picture, right.children)       # справа соревновательный
        self.assertIs(left.parent, right.parent)                      # столбцы в одном ряду
        self.assertEqual(left.parent.children, [left, right])

    def test_language_switch_translates_mode_names(self):
        from core.i18n import i18n
        i18n.set_language('english')
        self.screen('mode').refresh_texts()
        self.assertEqual(self.screen('mode').competitive_button.text, 'Competitive mode')
        i18n.set_language('russian')

    def test_back_chain(self):
        self.login()
        self.app.go('mode')
        Clock.settle()
        self.screen('mode').single_button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'betting')
        self.assertTrue(self.app._on_keyboard(None, 27))
        Clock.settle()
        self.assertEqual(self.sm.current, 'mode')                    # из ставки — в выбор режима
        self.assertTrue(self.app._on_keyboard(None, 27))
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')
        self.screen('mode')
        self.app.go('mode')
        Clock.settle()
        self.screen('mode').back_button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')

    def test_betting_back_button_returns_to_mode(self):
        self.login()
        self.app.go_betting()
        Clock.settle()
        self.screen('betting').back_button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'mode')

    def test_language_switch_translates_mode_screen(self):
        self.login()
        self.screen('menu').lang_button.press()
        self.app.go('mode')
        Clock.settle()
        self.assertEqual(self.screen('mode').single_button.text, 'Single player')


if __name__ == '__main__':
    unittest.main()
