#!/bin/python3

import sys
import shlex
import argparse
import functools
import subprocess
from pathlib import Path
from ipaddress import ip_address
from configparser import ConfigParser

WHITELIST_CHAIN_NAME = "full-vpn-whitelist"

run_command = functools.partial(subprocess.check_output, text=True)

parser = argparse.ArgumentParser()
parser.add_argument("--algo-path", type=Path)
parser.add_argument("command")


def parse_config(file: str) -> dict:
    with open(file) as f:
        lines = [
            line
            for line in map(str.strip, f)
            if line and not line.startswith("#")
        ]
    config = {"users": []}
    for line in lines:
        if "=" in line:
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
        else:
            config["users"].append(line)
    return config


def clear_rules(iptables: str):
    for line in map(
        shlex.split,
        run_command(["sudo", f"{iptables}-save", "-t", "filter"]).splitlines(),
    ):
        if line[0] != "-A" or line[1] != WHITELIST_CHAIN_NAME:
            continue
        run_command(["sudo", iptables, "-D", *line[1:]])


def add_rule(iptables: str, option: str, address: str | None, jump: str):
    command = ["sudo", iptables, "-A", WHITELIST_CHAIN_NAME]
    if address:
        command.extend([option, address, "-j", jump])
    else:
        command.extend(["-j", jump])
    run_command(command)


def _split_ips(ips: str) -> list[str]:
    return [ip for ip in map(str.strip, ips.split(",")) if ip]


def get_addresses(configs_path: Path, name: str) -> tuple[list[str], list[str]]:
    v4 = []
    v6 = []
    parser = ConfigParser()
    parser.read(configs_path / (name + ".conf"))
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

    algo_path = args.algo_path or Path("~").expanduser() / "algo"
    configs_path = algo_path / "configs" / "localhost"
    server_ip_v4 = configs_path.readlink().name
    configs_path = configs_path / "wireguard"
    whitelist_path = algo_path / "full-vpn-whitelist.txt"

    config = parse_config(whitelist_path)
    list_jump = config.get("LIST_JUMP", "ACCEPT")
    other_jump = config.get("OTHER_JUMP", "DROP")
    server_ip_v6 = config.get("IPv6_SERVER_ADDRESS")

    clear_rules("iptables")
    clear_rules("ip6tables")

    # always allow connecting to the server itself
    add_rule("iptables", "-d", server_ip_v4, "ACCEPT")
    if server_ip_v6:
        add_rule("ip6tables", "-d", server_ip_v6, "ACCEPT")

    if args.command == "start":
        for name in config["users"]:
            v4, v6 = get_addresses(configs_path, name)
            for ip in v4:
                add_rule("iptables", "-s", ip, list_jump)
            for ip in v6:
                add_rule("ip6tables", "-s", ip, list_jump)

    add_rule("iptables", "-s", None, other_jump)
    add_rule("ip6tables", "-s", None, other_jump)


if __name__ == "__main__":
    main(sys.argv[1:])
