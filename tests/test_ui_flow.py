"""Прогон интерфейса через заглушку Kivy (см. kivy_stub.py)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import kivy_stub  # noqa: E402

kivy_stub.install()

import core.round  # noqa: E402
from core.cards import Card, Deck  # noqa: E402
from core.i18n import i18n, t  # noqa: E402
from core.round import DEALER, INSURANCE, OVER, PLAYER  # noqa: E402
import main  # noqa: E402
from ui import theme  # noqa: E402
from tests.test_profile_lock import FakeClock  # noqa: E402

Clock = kivy_stub.Clock


def touch_owner(screen, point):
    """Кто получит нажатие в точке. Повторяет правила Kivy: слои проверяются сверху вниз,
    ОТКЛЮЧЁННЫЙ виджет поглощает нажатия в своих границах, включённая кнопка — принимает.
    Виджеты внутри панелей (без своего положения) занимают прямоугольник родителя."""
    from ui.widgets import TouchBlocker

    def inside(w):
        return w.x <= point[0] <= w.x + w.width and w.y <= point[1] <= w.y + w.height

    def walk(widget, in_rect):
        if isinstance(widget, TouchBlocker):
            return widget if widget.opacity > 0.01 else None
        if getattr(widget, 'passes_touch_when_hidden', False) and widget.opacity < 0.01:
            return None
        if widget.disabled and in_rect:
            return widget                                   # Kivy: disabled поглощает нажатие
        for child in reversed(widget.children):
            hit = walk(child, in_rect)
            if hit is not None:
                return hit
        if isinstance(widget, kivy_stub.Button) and in_rect:
            return widget
        return None

    for widget in reversed(screen.children):
        hit = walk(widget, inside(widget))
        if hit is not None:
            return hit
    return None


def center(widget):
    return (widget.x + widget.width / 2, widget.y + widget.height / 2)


def C(text):
    suits = {'H': 'hearts', 'D': 'diamonds', 'C': 'clubs', 'S': 'spades'}
    return Card(text[:-1], suits[text[-1]])


class AppCase(unittest.TestCase):
    SIZE_BEFORE = True

    def setUp(self):
        Clock.reset()
        kivy_stub.Animation.running.clear()
        kivy_stub.ScreenManager.SIZE_BEFORE_PRE_ENTER = self.SIZE_BEFORE
        i18n.set_language('russian')
        self._orig_deck = core.round.Deck
        self._data_tmp = tempfile.TemporaryDirectory()
        os.environ['BLACKJACK_DATA_DIR'] = self._data_tmp.name
        self.app = main.BlackjackApp()
        self.root = self.app.build()
        self.clock = FakeClock()
        self.app.storage._clock = self.clock          # время для блокировок управляется тестом
        Clock.settle()
        self.sm = self.app.sm
        self.game = self.app.game

    def tearDown(self):
        core.round.Deck = self._orig_deck
        os.environ.pop('BLACKJACK_DATA_DIR', None)
        self._data_tmp.cleanup()

    # ---------- помощники ----------
    def stack(self, *names):
        core.round.Deck = lambda: Deck(cards=[C(n) for n in reversed(names)])

    def login(self, name='alice'):
        user, err = self.app.storage.register(name, 'secret')
        self.assertIsNone(err)
        self.app.login_success(name)
        Clock.settle()

    def screen(self, name):
        return self.sm.screens[name]

    def start_round(self, bet=100, deck=None):
        self.login()
        if deck:
            self.stack(*deck)
        self.app.go_betting()
        Clock.settle()
        betting = self.screen('betting')
        betting.input.type(str(bet))
        betting.start()
        Clock.settle()

    def settle(self):
        Clock.settle()
        self.assertEqual(self.game._pending, 0, 'остались незавершённые анимации')

    def press(self, key):
        self.game.buttons[key].press()
        self.settle()


class FlowTests(AppCase):
    def test_starts_on_login(self):
        self.assertEqual(self.sm.current, 'login')

    def test_register_then_menu(self):
        login = self.screen('login')
        login.switch_mode()
        login.user_input.type('alice')
        login.pass_input.type('secret')
        login.submit()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')
        self.assertEqual(self.app.username, 'alice')
        self.assertEqual(self.app.storage.last_user, 'alice')

    def test_login_errors_show_alert(self):
        login = self.screen('login')
        login.user_input.type('nobody')
        login.pass_input.type('whatever')
        login.submit()
        self.assertIsNotNone(self.app.alert)
        self.assertEqual(self.sm.current, 'login')
        self.app.alert.dismiss()
        self.assertIsNone(self.app.alert)

    def test_password_toggle(self):
        login = self.screen('login')
        self.assertTrue(login.pass_input.password)
        login.toggle_password()
        self.assertFalse(login.pass_input.password)

    def test_menu_navigation_and_language(self):
        self.login()
        menu = self.screen('menu')
        self.assertEqual(menu.buttons['play'].text, 'Играть')
        menu.lang_button.press()
        self.assertEqual(menu.buttons['play'].text, 'Play')
        self.assertEqual(self.app.storage.language, 'english')
        for key, target in (('profile', 'profile'), ('leaderboard', 'leaderboard'),
                            ('skins', 'skins')):
            menu.buttons[key].press()
            Clock.settle()
            self.assertEqual(self.sm.current, target)
            self.app.go('menu')
            Clock.settle()

    def test_profile_texts(self):
        self.login()
        self.app.go('profile')
        Clock.settle()
        profile = self.screen('profile')
        self.assertEqual(profile.name_label.text, 'alice')
        self.assertIn('alice', profile.login_label.text)
        self.assertEqual(profile.rows[0].text, f"{t('balance')}: $1000")
        self.assertEqual(profile.rows[4].text, f"{t('win_rate')}: 0.0%")

    def test_leaderboard_rows(self):
        self.login()
        self.app.go('leaderboard')
        Clock.settle()
        grid = self.screen('leaderboard').grid
        self.assertEqual(len(grid.children), 1)   # только alice, гостя больше нет

    def test_skins_buy_and_select(self):
        self.login()
        user = self.app.user
        self.app.go('skins')
        Clock.settle()
        skins = self.screen('skins')
        skins.buy({'id': 'gold', 'price': 1500, 'name_key': 'skin_gold'})
        self.assertIsNotNone(self.app.alert)              # не хватает денег
        self.app.alert.dismiss()
        user['balance'] = 2000
        skins.buy({'id': 'gold', 'price': 1500, 'name_key': 'skin_gold'})
        self.assertEqual(user['balance'], 500)
        self.assertIn('gold', user['skins'])
        skins.select({'id': 'gold'})
        self.assertEqual(user['current_skin'], 'gold')

    def test_back_key(self):
        self.login()
        self.app.go('profile')
        Clock.settle()
        self.assertTrue(self.app._on_keyboard(None, 27))
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')
        self.assertFalse(self.app._on_keyboard(None, 27))   # из меню — выход
        self.assertFalse(self.app._on_keyboard(None, 13))

    def test_auto_login_on_restart(self):
        self.login()
        directory = self.app.user_data_dir
        app2 = main.BlackjackApp()
        app2._tmp = directory
        app2.build()
        self.assertEqual(app2.sm.current, 'menu')
        self.assertEqual(app2.username, 'alice')

    def test_betting_validation(self):
        self.login()
        self.app.go_betting()
        Clock.settle()
        betting = self.screen('betting')
        betting.input.type('0')
        betting.start()
        self.assertIsNotNone(self.app.alert)
        self.app.alert.dismiss()
        betting.input.text = ''
        betting.input.type('5000')
        betting.start()
        self.assertIsNotNone(self.app.alert)
        self.app.alert.dismiss()
        self.assertEqual(self.sm.current, 'betting')
        betting.chip_buttons[2][1].press()     # $100
        self.assertEqual(betting.bet, 100)


class GameFlowMixin:
    def test_stand_and_dealer_plays(self):
        # игрок 10+9, дилер 10+6 -> берёт 2 -> 18; игрок выигрывает
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        r = self.game.round
        self.assertEqual(self.sm.current, 'game')
        self.assertEqual(r.state, PLAYER)
        self.assertEqual(len(self.game._cards), 4)
        hole = self.game._cards[r.dealer.cards[1]]
        self.assertFalse(hole.face_up)
        self.assertFalse(self.game.buttons['hit'].disabled)
        self.assertFalse(self.game.buttons['menu'].disabled)
        self.assertNotIn('new_game', self.game.buttons)   # «Новая игра» — в панели результата
        self.assertEqual(self.app.user['balance'], 900)

        self.press('stand')
        self.assertEqual(r.state, OVER)
        self.assertTrue(hole.face_up)
        self.assertEqual(len(r.dealer.cards), 3)
        self.assertEqual(self.app.user['balance'], 1100)
        self.assertEqual(self.game.result_panel.opacity, 1)
        self.assertIn('100', self.game.result_label.text)       # чистый выигрыш
        self.assertTrue(self.game.buttons['hit'].disabled)
        self.assertFalse(self.game.result_buttons['new_game'].disabled)
        # прогресс сохранён на диск
        from core.storage import Storage
        self.assertEqual(Storage(self.app.user_data_dir).users['alice']['balance'], 1100)

    def test_player_blackjack(self):
        self.start_round(100, ['AS', '9H', 'KC', '7D'])
        r = self.game.round
        self.assertEqual(r.state, OVER)
        self.assertEqual(self.app.user['balance'], 900 + 250)
        self.assertEqual(self.game.result_label.text, t('player_blackjack'))
        self.assertTrue(self.game._cards[r.dealer.cards[1]].face_up)

    def test_dealer_blackjack(self):
        # у дилера туз: сначала предлагается страховка, от неё отказываемся
        self.start_round(100, ['9S', 'AH', '7C', 'KD'])
        self.assertEqual(self.game.round.state, INSURANCE)
        self.game.insurance_buttons['insurance_decline'].press()
        Clock.settle()
        self.assertEqual(self.game.round.state, OVER)
        self.assertEqual(self.app.user['balance'], 900)
        self.assertEqual(self.game.result_label.text, t('dealer_blackjack'))

    def test_dealer_blackjack_with_ten_up_has_no_insurance_offer(self):
        self.start_round(100, ['9S', 'KH', '7C', 'AD'])
        self.assertEqual(self.game.round.state, OVER)
        self.assertEqual(self.game.insurance_panel.opacity, 0)
        self.assertEqual(self.game.result_label.text, t('dealer_blackjack'))

    def test_hit_bust(self):
        self.start_round(100, ['10S', '10H', '6C', '7D', 'KS'])
        self.press('hit')
        r = self.game.round
        self.assertEqual(r.state, OVER)
        self.assertEqual(self.app.user['balance'], 900)
        self.assertEqual(self.game.result_label.text, t('dealer_wins'))
        self.assertIn('BUST', self.game.hand_labels[0].text)
        self.assertTrue(all(self.game._cards[c].dim for c in r.hands[0].cards))

    def test_double(self):
        self.start_round(100, ['5S', '9H', '6C', '8D', 'KS'])
        self.assertFalse(self.game.buttons['double'].disabled)
        self.press('double')
        r = self.game.round
        self.assertEqual(r.state, OVER)
        self.assertEqual(self.app.user['balance'], 800 + 400)
        self.assertEqual(len(self.game._cards), 5)

    def test_split_flow(self):
        self.start_round(100, ['8S', '10H', '8C', '8D', '3S', '2H', 'KC', 'QD'])
        r = self.game.round
        self.assertFalse(self.game.buttons['split'].disabled)
        self.press('split')
        self.assertEqual(len(r.hands), 2)
        self.assertEqual(len(self.game._cards), 4 + 2)
        # карты второй руки лежат во втором ряду
        row1_y = self.game._m['rows'][1][1]
        second_hand = [self.game._cards[c] for c in r.hands[1].cards]
        self.assertTrue(all(abs(w.y - row1_y) < 1 for w in second_hand))
        self.assertTrue(self.game.buttons['split'].disabled)   # повторный сплит запрещён
        self.assertEqual(self.app.user['balance'], 800)
        self.press('hit')       # рука 0: 8+3+K = 21 -> автостенд
        self.assertEqual(r.current, 1)
        self.press('hit')       # рука 1: 8+2+Q = 20
        self.press('stand')
        self.assertEqual(r.state, OVER)
        self.assertEqual(self.app.user['wins'], 2)
        self.assertEqual(self.app.user['balance'], 800 + 400)
        self.assertIn(str(self.app.user['balance']), self.game.result_label.text)

    def test_buttons_blocked_while_dealing(self):
        self.login()
        self.stack('10S', '10H', '9C', '6D', '2S')
        self.app.go_betting()
        Clock.settle()
        self.screen('betting').input.type('50')
        self.screen('betting').start()
        # раздача ещё идёт: действия игнорируются
        Clock.advance(0.3)
        self.game.do_hit()
        self.game.do_stand()
        Clock.settle()
        self.assertEqual(self.game.round.state, PLAYER)
        self.assertEqual(len(self.game.round.hands[0].cards), 2)

    def test_new_game_after_round(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        self.press('stand')
        self.game.result_buttons['new_game'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'betting')
        self.stack('AS', '9H', 'KC', '7D')
        betting = self.screen('betting')
        betting.input.type('50')
        betting.start()
        Clock.settle()
        # новый раунд начался с чистого стола
        self.assertEqual(self.sm.current, 'game')
        self.assertEqual(len(self.game._cards), 4)
        self.assertEqual(self.game.round.state, OVER)    # блэкджек

    def test_leave_mid_round_and_return(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        self.game.buttons['menu'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')
        self.assertIsNone(self.game.round)
        self.assertEqual(self.app.user['balance'], 900)   # ставка потеряна, как раньше

    def test_language_switch_in_game(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        i18n.set_language('english')
        self.game.refresh_texts()
        self.assertEqual(self.game.buttons['hit'].text, 'Hit')
        self.assertIn('Total', self.game.hand_labels[0].text)


class GameFlowSizeFirst(GameFlowMixin, AppCase):
    SIZE_BEFORE = True


class GameFlowSizeAfter(GameFlowMixin, AppCase):
    SIZE_BEFORE = False


class InsuranceSurrenderUITests(AppCase):
    def read_csv(self, name):
        import csv
        path = os.path.join(os.environ['BLACKJACK_DATA_DIR'], name)
        with open(path, newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def test_insurance_offer_panel_and_buttons(self):
        self.start_round(100, ['9S', 'AH', '7C', '5D', '2S'])
        g = self.game
        self.assertEqual(g.round.state, INSURANCE)
        self.assertEqual(g.insurance_panel.opacity, 1)
        self.assertIn(touch_owner(g, center(g.insurance_panel)), list(g.insurance_buttons.values()))
        self.assertIn('50', g.insurance_label.text)               # цена страховки
        for key in ('hit', 'stand', 'double', 'split', 'surrender'):
            self.assertTrue(g.buttons[key].disabled, key)           # пока не решили — нельзя
        g.insurance_buttons['insurance_decline'].press()
        Clock.settle()
        self.assertEqual(g.round.state, PLAYER)
        self.assertEqual(g.insurance_panel.opacity, 0)
        self.assertIsNone(touch_owner(g, center(g.insurance_panel)))   # панель убрана совсем
        self.assertFalse(g.buttons['hit'].disabled)
        self.assertFalse(g.buttons['surrender'].disabled)

    def test_insurance_pays_when_dealer_has_blackjack(self):
        self.start_round(100, ['9S', 'AH', '7C', 'KD'])
        self.game.insurance_buttons['insurance_take'].press()
        Clock.settle()
        r = self.game.round
        self.assertEqual(r.state, OVER)
        self.assertEqual(self.app.user['balance'], 1000)           # вышли «в ноль»
        self.assertEqual(self.game.result_label.text, t('dealer_blackjack_insured') + '100')
        self.assertIn('+$100', self.game.result_balance.text)
        self.assertTrue(self.game._cards[r.dealer.cards[1]].face_up)

    def test_lost_insurance_shown_in_result(self):
        self.start_round(100, ['10S', 'AH', '9C', '6D', '2S'])
        self.game.insurance_buttons['insurance_take'].press()
        Clock.settle()
        self.assertEqual(self.app.user['balance'], 850)
        self.press('stand')
        self.assertEqual(self.game.round.state, OVER)
        self.assertIn('-$50', self.game.result_balance.text)

    def test_surrender_button(self):
        self.start_round(100, ['10S', '10H', '6C', '7D'])
        g = self.game
        self.assertFalse(g.buttons['surrender'].disabled)
        self.press('surrender')
        self.assertEqual(g.round.state, OVER)
        self.assertEqual(self.app.user['balance'], 950)
        self.assertEqual(g.result_label.text, t('surrendered') + '50')
        self.assertEqual(g.result_panel.opacity, 1)

    def test_surrender_disabled_after_hit(self):
        self.start_round(100, ['5S', '10H', '6C', '7D', '2S'])
        self.press('hit')
        self.assertTrue(self.game.buttons['surrender'].disabled)

    # ---- регрессия: кнопки страховки должны получать нажатия ----
    def test_insurance_buttons_receive_touches(self):
        self.start_round(100, ['9S', 'AH', '7C', '5D', '2S'])
        g = self.game
        self.assertEqual(g.round.state, INSURANCE)
        owner = touch_owner(g, center(g.insurance_panel))
        self.assertIn(owner, list(g.insurance_buttons.values()),
                      'нажатие по панели страховки перехватил другой слой: %r' % owner)
        self.assertFalse(owner.disabled)

    def test_hidden_panels_do_not_swallow_touches(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])     # идёт ход игрока
        g = self.game
        self.assertIsNone(touch_owner(g, center(g.result_panel)))
        self.assertIsNone(touch_owner(g, center(g.insurance_panel)))

    def test_result_buttons_receive_touches(self):
        self.start_round(100, ['AS', '9H', 'KC', '7D'])               # блэкджек, раунд окончен
        g = self.game
        owner = touch_owner(g, center(g.result_panel))
        self.assertIn(owner, list(g.result_buttons.values()))

    def test_bottom_buttons_receive_touches_when_enabled(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        g = self.game
        for key, button in g.buttons.items():
            if not button.disabled:
                self.assertIs(touch_owner(g, center(button)), button, key)

    def test_dataset_location_rules(self):
        saved = os.environ.pop('BLACKJACK_DATA_DIR')
        try:
            self.assertEqual(self.app._dataset_dir(), os.path.join(main.BASE_DIR, 'data'))   # ПК
            main.ANDROID = True
            self.assertEqual(self.app._dataset_dir(), self.app.user_data_dir)               # телефон
        finally:
            main.ANDROID = False
            os.environ['BLACKJACK_DATA_DIR'] = saved
        self.assertEqual(self.app._dataset_dir(), saved)                    # явная папка главнее

    def test_profile_shows_how_much_is_recorded(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        self.press('stand')
        self.app.go('profile')
        Clock.settle()
        self.assertIn('1 / 1', self.screen('profile').dataset_label.text)

    def test_decisions_are_written_after_round(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        self.press('stand')
        rows = self.read_csv('blackjack_decisions_v1.csv')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['action'], rows[0]['player'], rows[0]['player_total'],
                          rows[0]['dealer_up'], rows[0]['round_result'], rows[0]['round_net']),
                         ('stand', 'alice', '19', '10', 'win', '100'))
        self.assertEqual(len(self.read_csv('blackjack_rounds_v1.csv')), 1)

    def test_insurance_and_hit_recorded_in_order(self):
        self.start_round(100, ['5S', 'AH', '6C', '9D', 'KS'])
        self.game.insurance_buttons['insurance_decline'].press()
        Clock.settle()
        self.press('hit')                                         # 5+6+K = 21 -> автостенд
        rows = self.read_csv('blackjack_decisions_v1.csv')
        self.assertEqual([r['action'] for r in rows], ['no_insurance', 'hit'])
        self.assertEqual([r['decision_idx'] for r in rows], ['0', '1'])

    def test_abandoned_round_is_not_recorded(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        self.game.buttons['menu'].press()                          # ушли посреди раунда
        Clock.settle()
        path = os.path.join(os.environ['BLACKJACK_DATA_DIR'], 'blackjack_decisions_v1.csv')
        self.assertFalse(os.path.exists(path))

    def test_language_switch_translates_new_buttons(self):
        self.start_round(100, ['9S', 'AH', '7C', '5D', '2S'])
        i18n.set_language('english')
        self.game.refresh_texts()
        self.assertEqual(self.game.buttons['surrender'].text, 'Surrender')
        self.assertEqual(self.game.insurance_buttons['insurance_take'].text, 'Insure')


class OverlayAndLayoutTests(AppCase):
    def test_transition_overlay_is_top_layer_and_blocks_touches(self):
        self.login()
        # затемнение — последний (то есть самый верхний) слой корневого виджета
        self.assertIs(self.root.children[-1], self.app.fade)
        self.assertEqual(self.app.fade.opacity, 0)
        self.assertFalse(self.app.fade.on_touch_down(None))      # не мешает, пока невидимо

        self.app.go('profile')
        Clock.advance(theme.FADE_IN + 0.01)
        self.assertEqual(self.app.fade.opacity, theme.FADE_PEAK)   # в пике всё затемнено
        self.assertEqual(self.sm.current, 'profile')               # экран сменился под завесой
        self.assertTrue(self.app.fade.on_touch_down(None))         # и нажатия заблокированы
        Clock.settle()
        self.assertEqual(self.app.fade.opacity, 0)
        self.assertFalse(self.app._fading)

    def test_go_during_fade_retargets(self):
        self.login()
        self.app.go('profile')
        self.app.go('skins')
        Clock.settle()
        self.assertEqual(self.sm.current, 'skins')

    def test_double_tap_start_does_not_charge_twice(self):
        self.login()
        self.stack('10S', '10H', '9C', '6D', '2S')
        self.app.go_betting()
        Clock.settle()
        betting = self.screen('betting')
        betting.input.type('100')
        betting.start()
        betting.start()
        Clock.settle()
        self.assertEqual(self.app.user['balance'], 900)

    def test_result_dim_covers_bottom_buttons(self):
        self.start_round(100, ['AS', '9H', 'KC', '7D'])          # блэкджек, раунд окончен
        order = self.game.children
        for button in self.game.buttons.values():
            self.assertGreater(order.index(self.game.dim), order.index(button))
        self.assertGreater(order.index(self.game.result_panel), order.index(self.game.dim))
        self.assertTrue(self.game.dim.on_touch_down(None))         # затемнение перехватывает
        self.assertIn(touch_owner(self.game, center(self.game.result_panel)),
                      list(self.game.result_buttons.values()))

    def test_hidden_result_panel_cannot_be_pressed(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        self.assertEqual(self.game.result_panel.opacity, 0)
        self.assertIsNone(touch_owner(self.game, center(self.game.result_panel)))
        self.assertFalse(self.game.dim.on_touch_down(None))

    def test_left_edges_are_aligned(self):
        self.start_round(100, ['10S', '10H', '9C', '6D', '2S'])
        x0 = self.game._m['x0']
        self.assertEqual(self.game.dealer_label.x, x0)
        self.assertEqual(self.game.hand_labels[0].x, x0)
        # правый край подписи с балансом совпадает с правым краем нижних кнопок
        right_label = self.game.info_label.x + self.game.info_label.width
        last = self.game.buttons['menu']
        self.assertAlmostEqual(right_label, last.x + last.width, delta=self.game.width * 0.01)

    def test_panels_have_same_width(self):
        for name in ('login', 'menu', 'skins', 'betting', 'mode'):
            self.assertEqual(self.screen(name).children[0].size_hint[0], theme.PANEL_W, name)
        for name in ('profile', 'leaderboard'):      # экраны с таблицей/двумя колонками шире
            self.assertEqual(self.screen(name).children[0].size_hint[0], theme.WIDE_PANEL_W, name)


class SoftTotalTests(AppCase):
    def test_total_changes_only_when_card_lands_and_soft_is_labelled(self):
        # игрок A+9 = мягкие 20; берёт 5 -> жёсткие 15
        self.start_round(100, ['AS', '10H', '9C', '6D', '5S'])
        label = self.game.hand_labels[0]
        self.assertIn('20', label.text)
        self.assertIn(t('soft'), label.text)

        self.game.buttons['hit'].press()          # карта ещё в полёте
        self.assertIn('20', label.text)           # число не прыгает раньше времени
        self.assertIn(t('soft'), label.text)
        Clock.settle()
        self.assertIn('15', label.text)           # карта легла — сумма обновилась
        self.assertNotIn(t('soft'), label.text)   # рука стала жёсткой

    def test_dealer_visible_then_total(self):
        self.start_round(100, ['10S', 'AH', '9C', '6D', '2S'])
        self.assertIn(f"{t('visible')}: 11", self.game.dealer_label.text)   # туз виден как 11
        self.game.insurance_buttons['insurance_decline'].press()
        Clock.settle()
        self.press('stand')
        self.assertIn(t('total'), self.game.dealer_label.text)

    def test_double_bust_hand_is_dimmed(self):
        self.start_round(100, ['6S', '9H', '6C', '8D', 'KS'])
        self.press('double')
        hand = self.game.round.hands[0]
        self.assertGreater(hand.value, 21)
        self.assertTrue(all(self.game._cards[c].dim for c in hand.cards))


class BackgroundTests(AppCase):
    def test_particles_toggle(self):
        bg = self.app.background
        self.assertTrue(bg._animated)
        before = [(p['x'], p['y']) for p in bg._particles]
        Clock.advance(1.0)
        after = [(p['x'], p['y']) for p in bg._particles]
        self.assertNotEqual(before, after)
        bg.set_animated(False)
        self.assertFalse(bg._group_added)
        frozen = [(p['x'], p['y']) for p in bg._particles]
        Clock.advance(1.0)
        self.assertEqual(frozen, [(p['x'], p['y']) for p in bg._particles])
        bg.set_animated(True)
        self.assertTrue(bg._group_added)

    def test_game_screen_pauses_particles(self):
        self.login()
        self.app.go_betting()
        Clock.settle()
        self.assertTrue(self.app.background._animated)
        self.screen('betting').input.type('50')
        self.screen('betting').start()
        Clock.settle()
        self.assertFalse(self.app.background._animated)   # на столе частиц нет
        self.game.buttons['menu'].press()
        Clock.settle()
        self.assertTrue(self.app.background._animated)


if __name__ == '__main__':
    unittest.main()
