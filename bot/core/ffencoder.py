# bot/core/ffencoder.py

from re import findall 
from math import floor
from time import time
from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, rename as aiorename
from shlex import split as ssplit
from asyncio import sleep as asleep, gather, create_subprocess_shell, create_task
from asyncio.subprocess import PIPE

from bot import Var, bot_loop, ffpids_cache, LOGS
from .func_utils import mediainfo, convertBytes, convertTime, sendMessage, editMessage
from .reporter import rep

ffargs = {
    '1080': Var.FFCODE_1080,
    '720': Var.FFCODE_720,
    '480': Var.FFCODE_480,
    '360': Var.FFCODE_360,
}

class FFEncoder:
    def __init__(self, message, path, name, qual):
        self.__proc = None
        self.is_cancelled = False
        self.message = message
        self.__name = name
        self.__qual = qual
        self.dl_path = path
        self.__total_time = None
        
        self.__ram_temp_in = "/ramdisk/AnimesGuyinput.mkv"
        self.__ram_temp_out = "/ramdisk/AnimesGuyoutput.mkv"
        self.out_path = ospath.join("encode", name)  # Final path on SSD
        self.__prog_file = '/ramdisk/prog.txt'       # Progress in RAM
        self.__start_time = time()

    async def progress(self):
        self.__total_time = await mediainfo(self.dl_path, get_duration=True)
        if isinstance(self.__total_time, str):
            self.__total_time = 1.0
            
        while not (self.__proc is None or self.is_cancelled):
            try:
                async with aiopen(self.__prog_file, 'r') as p:
                    text = await p.read()
            except:
                await asleep(8)
                continue

            if not text:
                await asleep(8)
                continue

            time_done = floor(int(t[-1]) / 1000000) if (t := findall("out_time_ms=(\d+)", text)) else 1
            ensize = int(s[-1]) if (s := findall(r"total_size=(\d+)", text)) else 0
            
            diff = time() - self.__start_time
            speed = ensize / diff if diff > 0 else 0
            percent = round((time_done / self.__total_time) * 100, 2)
            tsize = ensize / (max(percent, 0.01) / 100)
            eta = (tsize - ensize) / max(speed, 0.01)

            bar = "█" * floor(percent / 8) + "▒" * (12 - floor(percent / 8))
            
            progress_str = f"""<blockquote>‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b></blockquote>
<blockquote>‣ <b>Status :</b> <i>Encoding</i>
    <code>[{bar}]</code> {percent}%</blockquote> 
<blockquote>   ‣ <b>Size :</b> {convertBytes(ensize)} out of ~ {convertBytes(tsize)}
    ‣ <b>Speed :</b> {convertBytes(speed)}/s
    ‣ <b>Time Took :</b> {convertTime(diff)}
    ‣ <b>Time Left :</b> {convertTime(eta)}</blockquote>
<blockquote>‣ <b>File(s) Encoded:</b> <code>{Var.QUALS.index(self.__qual) + 1} / {len(Var.QUALS)}</code></blockquote>"""

            await editMessage(self.message, progress_str)

            if (prog := findall(r"progress=(\w+)", text)) and prog[-1] == 'end':
                break
            await asleep(8)

    async def start_encode(self):
        for f in [self.__prog_file, self.__ram_temp_in, self.__ram_temp_out]:
            try:
                await aioremove(f)
            except:
                pass

        async with aiopen(self.__prog_file, 'w'):
            pass

        await aiorename(self.dl_path, self.__ram_temp_in)

        ffcode = ffargs[self.__qual].format(self.__ram_temp_in, self.__prog_file, self.__ram_temp_out)
        LOGS.info(f'FFCode: {ffcode}')

        self.__proc = await create_subprocess_shell(ffcode, stdout=PIPE, stderr=PIPE)
        ffpids_cache.append(self.__proc.pid)

        _, return_code = await gather(
            create_task(self.progress()),
            self.__proc.wait()
        )
        ffpids_cache.remove(self.__proc.pid)

        if self.is_cancelled:
            try:
                await aiorename(self.__ram_temp_in, self.dl_path)
            except:
                pass
            return None

        if return_code != 0:
            err = (await self.__proc.stderr.read()).decode()
            await rep.report(f"FFmpeg error: {err}", "error")
            try:
                await aiorename(self.__ram_temp_in, self.dl_path)
            except:
                pass
            return None

        if ospath.exists(self.__ram_temp_out):
            await aiorename(self.__ram_temp_out, self.out_path)

        try:
            await aiorename(self.__ram_temp_in, self.dl_path)
        except:
            pass

        return self.out_path

    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc:
            try:
                self.__proc.kill()
            except:
                pass
