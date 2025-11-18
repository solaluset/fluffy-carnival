#!/bin/python3
"""
Wrapper script for simple reverse proxies with Caddy
Automatically generates config and iptables rules
"""

import sys
import json
import shlex
import signal
import argparse
import functools
import subprocess
from enum import StrEnum
from dataclasses import dataclass


CONFIG_FILE = "/home/caddy/proxies.txt"
BASE_JSON = "/home/caddy/caddy.json.base"
FINAL_JSON = "/home/caddy/caddy.json"
CADDY_EXE = "caddy"

IPTABLES_COMMENT = json.dumps("By caddy-wrapper :3")


class IPTables(StrEnum):
    v4 = "iptables"
    v6 = "ip6tables"


class IPTablesAction(StrEnum):
    APPEND = "A"
    DELETE = "D"


class Protocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


@dataclass
class ProxyRecord:
    name: str
    local_port: int
    protocol: Protocol
    remote_address: str

    def as_dict(self) -> dict:
        return {
            self.name: {
                "listen": [f"{self.protocol}/[::]:{self.local_port}"],
                "routes": [
                    {
                        "handle": [
                            {
                                "handler": "proxy",
                                "upstreams": [
                                    {
                                        "dial": [
                                            f"{self.protocol}/{self.remote_address}"
                                        ]
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        }

    def get_iptables(self, action: IPTablesAction) -> str:
        return f"-{action} INPUT -p {self.protocol} -m {self.protocol} --dport {self.local_port} -j ACCEPT -m comment --comment {IPTABLES_COMMENT}"


def parse_config(file: str) -> list[ProxyRecord]:
    with open(file) as f:
        return [
            ProxyRecord(name, int(port), Protocol(protocol), addr)
            for name, port, protocol, addr in (
                line.split() for line in f if not line.lstrip().startswith("#")
            )
        ]


def write_caddy_json(
    base_file: str, proxies: list[ProxyRecord], output_file: str
) -> None:
    with open(base_file) as f:
        config = json.load(f)
    for record in proxies:
        config["apps"]["layer4"]["servers"].update(record.as_dict())
    with open(output_file, "w") as f:
        json.dump(config, f)


run_command = functools.partial(subprocess.check_output, text=True)


def _rule_as_args(rule: str) -> list[tuple[str, str]]:
    parts = shlex.split(rule)
    return [(x, y) for x, y in zip(parts[::2], parts[1::2])]


def get_current_rules(iptables: IPTables) -> list[list[tuple[str, str]]]:
    return [
        _rule_as_args(rule)
        for rule in run_command(
            ["sudo", f"{iptables}-save", "-t", "filter"]
        ).splitlines()
        if IPTABLES_COMMENT in rule
    ]


def execute_rule(iptables: IPTables, rule: list[tuple[str, str]]) -> None:
    run_command(["sudo", iptables] + [a for x in rule for a in x])


def update_iptables(proxies: list[ProxyRecord]) -> None:
    for iptables in IPTables:
        current_rules = get_current_rules(iptables)
        desired_rules = [
            _rule_as_args(record.get_iptables(IPTablesAction.APPEND))
            for record in proxies
        ]

        for rule in current_rules:
            if set(rule) in map(set, desired_rules):
                continue
            assert rule[0][0] == "-A", "rule identification failed"
            rule[0] = ("-D", rule[0][1])
            execute_rule(iptables, rule)

        for rule in desired_rules:
            if set(rule) in map(set, current_rules):
                continue
            execute_rule(iptables, rule)


parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("args", nargs=argparse.REMAINDER)


def main(args: list[str]) -> None:
    args = parser.parse_args(args)

    print("Generating config...")
    proxies = parse_config(CONFIG_FILE)
    write_caddy_json(BASE_JSON, proxies, FINAL_JSON)

    print("Updating iptables...")
    update_iptables(proxies)

    # signals will be passed to Caddy, Python should ignore them
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    original_sigterm_handler = signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        print("Running Caddy...")
        run_command(
            [CADDY_EXE, args.command, "--config", FINAL_JSON] + args.args
        )
    finally:
        signal.signal(signal.SIGINT, original_sigint_handler)
        signal.signal(signal.SIGTERM, original_sigterm_handler)
        if args.command == "run":
            # done running, clear
            print("Restoring iptables...")
            update_iptables([])


if __name__ == "__main__":
    main(sys.argv[1:])
