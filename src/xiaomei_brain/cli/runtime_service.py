"""CLI bridge for the host-local AI runtime supervisor."""

from __future__ import annotations

import argparse
import json
import sys

from xiaomei_brain.runtime_services import LocalAIRuntimeManager
from xiaomei_brain.runtime_services.manager import LocalAIRuntimeError


def cmd_runtime_service(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="xiaomei-brain runtime-service")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    status = commands.add_parser("status")
    status.add_argument("service")
    select = commands.add_parser("select")
    select.add_argument("service")
    select.add_argument("model")
    select_device = commands.add_parser("select-device")
    select_device.add_argument("service")
    select_device.add_argument("device", choices=("auto", "cpu", "cuda"))
    for name in ("start", "restart"):
        command = commands.add_parser(name)
        command.add_argument("service")
        command.add_argument("--device", choices=("auto", "cpu", "cuda"), default=None)
    stop = commands.add_parser("stop")
    stop.add_argument("service")
    download = commands.add_parser("download")
    download.add_argument("service")
    cancel_download = commands.add_parser("cancel-download")
    cancel_download.add_argument("service")
    log = commands.add_parser("log")
    log.add_argument("service")

    parsed = parser.parse_args(args)
    manager = LocalAIRuntimeManager()
    try:
        if parsed.command == "list":
            result = {"services": manager.list_services(), "system": manager.system_status()}
        elif parsed.command == "status":
            result = manager.status(parsed.service)
        elif parsed.command == "select":
            result = manager.select_model(parsed.service, parsed.model)
        elif parsed.command == "select-device":
            result = manager.select_device(parsed.service, parsed.device)
        elif parsed.command == "start":
            result = manager.start(parsed.service, device=parsed.device)
        elif parsed.command == "restart":
            result = manager.restart(parsed.service, device=parsed.device)
        elif parsed.command == "stop":
            result = manager.stop(parsed.service)
        elif parsed.command == "download":
            result = manager.download(parsed.service)
        elif parsed.command == "cancel-download":
            result = manager.cancel_download(parsed.service)
        else:
            result = {"service": parsed.service, "content": manager.read_log(parsed.service)}
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except (KeyError, LocalAIRuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
