from re import findall
from math import floor
from time import time
from os import path as ospath
from aiofiles.os import remove as aioremove, path as aiopath
from asyncio import sleep as asleep, gather, create_subprocess_shell, create_task
from asyncio.subprocess import PIPE, DEVNULL
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

UPDATE_INTERVAL = 10  # seconds between Telegram message edits


class FFEncoder:
    def __init__(self, message, path, name, qual):
        self.__proc = None
        self.is_cancelled = False
        self.message = message
        self.__name = name
        self.__qual = qual
        self.dl_path = path
        self.__total_time = None
        self.final_path = ospath.join("encode", name)
        self.__start_time = time()

    # ------------------------------------------------------------------
    # STDERR DRAIN  — keeps the stderr pipe from blocking FFmpeg
    # ------------------------------------------------------------------
    async def __drain_stderr(self):
        try:
            while True:
                line = await self.__proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if text:
                    LOGS.debug(f"FFmpeg stderr: {text}")
        except Exception as e:
            LOGS.debug(f"stderr drain ended: {e}")

    # ------------------------------------------------------------------
    # PROGRESS MONITOR — reads structured key=value blocks from stdout
    # ------------------------------------------------------------------
    async def progress(self):
        self.__total_time = await mediainfo(self.dl_path, get_duration=True) or 1800.0

        # --- get total frames + fps via ffprobe ---
        total_frames = None
        fps = 30.0
        try:
            cmd = (
                f"ffprobe -v error -select_streams v:0 "
                f"-show_entries stream=nb_frames,r_frame_rate "
                f"-of default=noprint_wrappers=1 "
                f"{shlex.quote(self.dl_path)}"
            )
            probe = await create_subprocess_shell(cmd, stdout=PIPE, stderr=DEVNULL)
            out, _ = await probe.communicate()
            for line in out.decode("utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("nb_frames="):
                    try:
                        total_frames = int(line.split("=", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("r_frame_rate="):
                    fps_str = line.split("=", 1)[1]
                    if "/" in fps_str:
                        try:
                            num, den = map(int, fps_str.split("/"))
                            if den:
                                fps = num / den
                        except Exception:
                            pass
                    else:
                        try:
                            fps = float(fps_str)
                        except Exception:
                            pass
        except Exception as e:
            LOGS.warning(f"ffprobe failed: {e}")

        if total_frames is None:
            total_frames = int(self.__total_time * fps)

        LOGS.info(f"Progress monitor: total_frames={total_frames} fps={fps}")

        progress_dict = {}
        last_update_time = 0.0
        current_frame = 0
        current_fps = fps
        speed = 1.0

        try:
            while True:
                line = await self.__proc.stdout.readline()
                if not line:
                    break  # FFmpeg exited / EOF

                if self.is_cancelled:
                    break

                text = line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue

                # parse key=value
                if "=" in text:
                    k, v = text.split("=", 1)
                    progress_dict[k.strip()] = v.strip()

                # FFmpeg emits a "progress" key at the end of each stats block
                if "progress" not in progress_dict:
                    continue

                # encoding finished
                if progress_dict.get("progress") == "end":
                    LOGS.info("FFmpeg reported progress=end")
                    break

                # --- parse block values ---
                try:
                    frame_str = progress_dict.get("frame", "0")
                    current_frame = int(frame_str) if frame_str.isdigit() else current_frame
                except Exception:
                    pass

                try:
                    fps_str = progress_dict.get("fps", "")
                    if fps_str and fps_str.upper() != "N/A":
                        val = float(fps_str)
                        if val > 0:
                            current_fps = val
                except Exception:
                    pass

                try:
                    sp = progress_dict.get("speed", "1x")
                    if sp and sp.upper() != "N/A":
                        speed = float(sp.replace("x", ""))
                    if speed <= 0:
                        speed = 1.0
                except Exception:
                    pass

                progress_dict.clear()

                # --- throttle Telegram edits ---
                now = time()
                if now - last_update_time < UPDATE_INTERVAL:
                    continue
                last_update_time = now

                # --- build UI ---
                percent = round(min((current_frame / total_frames) * 100, 100), 1)
                elapsed = now - self.__start_time
                remaining_frames = max(0, total_frames - current_frame)
                eta = remaining_frames / (current_fps * speed) if current_fps > 0 else 0

                bar = "█" * int(percent // 8) + "░" * (12 - int(percent // 8))

                progress_str = (
                    f"<blockquote>‣ <b>Anime Name :</b> <b><i>{self.__name}</i></b></blockquote>\n\n"
                    f"<blockquote>‣ <b>Status :</b> <i>Encoding {self.__qual}p</i>\n"
                    f"    <code>[{bar}]</code> {percent}%</blockquote>\n"
                    f"<blockquote>   ‣ <b>Speed :</b> {speed:.2f}x ({current_fps:.1f} fps)\n"
                    f"    ‣ <b>Elapsed :</b> {convertTime(elapsed)}\n"
                    f"    ‣ <b>ETA :</b> {convertTime(eta)}</blockquote>\n"
                    f"<blockquote>‣ <b>Progress :</b> <code>{Var.QUALS.index(self.__qual)+1}/{len(Var.QUALS)}</code></blockquote>"
                )

                await editMessage(self.message, progress_str)

        except Exception as e:
            LOGS.error(f"Progress loop error: {e}")

        await asleep(2)

    # ------------------------------------------------------------------
    # MAIN ENCODE FLOW  — no RAM disk, direct file encode
    # ------------------------------------------------------------------
    async def start_encode(self):
        # 1️⃣ Build FFmpeg command
        # The FFCODE strings already wrap {} in single quotes e.g. -i '{}'
        # so do NOT use shlex.quote() — it would double-quote the paths.
        raw_cmd = ffargs[self.__qual].format(self.dl_path, self.final_path)

        # Strip flags that suppress stdout (they break -progress pipe:1)
        for flag in ["-loglevel error", "-loglevel quiet", "-nostats", "-hide_banner"]:
            raw_cmd = raw_cmd.replace(flag, "")

        # Inject -progress pipe:1 right after the ffmpeg binary
        ffcode = raw_cmd.replace("ffmpeg ", "ffmpeg -progress pipe:1 ", 1)

        # Collapse any extra whitespace left by the removals
        ffcode = " ".join(ffcode.split())
        LOGS.info(f"FFmpeg Command: {ffcode}")

        await editMessage(
            self.message,
            f"<i>Encoding {self.__qual}p… (FFmpeg warming up)</i>"
        )

        # 2️⃣ Launch FFmpeg
        self.__proc = await create_subprocess_shell(
            ffcode,
            stdout=PIPE,   # structured progress lives here
            stderr=PIPE    # encoder logs/warnings (drained async)
        )

        ffpids_cache.append(self.__proc.pid)

        # 3️⃣ Run progress reader + stderr drain + wait concurrently
        _, _, return_code = await gather(
            create_task(self.progress()),
            create_task(self.__drain_stderr()),
            self.__proc.wait()
        )

        if self.__proc.pid in ffpids_cache:
            ffpids_cache.remove(self.__proc.pid)

        # 4️⃣ Cancelled?
        if self.is_cancelled:
            return None

        # 5️⃣ FFmpeg failed?
        if return_code != 0:
            LOGS.error(f"FFmpeg exited with code {return_code}")
            await rep.report(f"FFmpeg failed (exit {return_code}) for {self.__name}", "error")
            return None

        # 6️⃣ Verify output exists
        if not await aiopath.exists(self.final_path):
            LOGS.error("FFmpeg finished but output file not found!")
            await rep.report(f"Output missing after encode: {self.final_path}", "error")
            return None

        return self.final_path

    # ------------------------------------------------------------------
    async def cancel_encode(self):
        self.is_cancelled = True
        if self.__proc:
            try:
                self.__proc.kill()
            except Exception:
                pass
