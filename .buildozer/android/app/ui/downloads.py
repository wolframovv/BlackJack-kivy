"""Сохранение файла в общую папку «Загрузки» (на телефоне и на ПК)."""
import os
import shutil

ANDROID = 'ANDROID_ARGUMENT' in os.environ


def _unique_path(folder, name):
    path = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    number = 1
    while os.path.exists(path):
        path = os.path.join(folder, f'{base}_{number}{ext}')
        number += 1
    return path


def save_to_downloads(src_path, mime='application/zip'):
    """Копирует файл в «Загрузки». Возвращает текст, куда он попал. При ошибке бросает исключение."""
    name = os.path.basename(src_path)
    if not ANDROID:
        folder = os.path.join(os.path.expanduser('~'), 'Downloads')
        os.makedirs(folder, exist_ok=True)
        dest = _unique_path(folder, name)
        shutil.copyfile(src_path, dest)
        return dest
    from jnius import autoclass
    sdk = autoclass('android.os.Build$VERSION').SDK_INT
    if sdk >= 29:
        return _save_mediastore(src_path, name, mime)
    return _save_legacy(src_path, name)


def _save_mediastore(src_path, name, mime):
    """Android 10+: файл создаётся через MediaStore, разрешения не нужны."""
    from jnius import autoclass

    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    ContentValues = autoclass('android.content.ContentValues')
    Downloads = autoclass('android.provider.MediaStore$Downloads')
    FileUtils = autoclass('android.os.FileUtils')
    FileInputStream = autoclass('java.io.FileInputStream')

    resolver = PythonActivity.mActivity.getContentResolver()
    values = ContentValues()
    values.put('_display_name', name)
    values.put('mime_type', mime)
    values.put('relative_path', 'Download')
    uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise OSError('не удалось создать файл в Загрузках')
    source = FileInputStream(src_path)
    out = resolver.openOutputStream(uri)
    try:
        FileUtils.copy(source, out)      # копирование целиком на стороне Java
    finally:
        out.close()
        source.close()
    return f'Загрузки/{name}'


def _save_legacy(src_path, name):
    """Android 9 и старше: обычная запись в папку Download (нужно разрешение на запись)."""
    from jnius import autoclass

    Environment = autoclass('android.os.Environment')
    folder = Environment.getExternalStoragePublicDirectory('Download').getAbsolutePath()
    os.makedirs(folder, exist_ok=True)
    dest = _unique_path(folder, name)
    shutil.copyfile(src_path, dest)
    return f'Загрузки/{os.path.basename(dest)}'
