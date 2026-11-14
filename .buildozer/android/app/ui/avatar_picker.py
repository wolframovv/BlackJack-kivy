"""Выбор аватара из галереи.

Android: системное окно выбора картинки (ACTION_GET_CONTENT) — разрешения не нужны.
Картинка читается, обрезается до квадрата по центру, поворачивается по EXIF и
уменьшается до 256x256 прямо в Java (BitmapFactory), поэтому большие фото не занимают память.

ПК (для разработки): обычный выбор файла, файл копируется как есть (до 10 МБ).
"""
import os
import shutil

from kivy.clock import Clock
from kivy.metrics import sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView

from core.i18n import t
from . import theme
from .widgets import Lbl, Panel, StyledButton

ANDROID = 'ANDROID_ARGUMENT' in os.environ
REQUEST_CODE = 7421
AVATAR_SIZE = 256
MAX_DESKTOP_BYTES = 10 * 1024 * 1024
IMAGE_FILTERS = ['*.png', '*.jpg', '*.jpeg', '*.bmp', '*.webp',
                 '*.PNG', '*.JPG', '*.JPEG', '*.BMP', '*.WEBP']


def save_picked_image(uri, dest_path, size=AVATAR_SIZE):
    """Android: читает картинку по uri и сохраняет квадратный JPEG size×size в dest_path."""
    from jnius import autoclass, cast

    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    BitmapFactory = autoclass('android.graphics.BitmapFactory')
    Options = autoclass('android.graphics.BitmapFactory$Options')
    Bitmap = autoclass('android.graphics.Bitmap')
    CompressFormat = autoclass('android.graphics.Bitmap$CompressFormat')
    Matrix = autoclass('android.graphics.Matrix')
    ExifInterface = autoclass('android.media.ExifInterface')
    FileOutputStream = autoclass('java.io.FileOutputStream')

    resolver = PythonActivity.mActivity.getContentResolver()

    # 1) только размеры, без загрузки пикселей
    bounds = Options()
    bounds.inJustDecodeBounds = True
    stream = resolver.openInputStream(uri)
    BitmapFactory.decodeStream(stream, None, bounds)
    stream.close()
    width, height = bounds.outWidth, bounds.outHeight
    if width <= 0 or height <= 0:
        raise ValueError('это не картинка')

    # 2) читаем уменьшенной в 2, 4, 8... раза (короткая сторона остаётся не меньше size)
    sample = 1
    while min(width, height) // (sample * 2) >= size:
        sample *= 2
    options = Options()
    options.inSampleSize = sample
    stream = resolver.openInputStream(uri)
    bitmap = BitmapFactory.decodeStream(stream, None, options)
    stream.close()
    if bitmap is None:
        raise ValueError('не удалось прочитать картинку')

    # 3) поворот по EXIF (фото с камеры часто хранятся «на боку»)
    degrees = 0
    try:
        stream = resolver.openInputStream(uri)
        exif = ExifInterface(stream)
        orientation = exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, 1)
        stream.close()
        degrees = {6: 90, 3: 180, 8: 270}.get(orientation, 0)
    except Exception:
        pass

    # 4) квадрат по центру, поворот, масштаб, сохранение
    w, h = bitmap.getWidth(), bitmap.getHeight()
    side = min(w, h)
    matrix = Matrix()
    if degrees:
        matrix.postRotate(float(degrees))
    square = Bitmap.createBitmap(bitmap, (w - side) // 2, (h - side) // 2, side, side,
                                 matrix, True)
    scaled = Bitmap.createScaledBitmap(square, size, size, True)
    out = FileOutputStream(dest_path)
    scaled.compress(CompressFormat.JPEG, 90, out)
    out.flush()
    out.close()


def import_desktop_file(src, dest_path):
    """ПК: копирует выбранный файл (с проверкой размера)."""
    if os.path.getsize(src) > MAX_DESKTOP_BYTES:
        raise ValueError(t('avatar_too_big'))
    shutil.copyfile(src, dest_path)


class AvatarPicker:
    def __init__(self, app):
        self.app = app

    def pick(self, on_done, on_error):
        """Запускает выбор. on_done(путь_к_файлу) или on_error(текст) вызываются в потоке Kivy."""
        try:
            if ANDROID:
                self._pick_android(on_done, on_error)
            else:
                self._pick_desktop(on_done, on_error)
        except Exception as error:      # не должны ронять игру из-за галереи
            on_error(str(error) or t('avatar_failed'))

    # ---------- Android ----------
    def _pick_android(self, on_done, on_error):
        from android import activity
        from jnius import autoclass, cast

        Intent = autoclass('android.content.Intent')
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        dest = self.app.storage.new_avatar_path('.jpg')

        def finish_ok(dt, path=dest):
            on_done(path)

        def process(uri):
            try:
                save_picked_image(uri, dest)
            except Exception as error:
                try:
                    os.remove(dest)               # не оставляем недописанный файл
                except OSError:
                    pass
                message = f"{t('avatar_failed')}: {error}"
                Clock.schedule_once(lambda dt: on_error(message))
                return
            Clock.schedule_once(finish_ok)

        def on_result(request_code, result_code, intent):
            if request_code != REQUEST_CODE:
                return
            activity.unbind(on_activity_result=on_result)
            if result_code != -1 or intent is None:      # -1 == RESULT_OK; иначе отмена
                return
            uri = intent.getData()
            if uri is None:
                Clock.schedule_once(lambda dt: on_error(t('avatar_failed')))
                return
            Clock.schedule_once(lambda dt: process(uri))  # обработка уже в потоке Kivy

        activity.bind(on_activity_result=on_result)
        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.setType('image/*')
        intent.addCategory(Intent.CATEGORY_OPENABLE)

        String = autoclass('java.lang.String')
        title = cast('java.lang.CharSequence', String(t('choose_image')))
        PythonActivity.mActivity.startActivityForResult(
        Intent.createChooser(intent, title), REQUEST_CODE)

    # ---------- ПК ----------
    def _pick_desktop(self, on_done, on_error):
        from kivy.uix.filechooser import FileChooserIconView

        start = os.path.expanduser('~/Pictures')
        if not os.path.isdir(start):
            start = os.path.expanduser('~')
        chooser = FileChooserIconView(path=start, filters=IMAGE_FILTERS)

        view = ModalView(size_hint=(0.9, 0.9), auto_dismiss=True, background='',
                         background_color=(0, 0, 0, 0), overlay_color=(0, 0, 0, 0.65))
        panel = Panel()
        panel.add_widget(Lbl(text=t('choose_image'), size_hint_y=None, height=theme.BUTTON_H,
                             font_size=sp(22), color=theme.GOLD))
        panel.add_widget(chooser)
        row = BoxLayout(size_hint_y=None, height=theme.BUTTON_H, spacing=theme.SPACING)

        def choose(*args):
            if not chooser.selection:
                return
            source = chooser.selection[0]
            view.dismiss()
            ext = os.path.splitext(source)[1] or '.png'
            dest = self.app.storage.new_avatar_path(ext)
            try:
                import_desktop_file(source, dest)
            except Exception as error:
                on_error(str(error) or t('avatar_failed'))
                return
            on_done(dest)

        row.add_widget(StyledButton(text=t('save'), on_release=choose))
        row.add_widget(StyledButton(text=t('cancel'), base_color=theme.DARK_GRAY,
                                    down_color=theme.GRAY,
                                    on_release=lambda *a: view.dismiss()))
        panel.add_widget(row)
        view.add_widget(panel)
        view.open()
