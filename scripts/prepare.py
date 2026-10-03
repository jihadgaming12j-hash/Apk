#!/usr/bin/env python3
"""GitHub Actions এ চলে: ইনপুট যাচাই করে Android প্রজেক্টে নাম, URL, আইকন ও ওয়েব ফাইল বসায়।
সব ইনপুট environment variable থেকে আসে (shell এ সরাসরি বসানো হয় না, তাই injection ঝুঁকি নেই)।"""
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
APP = os.path.join(ROOT, 'android', 'app', 'src', 'main')
ASSET_URL = 'https://appassets.androidplatform.net/assets/www/index.html'
MAX_SRC = 25 * 1024 * 1024
MAX_ICON = 5 * 1024 * 1024
MAX_UNZIPPED = 150 * 1024 * 1024


def env(key, default=''):
    return os.environ.get(key, default)


def die(msg):
    print('ERROR:', msg)
    sys.exit(1)


def android_str(s):
    s = escape(s).replace("'", "\\'").replace('"', '\\"')
    if s[:1] in ('@', '?'):
        s = '\\' + s
    return s


def download(url, dest, limit):
    if not url.startswith(('http://', 'https://')):
        die('invalid download url')
    req = urllib.request.Request(url, headers={'User-Agent': 'mraiprime-apk-builder'})
    size = 0
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, 'wb') as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                die('file too large')
            f.write(chunk)


def make_icons(icon_path):
    sizes = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
    if icon_path:
        try:
            im = Image.open(icon_path).convert('RGBA')
        except Exception:
            die('icon file is not a valid image')
        w, h = im.size
        s = min(w, h)
        left, top = (w - s) // 2, (h - s) // 2
        im = im.crop((left, top, left + s, top + s))
    else:
        im = Image.new('RGBA', (512, 512), (5, 150, 105, 255))
        d = ImageDraw.Draw(im)
        d.ellipse((136, 136, 376, 376), fill=(255, 255, 255, 255))
    for density, px in sizes.items():
        out_dir = os.path.join(APP, 'res', 'mipmap-' + density)
        os.makedirs(out_dir, exist_ok=True)
        im.resize((px, px), Image.LANCZOS).save(os.path.join(out_dir, 'ic_launcher.png'))


def extract_zip(zpath, dest):
    with zipfile.ZipFile(zpath) as z:
        infos = z.infolist()
        names = [i.filename.replace('\\', '/') for i in infos]
        for n in names:
            if n.startswith('/') or '..' in n.split('/'):
                die('unsafe path in zip')
        if sum(i.file_size for i in infos) > MAX_UNZIPPED:
            die('zip content too large')
        if 'index.html' in names:
            prefix = ''
        else:
            cands = [n for n in names if re.fullmatch(r'[^/]+/index\.html', n)]
            if len(cands) != 1:
                die('index.html not found at zip root')
            prefix = cands[0][:-len('index.html')]
        real_dest = os.path.realpath(dest)
        for info in infos:
            n = info.filename.replace('\\', '/')
            if n.endswith('/') or not n.startswith(prefix):
                continue
            target = os.path.join(dest, n[len(prefix):])
            if not os.path.realpath(target).startswith(real_dest + os.sep):
                die('unsafe extract target')
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out)


def main():
    job = env('JOB_ID')
    if not re.fullmatch(r'[a-f0-9]{12}', job):
        die('bad job id')

    mode = env('MODE')
    if mode not in ('url', 'file'):
        die('bad mode')

    name = env('APP_NAME').strip()
    if not name or len(name) > 60:
        die('bad app name')

    pkg = env('APP_PACKAGE')
    if len(pkg) > 80 or not re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+', pkg):
        die('bad package name')

    orientation = env('ORIENTATION', 'portrait')
    if orientation not in ('portrait', 'landscape', 'auto'):
        orientation = 'portrait'
    refresh = env('REFRESH', '1') == '1'

    os.makedirs(os.path.join(APP, 'assets'), exist_ok=True)
    os.makedirs(os.path.join(APP, 'res', 'values'), exist_ok=True)

    # অ্যাপের নাম
    with open(os.path.join(APP, 'res', 'values', 'strings.xml'), 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
                '    <string name="app_name">%s</string>\n</resources>\n' % android_str(name))

    # কনফিগ
    if mode == 'url':
        url = env('TARGET_URL').strip()
        if not re.match(r'https?://', url, re.I) or len(url) > 500:
            die('bad url')
        start = url
    else:
        start = ASSET_URL

    with open(os.path.join(APP, 'assets', 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'mode': mode, 'url': start, 'orientation': orientation, 'refresh': refresh}, f)

    # ওয়েব ফাইল (file mode)
    if mode == 'file':
        www = os.path.join(APP, 'assets', 'www')
        shutil.rmtree(www, ignore_errors=True)
        os.makedirs(www, exist_ok=True)
        src_url = env('SRC_URL').strip()
        path = urlparse(src_url).path.lower()
        if path.endswith('.html'):
            download(src_url, os.path.join(www, 'index.html'), MAX_SRC)
        elif path.endswith('.zip'):
            tmp = os.path.join(ROOT, 'source.zip')
            download(src_url, tmp, MAX_SRC)
            extract_zip(tmp, www)
            os.remove(tmp)
        else:
            die('source must be .zip or .html')
        if not os.path.isfile(os.path.join(www, 'index.html')):
            die('index.html missing')

    # আইকন
    icon_path = None
    icon_url = env('ICON_URL').strip()
    if icon_url:
        icon_path = os.path.join(ROOT, 'icon.bin')
        download(icon_url, icon_path, MAX_ICON)
    make_icons(icon_path)
    if icon_path and os.path.exists(icon_path):
        os.remove(icon_path)

    print('OK: job=%s mode=%s package=%s orientation=%s refresh=%s' % (job, mode, pkg, orientation, refresh))


if __name__ == '__main__':
    main()
