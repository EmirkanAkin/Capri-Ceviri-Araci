"""Testler için llama-server taklidi: /health ve /completion. Gelen istemdeki metni "TR(...)" olarak çevirir.
Kullanım: python fake_llama_server.py --port N [--crash]"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])
if "--crash" in sys.argv:
    print("error: failed to load model (fake)", flush=True)
    sys.exit(1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send({"status": "ok"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["prompt"]
        if prompt.startswith("<start_of_turn>user\n"):          # TranslateGemma: metin 3 satır sonundan sonra
            text = prompt.split("\n\n\n", 1)[1].rsplit("<end_of_turn>", 1)[0]
            out = "\n".join(f"TR({line})" for line in text.split("\n"))
        else:                                                   # MiLMMT: "English: metin\nTurkish:"
            text = prompt.split("\nEnglish: ", 1)[1].rsplit("\n", 1)[0]
            out = f" TR({text})"
        self._send({"content": out, "stop": True})

    def _send(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
