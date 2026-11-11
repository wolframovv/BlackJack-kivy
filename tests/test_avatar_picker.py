"""Выбор аватара: код Android проверяется на поддельных jnius/android (логика, а не API)."""
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_ui_flow import AppCase, Clock  # noqa: E402
from ui import avatar_picker  # noqa: E402


class FakeAndroid:
    """Поддельные классы Android; запоминает вызовы, чтобы тест мог их проверить."""

    def __init__(self, width=4000, height=3000, orientation=1, decode_ok=True, exif_fails=False):
        self.width, self.height = width, height
        self.orientation, self.decode_ok, self.exif_fails = orientation, decode_ok, exif_fails
        self.option_objects = []
        self.bitmap = mock.MagicMock(name='bitmap')
        self.bitmap.getWidth.return_value = max(1, width // 8)
        self.bitmap.getHeight.return_value = max(1, height // 8)
        self.matrix = mock.MagicMock(name='matrix')
        self.square, self.scaled = mock.MagicMock(name='square'), mock.MagicMock(name='scaled')
        self.out = mock.MagicMock(name='out')
        self.streams = []

        fake = self

        def new_options():
            options = SimpleNamespace(outWidth=fake.width, outHeight=fake.height,
                                      inJustDecodeBounds=False, inSampleSize=1)
            fake.option_objects.append(options)
            return options

        def decode(stream, rect, options):
            return None if options.inJustDecodeBounds or not fake.decode_ok else fake.bitmap

        def exif_factory(stream):
            if fake.exif_fails:
                raise OSError('нет EXIF')
            exif = mock.MagicMock()
            exif.getAttributeInt.return_value = fake.orientation
            return exif

        self.Options = mock.MagicMock(side_effect=new_options)
        self.BitmapFactory = mock.MagicMock()
        self.BitmapFactory.decodeStream.side_effect = decode
        self.Bitmap = mock.MagicMock()
        self.Bitmap.createBitmap.return_value = self.square
        self.Bitmap.createScaledBitmap.return_value = self.scaled
        self.CompressFormat = mock.MagicMock()
        self.Matrix = mock.MagicMock(return_value=self.matrix)
        self.ExifInterface = mock.MagicMock(side_effect=exif_factory)
        self.ExifInterface.TAG_ORIENTATION = 'Orientation'
        self.FileOutputStream = mock.MagicMock(return_value=self.out)
        self.resolver = mock.MagicMock()
        self.resolver.openInputStream.side_effect = lambda uri: self.streams.append(
            mock.MagicMock()) or self.streams[-1]
        self.activity = mock.MagicMock()
        self.activity.mActivity.getContentResolver.return_value = self.resolver
        self.Intent = mock.MagicMock()
        self.PythonActivity = self.activity

    def autoclass(self, name):
        return {
            'org.kivy.android.PythonActivity': self.PythonActivity,
            'android.graphics.BitmapFactory': self.BitmapFactory,
            'android.graphics.BitmapFactory$Options': self.Options,
            'android.graphics.Bitmap': self.Bitmap,
            'android.graphics.Bitmap$CompressFormat': self.CompressFormat,
            'android.graphics.Matrix': self.Matrix,
            'android.media.ExifInterface': self.ExifInterface,
            'java.io.FileOutputStream': self.FileOutputStream,
            'android.content.Intent': self.Intent,
        }[name]

    def modules(self):
        jnius = types.ModuleType('jnius')
        jnius.autoclass = self.autoclass
        android = types.ModuleType('android')
        android.activity = mock.MagicMock(name='android.activity')
        self.android_activity = android.activity
        return {'jnius': jnius, 'android': android}


class SavePickedImageTests(unittest.TestCase):
    def run_save(self, **kwargs):
        fake = FakeAndroid(**kwargs)
        with mock.patch.dict(sys.modules, fake.modules()):
            avatar_picker.save_picked_image('content://uri', '/tmp/avatar.jpg')
        return fake

    def test_large_photo_is_downsampled_cropped_and_saved(self):
        fake = self.run_save(width=4000, height=3000)
        self.assertEqual(fake.option_objects[0].inJustDecodeBounds, True)     # сначала только размеры
        self.assertEqual(fake.option_objects[1].inSampleSize, 8)               # 3000 → 375 ≥ 256
        w, h = fake.bitmap.getWidth(), fake.bitmap.getHeight()                 # 500 × 375
        fake.Bitmap.createBitmap.assert_called_once_with(
            fake.bitmap, (w - h) // 2, 0, 375, 375, fake.matrix, True)         # квадрат по центру
        fake.Bitmap.createScaledBitmap.assert_called_once_with(fake.square, 256, 256, True)
        fake.scaled.compress.assert_called_once_with(fake.CompressFormat.JPEG, 90, fake.out)
        fake.FileOutputStream.assert_called_once_with('/tmp/avatar.jpg')
        fake.out.close.assert_called_once()
        for stream in fake.streams:                                            # потоки закрыты
            stream.close.assert_called()

    def test_small_image_is_not_downsampled(self):
        fake = self.run_save(width=300, height=300)
        self.assertEqual(fake.option_objects[1].inSampleSize, 1)

    def test_exif_rotation_applied(self):
        for orientation, degrees in ((6, 90.0), (3, 180.0), (8, 270.0)):
            fake = self.run_save(orientation=orientation)
            fake.matrix.postRotate.assert_called_once_with(degrees)

    def test_no_rotation_for_normal_or_unreadable_exif(self):
        self.run_save(orientation=1).matrix.postRotate.assert_not_called()
        self.run_save(exif_fails=True).matrix.postRotate.assert_not_called()

    def test_not_an_image_raises(self):
        with self.assertRaises(ValueError):
            self.run_save(width=0, height=0)

    def test_undecodable_image_raises(self):
        with self.assertRaises(ValueError):
            self.run_save(decode_ok=False)


class PickAndroidTests(AppCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeAndroid()
        patcher = mock.patch.dict(sys.modules, self.fake.modules())
        patcher.start()
        self.addCleanup(patcher.stop)
        flag = mock.patch.object(avatar_picker, 'ANDROID', True)
        flag.start()
        self.addCleanup(flag.stop)
        self.done, self.errors = [], []

    def start(self, save=None):
        patcher = mock.patch.object(avatar_picker, 'save_picked_image',
                                    save or self.fake_save)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app.picker.pick(self.done.append, self.errors.append)
        activity = sys.modules['android'].activity
        (_, kwargs), = activity.bind.call_args_list
        return activity, kwargs['on_activity_result']

    @staticmethod
    def fake_save(uri, dest):
        with open(dest, 'wb') as f:
            f.write(b'jpeg')

    def intent_with(self, uri='content://pic'):
        return SimpleNamespace(getData=lambda: uri)

    def test_launches_gallery_intent(self):
        self.start()
        intent = self.fake.Intent.return_value
        intent.setType.assert_called_once_with('image/*')
        self.fake.activity.mActivity.startActivityForResult.assert_called_once()
        args = self.fake.activity.mActivity.startActivityForResult.call_args[0]
        self.assertEqual(args[1], avatar_picker.REQUEST_CODE)

    def test_selected_image_is_saved_and_reported(self):
        activity, on_result = self.start()
        on_result(avatar_picker.REQUEST_CODE, -1, self.intent_with())
        Clock.settle()
        self.assertEqual(len(self.done), 1)
        self.assertTrue(os.path.exists(self.done[0]))
        self.assertTrue(self.done[0].startswith(self.app.storage.avatar_dir))
        self.assertEqual(self.errors, [])
        activity.unbind.assert_called_once()                       # слушатель снят

    def test_cancel_does_nothing(self):
        _, on_result = self.start()
        on_result(avatar_picker.REQUEST_CODE, 0, None)
        Clock.settle()
        self.assertEqual((self.done, self.errors), ([], []))

    def test_foreign_request_code_is_ignored(self):
        activity, on_result = self.start()
        on_result(12345, -1, self.intent_with())
        Clock.settle()
        self.assertEqual((self.done, self.errors), ([], []))
        activity.unbind.assert_not_called()

    def test_missing_uri_reports_error(self):
        _, on_result = self.start()
        on_result(avatar_picker.REQUEST_CODE, -1, self.intent_with(uri=None))
        Clock.settle()
        self.assertEqual(len(self.errors), 1)

    def test_processing_error_reports_and_leaves_no_file(self):
        created = []

        def broken_save(uri, dest):
            open(dest, 'wb').close()          # файл уже создан…
            created.append(dest)
            raise OSError('диск полон')       # …и тут ошибка

        _, on_result = self.start(broken_save)
        on_result(avatar_picker.REQUEST_CODE, -1, self.intent_with())
        Clock.settle()
        self.assertEqual(self.done, [])
        self.assertIn('диск полон', self.errors[0])
        self.assertFalse(os.path.exists(created[0]))

    def test_failure_to_launch_reports_error(self):
        self.fake.activity.mActivity.startActivityForResult.side_effect = RuntimeError('нет галереи')
        self.app.picker.pick(self.done.append, self.errors.append)
        self.assertEqual(self.done, [])
        self.assertIn('нет галереи', self.errors[0])


class DesktopImportTests(AppCase):
    def test_copy_small_file(self):
        src = os.path.join(self._data_tmp.name, 'pic.png')
        with open(src, 'wb') as f:
            f.write(b'12345')
        dest = self.app.storage.new_avatar_path('.png')
        avatar_picker.import_desktop_file(src, dest)
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), b'12345')

    def test_too_large_file_rejected(self):
        src = os.path.join(self._data_tmp.name, 'huge.png')
        with open(src, 'wb') as f:
            f.truncate(avatar_picker.MAX_DESKTOP_BYTES + 1)
        dest = self.app.storage.new_avatar_path('.png')
        with self.assertRaises(ValueError):
            avatar_picker.import_desktop_file(src, dest)
        self.assertFalse(os.path.exists(dest))


if __name__ == '__main__':
    unittest.main()
