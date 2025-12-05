from AnilistPython import Anilist
anilist = Anilist()

async def resolve_anilist_title_and_id(guess_name: str):
    """
    Tries to get proper English/Romaji title + AniList ID using user's custom name as guess.
    Returns (final_title: str, anilist_id: int) or (guess_name, None) on failure.
    """
    try:
        data = anilist.get_anime(guess_name)
        if not data:
            return guess_name, None

        english = data.get("name_english")
        romaji = data.get("name_romaji")

        preferred = english if english and english.lower() != "none" else romaji
        if not preferred:
            return guess_name, None

        anime_id = anilist.get_anime_id(guess_name)
        return preferred.strip(), anime_id if anime_id != -1 else None
    except Exception as e:
        print(f"[AniList Error] {e}")
        return guess_name, None
