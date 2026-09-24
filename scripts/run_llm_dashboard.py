"""Launch the pixel dashboard for the LLM exposure agent.

Read-only: it parses the activity journal and opens the agent's memory database
read-only. It never trades and holds no credentials.

Binds to localhost by default and that default should be kept. The page carries the
live position, the book and the agent's reasoning, and it has no authentication of
any kind, so exposing it on a public interface would publish the account's state to
anyone who finds the port. Reach it over an SSH tunnel instead:

    ssh -L 8787:127.0.0.1:8787 ubuntu@<host>
"""

from __future__ import annotations

import argparse

from btc_decision_agent.observability.llm_agent_dashboard import DEFAULT_COST_BPS, serve

DEFAULT_JOURNAL = "data/live/llm-agent-activity.jsonl"
DEFAULT_MEMORY = "data/live/llm-agent-memory.sqlite3"
DEFAULT_MODEL = "qwen3:30b-a3b"


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM agent dashboard (read-only).")
    parser.add_argument("--journal", default=DEFAULT_JOURNAL)
    parser.add_argument("--memory", default=DEFAULT_MEMORY)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="shown in the header")
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=DEFAULT_COST_BPS,
        help="round-trip commission shown beside the expected move",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host; keep on localhost and reach it over an SSH tunnel",
    )
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"ADVERTENCIA: enlazando en {args.host}. El panel no tiene autenticacion "
            "y muestra la posicion y el libro en vivo.",
            flush=True,
        )

    server = serve(
        args.journal,
        args.memory,
        model=args.model,
        cost_bps=args.cost_bps,
        host=args.host,
        port=args.port,
    )
    print(
        f"dashboard: http://{args.host}:{args.port}  "
        f"(journal={args.journal}, memoria={args.memory}, modelo={args.model})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
