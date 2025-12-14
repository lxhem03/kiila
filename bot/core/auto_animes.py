#fv2 - 7.3
from asyncio import gather, Lock, create_task, sleep as asleep, Event
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
from bot.modules.up_posts import mark_schedule_uploaded
from .tordownload import TorDownloader
from .database import db 
from .func_utils import getfeed, encode, editMessage, sendMessage, convertBytes, verify_sub, a_stream, s_stream
from .text_utils import TextEditor
from .ffencoder import FFEncoder
from .tguploader import TgUploader
from .reporter import rep
from AnilistPython import Anilist
from html import escape
from aiofiles.os import rename as aiorename


pipelineLock = Lock()
anilist = Anilist()

btn_formatter = {
    '1080':'𝟭𝟬𝟴𝟬𝗽', 
    '720':'𝟳𝟮𝟬𝗽',
    '480':'𝟰𝟴𝟬𝗽',
    '360':'𝟯𝟲𝟬𝗽'
}


ist = pytz.timezone('Asia/Kolkata')

async def daily_airing_job():
    """Runs every hour, checks airings in next 24 hours"""
    while True:
        await asleep(3600)

        await rep.report("Updating Airing Schedule for Next 24h...", "info")
        tasks = await db.get_all_rss_tasks()
        for task in tasks:
            anilist_id = task.get("anilist_id")
            if not anilist_id:
                continue
            try:
                data = anilist.get_anime_with_id(anilist_id)
                if data:
                    next_air = data.get("next_airing_ep")
                    if next_air and next_air.get("timeUntilAiring", 0) < 86400:
                        ep = next_air["episode"]
                        await db.set_today_airing(anilist_id, ep)
                        await rep.report(f"Upcoming EP{ep} for {task['custom_name']} in <24h", "info")
            except Exception as e:
                await rep.report(f"Airing update failed for ID {anilist_id}: {e}", "warning")
                
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

            expected = await db.get_today_airing(anilist_id) if anilist_id else None
            if not expected or expected.get("uploaded", False):
                continue

            expected_ep = expected["expected_ep"]

            feed = await getfeed(rss_link)
            if not feed or not hasattr(feed, "entries") or not feed.entries:
                continue

            for entry in feed.entries[:3]:
                title = entry.title
                link = entry.link
                guid = entry.get("id") or entry.get("guid") or link

                parser = TextEditor(title)
                ep_num = parser.pdata.get("episode_number")
                if not ep_num or int(ep_num) != expected_ep:
                    continue

                if await db.is_processed(task_id, guid):
                    continue

                if "1080" not in title.lower():
                    continue

                if avoid_keywords and any(kw in title.lower() for kw in avoid_keywords.split(",")):
                    continue

                if keywords and not all(kw in title.lower() for kw in [k.strip() for k in keywords.split(",") if k.strip()]):
                    continue

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
    async with pipelineLock:
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

            await rep.report(f"New episode found: {name}", "info")

            title_en = (
                aniInfo.adata.get("title", {}).get("english")
                or aniInfo.adata.get("title", {}).get("romaji")
                or custom_name
                or aniInfo.pdata.get("anime_title")
                or "Unknown Anime"
            )

            info_msg = await sendMessage(
                Var.MAIN_CHANNEL,
                f"<blockqoute><b>New Episode Found!</b>\n\n"
                f"<b>Title:</b> <code>{title_en}</code>\n"
                f"<b>Episode:</b> <code>{ep_no or '??'}</code>\n\n"
                f"<i>Downloading started...</i></blockqoute>"
            )

            post_msg = await bot.send_photo(
                Var.MAIN_CHANNEL,
                photo=await aniInfo.get_poster(),
                caption=await aniInfo.get_caption()
            )

            dl = await TorDownloader("/ramdisk").download(torrent, name)
            if not dl or not ospath.exists(dl):
                await editMessage(info_msg, f"<blockqoute>Download failed!\n<b>Title:</b> <code>{title_en}</code>\n<b>Episode:</b> <code>{ep_no or '??'}</code></blockqoute>")
                return

            if not await verify_sub(dl):
                await editMessage(info_msg, f"<blockqoute>Aborted: No English subtitles found.\n<b>Title:</b> <code>{title_en}</code>\n<b>Episode:</b> <code>{ep_no or '??'}</code></blockqoute>")
                await aioremove(dl)
                return

            await editMessage(info_msg, "Getting Audio Information....")
            a_type = await a_stream(dl) or "Unknown"
            await asleep(0.5)
            await editMessage(info_msg, "Checking subtitles...")
            s_type = await s_stream(dl) or "Unknown"
            await asleep(0.5)

            await editMessage(info_msg, f"<blockqoute>Fetching Information!\nTitle: {title_en}\nEpisode: {ep_no or '??'}\nAudio(s): {a_type}\nSubtitle: {s_type}</blockqoute>")

            await info_msg.delete()

            stat_msg = await sendMessage(Var.MAIN_CHANNEL, "Starting encoding...")

            btns = []
            for qual in Var.QUALS:
                filename = await aniInfo.get_upname(qual, custom_title=custom_name)
                await editMessage(stat_msg, f"Encoding [{qual}p]...")

                out_path = await FFEncoder(stat_msg, dl, filename, qual).start_encode()
                if not out_path or not ospath.exists(out_path):
                    continue

                msg = await TgUploader(stat_msg).upload(out_path, qual)

                link = f"https://t.me/{(await bot.get_me()).username}?start={await encode(f'get-{msg.id * abs(Var.FILE_STORE)}')}"
                text = f"{btn_formatter[qual]} - {convertBytes(msg.document.file_size)}"

                if btns and len(btns[-1]) == 1:
                    btns[-1].append(InlineKeyboardButton(text, url=link))
                else:
                    btns.append([InlineKeyboardButton(text, url=link)])

                await post_msg.edit_reply_markup(InlineKeyboardMarkup(btns))
                await db.saveAnime(ani_id, ep_no, qual, post_msg.id)
                bot_loop.create_task(extra_utils(msg.id, out_path))

            await stat_msg.delete()
            await aioremove(dl)

            if ani_id:
                ani_cache['completed'].add(ani_id)

            if anilist_id:
                bot_loop.create_task(mark_schedule_uploaded(anilist_id))

        except Exception:
            await rep.report(
                f"get_animes error (Task {task_id}): {format_exc()}",
                "error"
            )
        
async def extra_utils(msg_id, out_path):
    msg = await bot.get_messages(Var.FILE_STORE, message_ids=msg_id)

    if Var.BACKUP_CHANNEL != 0:
        for chat_id in Var.BACKUP_CHANNEL.split():
            await msg.copy(int(chat_id))
            
    # MediaInfo, ScreenShots, Sample Video ( Add-ons Features )
