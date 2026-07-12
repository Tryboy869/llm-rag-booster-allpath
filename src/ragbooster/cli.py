"""
cli.py — command-line entry point.

The old booster.py's `if __name__ == '__main__':` block relied on a
module-level global that only exists for the lifetime of one Python
process. Every CLI call was its own subprocess, so `load`/`ask`/`stats`
always found an empty global and returned "Not initialized" — this is
why the original test.py crashed with a KeyError when run for real.

Fix: state is saved to / loaded from a JSON file (default
`.ragbooster/session.json`) at the start and end of every command, so
state survives across separate `ragbooster ...` invocations, which is
exactly what a per-function CLI (e.g. an external Allpath-style runner
calling this once per function) needs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .client import RAGBooster, RAGBoosterError

DEFAULT_STATE_PATH = os.environ.get("RAGBOOSTER_STATE", ".ragbooster/session.json")


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def cmd_init(args) -> None:
    booster = RAGBooster(api_url=args.api_url, api_key=args.api_key or "",
                          model=args.model, provider=args.provider)
    os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
    booster.save(args.state)
    _print({"success": True, "provider": booster.provider.name, "state_file": args.state})


def _load_booster(state_path: str) -> RAGBooster:
    if not os.path.exists(state_path):
        _print({"error": f"No session at '{state_path}'. Run `ragbooster init` first."})
        sys.exit(1)
    return RAGBooster.load_from(state_path)


def cmd_load(args) -> None:
    booster = _load_booster(args.state)
    text = args.text
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    stats = booster.load_document(text, chunk_size=args.chunk_size, overlap=args.overlap)
    booster.save(args.state)
    _print(stats)


def cmd_ask(args) -> None:
    booster = _load_booster(args.state)
    try:
        result = booster.ask(args.question, top_k=args.top_k)
    except RAGBoosterError as e:
        _print({"error": str(e)})
        sys.exit(1)
    booster.save(args.state)
    _print(result)


def cmd_stats(args) -> None:
    booster = _load_booster(args.state)
    _print(booster.get_stats())


def cmd_serve(args) -> None:
    try:
        import uvicorn
    except ImportError:
        _print({"error": "Server mode needs the optional deps: pip install 'ragbooster[server]'"})
        sys.exit(1)
    uvicorn.run("ragbooster.server:app", host=args.host, port=args.port, reload=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ragbooster")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH,
                         help="Path to the session state file (default: .ragbooster/session.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Start a new session")
    p_init.add_argument("--api-url", required=True)
    p_init.add_argument("--api-key", default="")
    p_init.add_argument("--model", default="")
    p_init.add_argument("--provider", default=None,
                         choices=["openai", "groq", "anthropic", "ollama-chat", "ollama-generate"])
    p_init.set_defaults(func=cmd_init)

    p_load = sub.add_parser("load", help="Index a document (text or --file)")
    p_load.add_argument("text", nargs="?", default="")
    p_load.add_argument("--file")
    p_load.add_argument("--chunk-size", type=int, default=200)
    p_load.add_argument("--overlap", type=int, default=50)
    p_load.set_defaults(func=cmd_load)

    p_ask = sub.add_parser("ask", help="Ask a question against the loaded documents")
    p_ask.add_argument("question")
    p_ask.add_argument("--top-k", type=int, default=8)
    p_ask.set_defaults(func=cmd_ask)

    p_stats = sub.add_parser("stats", help="Show index stats")
    p_stats.set_defaults(func=cmd_stats)

    p_serve = sub.add_parser("serve", help="Run the HTTP API (requires ragbooster[server])")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
