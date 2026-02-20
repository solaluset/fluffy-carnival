#!/bin/python3

import os
import sys
import shlex
import argparse
import functools
import subprocess
from ipaddress import ip_address
from configparser import ConfigParser

ALGO_PATH = os.path.expanduser(os.path.join("~", "algo"))
CONFIGS_PATH = os.path.join(ALGO_PATH, "configs", "localhost", "wireguard")
WHITELIST_PATH = os.path.join(ALGO_PATH, "full-vpn-whitelist.txt")
WHITELIST_CHAIN_NAME = "full-vpn-whitelist"

run_command = functools.partial(subprocess.check_output, text=True)

parser = argparse.ArgumentParser()
parser.add_argument("command")


def parse_config(file: str) -> list[str]:
    with open(file) as f:
        return [
            line
            for line in map(str.strip, f)
            if line and not line.startswith("#")
        ]


def clear_rules(iptables: str):
    for line in map(
        shlex.split,
        run_command(["sudo", f"{iptables}-save", "-t", "filter"]).splitlines(),
    ):
        if line[0] != "-A" or line[1] != WHITELIST_CHAIN_NAME:
            continue
        run_command(["sudo", iptables, "-D", *line[1:]])


def add_rule(iptables: str, source: str | None):
    command = ["sudo", iptables, "-A", WHITELIST_CHAIN_NAME]
    if source:
        command.extend(["-s", source, "-j", "ACCEPT"])
    else:
        command.extend(["-j", "DROP"])
    run_command(command)


def _split_ips(ips: str) -> list[str]:
    return [ip for ip in map(str.strip, ips.split(",")) if ip]


def get_addresses(name: str) -> tuple[list[str], list[str]]:
    v4 = []
    v6 = []
    parser = ConfigParser()
    parser.read(os.path.join(CONFIGS_PATH, name + ".conf"))
    for ip in _split_ips(parser["Interface"]["Address"]):
        version = ip_address(ip).version
        if version == 4:
            v4.append(ip)
        elif version == 6:
            v6.append(ip)
        else:
            raise ValueError(f"unknown IP version: {version}")
    return v4, v6


def main(args: list[str]) -> None:
    args = parser.parse_args(args)

    if args.command not in ("start", "stop"):
        raise ValueError("unknown command")

    clear_rules("iptables")
    clear_rules("ip6tables")

    if args.command == "start":
        names = parse_config(WHITELIST_PATH)
        for name in names:
            v4, v6 = get_addresses(name)
            for ip in v4:
                add_rule("iptables", ip)
            for ip in v6:
                add_rule("ip6tables", ip)

    add_rule("iptables", None)
    add_rule("ip6tables", None)


if __name__ == "__main__":
    main(sys.argv[1:])
