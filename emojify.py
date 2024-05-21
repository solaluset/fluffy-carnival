from string import ascii_uppercase, digits


LETTER_A = "\N{REGIONAL INDICATOR SYMBOL LETTER A}"
EMPTY_SQUARE = "\N{COMBINING ENCLOSING KEYCAP}"
PLUS = "\N{HEAVY PLUS SIGN}"
MINUS = "\N{HEAVY MINUS SIGN}"

MAPPING = {}

for i, c in enumerate(ascii_uppercase):
    MAPPING[c] = chr(ord(LETTER_A) + i)

for c in digits:
    MAPPING[c] = c + EMPTY_SQUARE

MAPPING["+"] = PLUS
MAPPING["-"] = MINUS

TR = str.maketrans(MAPPING)


def emojify(text: str) -> str:
    """
    Turns capital letters and digits into emojis
    "T E X T" -> "🇹 🇪 🇽 🇹"
    """
    return text.translate(TR)


if __name__ == "__main__":
    print(emojify(input()))
