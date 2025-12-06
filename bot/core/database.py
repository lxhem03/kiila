from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var
from datetime import datetime
import pytz

ist = pytz.timezone('Asia/Kolkata')

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]
        self.__rss_tasks = self.__db.rss_tasks
        self.__today_airing = self.__db.today_airing

    async def getAnime(self, ani_id):
        botset = await self.__animes.find_one({'_id': ani_id})
        return botset or {}

    async def saveAnime(self, ani_id, ep, qual, post_id=None):
        quals = (await self.getAnime(ani_id)).get(ep, {qual: False for qual in Var.QUALS})
        quals[qual] = True
        await self.__animes.update_one({'_id': ani_id}, {'$set': {ep: quals}}, upsert=True)
        if post_id:
            await self.__animes.update_one({'_id': ani_id}, {'$set': {"msg_id": post_id}}, upsert=True)

    async def reboot(self):
        await self.__animes.drop()

    async def get_next_task_id(self):
        result = await self.__rss_tasks.find_one_and_update(
            {"_id": "TASK_COUNTER"},
            {"$inc": {"count": 1}},
            upsert=True,
            return_document=True
        )
        return result["count"]

    async def add_rss_task(self, rss_link: str, custom_name: str, keywords: str = "", avoid_keywords: str = "", final_title: str = None, anilist_id: int = None):
        task_id = await self.get_next_task_id()
        doc = {
            "task_id": task_id,
            "rss_link": rss_link,
            "custom_name": custom_name.strip(),
            "keywords": keywords.strip().lower(),
            "avoid_keywords": avoid_keywords.strip().lower(),
            "final_title": final_title or custom_name.strip(),
            "anilist_id": anilist_id,
            "processed_items": [],
            "active": True,
            "added_at": datetime.utcnow()
        }
        await self.__rss_tasks.insert_one(doc)
        return task_id, doc

    async def get_all_rss_tasks(self):
        return await self.__rss_tasks.find({"active": True}).sort("task_id").to_list(length=None)

    async def get_rss_task(self, task_id: int):
        return await self.__rss_tasks.find_one({"task_id": task_id, "active": True})

    async def add_processed_item(self, task_id: int, guid: str):
        await self.__rss_tasks.update_one(
            {"task_id": task_id},
            {"$addToSet": {"processed_items": guid}}
        )

    async def is_processed(self, task_id: int, guid: str):
        task = await self.__rss_tasks.find_one(
            {"task_id": task_id, "processed_items": guid}
        )
        return bool(task)

    async def delete_rss_task(self, task_id: int):
        result = await self.__rss_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"active": False}}
        )
        return result  # Now returns UpdateResult (fixes NoneType error)

    async def set_today_airing(self, anilist_id: int, expected_ep: int):
        today = datetime.now(ist).strftime("%Y-%m-%d")
        await self.__today_airing.update_one(
            {"anilist_id": anilist_id, "date": today},
            {"$set": {"expected_ep": expected_ep, "uploaded": False}},
            upsert=True
        )

    async def get_today_airing(self, anilist_id: int):
        today = datetime.now(ist).strftime("%Y-%m-%d")
        return await self.__today_airing.find_one({"anilist_id": anilist_id, "date": today})

    async def mark_today_uploaded(self, anilist_id: int):
        today = datetime.now(ist).strftime("%Y-%m-%d")
        await self.__today_airing.update_one(
            {"anilist_id": anilist_id, "date": today},
            {"$set": {"uploaded": True}}
        )

db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
