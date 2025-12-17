"""
A simple program intended to encrypt and decrypt data with a password
Originally made by Sóla Lusøt in 2023
"""

import sys
import typing
import argparse
from contextlib import contextmanager

from nacl.utils import random
from nacl.secret import Aead
from nacl.pwhash import argon2id


MEGABYTE = 1024**2

IO = typing.TypeVar("IO", bound=typing.IO)


class Encryptor:
    hasher = argon2id

    def __init__(
        self,
        key: bytes,
        opslimit: int | None = None,
        memlimit: int | None = None,
    ):
        self.key = key
        self.opslimit = opslimit or self.hasher.OPSLIMIT_MODERATE
        self.memlimit = (memlimit or self.hasher.MEMLIMIT_MODERATE) // MEGABYTE

        if self.opslimit < 1:
            raise ValueError("opslimit must be at least 1")
        if self.memlimit < 1:
            raise ValueError(f"memlimit must be at least {MEGABYTE}")

    def get_box(self, opslimit: int, memlimit: int, salt: bytes) -> Aead:
        key = self.hasher.kdf(
            Aead.KEY_SIZE,
            self.key,
            salt,
            opslimit,
            memlimit * MEGABYTE,
        )
        return Aead(key)

    def pack_header(self) -> bytes:
        return self.opslimit.to_bytes(1) + self.memlimit.to_bytes(3)

    def unpack_header(self, data: bytes) -> tuple[int, int, bytes]:
        opslimit, memlimit, data = data[:1], data[1:4], data[4:]
        return int.from_bytes(opslimit), int.from_bytes(memlimit), data

    def encrypt(self, data: bytes, aad: bytes = b"") -> bytes:
        salt = random(self.hasher.SALTBYTES)
        return (
            self.pack_header()
            + salt
            + self.get_box(self.opslimit, self.memlimit, salt).encrypt(
                data, aad=aad
            )
        )

    def decrypt(self, data: bytes, aad: bytes = b"") -> bytes:
        opslimit, memlimit, data = self.unpack_header(data)
        salt, data = (
            data[: self.hasher.SALTBYTES],
            data[self.hasher.SALTBYTES :],
        )
        return self.get_box(opslimit, memlimit, salt).decrypt(data, aad=aad)


cmd_parser = argparse.ArgumentParser()
cmd_parser.add_argument(
    "-a", dest="action", help="encrypt/decrypt", default="encrypt"
)
cmd_parser.add_argument("-k", dest="key_file", help="stdin if omitted")
cmd_parser.add_argument("-o", dest="output_file", help="stdout if omitted")
cmd_parser.add_argument("file")


@contextmanager
def open_or_default(file: str | None, default: IO) -> IO:
    if file is not None and file != "-":
        with open(file, default.mode) as f:
            yield f
    else:
        yield default


def main(argv: list[str]):
    args = cmd_parser.parse_args(argv)

    with open_or_default(args.key_file, sys.stdin.buffer) as key_file:
        encryptor = Encryptor(key_file.read())

    with open_or_default(args.file, sys.stdin.buffer) as in_file:
        data = in_file.read()

    if args.action == "encrypt":
        data = encryptor.encrypt(data)
    elif args.action == "decrypt":
        data = encryptor.decrypt(data)
    else:
        raise ValueError("unknown action")

    with open_or_default(args.output_file, sys.stdout.buffer) as out_file:
        out_file.write(data)


if __name__ == "__main__":
    main(sys.argv[1:])
