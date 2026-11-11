"""Экран соревновательного стола: раунд с ботами, спец-карты, выбор жертвы, анимации."""
import random
import unittest
from types import SimpleNamespace
from unittest import mock

from core.bots import Bot
from core.competitive import SpecialCard, Table
from tests.test_ui_flow import AppCase, C, Clock, center, touch_owner
from ui.screens import competitive
from ui.widgets import SpecialCardWidget

BOT_HANDS = [('2C', '3D'), ('3C', '2D'), ('4C', '2H'), ('2S', '3H')]


def codes(cards):
    letters = {'hearts': 'H', 'diamonds': 'D', 'clubs': 'C', 'spades': 'S'}
    return [f'~{c.value}' if c.rank == 'avg' else c.rank + letters[c.suit] for c in cards]


class TableCase(AppCase):
    def setUp(self):
        super().setUp()
        self.screen_t = self.app.table_screen
        # боты без ошибок и без случайностей в решениях, чтобы сценарии были повторяемыми
        patcher = mock.patch.object(
            competitive, 'make_bot',
            lambda name, rng, bet=100: Bot(name, rng, err=0.0, rivalry=0.3, bet=bet))
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_deck(self, human=('10H', '6S'), dealer=('KD', '7S'), extras=()):
        """Колода, сданная так: у игрока карты human, у ботов BOT_HANDS, у дилера dealer,
        затем extras ('*swap' — спец-карта). «Кнопка» всегда у игрока: он ходит первым."""
        firsts = [human[0]] + [h[0] for h in BOT_HANDS] + [dealer[0]]
        seconds = [human[1]] + [h[1] for h in BOT_HANDS] + [dealer[1]]
        sequence = [C(x) for x in firsts + seconds]
        for item in extras:
            sequence.append(SpecialCard(item[1:]) if item.startswith('*') else C(item))
        sequence += [C('2D')] + [C('9D') for _ in range(40)]     # дальше боты берут быстро

        def build(table):
            table.button = 0
            table.deck = list(reversed(sequence))
        patcher = mock.patch.object(Table, 'build_deck', build)
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self, bet=100):
        self.login()
        self.app.mode = 'competitive'
        self.app.start_game(bet)
        Clock.settle()

    def advance_until(self, condition, limit=60.0):
        waited = 0.0
        while not condition():
            Clock.advance(0.05)
            waited += 0.05
            if waited > limit:
                self.fail('условие не наступило за %s с' % limit)

    def wait_request(self, kind):
        self.advance_until(lambda: self.screen_t._request is not None
                           and self.screen_t._request.kind == kind)

    def tap_zone(self, index=0):
        zones = [z for z in self.screen_t.zones if z.opacity > 0.01]
        zone = zones[index]
        zone.collide_point = lambda x, y: True          # в заглушке Kivy этого метода нет
        self.assertTrue(zone.on_touch_down(SimpleNamespace(pos=(1, 1))))

    def human_cards(self):
        return codes(self.screen_t.engine.players[0].hands[0].cards)

    def check_widgets_match_table(self):
        s = self.screen_t
        expected = {id(c) for seat in range(5) for h in s.engine.players[seat].hands
                    for c in h.cards} | {id(c) for c in s.engine.dealer.cards}
        self.assertEqual(set(s._cards), expected)


class StartAndRoundTests(TableCase):
    def test_table_opens_with_five_players_and_deals(self):
        self.fake_deck()
        self.start(bet=100)
        s = self.screen_t
        self.assertEqual(self.sm.current, 'table')
        self.assertEqual(len(s.players), 5)
        self.assertEqual(self.app.user['balance'], 900)             # ставка списана один раз
        self.wait_request('action')
        self.assertEqual(len(s._cards), 12)                         # 10 карт игроков + 2 у дилера
        self.check_widgets_match_table()
        self.assertEqual(self.human_cards(), ['10H', '6S'])
        dealer_hole = s._cards[id(s.engine.dealer.cards[1])][1]
        self.assertFalse(dealer_hole.face_up)                       # закрытая карта дилера
        self.assertEqual(s.board.text, s.players[0].name)           # на табло имя ходящего
        for key in ('hit', 'stand', 'double'):
            self.assertFalse(s.buttons[key].disabled)
        self.assertTrue(all(b.disabled for b in s.choice_buttons))

    def test_five_seats_do_not_overlap_and_fit_the_screen(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        m = s._m
        boxes = []
        for seat in m['seats']:
            boxes.append((seat['x'], seat['y'], seat['x'] + seat['w'], seat['y'] + seat['ch']))
        for a in range(5):
            x0, y0, x1, y1 = boxes[a]
            self.assertGreaterEqual(x0, 0)
            self.assertLessEqual(x1, m['W'])
            self.assertLessEqual(y1, m['H'])
            for b in range(a + 1, 5):
                bx0, by0, bx1, by1 = boxes[b]
                self.assertTrue(x1 <= bx0 or bx1 <= x0 or y1 <= by0 or by1 <= y0, (a, b))
        left = [m['seats'][1]['x'] + m['seats'][1]['w'], m['seats'][2]['x'] + m['seats'][2]['w']]
        right = [m['seats'][3]['x'], m['seats'][4]['x']]
        self.assertLess(max(left), m['dealer']['x'])                 # слева два бота, у центра дилер
        self.assertGreater(min(right), m['dealer']['x'] + m['dealer']['w'])
        self.assertEqual(m['seats'][1]['x'] < m['W'] / 2, True)
        self.assertEqual(m['seats'][3]['x'] > m['W'] / 2, True)

    def test_stand_plays_the_round_to_the_end(self):
        self.fake_deck()
        self.start(bet=100)
        s = self.screen_t
        self.wait_request('action')
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=120)
        self.assertEqual(s.result_panel.opacity, 1)
        self.assertEqual(self.app.user['balance'], s.players[0].balance)
        self.assertEqual(s.result_balance.text, f"Новый баланс: ${self.app.user['balance']}")
        hole = s._cards[id(s.engine.dealer.cards[1])][1]
        self.assertTrue(hole.face_up)                               # карта дилера открыта
        self.check_widgets_match_table()
        # у игрока 16 против 17 дилера: проигрыш ставки
        self.assertEqual(self.app.user['balance'], 900)
        self.assertEqual(s.board.text, 'ДИЛЕР')

    def test_hit_adds_a_card_and_double_charges_once_more(self):
        self.fake_deck(human=('5H', '5S'), extras=('9D',))
        self.start(bet=100)
        s = self.screen_t
        self.wait_request('action')
        s.buttons['double'].press()
        self.advance_until(lambda: len(self.human_cards()) == 3)
        self.assertEqual(self.human_cards(), ['5H', '5S', '9D'])
        self.assertEqual(self.app.user['balance'], 800)             # ставка удвоена
        self.advance_until(lambda: s._over, limit=120)
        self.assertEqual(self.app.user['balance'], 800 + 400)       # 19 против 17: выигрыш x2

    def test_new_balance_is_saved_on_leaving_midround(self):
        self.fake_deck()
        self.start(bet=100)
        s = self.screen_t
        self.wait_request('action')
        s.ask_leave()
        self.assertIsNotNone(s._leave_dialog)                       # деньги пропадут: спрашиваем
        s._leave_dialog.back_button.press()
        self.assertIsNone(s._leave_dialog)
        self.assertEqual(self.sm.current, 'table')
        s.ask_leave()
        s._leave_dialog.confirm_button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')
        self.assertEqual(self.app.user['balance'], 900)
        self.assertIsNone(s._iter)

    def test_back_key_asks_and_menu_is_direct_after_round(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        self.wait_request('action')
        self.assertTrue(self.app._on_keyboard(None, 27))
        self.assertIsNotNone(s._leave_dialog)
        self.assertTrue(self.app._on_keyboard(None, 27))            # второй раз закрывает окно
        self.assertIsNone(s._leave_dialog)
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=120)
        s.menu_button.press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'menu')                   # после раунда без вопроса

    def test_result_buttons_new_game_and_menu(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=120)
        s.result_buttons['new_game'].press()
        Clock.settle()
        self.assertEqual(self.sm.current, 'betting')
        self.assertEqual(self.app.mode, 'competitive')


class ButtonsAndLayoutTests(TableCase):
    def test_every_enabled_button_receives_the_touch(self):
        """Регрессия: невидимые отключённые кнопки выбора лежали поверх кнопок действий и
        поглощали все нажатия игрока (в Kivy отключённая кнопка поглощает касания)."""
        self.fake_deck()
        self.start()
        s = self.screen_t
        self.wait_request('action')
        for key in ('hit', 'stand', 'double'):
            self.assertFalse(s.buttons[key].disabled)
            self.assertIs(touch_owner(s, center(s.buttons[key])), s.buttons[key], key)
        self.assertTrue(all(b.x < 0 for b in s.choice_buttons))     # спрятаны за экраном

    def test_choice_buttons_receive_touches_and_actions_move_away(self):
        self.fake_deck(extras=('*swap',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('swap')
        visible = [b for b in s.choice_buttons if b.opacity > 0]
        self.assertEqual(len(visible), 2)
        for button in visible:
            self.assertIs(touch_owner(s, center(button)), button)
        self.assertTrue(all(b.x < 0 for b in s.buttons.values()))
        # два варианта стоят по центру экрана
        W = s._m['W']
        self.assertAlmostEqual((visible[0].x + visible[1].right) / 2, W / 2, delta=1)

    def test_action_buttons_are_centered_equal_and_clear_of_the_cards(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        self.wait_request('action')
        W = s._m['W']
        row = [s.buttons[key] for key in competitive.ACTION_KEYS]
        self.assertEqual(competitive.ACTION_KEYS, ('hit', 'stand', 'double', 'split', 'surrender'))
        self.assertAlmostEqual((row[0].x + row[-1].right) / 2, W / 2, delta=1)
        gaps = [row[i + 1].x - row[i].right for i in range(len(row) - 1)]
        self.assertAlmostEqual(max(gaps), min(gaps), delta=0.5)
        self.assertEqual(len({round(b.width) for b in row}), 1)
        self.assertEqual(len({round(b.y) for b in row}), 1)
        for button in row:                                           # «Меню» не мешает кнопкам действий
            self.assertTrue(s.menu_button.right <= button.x or button.right <= s.menu_button.x
                            or s.menu_button.top <= button.y or button.top <= s.menu_button.y)
        for button in row + [s.menu_button]:
            self.assertGreaterEqual(button.x, 0)
            self.assertLessEqual(button.right, W)
        human_cards_bottom = min(w.y for _, w, _ in s._cards.values()
                                 if w.x > W * 0.3 and w.y < s._m['H'] * 0.35)
        self.assertLess(row[0].top, human_cards_bottom)             # кнопки ниже карт игрока

    def test_split_button_enabled_only_for_a_pair_and_works(self):
        self.fake_deck(human=('10H', '6S'))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        self.assertTrue(s.buttons['split'].disabled)                # не пара
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=120)

    def test_split_deals_a_card_to_each_hand_and_charges_the_bet(self):
        self.fake_deck(human=('8H', '8S'))
        self.start(bet=100)
        s = self.screen_t
        self.wait_request('action')
        self.assertFalse(s.buttons['split'].disabled)
        s.buttons['split'].press()
        self.advance_until(lambda: len(s.engine.players[0].hands) == 2 and
                           all(len(h.cards) == 2 for h in s.engine.players[0].hands))
        hands = s.engine.players[0].hands
        self.assertEqual([codes(h.cards) for h in hands], [['8H', '2D'], ['8S', '9D']])
        self.assertEqual(self.app.user['balance'], 800)             # вторая ставка
        self.check_widgets_match_table()
        self.wait_request('action')                                  # ход второй руки
        self.assertTrue(s.buttons['split'].disabled)                 # сплит один раз за раунд
        self.assertIn('/2', s.board.text)                            # на табло «Имя (2/2)»
        s.buttons['stand'].press()
        self.wait_request('action')
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=200)
        self.assertEqual(self.app.user['balance'], s.players[0].balance)

    def test_top_shade_is_dark_at_the_top_and_fades_down(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        shade = s.shade
        self.assertAlmostEqual(shade.top, s._m['H'])                 # доходит до верха экрана
        self.assertAlmostEqual(shade.width, s._m['W'])
        self.assertLess(shade.y, s._m['dealer']['y'] + s._m['dealer']['ch'])   # до карт дилера
        self.assertEqual(shade.alphas[0], 0)                         # внизу прозрачно
        self.assertEqual(shade.alphas, sorted(shade.alphas))         # вверх только темнее
        self.assertGreater(shade.alphas[-1], 180)                    # сверху тёмное
        self.assertLess(s.children.index(shade), s.children.index(s.layer))  # карты поверх тени


class NamesAndFramesTests(TableCase):
    def test_names_are_centered_right_above_each_hand(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        self.wait_request('action')
        for seat, g in enumerate(s._m['seats']):
            fan_center = g['x'] + g['w'] / 2
            name = s.seat_name[seat]
            self.assertAlmostEqual(name.x + name.width / 2, fan_center, delta=0.5, msg=seat)
            self.assertGreaterEqual(name.y, g['y'] + g['ch'] - 1, seat)      # над веером
            self.assertEqual(name.halign, 'center')
            avatar = s.seat_avatar[seat]
            self.assertLessEqual(avatar.right, name.x + 1, seat)             # аватар не налезает
        dealer = s._m['dealer']
        self.assertAlmostEqual(s.dealer_label.x + s.dealer_label.width / 2,
                               dealer['x'] + dealer['w'] / 2, delta=0.5)

    def test_gold_frames_never_cover_the_buttons(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        self.wait_request('action')
        bar_top = s._m['bar_top']
        for count in range(1, 9):                                    # от одной карты до восьми
            hand = s.engine.players[0].hands[0]
            while len(hand.cards) < count:
                hand.cards.append(C('2D'))
            while len(hand.cards) > count:
                hand.cards.pop()
            x, y, w, h = s._hand_rect(0, 0)
            self.assertGreaterEqual(y, bar_top, count)
            self.assertGreater(h, 0)
        s._sync(animate=False)
        s._place_turn_box()
        buttons = list(s.buttons.values()) + [s.menu_button]
        frame = s.turn_box
        self.assertGreater(frame.opacity, 0)
        for button in buttons:
            overlap = not (frame.right <= button.x or button.right <= frame.x
                           or frame.top <= button.y or button.top <= frame.y)
            self.assertFalse(overlap, button.text)

    def test_target_zone_over_own_cards_stays_above_the_buttons(self):
        self.fake_deck(human=('5H', '6S'), extras=('*dealer',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('dealer_card')
        for zone in s.zones:
            if zone.opacity > 0.01:
                self.assertGreaterEqual(zone.y, s._m['bar_top'])
        self.tap_zone(0)
        self.advance_until(lambda: len(self.human_cards()) == 3)


class SurrenderFlowTests(TableCase):
    def test_surrender_button_gives_back_half_and_ends_the_hand(self):
        self.fake_deck(human=('10H', '6S'))
        self.start(bet=100)
        s = self.screen_t
        self.wait_request('action')
        self.assertFalse(s.buttons['surrender'].disabled)
        self.assertEqual(s.buttons['surrender'].text, 'Сдаться')
        s.buttons['surrender'].press()
        self.advance_until(lambda: s._over, limit=200)
        self.assertEqual(self.app.user['balance'], 950)              # половина ставки вернулась
        self.assertEqual(self.app.user['balance'], s.players[0].balance)
        self.assertIn('СДАЛСЯ', s.seat_info[0].text)
        self.assertIn('-$50', s.seat_info[0].text)
        self.assertEqual(s.result_label.text, 'Дилер победил!')

    def test_surrender_is_only_offered_as_the_first_action(self):
        self.fake_deck(human=('2H', '3S'))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        self.assertFalse(s.buttons['surrender'].disabled)
        s.buttons['hit'].press()
        self.wait_request('action')
        self.assertTrue(s.buttons['surrender'].disabled)             # после «взять» нельзя
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=200)

    def test_surrender_not_available_after_split(self):
        self.fake_deck(human=('8H', '8S'))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['split'].press()
        self.wait_request('action')
        self.assertTrue(s.buttons['surrender'].disabled)
        s.buttons['stand'].press()
        self.wait_request('action')
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=200)


class StyleGuardTests(unittest.TestCase):
    def test_input_text_colour_is_restored_after_the_rounded_background(self):
        """Регрессия: цвет фона поля перекрывал цвет текста, и вводимый текст был белым."""
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'ui', 'style.kv')
        with open(path, encoding='utf-8') as f:
            rule = f.read().split('<LimitedInput>:')[1].split('\n<')[0]
        self.assertIn('RoundedRectangle', rule)
        self.assertGreater(rule.index('self.foreground_color'), rule.index('RoundedRectangle'))


class SpecialResultTests(TableCase):
    def test_dealer_blackjack_ends_the_round_after_reveal(self):
        self.fake_deck(dealer=('AS', 'KD'))
        self.start(bet=100)
        s = self.screen_t
        self.advance_until(lambda: s._over, limit=30)               # никто не ходит
        hole = s._cards[id(s.engine.dealer.cards[1])][1]
        self.assertTrue(hole.face_up)
        self.assertEqual(self.app.user['balance'], 900)
        self.assertEqual(s.result_label.text, 'Дилер победил!')

    def test_player_blackjack_pays_three_to_two(self):
        self.fake_deck(human=('AH', 'KS'))
        self.start(bet=100)
        s = self.screen_t
        self.advance_until(lambda: s._over or s._request is not None, limit=200)
        self.assertEqual(s.engine.players[0].hands[0].status, 'natural')
        self.advance_until(lambda: s._over, limit=200)               # игрок не ходит: рука закончена
        self.assertEqual(self.app.user['balance'], 900 + 250)
        self.assertIn('BLACKJACK', s.seat_info[0].text)
        self.assertIn('Вы победили', s.result_label.text)

    def test_averaged_card_is_drawn_with_value_and_avg_label(self):
        self.fake_deck(human=('9H', '8S'), extras=('*average',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.advance_until(lambda: self.human_cards()[:1] == ['~9'])
        widget = s._cards[id(s.engine.players[0].hands[0].cards[0])][1]
        self.assertEqual(widget.fallback_text, '9\nAVG')            # (9+8)/2 = 8,5 -> 9


class SpecialCardFlowTests(TableCase):
    def test_big_card_grows_then_disappears(self):
        self.fake_deck(extras=('*average',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.advance_until(lambda: s._special is not None)
        card = s._special
        self.assertIsInstance(card, SpecialCardWidget)
        self.assertEqual(card.kind, 'average')
        self.assertIn('Average', s.caption.text)
        self.assertEqual(card.pos, s._m['deck'])                    # вылетает из колоды
        Clock.advance(competitive.SPECIAL_GROW + 0.1)
        big_w, big_h = s._m['big']
        self.assertAlmostEqual(card.width, big_w)                   # выросла и встала по центру
        self.assertAlmostEqual(card.height, big_h)
        self.assertAlmostEqual(card.center_x, s._m['W'] / 2)
        self.assertTrue(card.face_up)                               # перевернулась
        self.advance_until(lambda: s._special is None)
        self.advance_until(lambda: card not in s.spec_layer.children)
        self.assertEqual(self.human_cards()[0], '~8')               # Average: (10+6)/2 = 8
        self.check_widgets_match_table()

    def test_swap_with_human_choice_and_target_zones(self):
        self.fake_deck(extras=('*swap',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('swap')
        self.assertEqual([b.text for b in s.choice_buttons if b.opacity > 0],
                         ['Поменяться', 'Отказаться'])
        self.assertTrue(all(b.disabled for b in s.buttons.values()))
        s.choice_buttons[0].press()                                  # «Поменяться»
        visible = [z for z in s.zones if z.opacity > 0.01]
        self.assertEqual(len(visible), 4)                           # рамка у каждого бота
        self.assertEqual(s.caption.text, 'Выбери игрока')
        self.assertEqual([b.text for b in s.choice_buttons if b.opacity > 0], ['Назад'])
        s.choice_buttons[0].press()                                  # «Назад» к вопросу
        self.assertEqual([b.text for b in s.choice_buttons if b.opacity > 0],
                         ['Поменяться', 'Отказаться'])
        s.choice_buttons[0].press()
        self.tap_zone(0)                                             # первый бот (место 1)
        self.advance_until(lambda: len(self.human_cards()) == 3)
        self.assertEqual(self.human_cards(), ['2C', '3D', '2D'])     # чужая рука + обычная карта
        self.assertEqual(codes(s.engine.players[1].hands[0].cards)[:2], ['10H', '6S'])
        self.assertTrue(all(z.opacity <= 0.01 for z in s.zones))
        self.check_widgets_match_table()

    def test_swap_decline(self):
        self.fake_deck(extras=('*swap',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('swap')
        s.choice_buttons[1].press()
        self.advance_until(lambda: len(self.human_cards()) == 3)
        self.assertEqual(self.human_cards(), ['10H', '6S', '2D'])
        self.assertEqual(s.engine.events[-1].info, 'declined')

    def test_dealer_card_pick_by_tapping_own_card(self):
        self.fake_deck(human=('5H', '6S'), extras=('*dealer',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('dealer_card')
        self.assertEqual(s.caption.text, 'Выбери свою карту, которую отдашь дилеру')
        self.assertEqual(len([z for z in s.zones if z.opacity > 0.01]), 2)   # по рамке на карту
        self.tap_zone(1)                                             # отдаём 6S
        self.advance_until(lambda: len(self.human_cards()) == 3)
        self.assertEqual(self.human_cards(), ['5H', 'KD', '2D'])     # получили открытую карту дилера
        self.assertEqual(codes(s.engine.dealer.cards), ['6S', '7S'])
        self.check_widgets_match_table()

    def test_snc_yes_and_decline(self):
        for yes in (True, False):
            self.setUp()
            self.fake_deck(human=('5H', '5S'), extras=('*snc',))
            self.start(bet=100)
            s = self.screen_t
            self.wait_request('action')
            s.buttons['hit'].press()
            self.wait_request('snc')
            self.assertEqual(s.caption.text, 'Разделить руку на две одинаковые?')
            s.choice_buttons[0 if yes else 1].press()
            self.advance_until(lambda: len(self.human_cards()) == 3)
            hands = s.engine.players[0].hands
            self.assertEqual(len(hands), 2 if yes else 1)
            if yes:
                self.assertEqual(codes(hands[1].cards), ['5H', '5S'])
                self.assertEqual(self.app.user['balance'], 800)      # вторая ставка
                self.assertEqual(len(s._cards), 12 + 3)
            self.check_widgets_match_table()

    def test_min_other_with_target_choice(self):
        self.fake_deck(human=('3H', '2S'), extras=('*min',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('min')
        self.assertEqual([b.text for b in s.choice_buttons if b.opacity > 0],
                         ['Себе', 'Другому'])
        s.choice_buttons[1].press()
        self.assertEqual(len([z for z in s.zones if z.opacity > 0.01]), 4)
        self.tap_zone(2)                                             # третий бот (место 3)
        self.advance_until(lambda: any(e.kind == 'min' for e in s.engine.events))
        self.assertEqual(s.engine.events[-1].info, 'other')
        self.assertEqual(s.engine.events[-1].targets, (3,))
        self.advance_until(lambda: len(self.human_cards()) == 3)
        self.check_widgets_match_table()

    def test_min_self(self):
        self.fake_deck(human=('3H', '2S'), extras=('*min',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('min')
        s.choice_buttons[0].press()
        self.advance_until(lambda: len(self.human_cards()) == 4)     # копия двойки + обычная карта
        self.assertEqual(self.human_cards(), ['3H', '2S', '2S', '2D'])

    def test_one_for_all_buttons(self):
        self.fake_deck(human=('3H', '4S'), extras=('*one_for_all',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.wait_request('one_for_all')
        self.assertEqual([b.text for b in s.choice_buttons if b.opacity > 0], ['Взять', 'Хватит'])
        s.choice_buttons[0].press()                                  # все берут по карте
        self.advance_until(lambda: len(self.human_cards()) == 3)
        for seat in range(1, 5):
            self.assertGreaterEqual(len(s.engine.players[seat].hands[0].cards), 3)
        self.check_widgets_match_table()

    def test_automatic_cards_update_the_table(self):
        for special in ('troll', 'loser', 'average'):
            self.setUp()
            self.fake_deck(human=('9H', '8S'), extras=(f'*{special}',))
            self.start()
            s = self.screen_t
            self.wait_request('action')
            s.buttons['hit'].press()
            self.advance_until(lambda: any(e.kind == special for e in s.engine.events))
            self.assertEqual(s.engine.events[-1].kind, special)
            self.assertIn(SpecialCardWidget, [type(w) for w in s.spec_layer.children])
            self.advance_until(lambda: s._request is not None or s._over, limit=200)
            self.check_widgets_match_table()
            for i in range(5):
                for hand in s.engine.players[i].hands:
                    self.assertEqual(len(hand.cards) > 0, True)

    def test_loser_takes_the_biggest_card_from_bots(self):
        self.fake_deck(human=('4H', '6S'), extras=('*loser',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['hit'].press()
        self.advance_until(lambda: any(e.kind == 'loser' for e in s.engine.events))
        for seat in range(1, 5):
            self.assertEqual(len(s.engine.players[seat].hands[0].cards), 1)
        self.assertEqual(self.human_cards(), ['4H', '6S', '4C'])      # самая большая из убранных
        self.advance_until(lambda: len(self.human_cards()) == 4)
        self.assertEqual(self.human_cards(), ['4H', '6S', '4C', '2D'])
        self.check_widgets_match_table()


class BotBehaviourTests(TableCase):
    def test_think_delays_are_in_range(self):
        s = self.screen_t
        for _ in range(300):
            for kind in competitive.SPECIAL_ASKS:
                self.assertTrue(1.0 <= s._think_delay(kind) <= 3.0)
            self.assertTrue(0.6 <= s._think_delay('action') <= 1.4)

    def test_bot_waits_one_to_three_seconds_before_special_choice(self):
        # игрок встаёт, бот 1 (2C 3D) берёт карту и вытягивает Swap
        self.fake_deck(extras=('*swap',))
        self.start()
        s = self.screen_t
        self.wait_request('action')
        s.buttons['stand'].press()
        marks = {}
        original_answer = s.engine.answer

        def answer(step):
            if step.kind == 'swap':
                marks['asked'] = Clock.now
            return original_answer(step)
        s.engine.answer = answer
        original_effect = s._n_effect

        def effect(info):
            marks.setdefault('effect', Clock.now)
            return original_effect(info)
        s._n_effect = effect
        self.advance_until(lambda: 'effect' in marks, limit=120)
        waited = marks['effect'] - marks['asked']
        self.assertGreaterEqual(waited, 1.0 - 0.01)
        self.assertLessEqual(waited, 3.0 + 0.1)
        self.assertIn('думает', s.caption.text.lower() + 'думает')   # подпись показывалась

    def test_board_shows_whose_turn_it_is(self):
        self.fake_deck()
        self.start()
        s = self.screen_t
        self.wait_request('action')
        seen = [s.board.text]
        s.buttons['stand'].press()
        self.advance_until(lambda: s._over, limit=120)
        # ходили боты: имя на табло менялось, в конце — дилер
        self.assertEqual(s.board.text, 'ДИЛЕР')
        self.assertNotEqual(seen[0], 'ДИЛЕР')


class TurnBoardTests(TableCase):
    def test_name_rolls_up_like_a_drum(self):
        from ui.widgets import TurnBoard
        board = TurnBoard(size_hint=(None, None))
        board.pos = (10, 500)
        board.size = (200, 40)
        board.set_text('Макс', animate=False)
        self.assertEqual(board._front.text, 'Макс')
        self.assertEqual(board._front.y, 500)                        # стоит внутри табло
        old = board._front
        board.set_text('Лиза')
        new = board._front
        self.assertEqual(board.text, 'Лиза')
        self.assertEqual(new.text, 'Лиза')
        self.assertEqual(new.y, 500 - 40)                            # выезжает снизу
        Clock.advance(board.SPEED + 0.05)
        self.assertEqual(new.y, 500)
        self.assertEqual(old.y, 500 + 40)                            # старое уехало вверх
        board.set_text('Лиза')                                       # то же имя: ничего не меняется
        self.assertIs(board._front, new)
        board.set_text('Соня')                                       # следующее снова снизу
        self.assertEqual(board._front.y, 500 - 40)
        Clock.advance(board.SPEED + 0.05)
        self.assertEqual(board._front.y, 500)


class StressTests(TableCase):
    def auto_human(self, rng):
        s = self.screen_t
        request = s._request
        if request is None:
            return
        if request.kind == 'action':
            choice = 'hit' if rng.random() < 0.85 else 'stand'      # чаще берём: больше спец-карт
            s.buttons[choice].press()
        elif request.kind == 'dealer_card':
            if any(z.opacity > 0.01 for z in s.zones):
                self.tap_zone(0)
        else:
            zones = [z for z in s.zones if z.opacity > 0.01]
            if zones:                                                # уже выбираем жертву
                self.tap_zone(rng.randrange(len(zones)))
            else:
                buttons = [b for b in s.choice_buttons if b.opacity > 0]
                rng.choice(buttons).press()

    def test_many_random_rounds_with_human_choices(self):
        rng = random.Random(11)
        seen = set()
        self.login()
        self.app.mode = 'competitive'
        for number in range(40):
            self.screen_t.rng_factory = lambda n=number: random.Random(1000 + n)
            self.app.user['balance'] = 1000
            self.app.start_game(50)
            Clock.advance(0.5)
            waited = 0.0
            while not self.screen_t._over:
                request = self.screen_t._request
                if request is not None:
                    seen.add(request.kind)
                    self.auto_human(rng)
                Clock.advance(0.05)
                waited += 0.05
                self.assertLess(waited, 400, f'раунд {number} не закончился')
            s = self.screen_t
            self.assertEqual(self.app.user['balance'], s.players[0].balance)
            self.assertEqual(s.result_panel.opacity, 1)
            for seat in range(5):
                for hand in s.engine.players[seat].hands:
                    self.assertFalse(hand.live)
            self.app.go('menu')
            Clock.settle()
        self.assertIn('action', seen)
        specials = seen - {'action'}
        print('запросы игрока в стресс-тесте:', sorted(seen))
        self.assertGreaterEqual(len(specials), 3)             # прошли разные окна выбора


if __name__ == '__main__':
    unittest.main()
