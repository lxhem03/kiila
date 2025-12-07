from time import time
from math import floor
from .func_utils import editMessage, humanbytes

async def progress_for_pyrogram(current, total, message, start_time, ud_type="Downloading"):
    now = time()
    diff = now - start_time

    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed = int(diff)
        eta = int((total - current) / speed) if speed > 0 else 0

        # Time formatter
        def time_fmt(secs):
            mins, secs = divmod(secs, 60)
            hours, mins = divmod(mins, 60)
            return f"{hours}h {mins}m {secs}s" if hours else f"{mins}m {secs}s" if mins else f"{secs}s"

        bar = "█" * int(percentage / 5) + "░" * (20 - int(percentage / 5))

        text = f"""
**{ud_type}**

{bar} {percentage:.1f}%

**Done:** {humanbytes(current)} / {humanbytes(total)}
**Speed:** {humanbytes(speed)}/s
**Elapsed:** {time_fmt(elapsed)}
**ETA:** {time_fmt(eta)}
"""

        try:
            await editMessage(message, text)
        except:
            pass
