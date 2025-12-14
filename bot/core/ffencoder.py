# bot/core/ffencoder.py - FULL RAM ENCODING + CORRECT INDENTATION + PROGRESS BAR WORKING

from re import findall 
from math import floor
from time import time
from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, rename as aiorename, path as aiopath
from asyncio import sleep as asleep, gather, create_subprocess_shell, create_task
from asyncio.subprocess import PIPE
import shutil

from bot import Var, bot_loop, ffpids_cache, LOGS
from .func_utils import mediainfo, convertBytes, convertTime, editMessage
from .reporter import rep

ffargs = {
    '1080': Var.FFCODE_1080,
    '720': Var.FFCODE_720,
    '480': Var.FFCODE_480,
    '360': Var.FFCODE_360,
}

last_update_time = 0
UPDATE_INTERVAL = 10

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
        self.__prog_file = "/ramdisk/prog.txt"
        self.final_path = ospath.join("encode", name)

        self.__start_time = time()


    async def progress(self):
        self.__total_time = await mediainfo(self.dl_path, get_duration=True) or 1800.0
        LOGS.info(f"Progress monitoring started | Duration: {self.__total_time}s")

        # Get video FPS and total frames (best effort)
        total_frames = None
        fps = 30.0
        try:
            import subprocess
            cmd = [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=nb_frames,r_frame_rate',
                '-of', 'default=noprint_wrappers=1',
                self.dl_path
            ]
            out = subprocess.check_output(cmd).decode('utf-8').strip().splitlines()
            for line in out:
                if line.startswith('nb_frames='):
                    try:
                        total_frames = int(line.split('=', 1)[1])
                    except:
                        pass
                elif line.startswith('r_frame_rate='):
                    try:
                        num, den = map(int, line.split('=', 1)[1].split('/'))
                        fps = num / den if den != 0 else 30.0
                    except:
                        pass
            LOGS.info(f"Detected: total_frames={total_frames}, fps={fps}")
        except Exception as e:
            LOGS.warning(f"ffprobe failed: {e}")

        # Fallback estimation
        if total_frames is None and self.__total_time > 0:
            total_frames = int(self.__total_time * fps)
            LOGS.info(f"Estimated total_frames: {total_frames}")

        last_percent = -1
        current_frame = 0

        while not (self.__proc is None or self.is_cancelled):
            try:
                if not await aiopath.exists(self.__prog_file):
                    await asleep(5)
                    continue

                async with aiopen(self.__prog_file, 'r') as f:
                    text = await f.read()

                if not text.strip():
                    await asleep(5)
                    continue

                # Extract frame and fps
                frame_match = findall(r"frame=\s*(\d+)", text)
                fps_match = findall(r"fps=\s*([\d.]+)", text)
                speed_match = findall(r"speed=\s*([\d.]+)x", text)

                if frame_match:
                    current_frame = int(frame_match[-1])

                current_fps = float(fps_match[-1]) if fps_match else fps
                speed = float(speed_match[-1]) if speed_match else 1.0

                # Calculate percent from frames
                if total_frames and total_frames > 0:
                    percent = round((current_frame / total_frames) * 100, 1)
                else:
                    percent = 0

                now = time()

                should_update = False

                if abs(percent - last_percent) >= 0.1:
                should_update = True

                elif now - last_update_time >= UPDATE_INTERVAL:
                    should_update = True

                if not should_update:
                    await asleep(5)
                    continue

                last_percent = percent
                last_update_time = now
                diff = time() - self.__start_time

                # ETA from remaining frames
                remaining_frames = max(0, total_frames - current_frame) if total_frames else 0
                eta = remaining_frames / (current_fps * speed) if current_fps > 0 and speed > 0 else 0

                bar = "█" * int(percent // 8) + "░" * (12 - int(percent // 8))

                progress_str = f"""<blockquote>‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b></blockquote>
<blockquote>‣ <b>Status :</b> <i>Encoding {self.__qual}p</i>
    <code>[{bar}]</code> {percent}%</blockquote>
<blockquote>   ‣ <b>Speed :</b> {speed:.2f}x ({current_fps:.1f} fps)
    ‣ <b>Elapsed :</b> {convertTime(diff)}
    ‣ <b>ETA :</b> {convertTime(eta)}</blockquote>
<blockquote>‣ <b>Progress :</b> <code>{Var.QUALS.index(self.__qual)+1}/{len(Var.QUALS)}</code></blockquote>"""

                await editMessage(self.message, progress_str)

                if "progress=end" in text:
                    LOGS.info("Encoding completed")
                    break

            except Exception as e:
                LOGS.error(f"Progress error: {e}")
                await asleep(10)

        await asleep(5)

    async def start_encode(self):
        # Clean old temp files
        for f in [self.__prog_file, self.__ram_input, self.__ram_output]:
            if await aiopath.exists(f):
                await aioremove(f)

        # Create progress file in RAM
        async with aiopen(self.__prog_file, 'w'):
            pass
        LOGS.info("Progress file created")

        # Move input to RAM
        await aiorename(self.dl_path, self.__ram_input)
        LOGS.info("Input moved to RAM")

        # Build command
        ffcode = ffargs[self.__qual].format(self.__ram_input, self.__ram_output)
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

        if self.is_cancelled:
            LOGS.info("Encoding cancelled")
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        if return_code != 0:
            err = (await self.__proc.stderr.read()).decode()
            LOGS.error(f"FFmpeg failed: {err}")
            await rep.report(f"FFmpeg failed: {err}", "error")
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        # Success — move final from RAM to SSD
        if await aiopath.exists(self.__ram_output):
            shutil.move(self.__ram_output, self.final_path)
            LOGS.info("Final file moved to SSD")

        # Restore original
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
