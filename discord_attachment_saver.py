"""
A script that parses your Discord data package and downloads all attachments you've sent
Sóla Lusøt, 2025
"""

import sys
import json
import time
from pathlib import Path
from urllib.request import urlparse

import requests


def download(url: str, dest: Path) -> str | None:
    url_path = urlparse(url).path.split("/")
    filename = url_path[-2] + "_" + url_path[-1]
    dest_path = dest / "attachments" / filename
    if dest_path.is_file() and dest_path.stat().st_size > 0:
        return filename

    try:
        response = requests.get(url)
        response.raise_for_status()
    except Exception as e:
        if isinstance(e, requests.HTTPError) and e.response.status_code == 404:
            return None
        print(e)
        print("Error, retrying in 5 seconds...")
        time.sleep(5)
        return download(url, dest)

    dest_path.parent.mkdir(exist_ok=True)
    with dest_path.open("wb") as f:
        f.write(response.content)
    return filename


def main(args: list[str]) -> None:
    root = Path(args[0])
    with (root / "index.json").open() as f:
        index = json.load(f)
    all_channels = list(root.iterdir())
    channel_count = len(all_channels)

    for i, channel in enumerate(all_channels, 1):
        messages_path = channel / "messages.json"
        if not messages_path.is_file():
            continue

        print(
            f"({i}/{channel_count}) Downloading {channel}: {index.get(channel.name[1:], '???')}"
        )

        with messages_path.open() as f:
            messages = json.load(f)

        for msg in messages:
            if isinstance(msg["Attachments"], list):
                continue
            msg["Attachments"] = [
                download(attachment, messages_path.parent)
                for attachment in msg["Attachments"].split()
            ]

        with messages_path.open("w") as f:
            json.dump(messages, f)


if __name__ == "__main__":
    main(sys.argv[1:])
