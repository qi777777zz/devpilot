from __future__ import annotations

import argparse

import uvicorn

from devpilot.config import get_settings
from devpilot.db import Database
from devpilot.service import Worker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DevPilot API and task console")
    parser.add_argument("command", nargs="?", choices=["server", "worker"], default="server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    if args.command == "server":
        uvicorn.run("devpilot.api:app", host=args.host, port=args.port, reload=args.reload)
        return
    settings = get_settings()
    database = Database(settings)
    database.create_schema()
    with database.session_factory() as session:
        Worker.create(session, settings).run_forever()


if __name__ == "__main__":
    main()
