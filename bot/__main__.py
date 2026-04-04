from asyncio import create_task, create_subprocess_exec, create_subprocess_shell, run as asyrun, all_tasks, gather, sleep as asleep
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.filters import command, user
from os import path as ospath, execl, kill, remove as osremove
from sys import executable
from signal import SIGKILL
from bot import bot, Var, bot_loop, sch, LOGS, ffQueue, ffLock, ffpids_cache, ff_queued
from bot.core.auto_animes import fetch_animes
from bot.core.func_utils import clean_up, new_task, editMessage
from bot.modules.up_posts import upcoming_animes
from aiohttp import web

async def _kill_ff_procs():
    for pid in ffpids_cache:
        try:
            kill(pid, SIGKILL)
            LOGS.info(f"Killed FFmpeg PID: {pid}")
        except (OSError, ProcessLookupError):
            LOGS.error("Killing Process Failed !!")

@bot.on_message(command('restart') & user(Var.ADMINS))
@new_task
async def restart_cmd(client, message):
    rmessage = await message.reply('<i>Restarting...</i>')
    if sch.running:
        sch.shutdown(wait=False)
    await clean_up()
    await _kill_ff_procs()
    await (await create_subprocess_exec('python3', 'update.py')).wait()
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{rmessage.chat.id}\n{rmessage.id}\n")
    execl(executable, executable, "-m", "bot")

@bot.on_message(command('update') & user(Var.ADMINS))
@new_task
async def update_cmd(client, message):
    umessage = await message.reply('<i>Checking for updates...</i>')

    if not Var.UPSTREAM_REPO:
        await editMessage(umessage, '<b>UPSTREAM_REPO is not set in config!</b>')
        return

    from asyncio.subprocess import PIPE as APIPE

    git_cmd = (
        f"git init -q "
        f"&& git config --global user.email bot@autobot.com "
        f"&& git config --global user.name AutoBot "
        f"&& git add . "
        f"&& git commit -sm update -q "
        f"&& git remote remove origin 2>/dev/null; git remote add origin {Var.UPSTREAM_REPO} "
        f"&& git fetch origin -q "
        f"&& git reset --hard origin/{Var.UPSTREAM_BRANCH} -q"
    )

    await editMessage(umessage, f'<i>Pulling from <code>{Var.UPSTREAM_REPO}</code> [{Var.UPSTREAM_BRANCH}]...</i>')
    proc = await create_subprocess_shell(git_cmd, stdout=APIPE, stderr=APIPE)
    stdout, stderr = await proc.communicate()
    out = stdout.decode(errors='ignore').strip()
    err = stderr.decode(errors='ignore').strip()
    result = (out or err or 'No output')[:2000]

    if proc.returncode == 0:
        await editMessage(umessage, f'<i>✅ Updated successfully!</i>\n<pre>{result}</pre>\n<i>Restarting now...</i>')
    else:
        await editMessage(umessage, f'<i>⚠️ Git pull failed (exit {proc.returncode})</i>\n<pre>{result}</pre>\n<i>Restarting anyway...</i>')

    if sch.running:
        sch.shutdown(wait=False)
    await clean_up()
    await _kill_ff_procs()
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{umessage.chat.id}\n{umessage.id}\n")
    execl(executable, executable, "-m", "bot")

async def send_restart_confirmation():
    if ospath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="<i>Restarted successfully!</i>")
        except Exception as e:
            LOGS.error(e)
        try:
            osremove(".restartmsg")
        except:
            pass
            
async def queue_loop():
    LOGS.info("Queue Loop Started !!")
    while True:
        if not ffQueue.empty():
            post_id = await ffQueue.get()
            await asleep(1.5)
            ff_queued[post_id].set()
            await asleep(1.5)
            async with ffLock:
                ffQueue.task_done()
        await asleep(10)

async def main():
    sch.add_job(upcoming_animes, "cron", hour=0, minute=30)
    await bot.start()
    await send_restart_confirmation()
    LOGS.info('Auto Anime Bot Started!')
    sch.start()
    bot_loop.create_task(queue_loop())
    await fetch_animes()
    await idle()
    LOGS.info('Auto Anime Bot Stopped!')
    await bot.stop()
    for task in all_tasks:
        task.cancel()
    await clean_up()
    LOGS.info('Finished AutoCleanUp !!')
    
if __name__ == '__main__':
    bot_loop.run_until_complete(main())
