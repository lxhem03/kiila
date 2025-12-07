from os import path as ospath
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove as aioremove, mkdir
from aiohttp import ClientSession
import re

from torrentp import TorrentDownloader
from bot import LOGS
from bot.core.func_utils import handle_logs
from bot.core.reporter import rep

class TorDownloader:
    def __init__(self, path="."):
        self.__downdir = path
        self.__torpath = "torrents/"

    @handle_logs
    async def download(self, torrent, name=None):
        try:
            if torrent.startswith("magnet:"):
                # Fix common broken magnets (missing &dn= or invalid encoding)
                if "dn=" not in torrent:
                    clean_name = re.sub(r"[^\w\s\-–—()]+", "", name or "Unknown").strip()
                    clean_name = re.sub(r"\s+", ".", clean_name)
                    torrent += f"&dn={clean_name}"

                torp = TorrentDownloader(torrent, self.__downdir)
                await torp.start_download()
                # Fallback name if torrent has no name
                final_path = ospath.join(self.__downdir, name or "Unknown_Anime")
                return final_path

            elif torrent.endswith(".torrent") or "nyaa.si/download" in torrent:
                torfile = await self.get_torfile(torrent)
                if not torfile:
                    return None

                torp = TorrentDownloader(torfile, self.__downdir)
                await torp.start_download()
                await aioremove(torfile)

                try:
                    torrent_name = torp._torrent_info._info.name()
                    return ospath.join(self.__downdir, torrent_name)
                except:
                    return ospath.join(self.__downdir, name or "Unknown_Anime")

        except Exception as e:
            await rep.report(f"TorDownloader failed: {e}\nTorrent: {torrent}", "error")
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
