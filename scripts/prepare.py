#!/usr/bin/env python3
"""GitHub Actions এ চলে: ইনপুট যাচাই করে Android প্রজেক্টে নাম, URL, আইকন ও ওয়েব ফাইল বসায়।
সব ইনপুট environment variable থেকে আসে (shell এ সরাসরি বসানো হয় না, তাই injection ঝুঁকি নেই)।
আপলোড করা আইকন/সোর্স ফাইল uploads_in/ ফোল্ডারে আগেই নামানো থাকে (GitHub release থেকে)।"""
import json
import os
import re
import shutil
import sys
import zipfile
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
APP = os.path.join(ROOT, 'android', 'app', 'src', 'main')
IN_DIR = os.path.join(ROOT, 'uploads_in')
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


def find_upload(prefix, exts):
    for ext in exts:
        p = os.path.join(IN_DIR, prefix + '.' + ext)
        if os.path.isfile(p):
            return p
    return None


def make_icons(icon_path):
    sizes = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
    if icon_path:
        im = Image.open(icon_path).convert('RGBA')
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
            if n.startswith('__MACOSX/'):
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
    www = os.path.join(APP, 'assets', 'www')
    if mode == 'file':
        shutil.rmtree(www, ignore_errors=True)
        os.makedirs(www, exist_ok=True)
        src = find_upload('source', ('zip', 'html'))
        if not src:
            die('source file not found in uploads_in (upload step failed)')
        if os.path.getsize(src) > MAX_SRC:
            die('source file too large')
        print('SOURCE: %s (%d bytes)' % (os.path.basename(src), os.path.getsize(src)))
        if src.endswith('.html'):
            shutil.copy(src, os.path.join(www, 'index.html'))
        else:
            extract_zip(src, www)
        idx = os.path.join(www, 'index.html')
        if not os.path.isfile(idx) or os.path.getsize(idx) == 0:
            die('index.html missing or empty')

    # আইকন
    icon_path = find_upload('icon', ('png', 'jpg', 'jpeg'))
    if icon_path:
        try:
            if os.path.getsize(icon_path) > MAX_ICON:
                raise ValueError('icon too large')
            Image.open(icon_path).verify()
            print('ICON: custom icon used (%d bytes)' % os.path.getsize(icon_path))
        except Exception as e:
            print('::warning::ICON invalid (%s). Default icon will be used.' % e)
            icon_path = None
    else:
        print('ICON: no icon uploaded, default icon will be used')
    make_icons(icon_path)

    # প্যাকেজ হওয়া ফাইলের তালিকা (লগে দেখার জন্য)
    if mode == 'file':
        total = 0
        for base, _, files in os.walk(www):
            for fn in sorted(files):
                p = os.path.join(base, fn)
                total += 1
                if total <= 40:
                    print('ASSET: %s (%d bytes)' % (os.path.relpath(p, www), os.path.getsize(p)))
        print('ASSET: total %d files' % total)
        with open(os.path.join(www, 'index.html'), 'rb') as f:
            head = f.read(300).decode('utf-8', 'replace')
        print('INDEX HEAD: ' + ' '.join(head.split())[:250])

    print('OK: job=%s mode=%s package=%s orientation=%s refresh=%s' % (job, mode, pkg, orientation, refresh))


if __name__ == '__main__':
    main()
