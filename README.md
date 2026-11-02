# Facebook → Telegram publishing bot

Private bot: send a public Facebook post/video URL, get downloaded media and a draft with **Publish**, **Edit text**, **Location**, **Cancel** buttons.

## Setup
1. Create a **new** Telegram bot using @BotFather (`/newbot`). Never share the token in chat.
2. Add the bot as an **administrator** of the target Telegram channel with permission to post.
3. Obtain your numeric Telegram user ID (e.g. via @userinfobot).
4. Copy `.env.example` to `.env`; set `BOT_TOKEN`, `ADMIN_ID`, `CHANNEL_ID`.
5. Install Python 3.11+, `ffmpeg` (for some video formats), then:
   ```bash
   pip install -r requirements.txt
   python bot.py
   ```
6. Send `/start` to your new bot, then a public Facebook link.

## Deployment
Run as a **background worker** (not a web service). Start command: `python bot.py`. Configure environment variables in your host's dashboard. Only one polling instance per token. `bot.sqlite3` and `media/` are local; use persistent disk if your host supports it. Without persistent storage, drafts and downloaded files disappear after redeploy/restart. A future version can store drafts in Turso and media in object storage.

## Known limitations
- Facebook actively restricts scraping. Public video download uses yt-dlp; photo fallback may retrieve **only the post cover**, not the complete album. Private/restricted posts may fail. **Do not treat a cover image as proof that the full album was fetched.**
- Location is extracted only when the description explicitly labels a place (📍, Location:, Локація:, etc.). It does not infer geolocation from visuals or Facebook check-in metadata. Manual text locations are sent as text, not Telegram map pins. Send a Telegram location to publish a map pin.
- Telegram has upload size/format restrictions. Large media can fail; ffmpeg may be needed. This first version does not compress oversized videos.
- Album sends may partially succeed before a network error; the bot stops retries and marks the draft `needs_review` to reduce duplicate posts.
- The publication consists of media, optional location, and a source-link message.
- Keep copyright and privacy in mind; publish only content you have permission to reuse.

## Upload to GitHub from phone
1. Open https://github.com/vegenberg-max/charivna-facebook-bot
2. Choose **Add file → Upload files** (on mobile, use browser desktop site if the option is hidden).
3. **Extract this ZIP first** and select the files inside (not the ZIP itself). Commit changes.
4. Never upload `.env` or a Telegram bot token. `.env.example` is safe.

## Render setup
Use a **Background Worker**, not a Web Service. Add BOT_TOKEN and ADMIN_ID as environment variables and make the bot an admin of the target channel. Free Render plans may not support background workers; check plan/pricing before creating any paid service. This bot stores drafts and media locally, so they are lost when a non-persistent instance restarts. Facebook albums and location extraction have limitations as described above.
