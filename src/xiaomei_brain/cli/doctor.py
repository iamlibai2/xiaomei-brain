"""xiaomei-brain doctor — 系统自检."""

from __future__ import annotations


def cmd_doctor(args: list[str]) -> None:
    from xiaomei_brain.doctor import main as doctor_main
    doctor_main(args)
