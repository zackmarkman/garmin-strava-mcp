"""Print a fresh SERVER_TOKEN and FERNET_KEY. Paste into your .env."""

from __future__ import annotations

import secrets

from cryptography.fernet import Fernet


def main() -> None:
    print(f"SERVER_TOKEN={secrets.token_hex(32)}")
    print(f"FERNET_KEY={Fernet.generate_key().decode()}")


if __name__ == "__main__":
    main()
