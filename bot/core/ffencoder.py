from re import findall
from math import floor
from time import time
from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, rename as aiorename, path as aiopath
from asyncio import sleep as asleep, gather, create_subprocess_shell, create_task
from asyncio.subprocess import PIPE, DEVNULL
import shutil
import shlex

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

    # ------------------------------------------------------------------
    # FFmpeg VALIDATION (NO ENCODING, NO RAM MOVE)
    # ------------------------------------------------------------------
    async def validate_ffmpeg(self):
        """
        Validates FFmpeg arguments, filters, and encoders.
        Does NOT encode, does NOT touch RAM, does NOT create output.
        Catches syntax / drawtext / encoder init errors early.
        """
        validate_cmd = (
            "ffmpeg -loglevel error -nostats -hide_banner "
            f"-i {shlex.quote(self.dl_path)} "
            '-vf '
            "\"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
            "text='validation':x=0:y=0:fontsize=12:fontcolor=white\" "
            "-f null -"
        )

        LOGS.info(f"Validating FFmpeg command: {validate_cmd}")

        proc = await create_subprocess_shell(
            validate_cmd,
            stdout=DEVNULL,
            stderr=PIPE
        )

        _, err = await proc.communicate()

        if proc.returncode != 0:
            error_text = err.decode(errors="ignore")
            LOGS.error(f"FFmpeg validation failed: {error_text}")
            await rep.report(f"FFmpeg validation failed:\n{error_text}", "error")
            return False

        LOGS.info("FFmpeg validation successful")
        return True

    # ------------------------------------------------------------------
    # PROGRESS MONITOR (IMPROVED ffprobe HANDLING)
    # ------------------------------------------------------------------
    async def progress(self):
        self.__total_time = await mediainfo(self.dl_path, get_duration=True) or 1800.0
        LOGS.info(f"Progress monitoring started | Duration: {self.__total_time}s")

        total_frames = None
        fps = 30.0

        # Use async subprocess for ffprobe to avoid blocking the event loop
        try:
            cmd = [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=nb_frames,r_frame_rate',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                self.dl_path
            ]
            proc = await create_subprocess_shell(
                ' '.join(cmd),
                stdout=PIPE,
                stderr=DEVNULL
            )
            out, _ = await proc.communicate()
            lines = out.decode('utf-8').strip().splitlines()

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if 'nb_frames' in line or total_frames is None:  # Prefer nb_frames if available
                    try:
                        total_frames = int(line)
                        continue
                    except ValueError:
                        pass
                try:
                    num, den = map(int, line.split('/'))
                    fps = num / den if den else 30.0
                except:
                    pass

        except Exception as e:
            LOGS.warning(f"Async ffprobe failed: {e}")

        if total_frames is None:
            total_frames = int(self.__total_time * fps)

        LOGS.info(f"Calculated total_frames: {total_frames} | fps: {fps}")

        last_percent = -1
        current_frame = 0

        global last_update_time

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

                frame_match = findall(r"frame=\s*(\d+)", text)
                fps_match = findall(r"fps=\s*([\d.]+)", text)
                speed_match = findall(r"speed=\s*([\d.]+)x", text)

                if frame_match:
                    current_frame = int(frame_match[-1])

                current_fps = float(fps_match[-1]) if fps_match else fps
                speed = float(speed_match[-1]) if speed_match else 1.0

                percent = round((current_frame / total_frames) * 100, 1)
                now = time()

                if abs(percent - last_percent) < 0.1 and now - last_update_time < UPDATE_INTERVAL:
                    await asleep(5)
                    continue

                last_percent = percent
                last_update_time = now

                diff = time() - self.__start_time
                remaining_frames = max(0, total_frames - current_frame)
                eta = remaining_frames / (current_fps * speed) if current_fps > 0 else 0

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
                    break

            except Exception as e:
                LOGS.error(f"Progress error: {e}")
                await asleep(10)

        await asleep(5)

    # ------------------------------------------------------------------
    # MAIN ENCODE FLOW (RAM LOGIC UNTOUCHED)
    # ------------------------------------------------------------------
    async def start_encode(self):
        # 1️⃣ Validate FFmpeg FIRST
        if not await self.validate_ffmpeg():
            return None

        # 2️⃣ Clean old temp files
        for f in [self.__prog_file, self.__ram_output]:
            if await aiopath.exists(f):
                await aioremove(f)

        async with aiopen(self.__prog_file, 'w'):
            pass

        # 3️⃣ Move input to RAM
        await aiorename(self.dl_path, self.__ram_input)

        # 4️⃣ Build FFmpeg command
        ffcode = ffargs[self.__qual].format(self.__ram_input, self.__ram_output)
        LOGS.info(f'FFmpeg Command: {ffcode}')

        self.__proc = await create_subprocess_shell(
            ffcode,
            stdout=DEVNULL,
            stderr=PIPE
        )

        ffpids_cache.append(self.__proc.pid)

        await editMessage(self.message, f"<i>Encoding {self.__qual}p... (x265 warm‑up)</i>")

        _, return_code = await gather(
            create_task(self.progress()),
            self.__proc.wait()
        )

        if self.__proc.pid in ffpids_cache:
            ffpids_cache.remove(self.__proc.pid)

        if self.is_cancelled:
            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        if return_code != 0:
            err = await self.__proc.stderr.read()
            error_text = err.decode(errors='ignore')
            LOGS.error(f"FFmpeg failed: {error_text}")
            await rep.report(f"FFmpeg failed:\n{error_text}", "error")

            if await aiopath.exists(self.__ram_input):
                await aiorename(self.__ram_input, self.dl_path)
            return None

        # 6️⃣ Move output from RAM
        if await aiopath.exists(self.__ram_output):
            shutil.move(self.__ram_output, self.final_path)

        if await aiopath.exists(self.__ram_input):
            await aiorename(self.__ram_input, self.dl_path)

        try:
            await aioremove(self.__prog_file)
        except:
            pass

        return self.final_path

    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc:
            try:
                self.__proc.kill()
            except:
                pass
