from calendar import month_name
from datetime import datetime
from random import choice
from anitopy import parse

from bot import Var
from .ffencoder import ffargs
from .func_utils import handle_logs
from .reporter import rep

from AnilistPython import Anilist
anilist = Anilist() 

CAPTION_FORMAT = """
<b>㊂ <i>{title}</i></b>
<b>╭┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅</b>
<b>Genres:</b> <i>{genres}</i>
<b>Episode:</b> <i>{ep_no}</i>
<b>Audio: Japanese</b>
<b>Subtitle: English</b>
<b>╰┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅</b>
<i>{plot}</i>
╭┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅
  <b><i>Powered By</i></b> ~ <b><i>{cred}</i></b>
╰┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅
"""

GENRES_EMOJI = {"Action": "👊", "Adventure": choice(['🪂', '🧗‍♀']), "Comedy": "🤣", "Drama": " 🎭", "Ecchi": choice(['💋', '🥵']), "Fantasy": choice(['🧞', '🧞‍♂', '🧞‍♀','🌗']), "Hentai": "🔞", "Horror": "☠", "Mahou Shoujo": "☯", "Mecha": "🤖", "Music": "🎸", "Mystery": "🔮", "Psychological": "♟", "Romance": "💞", "Sci-Fi": "🛸", "Slice of Life": choice(['☘','🍁']), "Sports": "⚽️", "Supernatural": "🫧", "Thriller": choice(['🥶', '🔪','🤯'])}

class TextEditor:
    def __init__(self, name):
        self.__name = name
        self.adata = {}
        self.pdata = parse(name)

    async def load_anilist(self, anilist_id: int = None, custom_name: str = None):
        """
        Smart loader — priority:
        1. By AniList ID (100% accurate)
        2. By custom_name
        3. Fallback to parsed title
        """
        if anilist_id:
            try:
                data = anilist.get_anime_with_id(anilist_id)
                if data:
                    self.adata = self._convert_data(data, anilist_id)
                    return
            except:
                pass

        search_name = custom_name or self.pdata.get("anime_title") or self.__name
        if search_name:
            try:
                data = anilist.get_anime(search_name)
                if data:
                    aid = anilist.get_anime_id(search_name)
                    self.adata = self._convert_data(data, aid if aid != -1 else None)
                    return
            except:
                pass

        # Final fallback
        self.adata = {}

    def _convert_data(self, data: dict, anilist_id):
        desc = data.get("desc", "") or ""
        desc = desc.replace("<br>", "\n").replace("<i>", "*").replace("</i>", "*")
        if len(desc) > 300:
            desc = desc[:297] + "..."

        return {
            "id": anilist_id,
            "title": {
                "english": data.get("name_english"),
                "romaji": data.get("name_romaji"),
                "native": data.get("name_romaji")
            },
            "description": desc,
            "genres": data.get("genres", []),
            "averageScore": data.get("average_score"),
            "episodes": data.get("airing_episodes") or "??"
        }

    @handle_logs
    async def get_id(self):
        return self.adata.get("id")

    @handle_logs
    async def get_poster(self):
        if aid := self.adata.get("id"):
            return f"https://img.anili.st/media/{aid}"
        return "https://telegra.ph/file/112ec08e59e73b6189a20.jpg"

    @handle_logs
    async def get_upname(self, qual="", custom_title=None):
        title = custom_title or self.pdata.get("anime_title")
        
        season_num = "1"
        if s := self.pdata.get("anime_season"):
            if isinstance(s, list):
                season_num = str(s[-1]) if s else "1"
            else:
                season_num = str(s)

        ep = self.pdata.get("episode_number") or "??"
        quality = f"{qual}p" if qual else ""
        sub = "Sub"

        return f"[S{season_num}-E{ep}] {title} [{quality}] [{sub}] {Var.BRAND_UNAME}.mkv"

    @handle_logs
    async def get_caption(self):
        titles = self.adata.get("title", {})
        title = titles.get("english") or titles.get("romaji")
        genres = ", ".join(f"{GENRES_EMOJI.get(g, 'Film')} #{g.replace(' ', '_')}" for g in (self.adata.get("genres") or []))
        plot = self.adata.get("description", "No description available.")

        return CAPTION_FORMAT.format(
            title=title,
            genres=genres or "N/A",
            ep_no=self.pdata.get("episode_number") or "??",
            plot=plot,
            cred=Var.BRAND_UNAME
)
