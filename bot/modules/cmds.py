from asyncio import sleep as asleep, gather
from pyrogram.filters import command, private, user
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, MessageNotModified
from bot import bot, bot_loop, Var, ani_cache
from bot.core.database import db
from bot.core.func_utils import decode, is_fsubbed, get_fsubs, editMessage, sendMessage, new_task, convertTime, getfeed
from bot.core.auto_animes import get_animes
from bot.core.reporter import rep
from bot.core.anilist_helper import resolve_anilist_title_and_id

@bot.on_message(command('start') & private)
@new_task
async def start_msg(client, message):
    uid = message.from_user.id
    from_user = message.from_user
    txtargs = message.text.split()
    temp = await sendMessage(message, "<i>Connecting..</i>")
    if not await is_fsubbed(uid):
        txt, btns = await get_fsubs(uid, txtargs)
        return await editMessage(temp, txt, InlineKeyboardMarkup(btns))
    if len(txtargs) <= 1:
        await temp.delete()
        btns = []
        for elem in Var.START_BUTTONS.split():
            try:
                bt, link = elem.split('|', maxsplit=1)
            except:
                continue
            if len(btns) != 0 and len(btns[-1]) == 1:
                btns[-1].insert(1, InlineKeyboardButton(bt, url=link))
            else:
                btns.append([InlineKeyboardButton(bt, url=link)])
        smsg = Var.START_MSG.format(first_name=from_user.first_name,
                                    last_name=from_user.first_name,
                                    mention=from_user.mention, 
                                    user_id=from_user.id)
        if Var.START_PHOTO:
            await message.reply_photo(
                photo=Var.START_PHOTO, 
                caption=smsg,
                reply_markup=InlineKeyboardMarkup(btns) if len(btns) != 0 else None
            )
        else:
            await sendMessage(message, smsg, InlineKeyboardMarkup(btns) if len(btns) != 0 else None)
        return
    try:
        arg = (await decode(txtargs[1])).split('-')
    except Exception as e:
        await rep.report(f"User : {uid} | Error : {str(e)}", "error")
        await editMessage(temp, "<b>Input Link Code Decode Failed !</b>")
        return
    if len(arg) == 2 and arg[0] == 'get':
        try:
            fid = int(int(arg[1]) / abs(int(Var.FILE_STORE)))
        except Exception as e:
            await rep.report(f"User : {uid} | Error : {str(e)}", "error")
            await editMessage(temp, "<b>Input Link Code is Invalid !</b>")
            return
        try:
            msg = await client.get_messages(Var.FILE_STORE, message_ids=fid)
            if msg.empty:
                return await editMessage(temp, "<b>File Not Found !</b>")
            nmsg = await msg.copy(message.chat.id, reply_markup=None)
            await temp.delete()
            if Var.AUTO_DEL:
                async def auto_del(msg, timer):
                    await asleep(timer)
                    await msg.delete()
                await sendMessage(message, f'<i>File will be Auto Deleted in {convertTime(Var.DEL_TIMER)}, Forward to Saved Messages Now..</i>')
                bot_loop.create_task(auto_del(nmsg, Var.DEL_TIMER))
        except Exception as e:
            await rep.report(f"User : {uid} | Error : {str(e)}", "error")
            await editMessage(temp, "<b>File Not Found !</b>")
    else:
        await editMessage(temp, "<b>Input Link is Invalid for Usage !</b>")
    
@bot.on_message(command('pause') & private & user(Var.ADMINS))
async def pause_fetch(client, message):
    ani_cache['fetch_animes'] = False
    await sendMessage(message, "`Successfully Paused Fetching Animes...`")

@bot.on_message(command('resume') & private & user(Var.ADMINS))
async def pause_fetch(client, message):
    ani_cache['fetch_animes'] = True
    await sendMessage(message, "`Successfully Resumed Fetching Animes...`")

@bot.on_message(command('log') & private & user(Var.ADMINS))
@new_task
async def _log(client, message):
    await message.reply_document("log.txt", quote=True)


@bot.on_message(command('addtask') & private & user(Var.ADMINS))
@new_task
async def add_task(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or "|" not in args[1]:
        return await sendMessage(message, "<b>Usage:</b>\n`/addtask <rss_link> | Custom Name`")

    rss_part, custom_name = args[1].split("|", 1)
    rss_link = rss_part.strip()
    custom_name = custom_name.strip()

    if not rss_link.startswith("http"):
        return await sendMessage(message, "<b>Invalid RSS link!</b>")

    # Get title from RSS exactly like before
    if not (taskInfo := await getfeed(rss_link, 0)):
        return await sendMessage(message, "<b>Invalid or empty RSS feed!</b>")

    rss_title = taskInfo.title  # This is the proven working title from nyaa

    # Resolve AniList data using custom_name as guess
    final_title, anilist_id = await resolve_anilist_title_and_id(custom_name)

    
    bot_loop.create_task(get_animes(
        name=rss_title,
        torrent=taskInfo.link,
        force=True,
        anilist_id=anilist_id,
        custom_name=custom_name,
        task_id=task_id
    ))

    await sendMessage(message,
        f"<b>Temporary Task Started!</b>\n\n"
        f"• RSS Title: <code>{rss_title}</code>\n"
        f"• Your Name: <code>{custom_name}</code>\n"
        f"• Final Title → <code>{final_title}</code>\n"
        f"• AniList ID: <code>{anilist_id or 'Not found'}</code>"
    )


# ===================== /addlink - PERMANENT AUTO TASK =====================
@bot.on_message(command('addlink') & private & user(Var.ADMINS))
@new_task
async def add_permanent_task(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or "|" not in args[1]:
        return await sendMessage(message,
            "<b>Usage:</b>\n"
            "/addlink <rss_link> | Custom Name | keywords (optional) | avoid keywords (optional)"
        )

    parts = [p.strip() for p in args[1].split("|", 3)]
    if len(parts) < 2:
        return await sendMessage(message, "<b>You must provide RSS link and Custom Name!</b>")

    rss_link = parts[0]
    custom_name = parts[1]
    keywords = parts[2] if len(parts) > 2 else ""
    avoid_keywords = parts[3] if len(parts) > 3 else ""

    if not rss_link.startswith("http"):
        return await sendMessage(message, "<b>Invalid RSS link!</b>")

    # Validate RSS first
    if not (taskInfo := await getfeed(rss_link, 0)):
        return await sendMessage(message, "<b>Invalid or empty RSS feed!</b>")

    rss_title = taskInfo.title

    # Resolve proper title + AniList ID
    final_title, anilist_id = await resolve_anilist_title_and_id(custom_name)

    # Save to DB
    task_id, doc = await db.add_rss_task(
        rss_link=rss_link,
        custom_name=custom_name,
        keywords=keywords,
        avoid_keywords=avoid_keywords,
        final_title=final_title,
        anilist_id=anilist_id
    )

    await sendMessage(message,
        f"<b>Permanent Task Added Successfully!</b>\n\n"
        f"• Task ID: <code>{task_id}</code>\n"
        f"• RSS Title: <code>{rss_title}</code>\n"
        f"• Your Name: <code>{custom_name}</code>\n"
        f"• Final Title → <code>{final_title}</code>\n"
        f"• AniList ID: <code>{anilist_id or 'Not found'}</code>\n"
        f"• Keywords: <code>{keywords or 'None'}</code>\n"
        f"• Avoid: <code>{avoid_keywords or 'None'}</code>\n\n"
        f"<i>Scheduler will be activated when we reach get_animes loop</i>"
    )


# ===================== /listlink =====================
@bot.on_message(command('listlink') & private & user(Var.ADMINS))
@new_task
async def list_tasks(client, message):
    tasks = await db.get_all_rss_tasks()
    if not tasks:
        return await sendMessage(message, "<i>No permanent tasks found.</i>")

    text = "<b>Permanent RSS Tasks:</b>\n\n"
    for t in tasks:
        text += (
            f"• <b>ID:</b> <code>{t['task_id']}</code>\n"
            f"  <b>Title:</b> <code>{t['final_title']}</code>\n"
            f"  <b>Custom:</b> <code>{t['custom_name']}</code>\n"
            f"  <b>AniList ID:</b> <code>{t['anilist_id'] or '—'}</code>\n"
            f"  <b>Keywords:</b> <code>{t['keywords'] or '—'}</code>\n"
            f"  <b>Avoid:</b> <code>{t['avoid_keywords'] or '—'}</code>\n"
            f"  <b>Link:</b> <code>{t['rss_link'][:50]}...</code>\n\n"
        )
    await sendMessage(message, text)


# ===================== /deletelink =====================
@bot.on_message(command('deletelink') & private & user(Var.ADMINS))
@new_task
async def delete_task(client, message):
    if len(message.text.split()) < 2:
        return await sendMessage(message, "<b>Usage:</b> /deletelink <task_id>")

    try:
        task_id = int(message.text.split()[1])
    except:
        return await sendMessage(message, "<b>Invalid task ID!</b>")

    result = await db.delete_rss_task(task_id)
    if result.modified_count == 0:
        return await sendMessage(message, "<b>Task not found or already deleted!</b>")

    await sendMessage(message, f"<b>Task {task_id} has been deactivated.</b>")
