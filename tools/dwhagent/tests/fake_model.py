"""A scripted stand-in for the Anthropic Messages API, so the agent's wiring can be tested without a key.

The real Claude Code CLI (bundled with claude-agent-sdk) talks to it through ANTHROPIC_BASE_URL. The
"model" plays a fixed list of tool calls, one per turn, then says it is done. Every request is kept
in `requests`, so a test can read what each tool call returned (allowed output or the refusal).
"""
from __future__ import annotations

import itertools
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUBAGENT_MARK = "REVIEWER-PROBE"


class FakeModel:
    def __init__(self, script: list[tuple[str, dict]], subagent_script: list[tuple[str, dict]] | None = None):
        self.script, self.sub_script = script, subagent_script or []
        self.requests: list[dict] = []
        self._ids = itertools.count(1)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()

    # what the agent sent back for each tool call, in order: (is_subagent, is_error, text)
    def tool_results(self) -> list[tuple[bool, bool, str]]:
        out, seen = [], set()
        for body in self.requests:
            sub = SUBAGENT_MARK in json.dumps(body.get("messages", [])[:1])
            for m in body.get("messages", []):
                for b in m.get("content", []) if isinstance(m.get("content"), list) else []:
                    if b.get("type") == "tool_result" and b["tool_use_id"] not in seen:
                        seen.add(b["tool_use_id"])
                        c = b.get("content")
                        text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [])
                        out.append((sub, bool(b.get("is_error")), text))
        return out

    def offered_tools(self) -> list[str]:
        main = [b for b in self.requests if b.get("tools") and SUBAGENT_MARK not in json.dumps(b["messages"][:1])]
        return [t["name"] for t in main[0]["tools"]] if main else []

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self._json({})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                if "count_tokens" in self.path:
                    return self._json({"input_tokens": 100})
                fake.requests.append(body)
                msgs = body.get("messages", [])
                tools = [t.get("name") for t in body.get("tools", [])]
                sub = SUBAGENT_MARK in json.dumps(msgs[:1])
                script = fake.sub_script if sub else fake.script
                done = sum(1 for m in msgs if isinstance(m.get("content"), list)
                           for b in m["content"] if b.get("type") == "tool_result")
                if not tools or done >= len(script) or body.get("max_tokens", 1000) < 50:
                    return self._sse(None, "no problems found" if sub else "Finished.")
                name, inp = script[done]
                if name == "SUBAGENT":
                    name = "Agent" if "Agent" in tools else "Task"
                    inp = {**inp, "prompt": f"{SUBAGENT_MARK}: {inp.get('prompt', '')}"}
                return self._sse((name, inp), "")

            def _json(self, obj):
                b = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _sse(self, tool, text):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()

                def ev(t, d):
                    self.wfile.write(f"event: {t}\ndata: {json.dumps({'type': t, **d})}\n\n".encode())
                ev("message_start", {"message": {
                    "id": f"msg_{next(fake._ids)}", "type": "message", "role": "assistant", "model": "fake",
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 1}}})
                if tool:
                    ev("content_block_start", {"index": 0, "content_block": {
                        "type": "tool_use", "id": f"toolu_{next(fake._ids):05d}", "name": tool[0], "input": {}}})
                    ev("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta",
                                                                     "partial_json": json.dumps(tool[1])}})
                else:
                    ev("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}})
                    ev("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": text}})
                ev("content_block_stop", {"index": 0})
                ev("message_delta", {"delta": {"stop_reason": "tool_use" if tool else "end_turn",
                                               "stop_sequence": None}, "usage": {"output_tokens": 5}})
                ev("message_stop", {})

        return H
