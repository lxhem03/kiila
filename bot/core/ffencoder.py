# bot/core/ffencoder.py - fix 

from re import findall 
from math import floor
from time import time
from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, rename as aiorename, path as aiopath
from shlex import split as ssplit
from asyncio import sleep as asleep, gather, create_subprocess_shell, create_task
from asyncio.subprocess import PIPE
import shutil  # ← THIS FIXES CROSS-DEVICE MOVE

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
        self.__prog_file = "/ramdisk/ff_progress.txt"
        
        # FINAL DESTINATION ON SSD
        self.final_path = ospath.join("encode", name)

        self.__start_time = time()

    async def progress(self):
        # Get real duration once
        self.__total_time = await mediainfo(self.dl_path, get_duration=True) or 1.0

        last_percent = 0

        while not (self.__proc is None or self.is_cancelled):
            try:
                async with aiopen(self.__prog_file, 'r') as f:
                    text = await f.read()
            except:
                await asleep(8)
                continue

            if not text.strip():
                await asleep(8)
                continue

            # Extract values safely
            out_time_ms = findall(r"out_time_ms=(\d+)", text)
            total_size = findall(r"total_size=(\d+)", text)

            if not out_time_ms:
                await asleep(8)
                continue

            time_done = int(out_time_ms[-1]) / 1_000_000  # seconds
            current_size = int(total_size[-1]) if total_size else 0

            diff = time() - self.__start_time
            if diff < 1:
                await asleep(8)
                continue

            speed = current_size / diff  # bytes per second

            # ESTIMATED FINAL SIZE = current speed × total duration
            estimated_final_size = int(speed * self.__total_time)

            # Progress percentage
            percent = round((time_done / self.__total_time) * 100, 2)
            if percent == last_percent:  # avoid spam
                await asleep(5)
                continue
            last_percent = percent

            # ETA
            remaining_time = (self.__total_time - time_done) if speed > 0 else 0
            eta = remaining_time / speed if speed > 0 else 0

            # Progress bar
            bar = "█" * floor(percent / 8) + "░" * (12 - floor(percent / 8))

            progress_str = f"""<blockquote>‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b></blockquote>
<blockquote>‣ <b>Status :</b> <i>Encoding {self.__qual}p</i>
    <code>[{bar}]</code> {percent}%</blockquote>
<blockquote>   ‣ <b>Size :</b> {convertBytes(current_size)} → ~{convertBytes(estimated_final_size)}
    ‣ <b>Speed :</b> {convertBytes(speed)}/s
    ‣ <b>Elapsed :</b> {convertTime(diff)}
    ‣ <b>ETA :</b> {convertTime(eta)}</blockquote>
<blockquote>‣ <b>Progress :</b> <code>{Var.QUALS.index(self.__qual) + 1}/{len(Var.QUALS)}</code></blockquote>"""

            await editMessage(self.message, progress_str)

            # Stop when ffmpeg says "progress=end"
            if "progress=end" in text.lower():
                break

            await asleep(6)  # update every ~6 seconds

    async def start_encode(self):
        # Clean old temp files
        for f in [self.__prog_file, self.__ram_input, self.__ram_output]:
            if await aiopath.exists(f):
                await aioremove(f)

        # Create progress file
        async with aiopen(self.__prog_file, 'w'):
            pass

        # Move input to RAM (same device → fast rename)
        await aiorename(self.dl_path, self.__ram_input)

        # Build command
        ffcode = ffargs[self.__qual].format(self.__ram_input, self.__prog_file, self.__ram_output)
        LOGS.info(f"FFmpeg Command: {ffcode}")

        self.__proc = await create_subprocess_shell(ffcode, stdout=PIPE, stderr=PIPE)
        ffpids_cache.append(self.__proc.pid)

        _, return_code = await gather(
            create_task(self.progress()),
            self.__proc.wait()
        )

        ffpids_cache.remove(self.__proc.pid)

        # CANCELLED → restore original
        if self.is_cancelled:
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        # FAILED → restore + report
        if return_code != 0:
            err = (await self.__proc.stderr.read()).decode()
            await rep.report(f"FFmpeg failed: {err}", "error")
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        # SUCCESS → move final file from RAM → SSD using shutil (cross-device safe)
        if await aiopath.exists(self.__ram_output):
            # shutil.move works across devices (copy + delete)
            shutil.move(self.__ram_output, self.final_path)

        # Restore original file
        if await aiopath.exists(self.__ram_input):
            await aiorename(self.__ram_input, self.dl_path)

        return self.final_path

    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc:
            try:
                self.__proc.kill()
            except:
                pass
