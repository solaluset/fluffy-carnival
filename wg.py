#!/bin/python3
# Show meaningful peer names instead of some base64

import os
import re
import subprocess
from configparser import ConfigParser


CONFIGS_PATH = os.path.expanduser(
    os.path.join("~", "algo", "configs", "localhost", "wireguard")
)
IP_PATTERN = re.compile("allowed ips: ([^/]+)/32")
COLOR_PATTERN = re.compile("\x1b[^m]+m")


def collect_addresses(directory: str) -> dict[str, str]:
    addresses = {}
    for file in os.listdir(directory):
        if file.endswith(".conf"):
            parser = ConfigParser()
            parser.read(os.path.join(directory, file))
            addresses[file] = parser["Interface"]["Address"]
    return addresses


def get_wg_output() -> str:
    return subprocess.check_output(
        ["sudo", "script", "-q", "/dev/null", "-c", "wg"], text=True
    )


def _patch_part(part: str, address_mapping: dict[str, str]) -> str:
    clean_part = COLOR_PATTERN.sub("", part)
    if not clean_part.startswith("peer:"):
        return part
    ip_match = IP_PATTERN.search(clean_part)
    if not ip_match:
        return part
    ip = ip_match.group(1)
    if ip not in address_mapping:
        return part
    peer = clean_part.split(None, 3)[1]
    return part.replace(peer, address_mapping[ip], 1)


def patch_wg_output(output: str, address_mapping: dict[str, str]) -> str:
    return "\n\n".join(
        _patch_part(part, address_mapping) for part in output.split("\n\n")
    )


def main():
    print(
        patch_wg_output(
            get_wg_output(),
            {v: k for k, v in collect_addresses(CONFIGS_PATH).items()},
        ),
        end="",
    )


if __name__ == "__main__":
    main()
