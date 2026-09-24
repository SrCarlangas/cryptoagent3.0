"""Launch the local observability dashboard for the demo agent.

Reads the activity journal written by scripts/run_realtime_demo.py. Read-only, no trading.

Example:
    .venv/bin/python -m scripts.run_dashboard --journal data/live/realtime-demo-activity.jsonl --port 8787
    # then open http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse

from btc_decision_agent.observability.dashboard import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC demo agent observability dashboard (read-only).")
    parser.add_argument("--journal", default="data/live/realtime-demo-activity.jsonl", help="activity journal path")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (localhost by default)")
    parser.add_argument("--port", type=int, default=8787, help="bind port")
    args = parser.parse_args()

    server = serve(args.journal, host=args.host, port=args.port)
    print(f"dashboard: http://{args.host}:{args.port}  (journal={args.journal})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
