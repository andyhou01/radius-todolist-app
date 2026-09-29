"""Deterministic OpenAI-compatible mock for Azure-hosted and vendor-hosted models."""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROVIDER = os.environ["PROVIDER"]
PORT = int(os.environ["PORT"])


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        prompt = " ".join(str(m.get("content", "")) for m in payload.get("messages", []))
        answer = f"[{PROVIDER}:{payload.get('model')}] echo: {prompt}"
        prompt_tokens, completion_tokens = len(prompt.split()), len(answer.split())
        body = json.dumps({
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": answer}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens},
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
