
import asyncio
import html
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from yt_dlp import YoutubeDL

load_dotenv()
TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN = int(os.environ.get('ADMIN_ID', '0'))
CHANNEL = os.environ.get('CHANNEL_ID', '@romania_lovers')
COOKIE_FILE = os.environ.get('FACEBOOK_COOKIES_FILE', '')
ROOT = Path(__file__).resolve().parent
DB = ROOT / 'bot.sqlite3'
MEDIA = ROOT / 'media'
MEDIA.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('facebook-bot')


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS drafts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, caption TEXT DEFAULT '',
          location TEXT DEFAULT '', latitude REAL, longitude REAL,
          files_json TEXT NOT NULL, status TEXT DEFAULT 'draft', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')


def create_draft(url, caption, paths):
    with db() as c:
        cur = c.execute('INSERT INTO drafts(url,caption,files_json) VALUES(?,?,?)',
                        (url, caption[:3500], json.dumps(paths)))
        return cur.lastrowid


def get_draft(did):
    with db() as c:
        return c.execute('SELECT * FROM drafts WHERE id=?', (did,)).fetchone()


def update_draft(did, **fields):
    allowed = {'caption', 'location', 'latitude', 'longitude', 'status'}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    with db() as c:
        c.execute('UPDATE drafts SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?',
                  (*fields.values(), did))


def keyboard(did):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('👁 Переглянути пост', callback_data=f'preview:{did}')],
        [InlineKeyboardButton('📢 Опублікувати', callback_data=f'publish:{did}')],
        [InlineKeyboardButton('✏️ Редагувати текст', callback_data=f'edit:{did}'),
         InlineKeyboardButton('📍 Локація', callback_data=f'location:{did}')],
        [InlineKeyboardButton('🗑 Скасувати', callback_data=f'cancel:{did}')]
    ])


def valid_fb_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        return host in {'facebook.com', 'www.facebook.com', 'm.facebook.com',
                        'web.facebook.com', 'fb.watch', 'www.fb.watch'} and parsed.scheme in ('https', 'http')
    except Exception:
        return False


def download_facebook(url, did):
    folder = MEDIA / str(did)
    folder.mkdir(parents=True, exist_ok=True)
    opts = {
        'outtmpl': str(folder / '%(id)s_%(autonumber)s.%(ext)s'),
        'format': 'best[ext=mp4]/best', 'merge_output_format': 'mp4',
        'playlistend': 20, 'noplaylist': False, 'quiet': True,
        'ignoreerrors': True, 'socket_timeout': 25,
    }
    if COOKIE_FILE and Path(COOKIE_FILE).is_file():
        opts['cookiefile'] = COOKIE_FILE
    title = ''
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = info.get('description') or info.get('title') or ''
    except Exception as exc:
        log.warning('yt-dlp failed: %s', exc)
    files = sorted([p for p in folder.iterdir() if p.suffix.lower() in {'.mp4', '.mkv', '.webm', '.jpg', '.jpeg', '.png'}])
    if not files:
        try:
            resp = requests.get(url, headers={'User-Agent': 'facebookexternalhit/1.1'}, timeout=20)
            soup = BeautifulSoup(resp.text, 'html.parser')
            og_title = soup.find('meta', attrs={'property': 'og:description'})
            if og_title and not title:
                title = og_title.get('content', '')
            img = soup.find('meta', attrs={'property': 'og:image'})
            if img and img.get('content'):
                r = requests.get(img['content'], timeout=25)
                r.raise_for_status()
                if r.headers.get('content-type', '').startswith('image/') and len(r.content) < 18_000_000:
                    p = folder / 'cover.jpg'
                    p.write_bytes(r.content)
                    files = [p]
        except Exception as exc:
            log.warning('Image fallback failed: %s', exc)
    return title[:3500], [str(p) for p in files]


def detect_location(text):
    pattern = r'(?:📍|Location:|Місце:|Локація:|Locația:|Locatie:)\s*([^\n,]{3,90}(?:,\s*[^\n,]{2,50})?)'
    match = re.search(pattern, text, flags=re.I)
    return match.group(1).strip() if match else ''


def preview(row):
    return (f'Чернетка #{row["id"]}\n\n'
            f'📝 {row["caption"][:900] or "Без опису"}\n\n'
            f'📍 {row["location"] or "Не знайдено — можна вказати вручну"}\n'
            f'🔗 {row["url"]}')


def publication_caption(row):
    location = (row['location'] or '').strip()
    location_line = f'📍 {html.escape(location)}\n\n' if location else ''
    channel_line = '<b><a href="https://t.me/romania_lovers">🇷🇴 Discover Romania</a></b>'
    return location_line + channel_line


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN:
        return
    await update.message.reply_text('Надішли посилання на Facebook-відео або пост із фото. Я підготую чернетку для каналу.')


async def incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN:
        return
    if update.message.location:
        pending = context.user_data.pop('pending', None)
        if pending and pending[0] == 'location':
            loc = update.message.location
            update_draft(pending[1], latitude=loc.latitude, longitude=loc.longitude,
                         location=f'{loc.latitude:.5f}, {loc.longitude:.5f}')
            row = get_draft(pending[1])
            await update.message.reply_text(preview(row), reply_markup=keyboard(row['id']), disable_web_page_preview=True)
        return
    text = update.message.text or ''
    pending = context.user_data.pop('pending', None)
    if pending:
        kind, did = pending
        if kind == 'edit':
            update_draft(did, caption=text[:3500])
        elif kind == 'location':
            update_draft(did, location=text[:150], latitude=None, longitude=None)
        row = get_draft(did)
        await update.message.reply_text(preview(row), reply_markup=keyboard(did), disable_web_page_preview=True)
        return
    match = re.search(r'https?://[^\s<>]+', text)
    url = match.group(0).rstrip(').,') if match else ''
    if not valid_fb_url(url):
        await update.message.reply_text('Надішли посилання facebook.com або fb.watch.')
        return
    status = await update.message.reply_text('⏳ Завантажую матеріали Facebook…')
    did = create_draft(url, '', [])
    title, files = await asyncio.to_thread(download_facebook, url, did)
    if not files:
        update_draft(did, status='failed')
        await status.edit_text('Не вдалося отримати медіа. Можливо, пост приватний або Facebook обмежує завантаження. Спробуй інше посилання.')
        return
    location = detect_location(title)
    with db() as c:
        c.execute('UPDATE drafts SET caption=?, location=?, files_json=? WHERE id=?',
                  (title, location, json.dumps(files), did))
    row = get_draft(did)
    await status.edit_text(f'✅ Отримано файлів: {len(files)}. Готую попередній перегляд…')
    try:
        await send_media(context.bot, update.effective_chat.id, row, include_caption=False)
    except Exception as exc:
        log.warning('Preview failed: %s', exc)
        await update.message.reply_text('Попередній перегляд не вдалося надіслати (можливо, файл завеликий).')
    await update.message.reply_text(preview(row), reply_markup=keyboard(did), disable_web_page_preview=True)


async def send_media(bot, chat_id, row, include_caption=True):
    paths = [Path(p) for p in json.loads(row['files_json']) if Path(p).is_file()]
    if not paths:
        raise RuntimeError('Media files missing')
    caption = publication_caption(row) if include_caption else ''
    for start_index in range(0, len(paths), 10):
        chunk = paths[start_index:start_index + 10]
        if len(chunk) == 1:
            p = chunk[0]
            with p.open('rb') as f:
                cap = caption if start_index == 0 else None
                if p.suffix.lower() in {'.mp4', '.mkv', '.webm'}:
                    await bot.send_video(chat_id, video=f, caption=cap,
                                         parse_mode=ParseMode.HTML, supports_streaming=True,
                                         read_timeout=120, write_timeout=120)
                else:
                    await bot.send_photo(chat_id, photo=f, caption=cap,
                                         parse_mode=ParseMode.HTML,
                                         read_timeout=120, write_timeout=120)
        else:
            handles = [p.open('rb') for p in chunk]
            try:
                media = []
                for i, (p, f) in enumerate(zip(chunk, handles)):
                    cap = caption if start_index == 0 and i == 0 else None
                    if p.suffix.lower() in {'.mp4', '.mkv', '.webm'}:
                        media.append(InputMediaVideo(media=f, caption=cap, parse_mode=ParseMode.HTML))
                    else:
                        media.append(InputMediaPhoto(media=f, caption=cap, parse_mode=ParseMode.HTML))
                await bot.send_media_group(chat_id, media, read_timeout=120, write_timeout=120)
            finally:
                for f in handles:
                    f.close()


async def action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN:
        return
    q = update.callback_query
    await q.answer()
    kind, did_s = q.data.split(':', 1)
    did = int(did_s)
    row = get_draft(did)
    if not row or row['status'] != 'draft':
        await q.message.reply_text('Чернетка вже оброблена або відсутня.')
        return
    if kind in ('edit', 'location'):
        context.user_data['pending'] = (kind, did)
        await q.message.reply_text('Надішли новий текст.' if kind == 'edit'
                                   else 'Напиши місто/адресу або надішли геолокацію Telegram.')
    elif kind == 'preview':
        try:
            await send_media(context.bot, q.message.chat_id, row)
            await q.message.reply_text('👁 Це вигляд фінального поста. У канал нічого не опубліковано.',
                                       reply_markup=keyboard(did))
        except Exception as exc:
            log.exception('Final preview failed: %s', exc)
            await q.message.reply_text('⚠️ Не вдалося показати пост. Перевір, чи файли збережені на сервері.')
    elif kind == 'cancel':
        update_draft(did, status='cancelled')
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text('🗑 Чернетку скасовано.')
    elif kind == 'publish':
        update_draft(did, status='publishing')
        try:
            await send_media(context.bot, CHANNEL, row)
            update_draft(did, status='published')
            await q.edit_message_reply_markup(reply_markup=None)
            await q.message.reply_text('✅ Опубліковано в канал.')
        except Exception as exc:
            update_draft(did, status='needs_review')
            log.exception('Publish error: %s', exc)
            await q.message.reply_text('⚠️ Помилка публікації. Перевір канал перед повтором, щоб не створити дубль.')


def main():
    if not TOKEN or not ADMIN:
        raise SystemExit('Set BOT_TOKEN and ADMIN_ID in .env or environment')
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(action, pattern=r'^(preview|publish|edit|location|cancel):\d+$'))
    app.add_handler(MessageHandler((filters.TEXT | filters.LOCATION) & ~filters.COMMAND, incoming))
    log.info('Starting bot polling')
    app.run_polling(drop_pending_updates=False)


if __name__ == '__main__':
    main()
