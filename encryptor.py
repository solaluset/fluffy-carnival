"""
A simple program intended to encrypt and decrypt a short text with a password.
Made by Sóla Lusøt in 2023
"""

import sys

from nacl.utils import random
from nacl.pwhash import argon2id
from nacl.secret import SecretBox


def get_box(password: str, salt: bytes):
    key = argon2id.kdf(
        SecretBox.KEY_SIZE,
        password.encode(),
        salt,
        argon2id.OPSLIMIT_MODERATE,
        argon2id.MEMLIMIT_MODERATE,
    )
    return SecretBox(key)


def encrypt(data: bytes, password: str) -> bytes:
    salt = random(argon2id.SALTBYTES)
    return salt + get_box(password, salt).encrypt(data)


def decrypt(data: bytes, password: str) -> bytes:
    salt, data = data[: argon2id.SALTBYTES], data[argon2id.SALTBYTES :]
    return get_box(password, salt).decrypt(data)


def my_input(prompt: str):
    if not sys.stdin.isatty():
        prompt = ""
    return input(prompt)


def print_usage():
    print("Invalid arguments.", file=sys.stderr)
    print(f"Usage: {sys.argv[0]} -e <file>", file=sys.stderr)
    print(f"Or: {sys.argv[0]} -d <file>", file=sys.stderr)


if __name__ == "__main__":
    try:
        _, operation, file = sys.argv
        if operation not in ("-e", "-d"):
            raise ValueError("unknown operation")
    except ValueError:
        print_usage()
        sys.exit(1)
    password = my_input("Password: ")
    if operation == "-e":
        with open(file, "wb") as f:
            f.write(encrypt(my_input("Data: ").encode(), password))
    elif operation == "-d":
        with open(file, "rb") as f:
            print(decrypt(f.read(), password).decode())
