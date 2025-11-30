"""
Convert WireGuard config to make it route traffic only to whitelisted IPs
Everything else is routed as usual
"""

import sys
import argparse
import configparser
from ipaddress import ip_address
from collections import defaultdict


WHITELIST_SCRIPT = "/etc/wireguard/whitelist.sh"


argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("platform")
argument_parser.add_argument("file")
argument_parser.add_argument("--add", default="")


class ConfigParser(configparser.ConfigParser):
    # disable interpolation
    _DEFAULT_INTERPOLATION = None

    # do not change to lowercase
    def optionxform(self, name: str) -> str:
        return name


def _split_ips(ips: str) -> list[str]:
    return [i.strip() for i in ips.split(",") if i.strip()]


def _clean_ip(ip: str) -> str:
    ip = ip.partition("/")[0]
    if ip.startswith("["):
        return ip.removeprefix("[").partition("]")[0]
    if ip.count(":") == 1:
        return ip.partition(":")[0]
    return ip


def _get_server_ip(ip: str) -> str:
    ip = ip_address(_clean_ip(ip))
    ip_bytes = bytearray(ip.packed)
    ip_bytes[-2:] = [0, 1]
    return str(ip_address(bytes(ip_bytes)))


def collect_addresses(config: ConfigParser, additional: str) -> list[str]:
    result = [_clean_ip(config["Peer"]["Endpoint"])]
    result.extend(
        map(_get_server_ip, _split_ips(config["Interface"]["Address"]))
    )
    result.extend(_split_ips(config["Interface"]["DNS"]))
    result.extend(_split_ips(additional))
    return result


def group_by_version(ips: list[str]) -> dict[int, list[str]]:
    grouped = defaultdict(list)
    for ip in ips:
        grouped[ip_address(_clean_ip(ip)).version].append(ip)
    return grouped


def main(argv: list[str]) -> None:
    args = argument_parser.parse_args(argv)
    platform = args.platform.lower()
    if platform not in ("linux", "android", "windows"):
        raise ValueError("unknown platform")
    config = ConfigParser()
    with open(args.file) as f:
        config.read_file(f)
    addresses = group_by_version(collect_addresses(config, args.add))
    addresses_v4 = addresses.pop(4)
    addresses_v6 = addresses.pop(6)
    if addresses:
        raise ValueError(f"unknown IP versions: {list(addresses.keys())}")
    if platform == "linux":
        addresses_v4 = " ".join(addresses_v4)
        addresses_v6 = " ".join(addresses_v6)
        config["Interface"][
            "PostUp"
        ] = f"{WHITELIST_SCRIPT} up %i '{addresses_v4}' '{addresses_v6}'"
        config["Interface"]["PreDown"] = f"{WHITELIST_SCRIPT} down %i"
    else:
        config["Peer"]["AllowedIPs"] = ", ".join(addresses_v4 + addresses_v6)
    config.write(sys.stdout)


if __name__ == "__main__":
    main(sys.argv[1:])
