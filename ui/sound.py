"""Звуки игры: click, card, win, lose, wasted (файлы лежат в etc/sounds/)."""
import os

NAMES = ('click', 'card', 'win', 'lose', 'wasted')
EXTENSIONS = ('.mp3', '.ogg', '.wav')


class SoundManager:
    def __init__(self):
        self.enabled = True
        self.volume = 0.8
        self._sounds = {}

    def load(self, folder):
        """Загружает звуки один раз при старте. Нет файла или ошибка — просто без звука."""
        try:
            from kivy.core.audio import SoundLoader
        except Exception:
            return
        for name in NAMES:
            for ext in EXTENSIONS:
                path = os.path.join(folder, name + ext)
                if not os.path.exists(path):
                    continue
                try:
                    sound = SoundLoader.load(path)
                except Exception:
                    sound = None
                if sound is not None:
                    sound.volume = self.volume
                    self._sounds[name] = sound
                    break

    def play(self, name):
        sound = self._sounds.get(name)
        if not self.enabled or sound is None:
            return
        try:
            sound.play()          # повторный вызов запускает звук с начала
        except Exception:
            pass                  # звук никогда не должен ронять игру


sounds = SoundManager()