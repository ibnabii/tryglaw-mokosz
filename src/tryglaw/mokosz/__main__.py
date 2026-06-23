import asyncio

from tryglaw.mokosz.client import MokoszClient
from tryglaw.mokosz.settings import MokoszSettings


def main() -> None:
    settings = MokoszSettings()
    client = MokoszClient(settings)
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
