import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from discord.ext import commands


class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

class KeepAlive(commands.Cog):
    def __init__(self, bot):
        port = int(os.environ.get("PORT", 10000))
        self.server = HTTPServer(("0.0.0.0", port), SimpleHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def cog_unload(self):
        self.server.shutdown()

async def setup(bot):
    await bot.add_cog(KeepAlive(bot))