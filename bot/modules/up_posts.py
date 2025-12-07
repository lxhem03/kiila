# bot/core/upcoming_animes.py

from json import loads as jloads
from os import path as ospath, execl
from sys import executable
from datetime import datetime
import pytz

from bot import Var, bot, ffQueue
from bot.core.database import db
from bot.core.reporter import rep
from AnilistPython import Anilist

anilist = Anilist()
ist = pytz.timezone('Asia/Kolkata')

TODAY_SCHEDULE_MSG = None

async def upcoming_animes():
    global TODAY_SCHEDULE_MSG

    if not Var.SEND_SCHEDULE:
        if not ffQueue.empty():
            await ffQueue.join()
        await rep.report("Auto Restarting..!!", "info")
        execl(executable, executable, "-m", "bot")
        return

    try:
        today_str = datetime.now(ist).strftime("%Y-%m-%d")
        airing_docs = await db.__today_airing.find({"date": today_str}).to_list(length=None)

        if not airing_docs:
            await rep.report("No anime scheduled for today.", "info")
            if TODAY_SCHEDULE_MSG:
                try:
                    await TODAY_SCHEDULE_MSG.delete()
                except:
                    pass
                TODAY_SCHEDULE_MSG = None
            return

        schedule_list = []
        for doc in airing_docs:
            anilist_id = doc["anilist_id"]
            try:
                data = anilist.get_anime_with_id(anilist_id)
                if not data:
                    continue

                next_air = data.get("next_airing_ep")
                if not next_air or next_air.get("episode") != doc["expected_ep"]:
                    continue

                airing_utc = datetime.fromtimestamp(next_air["airingAt"], tz=pytz.UTC)
                airing_ist = airing_utc.astimezone(ist)
                time_str = airing_ist.strftime("%I:%M %p").lstrip("0")

                title_en = data.get("name_english") or data.get("name_romaji") or "Unknown Anime"
                page_slug = data.get("siteUrl", "").split("/")[-1] or "unknown"

                schedule_list.append({
                    "title": title_en,
                    "time": time_str,
                    "page": page_slug,
                    "uploaded": doc.get("uploaded", False),
                    "anilist_id": anilist_id
                })
            except Exception as e:
                await rep.report(f"Failed to get time for ID {anilist_id}: {e}", "warning")

        if not schedule_list:
            return

        schedule_list.sort(key=lambda x: datetime.strptime(x["time"], "%I:%M %p"))

        text = "<b>Today's Airing Schedule [IST]</b>\n\n"
        for item in schedule_list:
            status = "Uploaded" if item["uploaded"] else "Pending"
            text += (
                f"<a href='https://anilist.co/anime/{item['anilist_id']}'>{item['title']}</a>\n"
                f"    • <b>Time:</b> {item['time']}\n"
                f"    • <b>Status:</b> {status}\n\n"
            )

        if TODAY_SCHEDULE_MSG:
            try:
                await TODAY_SCHEDULE_MSG.edit_text(text, disable_web_page_preview=True)
            except:
                TODAY_SCHEDULE_MSG = None

        if not TODAY_SCHEDULE_MSG:
            msg = await bot.send_message(Var.MAIN_CHANNEL, text, disable_web_page_preview=True)
            await msg.pin()
            TODAY_SCHEDULE_MSG = msg

    except Exception as err:
        await rep.report(f"upcoming_animes failed: {err}", "error")

    if not ffQueue.empty():
        await ffQueue.join()
    await rep.report("Auto Restarting..!!", "info")
    execl(executable, executable, "-m", "bot")


# Optional: Update status when uploaded (call this from get_animes after success)
async def mark_schedule_uploaded(anilist_id: int):
    global TODAY_SCHEDULE_MSG
    if not TODAY_SCHEDULE_MSG:
        return

    try:
        await db.mark_today_uploaded(anilist_id)
        await upcoming_animes()
    except:
        pass
