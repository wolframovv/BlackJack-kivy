[app]
title = BlackJack
package.name = blackjack
package.domain = org.blackjack

source.dir = .
# ИЗМЕНЕНО: добавлено kv (файл стилей ui/style.kv)
source.include_exts = py,png,jpg,jpeg,ttf,json,kv,mp3
source.include_patterns = cards/*,cards/*/*,etc/*
# ИЗМЕНЕНО: tests/* не нужны в приложении
source.exclude_patterns = bin/*,.buildozer/*,.venv/*,__pycache__/*,*.pyc,build.log,tests/*

version = 0.4.1

# ИЗМЕНЕНО: вместо pygame и pyjnius — kivy (pyjnius подтянется сам)
requirements = python3==3.10.12,hostpython3==3.10.12,kivy==2.3.0

orientation = landscape
fullscreen = 1

icon.filename = etc/icon.png
presplash.filename = etc/presplash.png

android.archs = arm64-v8a
android.api = 34
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24

android.sdk_path = /home/wolframovv/android-sdk
android.ndk_path = /home/wolframovv/android-sdk/ndk/25.1.8937393

android.allow_backup = True

p4a.bootstrap = sdl2
p4a.branch = v2024.01.21
p4a.version = v2024.01.21
# ИЗМЕНЕНО: локальные рецепты были нужны для pygame. Если в ./p4a-recipes нет
# ничего другого, что вам нужно, строку лучше оставить закомментированной.
# p4a.local_recipes = ./p4a-recipes

android.debug_artifact = apk
android.release_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1