from asyncio import sleep as asleep, gather
from pyrogram.filters import command, private, user, regex
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, MessageNotModified
from bot import bot, bot_loop, Var, ani_cache
from bot.core.database import db
from bot.core.func_utils import decode, is_fsubbed, get_fsubs, editMessage, sendMessage, new_task, convertTime, getfeed
from bot.core.auto_animes import get_animes
from bot.core.reporter import rep
from bot.core.anilist_helper import resolve_anilist_title_and_id

@bot.on_message(command("start") & private)
@new_task
async def start_msg(client, message):
    uid = message.from_user.id
    from_user = message.from_user
    txtargs = message.text.split()

    temp = await sendMessage(message, "<i>Connecting..</i>")

    # Force subscribe
    if not await is_fsubbed(uid):
        txt, btns = await get_fsubs(uid, txtargs)
        if temp:
            await editMessage(temp, txt, InlineKeyboardMarkup(btns))
        return

    if len(txtargs) <= 1:
        if temp:
            await temp.delete()

        btns = []
        for elem in Var.START_BUTTONS.split():
            try:
                bt, link = elem.split("|", 1)
            except:
                continue

            if btns and len(btns[-1]) == 1:
                btns[-1].append(InlineKeyboardButton(bt, url=link))
            else:
                btns.append([InlineKeyboardButton(bt, url=link)])

        smsg = Var.START_MSG.format(
            first_name=from_user.first_name,
            last_name=from_user.last_name,
            mention=from_user.mention,
            user_id=from_user.id
        )

        if Var.START_PHOTO:
            await message.reply_photo(
                photo=Var.START_PHOTO,
                caption=smsg,
                reply_markup=InlineKeyboardMarkup(btns) if btns else None
            )
        else:
            await sendMessage(
                message,
                smsg,
                InlineKeyboardMarkup(btns) if btns else None
            )
        return

    # ----------------- FILE DECODE PART -----------------

    try:
        decoded = await decode(txtargs[1])
        args = decoded.split("-")
    except Exception as e:
        await rep.report(f"User : {uid} | Decode Error : {e}", "error")
        return await editMessage(temp, "<b>Invalid or Corrupted Link !</b>")

    ids = []

    try:
        if len(args) == 3 and args[0] == "get":
            start = int(int(args[1]) / abs(int(Var.FILE_STORE)))
            end = int(int(args[2]) / abs(int(Var.FILE_STORE)))
            ids = range(start, end + 1) if start <= end else range(start, end - 1, -1)

        elif len(args) == 2 and args[0] == "get":
            ids = [int(int(args[1]) / abs(int(Var.FILE_STORE)))]

        else:
            return await editMessage(temp, "<b>Invalid Link Format !</b>")

    except Exception as e:
        await rep.report(f"User : {uid} | ID Parse Error : {e}", "error")
        return await editMessage(temp, "<b>Invalid File ID !</b>")


    sent_msgs = []

    try:
        for fid in ids:
            msg = await client.get_messages(Var.FILE_STORE, fid)
            if msg.empty:
                continue

            copied = await msg.copy(
                chat_id=uid,
                reply_markup=None,
                protect_content=Var.PROTECT_CONTENT
            )
            sent_msgs.append(copied)

    except Exception as e:
        await rep.report(f"User : {uid} | Fetch Error : {e}", "error")
        return await editMessage(temp, "<b>File Not Found !</b>")

    if temp:
        await temp.delete()

    if Var.AUTO_DEL and sent_msgs:
        note = await sendMessage(
            message,
            f"<i>Files will be auto deleted in {convertTime(Var.DEL_TIMER)}</i>"
        )

        async def auto_del():
            await asleep(Var.DEL_TIMER)
            for m in sent_msgs:
                try:
                    await m.delete()
                except:
                    pass

            try:
                reload_url = f"https://t.me/{client.me.username}?start={txtargs[1]}"
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("♻️ Get File Again", url=reload_url)]]
                )
                await editMessage(
                    note,
                    "<b>Your file(s) were deleted successfully.</b>",
                    kb
                )
            except:
                pass

        bot_loop.create_task(auto_del())
    
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

    feed = await getfeed(rss_link)
    if not feed or not feed.entries:
        return await sendMessage(message, "<b>Invalid or empty RSS feed!</b>")

    info = feed.entries[0]  # Take the newest item for one-time task

    # FORCE UPLOAD — NO FILTERS
    bot_loop.create_task(get_animes(
        name=info.title,
        torrent=info.link,
        force=True,           # ← BYPASSES DB CHECK
        custom_name=custom_name
    ))

    await sendMessage(message, f"<b>Force Task Started:</b> <code>{custom_name}</code>")

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


# ====================== /listlink with pagination (4 per page) ======================
@bot.on_message(command('listlink') & private & user(Var.ADMINS))
@new_task
async def list_tasks(client, message):
    arg = message.text.split()
    page = 1
    if len(arg) > 1:
        try:
            page = int(arg[1])
            if page < 1:
                page = 1
        except:
            page = 1

    tasks = await db.get_all_rss_tasks()
    if not tasks:
        return await sendMessage(message, "<i>No permanent tasks found.</i>")

    per_page = 4
    total_pages = (len(tasks) + per_page - 1) // per_page
    page = min(page, total_pages)

    start = (page - 1) * per_page
    end = start + per_page
    page_tasks = tasks[start:end]

    text = f"<b>Active RSS Tasks</b> (Page {page}/{total_pages})\n\n"
    for task in page_tasks:
        text += (
            f"<b>{task['task_id']} • {task['custom_name']}</b>\n"
            f"   • 1080p Only\n"
            f"   Keywords: <code>{task['keywords'] or 'Any'}</code>\n"
            f"   • Avoid: <code>{task['avoid_keywords'] or 'None'}</code>\n"
            f"   • Link: <code>{task['rss_link'][:45]}...</code>\n\n"
        )

    # Buttons
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀ PREV", callback_data=f"listpg_{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("NEXT ▶", callback_data=f"listpg_{page+1}"))

    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if message.reply_to_message:
        await message.reply_to_message.delete()

    await sendMessage(message, text, reply_markup=reply_markup)


# ====================== Callback for pagination ======================
@bot.on_callback_query(regex(r"^listpg_(\d+)$"))
async def list_pagination_cb(client, callback_query):
    page = int(callback_query.data.split("_")[1])

    tasks = await db.get_all_rss_tasks()
    if not tasks:
        return await callback_query.answer("No tasks!", show_alert=True)

    per_page = 4
    total_pages = (len(tasks) + per_page - 1) // per_page
    page = min(max(1, page), total_pages)

    start = (page - 1) * per_page
    end = start + per_page
    page_tasks = tasks[start:end]

    text = f"<b>Active RSS Tasks</b> (Page {page}/{total_pages})\n\n"
    for task in page_tasks:
        text += (
            f"<b>{task['task_id']} • {task['custom_name']}</b>\n"
            f"   • 1080p Only\n"
            f"   Keywords: <code>{task['keywords'] or 'Any'}</code>\n"
            f"   • Avoid: <code>{task['avoid_keywords'] or 'None'}</code>\n"
            f"   • Link: <code>{task['rss_link'][:45]}...</code>\n\n"
        )

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀ PREV", callback_data=f"listpg_{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("NEXT ▶", callback_data=f"listpg_{page+1}"))

    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None

    await callback_query.message.edit_text(text, reply_markup=reply_markup)
    await callback_query.answer()
# ===================== /deletelink =====================
@bot.on_message(command('deletelink') & private & user(Var.ADMINS))
@new_task
async def _deletelink(client, message):
    if len(message.text.split()) < 2:
        return await sendMessage(message, "<b>Usage: /deletelink <task_id></b>")

    try:
        task_id = int(message.text.split()[1])
    except:
        return await sendMessage(message, "<b>Invalid task ID!</b>")

    result = await db.delete_rss_task(task_id)
    if result is None or result.modified_count == 0:
        return await sendMessage(message, "<b>Task not found or already deleted!</b>")

    await sendMessage(message, f"<b>Task {task_id} deleted successfully.</b>")
