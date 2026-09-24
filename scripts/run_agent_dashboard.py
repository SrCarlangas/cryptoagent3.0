"""Launch the pixel dashboard for the local exposure agent.

Read-only: it parses the activity journal and the policy document. It never trades
and holds no credentials. Binds to localhost by default, so remote access is via an
SSH tunnel rather than an exposed port.
"""

from __future__ import annotations

import argparse

from btc_decision_agent.observability.agent_dashboard import serve

DEFAULT_JOURNAL = "data/live/exposure-agent-activity.jsonl"
DEFAULT_POLICY = "data/models/local-exposure-agent-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Exposure agent dashboard (read-only).")
    parser.add_argument("--journal", default=DEFAULT_JOURNAL)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host; keep on localhost and reach it over an SSH tunnel",
    )
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = serve(args.journal, args.policy, host=args.host, port=args.port)
    print(
        f"dashboard: http://{args.host}:{args.port}  "
        f"(journal={args.journal}, policy={args.policy})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
