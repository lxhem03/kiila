# bot/core/ffencoder.py \ FULL RAM ENCODING (PIPE PROGRESS)

from re import findall 
from math import floor
from time import time
from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, rename as aiorename, path as aiopath
from shlex import split as ssplit
from asyncio import sleep as asleep, gather, create_subprocess_shell, create_task
from asyncio.subprocess import PIPE
import shutil

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
        
        self.__ram_input = "/ramdisk/ff_temp_input.mkv"
        self.__ram_output = "/ramdisk/ff_temp_output.mkv"
        self.out_path = ospath.join("encode", name)
        
        self.__start_time = time()

    async def progress(self):
        self.__total_time = await mediainfo(self.dl_path, get_duration=True) or 1800.0
        LOGS.info(f"Progress started | Duration: {self.__total_time}s")

        last_percent = -1
        current_time = 0.0
        speed = 1.0

        while not (self.__proc is None or self.is_cancelled):
            try:
                if not self.__proc.stdout:
                    await asleep(5)
                    continue

                data = await self.__proc.stdout.read(1024)
                if not data:
                    await asleep(5)
                    continue

                text = data.decode(errors='ignore')
                lines = text.strip().split('\n')

                for line in lines:
                    if '=' not in line:
                        continue

                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    if key == 'out_time_ms':
                        try:
                            current_time = int(value) / 1_000_000
                        except:
                            current_time = 0.0
                    elif key == 'speed':
                        try:
                            speed_str = value.replace('x', '')
                            speed = float(speed_str) if speed_str != 'N/A' else 1.0
                        except:
                            speed = 1.0

                # Calculate progress
                percent = round((current_time / self.__total_time) * 100, 1)

                if abs(percent - last_percent) < 0.5:  # avoid spam
                    await asleep(5)
                    continue

                last_percent = percent
                diff = time() - self.__start_time
                eta = (self.__total_time - current_time) / speed if speed > 0 else 0

                bar = "█" * int(percent // 8) + "░" * (12 - int(percent // 8))

                progress_str = f"""<blockquote>‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b></blockquote>
<blockquote>‣ <b>Status :</b> <i>Encoding {self.__qual}p</i>
    <code>[{bar}]</code> {percent}%</blockquote>
<blockquote>   ‣ <b>Speed :</b> {speed:.2f}x
    ‣ <b>Elapsed :</b> {convertTime(diff)}
    ‣ <b>ETA :</b> {convertTime(eta)}</blockquote>
<blockquote>‣ <b>Progress :</b> <code>{Var.QUALS.index(self.__qual)+1}/{len(Var.QUALS)}</code></blockquote>"""

                await editMessage(self.message, progress_str)

                if 'progress=end' in text.lower():
                    break

            except Exception as e:
                LOGS.error(f"Progress loop error: {e}")
                await asleep(10)

            await asleep(6)    

    async def start_encode(self):
        for f in [self.__ram_input, self.__ram_output]:
            if await aiopath.exists(f):
                await aioremove(f)

        await aiorename(self.dl_path, self.__ram_input)

        ffcode = ffargs[self.__qual].format(self.__ram_input, self.__ram_output)
        LOGS.info(f'FFmpeg Command: {ffcode}')

        self.__proc = await create_subprocess_shell(ffcode, stdout=PIPE, stderr=PIPE)
        ffpids_cache.append(self.__proc.pid)

        _, return_code = await gather(
            create_task(self.progress()),
            self.__proc.wait()
        )

        ffpids_cache.remove(self.__proc.pid)

        if self.is_cancelled:
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        if return_code != 0:
            err = (await self.__proc.stderr.read()).decode()
            await rep.report(f"FFmpeg failed: {err}", "error")
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        if await aiopath.exists(self.__ram_output):
            shutil.move(self.__ram_output, self.out_path)

        if await aiopath.exists(self.__ram_input):
            await aiorename(self.__ram_input, self.dl_path)

        return self.out_path

    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc:
            try:
                self.__proc.kill()
            except:
                pass
