from multiprocessing import cpu_count
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from json import loads as jloads
from re import findall
from math import floor
from os import path as ospath
from time import time, sleep
from traceback import format_exc
from asyncio import sleep as asleep, create_subprocess_shell
from asyncio.subprocess import PIPE
from base64 import urlsafe_b64encode, urlsafe_b64decode

from aiohttp import ClientSession
from aiofiles import open as aiopen
from aioshutil import rmtree as aiormtree
from html_telegraph_poster import TelegraphPoster
from feedparser import parse as feedparse
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardButton
from pyrogram.errors import MessageNotModified, FloodWait, UserNotParticipant, ReplyMarkupInvalid, MessageIdInvalid
import feedparser
from bot import bot, bot_loop, LOGS, Var
from .reporter import rep
import subprocess


async def s_stream(filepath: str) -> str:
    """
    Detect subtitle languages in a video file.
    
    Returns:
        'Multi-Subs' -> English + another language exists
        'English'    -> Only English or undefined subtitles
        'No-Subs'    -> No subtitle tracks found
    """
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-select_streams", "s", "-show_entries", "stream=index:stream_tags=language",
            filepath
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        data = jloads(result.stdout)

        streams = data.get("streams", [])

        if not streams:
            return "No-Subs"

        languages = []
        for s in streams:
            lang = s.get("tags", {}).get("language", "").lower().strip()

            if lang in ["eng", "en", "english", ""]:  
                languages.append("english")
            else:
                languages.append(lang)

        unique_langs = set(languages)

        if "english" in unique_langs:
            if len(unique_langs) > 1:
                return "Multi-Subs"
            return "English"

        return "English"

    except Exception as e:
        print("Subtitle detection error:", e)
        return "English"


async def a_stream(filepath: str):
    """
    Returns:
        'Sub'  -> 1 or 2 audio tracks, ONLY (Japanese/Chinese/Korean) with NO English
        'Dual' -> 2 audio tracks, ONE Asian (JPN/CHN/KOR) + ONE English
        False  -> English-only, unsupported languages, more than 2 tracks, or missing language data
    """

    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-select_streams", "a",
            "-show_entries", "stream_tags=language",
            filepath
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        data = jloads(result.stdout)

        streams = data.get("streams", [])

        if len(streams) > 2:
            return False
        if len(streams) == 0:
            return False

        langs = []

        for s in streams:
            lang = s.get("tags", {}).get("language", "").lower().strip()

            if lang == "":
                return False

            if lang in ["jpn", "jp"]:
                lang = "japanese"
            if lang in ["zh", "chi", "zho", "chs", "cht"]:
                lang = "chinese"
            if lang in ["ko", "kor"]:
                lang = "korean"
            if lang in ["en", "eng"]:
                lang = "english"

            langs.append(lang)

        unique = set(langs)

        asian_set = {"japanese", "chinese", "korean"}

        if unique == {"english"}:
            return False

        for l in unique:
            if l not in asian_set and l != "english":
                return False

        if unique.issubset(asian_set):
            return "Sub"

        if "english" in unique and any(l in asian_set for l in unique):
            if len(unique) == 2:
                return "Dual"

        return False

    except Exception as e:
        print("FFprobe error:", e)
        return False

async def verify_sub(filepath: str) -> bool:
    """
    Returns True if the video has English or undefined subtitles.
    Returns False if no subtitles or no English subs.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-select_streams", "s",
            "-show_entries", "stream_tags=language",
            filepath
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        data = jloads(result.stdout)

        streams = data.get("streams", [])
        if not streams:
            return False

        for stream in streams:
            lang = stream.get("tags", {}).get("language", "").strip().lower()
            if lang in ["", "eng", "en", "english"]:
                return True

        return False
    except Exception as e:
        LOGS.warning(f"Subs check failed: {e}")
        return False

def handle_logs(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            await rep.report(format_exc(), "error")
    return wrapper
    
async def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(
        ThreadPoolExecutor(max_workers=8),  # 8 is more than enough
        pfunc
    )
    return await future if wait else future
    
def new_task(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return bot_loop.create_task(func(*args, **kwargs))
    return wrapper


async def getfeed(link, index=None):
    """
    Returns:
        - Full feed object with .entries list → if index is None
        - Single entry → if index is given
    """
    try:
        feed = await sync_to_async(feedparser.parse, link)
        
        # If feed is broken or empty
        if feed.bozo or not hasattr(feed, "entries") or not feed.entries:
            return None

        if index is not None:
            try:
                return feed.entries[index]
            except IndexError:
                return None
        
        return feed

    except Exception as e:
        LOGS.error(f"getfeed failed for {link} failed:\n{format_exc()}")
        return None
        
@handle_logs
async def aio_urldownload(link):
    async with ClientSession() as sess:
        async with sess.get(link) as data:
            image = await data.read()
    path = f"thumbs/{link.split('/')[-1]}"
    if not path.endswith((".jpg" or ".png")):
        path += ".jpg"
    async with aiopen(path, "wb") as f:
        await f.write(image)
    return path

@handle_logs
async def get_telegraph(out):
    client = TelegraphPoster(use_api=True)
    client.create_api_token("Mediainfo")
    uname = Var.BRAND_UNAME.lstrip('@')
    page = client.post(
        title="Mediainfo",
        author=uname,
        author_url=f"https://t.me/{uname}",
        text=f"""<pre>
{out}
</pre>
""",
        )
    return page.get("url")


async def sendMessage(chat, text, buttons=None, get_error=False, **kwargs):
    try:
        # FIX: Resolve reply_markup duplication
        reply_markup = buttons
        if 'reply_markup' in kwargs:
            if reply_markup is None:
                reply_markup = kwargs.pop('reply_markup')
            else:
                # If both, prioritize buttons param
                kwargs.pop('reply_markup', None)

        if isinstance(chat, int):
            print("IF executed in sendMessage")
            return await bot.send_message(
                chat_id=chat,
                text=text,
                disable_web_page_preview=True,
                disable_notification=False,
                reply_markup=reply_markup,
                **kwargs
            )
        else:
            print("ELSE executed in sendMessage")
            return await chat.reply_text(
                text=text,
                quote=True,
                disable_web_page_preview=True,
                disable_notification=False,
                reply_markup=reply_markup,
                **kwargs
            )
    except FloodWait as f:
        await rep.report(f"FloodWait {f.value}s", "warning")
        await asleep(f.value * 1.2)
        return await rep.report(f"🥸🍂", "warning")
    except ReplyMarkupInvalid:
        pass
    except Exception as e:
        await rep.report(format_exc(), "error")
        if get_error:
            raise e
        return str(e)
        
async def editMessage(msg, text, buttons=None, get_error=False, **kwargs):
    try:
        if not msg:
            return None
        return await msg.edit_text(
            text=text,
            disable_web_page_preview=True,
            reply_markup=buttons,
            **kwargs
        )
    except FloodWait as f:
        await rep.report(f"FloodWait {f.value}s", "warning")
        await asleep(f.value * 1.2)
        return await editMessage(msg, text, buttons, get_error, **kwargs)
    except ReplyMarkupInvalid:
        return await editMessage(msg, text, None, get_error, **kwargs)
    except (MessageNotModified, MessageIdInvalid):
        return msg
    except Exception as e:
        await rep.report(format_exc(), "error")
        if get_error:
            raise e
        return str(e)
        
async def editMessage(msg, text, buttons=None, get_error=False, **kwargs):
    try:
        if not msg:
            return None
        return await msg.edit_text(text=text, disable_web_page_preview=True, 
                                        reply_markup=buttons, **kwargs)
    except FloodWait as f:
        await rep.report(f, "warning")
        sleep(f.value * 1.2)
        return await editMessage(msg, text, buttons, get_error, **kwargs)
    except ReplyMarkupInvalid:
        return await editMessage(msg, text, None, get_error, **kwargs)
    except (MessageNotModified, MessageIdInvalid):
        pass
    except Exception as e:
        await rep.report(format_exc(), "error")
        if get_error:
            raise e
        return str(e)

async def encode(string):
    return (urlsafe_b64encode(string.encode("ascii")).decode("ascii")).strip("=")

async def decode(b64_str):
    return urlsafe_b64decode((b64_str.strip("=") + "=" * (-len(b64_str.strip("=")) % 4)).encode("ascii")).decode("ascii")

async def is_fsubbed(uid):
    if len(Var.FSUB_CHATS) == 0:
        return True
    for chat_id in Var.FSUB_CHATS:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=uid)
        except UserNotParticipant:
            return False
        except Exception as err:
            await rep.report(format_exc(), "warning")
            continue
    return True
        
async def get_fsubs(uid, txtargs):
    txt = "<b><i>Please Join Following Channels to Use this Bot!</i></b>\n\n"
    btns = []
    for no, chat in enumerate(Var.FSUB_CHATS, start=1):
        try:
            cha = await bot.get_chat(chat)
            member = await bot.get_chat_member(chat_id=chat, user_id=uid)
            sta = "Joined ✅️"
        except UserNotParticipant:
            sta = "Not Joined ❌️"
            inv = await bot.create_chat_invite_link(chat_id=chat)
            btns.append([InlineKeyboardButton(cha.title, url=inv.invite_link)])
        except Exception as err:
            await rep.report(format_exc(), "warning")
            continue
        txt += f"<b>{no}. Title :</b> <i>{cha.title}</i>\n  <b>Status :</b> <i>{sta}</i>\n\n"
    if len(txtargs) > 1:
        btns.append([InlineKeyboardButton('🗂 Get Files', url=f'https://t.me/{(await bot.get_me()).username}?start={txtargs[1]}')])
    return txt, btns

async def mediainfo(file, get_json=False, get_duration=False):
    try:
        outformat = "HTML"
        if get_duration or get_json:
            outformat = "JSON"
        process = await create_subprocess_shell(f"mediainfo '''{file}''' --Output={outformat}", stdout=PIPE, stderr=PIPE)
        stdout, _ = await process.communicate()
        if get_duration:
            try:
                return float(jloads(stdout.decode())['media']['track'][0]['Duration'])
            except Exception:
                return 1440 # 24min
        return await get_telegraph(stdout.decode())
    except Exception as err:
        await rep.report(format_exc(), "error")
        return ""
        
async def clean_up():
    try:
        (await aiormtree(dirtree) for dirtree in ("downloads", "thumbs", "encode"))
    except Exception as e:
        LOGS.error(str(e))

def convertTime(s: int) -> str:
    m, s = divmod(int(s), 60)
    hr, m = divmod(m, 60)
    days, hr = divmod(hr, 24)
    convertedTime = (f"{int(days)}d, " if days else "") + \
          (f"{int(hr)}h, " if hr else "") + \
          (f"{int(m)}m, " if m else "") + \
          (f"{int(s)}s, " if s else "")
    return convertedTime[:-2]

def convertBytes(sz) -> str:
    if not sz: 
        return ""
    sz = int(sz)
    ind = 0
    Units = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T', 5: 'P'}
    while sz > 2**10:
        sz /= 2**10
        ind += 1
    return f"{round(sz, 2)} {Units[ind]}B"

def humanbytes(size):
    """Convert bytes to human readable format (e.g. 1.5 GB)"""
    if not size:
        return "0 B"
    power = 2**10
    n = 0
    units = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"
