from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove as aioremove, mkdir
from aiohttp import ClientSession
import re

from torrentp import TorrentDownloader
from bot import LOGS
from bot.core.func_utils import handle_logs
from bot.core.reporter import rep

from time import time
from bot.core.progress import progress_for_pyrogram

class TorDownloader:
    def __init__(self, path="."):
        self.__downdir = path
        self.__torpath = "torrents/"

    @handle_logs
    async def download(self, torrent, name=None):
        try:
            # Create status message
            status_msg = await sendMessage(Var.MAIN_CHANNEL, "<i>Starting download...</i>")
            start_time = time()

            if torrent.startswith("magnet:"):
                if "dn=" not in torrent and name:
                    clean_name = re.sub(r"[^\w\s\-–—()]+", "", name).strip()
                    clean_name = re.sub(r"\s+", ".", clean_name)
                    torrent += f"&dn={clean_name}"

                torp = TorrentDownloader(torrent, self.__downdir)

                # Hook progress callback
                async def progress_callback(transferred, total):
                    await progress_for_pyrogram(transferred, total, status_msg, start_time, f"Downloading: {name or 'Unknown'}")

                torp.progress_callback = progress_callback
                await torp.start_download()

                final_path = ospath.join(self.__downdir, name or "Unknown_Anime")
            else:
                torfile = await self.get_torfile(torrent)
                if not torfile:
                    await editMessage(status_msg, "Failed to download .torrent file")
                    return None

                torp = TorrentDownloader(torfile, self.__downdir)
                async def progress_callback(transferred, total):
                    await progress_for_pyrogram(transferred, total, status_msg, start_time, "Downloading torrent file...")

                torp.progress_callback = progress_callback
                await torp.start_download()
                await aioremove(torfile)

                try:
                    final_path = ospath.join(self.__downdir, torp._torrent_info._info.name())
                except:
                    final_path = ospath.join(self.__downdir, name or "Unknown_Anime")

            await editMessage(status_msg, f"Download Complete for {name}\n\nMoving to encoding ⚙️")
            await rep.report(f"Download Complete for {name}\n\nFile Path:\n<code>{final_path}</code>", "info")

            return final_path

        except Exception as e:
            await rep.report(f"TorDownloader failed: {e}", "error")
            if 'status_msg' in locals():
                await editMessage(status_msg, f"Download failed: {str(e)}")
            return None

    @handle_logs
    async def get_torfile(self, url):
        if not await aiopath.isdir(self.__torpath):
            await mkdir(self.__torpath)

        tor_name = url.split('/')[-1].split('?')[0]
        if not tor_name.endswith(".torrent"):
            tor_name = "temp.torrent"
        des_dir = ospath.join(self.__torpath, tor_name)

        try:
            async with ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        async with aiopen(des_dir, 'wb') as f:
                            async for chunk in response.content.iter_chunked(1024*1024):
                                await f.write(chunk)
                        return des_dir
        except Exception as e:
            await rep.report(f"Failed to download .torrent: {e}", "warning")
        return None
