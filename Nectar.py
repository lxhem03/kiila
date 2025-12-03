from aiohttp import web

async def ping(request):
    return web.Response(text="OK")

def web_server():
    app = web.Application()
    app.add_routes([web.get("/", ping)])
    web.run_app(app, host="0.0.0.0", port=7860)
