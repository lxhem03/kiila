from asyncio import gather, create_task, sleep as asleep, Event
from asyncio.subprocess import PIPE
from os import path as ospath, system
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove
from traceback import format_exc
from base64 import urlsafe_b64encode
from time import time
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import timedelta, datetime
import pytz
from bot import bot, bot_loop, Var, ani_cache, ffQueue, ffLock, ff_queued
from .tordownload import TorDownloader
from .database import db
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep

btn_formatter = {
    '1080':'𝟭𝟬𝟴𝟬𝗽', 
    '720':'𝟳𝟮𝟬𝗽',
    '480':'𝟰𝟴𝟬𝗽',
    '360':'𝟯𝟲𝟬𝗽'
}


ist = pytz.timezone('Asia/Kolkata')

async def daily_airing_job():
    """Runs every day at 1:00 AM IST"""
    while True:
        now = datetime.now(ist)
        next_run = now.replace(hour=1, minute=0, second=0, microsecond=0)
        if now.hour >= 1:
            next_run += timedelta(days=1)
        seconds = (next_run - now).total_seconds()
        await asleep(seconds)

        await rep.report("Running Daily Airing Schedule Update...", "info")
        tasks = await db.get_all_rss_tasks()
        for task in tasks:
            anilist_id = task.get("anilist_id")
            if not anilist_id:
                continue
            try:
                data = anilist.get_anime_with_id(anilist_id)
                if not data:
                    continue
                next_ep = data.get("next_airing_ep")
                if next_ep and next_ep.get("episode"):
                    ep_num = next_ep["episode"]
                    await db.set_today_airing(anilist_id, ep_num)
                    await rep.report(f"Scheduled → {task['custom_name']} EP{ep_num}", "info")
            except:
                pass

async def fetch_animes():
    bot_loop.create_task(daily_airing_job())
    await rep.report("Smart RSS Scheduler + Daily Airing Job Started!", "info")

    while True:
        await asleep(90)

        if not ani_cache.get('fetch_animes', True):
            continue

        tasks = await db.get_all_rss_tasks()
        if not tasks:
            continue

        for task in tasks:
            if not task.get("active", True):
                continue

            rss_link = task["rss_link"]
            custom_name = task["custom_name"]
            anilist_id = task["anilist_id"]
            keywords = task["keywords"]
            avoid_keywords = task["avoid_keywords"]
            task_id = task["task_id"]

            # Get today's expected episode (if any)
            expected = await db.get_today_airing(anilist_id) if anilist_id else None
            if not expected or expected.get("uploaded", False):
                continue  # No airing today or already uploaded → skip task

            expected_ep = expected["expected_ep"]

            feed = await getfeed(rss_link)
            if not feed or not hasattr(feed, "entries") or not feed.entries:
                continue

            for entry in feed.entries[:3]:
                title = entry.title
                link = entry.link
                guid = entry.get("id") or entry.get("guid") or link

                # MUST match expected episode
                parser = TextEditor(title)
                ep_num = parser.pdata.get("episode_number")
                if not ep_num or int(ep_num) != expected_ep:
                    continue

                # Other checks (processed, 1080p, keywords)
                if await db.is_processed(task_id, guid):
                    continue

                if "1080" not in title.lower():
                    continue

                if avoid_keywords and any(kw in title.lower() for kw in avoid_keywords.split(",")):
                    continue

                if keywords and not all(kw in title.lower() for kw in [k.strip() for k in keywords.split(",") if k.strip()]):
                    continue

                # Process it
                await db.add_processed_item(task_id, guid)
                bot_loop.create_task(get_animes(
                    name=title,
                    torrent=link,
                    force=False,
                    anilist_id=anilist_id,
                    custom_name=custom_name,
                    task_id=task_id
                ))

async def get_animes(name, torrent, force=False, anilist_id=None, custom_name=None, task_id=None):
    try:
        aniInfo = TextEditor(name)
        await aniInfo.load_anilist(anilist_id=anilist_id, custom_name=custom_name)

        ani_id = await aniInfo.get_id() or 0
        ep_no = aniInfo.pdata.get("episode_number")

        if ani_id in ani_cache['completed'] and not force:
            return

        if not force:
            ani_data = await db.getAnime(ani_id)
            if ani_data and ep_no and (qual_data := ani_data.get(ep_no)) and all(qual_data.values()):
                return

        if "[Batch]" in name:
            await rep.report(f"Batch skipped: {name}", "warning")
            return

        await rep.report(f"New episode found → {name}", "info")

        post_msg = await bot.send_photo(
            Var.MAIN_CHANNEL,
            photo=await aniInfo.get_poster(),
            caption=await aniInfo.get_caption()
        )

        await asleep(1.5)
        stat_msg = await sendMessage(Var.MAIN_CHANNEL, f"<b>Anime:</b> <i>{name}</i>\n\n<i>Downloading...</i>")

        dl = await TorDownloader("./downloads").download(torrent, name)
        if not dl or not ospath.exists(dl):
            await editMessage(stat_msg, "<i>Download failed!</i>")
            return

        post_id = post_msg.id
        ffEvent = Event()
        ff_queued[post_id] = ffEvent
        if ffLock.locked():
            await editMessage(stat_msg, "<i>Queued for encoding...</i>")
        await ffQueue.put(post_id)
        await ffEvent.wait()

        await ffLock.acquire()
        btns = []
        for qual in Var.QUALS:
            filename = await aniInfo.get_upname(qual, custom_title=custom_name)
            await editMessage(stat_msg, f"<i>Encoding {qual}p...</i>")

            try:
                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
            except Exception as e:
                await rep.report(f"Encode failed: {e}", "error")
                ffLock.release()
                return

            await editMessage(stat_msg, f"<i>Uploading {qual}p...</i>")
            try:
                msg = await TgUploader(stat_msg).upload(out_path, qual)
            except Exception as e:
                await rep.report(f"Upload failed: {e}", "error")
                ffLock.release()
                return

            link = f"https://t.me/{(await bot.get_me()).username}?start={await encode('get-'+str(msg.id * abs(Var.FILE_STORE)))}"
            text = f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}"
            if btns and len(btns[-1]) == 1:
                btns[-1].insert(1, InlineKeyboardButton(text, url=link))
            else:
                btns.append([InlineKeyboardButton(text, url=link)])

            await post_msg.edit_reply_markup(InlineKeyboardMarkup(btns))
            await db.saveAnime(ani_id, ep_no, qual, post_id)
            bot_loop.create_task(extra_utils(msg.id, out_path))

        ffLock.release()
        await stat_msg.delete()
        await aioremove(dl)

        if ani_id:
            ani_cache['completed'].add(ani_id)
        if anilist_id:
            await db.mark_today_uploaded(anilist_id)            
        
    except Exception as e:
        await rep.report(f"get_animes error (Task {task_id}): {format_exc()}", "error")
        
async def extra_utils(msg_id, out_path):
    msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)

    if Var.BACKUP_CHANNEL != 0:
        for chat_id in Var.BACKUP_CHANNEL.split():
            await msg.copy(int(chat_id))
            
    # MediaInfo, ScreenShots, Sample Video ( Add-ons Features )
