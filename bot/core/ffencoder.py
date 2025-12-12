# bot/core/ffencoder.py — FULL RAM ENCODING + EXTRA LOGGING + WARMING UP MESSAGE

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
        self.dl_path = path  # Original download in /ramdisk
        self.__total_time = None
        
        # ALL TEMP FILES IN RAM
        self.__ram_input = "/ramdisk/ff_temp_input.mkv"
        self.__ram_output = "/ramdisk/ff_temp_output.mkv"
        self.__prog_file = "/ramdisk/prog.txt"
        
        # FINAL DESTINATION ON SSD
        self.final_path = ospath.join("encode", name)

        self.__start_time = time()

    async def progress(self):
        self.__total_time = await mediainfo(self.dl_path, get_duration=True) or 1800.0
        LOGS.info(f"Progress monitoring started for {self.__name} ({self.__qual}p) | Duration: {self.__total_time}s")

        last_percent = -1

        while not (self.__proc is None or self.is_cancelled):
            try:
                if not await aiopath.exists(self.__prog_file):
                    LOGS.info("Progress file not found — sleeping 5s")
                    await asleep(5)
                    continue

                async with aiopen(self.__prog_file, 'r') as f:
                    text = await f.read()
                LOGS.info(f"Read progress file: {len(text)} bytes")

                if not text.strip():
                    LOGS.info("Progress file empty — sleeping 5s")
                    await asleep(5)
                    continue

                # Extract out_time_ms and speed safely
                out_time_ms = findall(r"out_time_ms=(\d+)", text)
                speed_match = findall(r"speed=([\d.]+)x", text)

                if not out_time_ms:
                    LOGS.info("No out_time_ms in progress — sleeping 5s")
                    await asleep(5)
                    continue

                current_time = int(out_time_ms[-1]) / 1_000_000
                percent = round((current_time / self.__total_time) * 100, 1)

                speed = float(speed_match[-1]) if speed_match else 1.0

                if abs(percent - last_percent) < 0.5:
                    LOGS.info(f"Percent unchanged ({percent}%) — sleeping 5s")
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
                LOGS.info(f"Progress updated to {percent}%")

                if "progress=end" in text:
                    LOGS.info("Encoding complete — progress=end detected")
                    break

            except Exception as e:
                LOGS.error(f"Progress loop error: {e}")
                await asleep(10)

            await asleep(6)

    async def start_encode(self):
        # Clean old temp files
        for f in [self.__prog_file, self.__ram_input, self.__ram_output]:
            if await aiopath.exists(f):
                await aioremove(f)

        # Create empty progress file in RAM
        async with aiopen(self.__prog_file, 'w'):
            pass
        LOGS.info("Progress file created")

        # Move input to RAM
        await aiorename(self.dl_path, self.__ram_input)
        LOGS.info("Input moved to RAM")

        # Build command
        ffcode = ffargs[self.__qual].format(self.__ram_input, self.__prog_file, self.__ram_output)
        LOGS.info(f'FFmpeg Command: {ffcode}')

        self.__proc = await create_subprocess_shell(ffcode, stdout=PIPE, stderr=PIPE)
        LOGS.info("FFmpeg process started")

        ffpids_cache.append(self.__proc.pid)

        # Warm up message
        await editMessage(self.message, f"<i>Encoding {self.__qual}p... (Warming up x265 — may take 30–60 seconds)</i>")

        _, return_code = await gather(
            create_task(self.progress()),
            self.__proc.wait()
        )

        ffpids_cache.remove(self.__proc.pid)

        # Cancelled
        if self.is_cancelled:
            LOGS.info("Encoding cancelled")
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        # Failed
        if return_code != 0:
            err = (await self.__proc.stderr.read()).decode()
            LOGS.error(f"FFmpeg failed: {err}")
            await rep.report(f"FFmpeg failed: {err}", "error")
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        # Success — move final from RAM to SSD with shutil
        if await aiopath.exists(self.__ram_output):
            shutil.move(self.__ram_output, self.final_path)
            LOGS.info("Final file moved to SSD")

        # Restore original file
        if await aiopath.exists(self.__ram_input):
            await aiorename(self.__ram_input, self.dl_path)
            LOGS.info("Original file restored")

        # Clean progress file
        try:
            await aioremove(self.__prog_file)
            LOGS.info("Progress file cleaned")
        except:
            pass

        return self.final_path

    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc:
            try:
                self.__proc.kill()
                LOGS.info("FFmpeg process killed")
            except:
                pass
