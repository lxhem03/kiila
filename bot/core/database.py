from motor.motor_asyncio import AsyncIOMotorClient
from bot import Var
from datetime import datetime

class MongoDB:
    def __init__(self, uri, database_name):
        self.__client = AsyncIOMotorClient(uri)
        self.__db = self.__client[database_name]
        self.__animes = self.__db.animes[Var.BOT_TOKEN.split(':')[0]]
        self.__rss_tasks = self.__db.rss_tasks  # New collection for permanent tasks

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
        """Auto-increment task_id"""
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
            "keywords": keywords.strip(),
            "avoid_keywords": avoid_keywords.strip(),
            "final_title": final_title or custom_name.strip(),
            "anilist_id": anilist_id,
            "active": True,
            "added_at": datetime.utcnow()
        }
        await self.__rss_tasks.insert_one(doc)
        return task_id, doc

    async def get_all_rss_tasks(self):
        return await self.__rss_tasks.find({"active": True}).to_list(length=None)

    async def get_rss_task(self, task_id: int):
        return await self.__rss_tasks.find_one({"task_id": task_id, "active": True})

    async def delete_rss_task(self, task_id: int):
        return await self.__rss_tasks.update_one(
            {"task_id": task_id},
            {"$set": {"active": False}}
        )

    async def deactivate_rss_task(self, task_id: int):
        await self.delete_rss_task(task_id)  # same for now

db = MongoDB(Var.MONGO_URI, "FZAutoAnimes")
