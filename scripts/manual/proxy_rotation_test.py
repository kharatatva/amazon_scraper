"""Manual proxy-pool diagnostic for the scraper."""
# Manual network script: requests a public proxy list and validates against Amazon.

import asyncio

from src.scraper.proxies import ProxyAcquisitionError, ProxyManager


async def main():
    """Request and validate a public proxy pool for manual diagnosis."""
    manager = ProxyManager()
    try:
        await manager.get_healthy_proxies()
    except ProxyAcquisitionError as exc:
        print(f"Proxy validation failed: {exc}")
        return

    proxy = manager.get_next_proxy()
    if not proxy:
        print("No validated proxy is available.")
        return

    print("Selected one validated proxy for the shared browser.")
    replacement = await manager.rotate_proxy(proxy)
    print("Rotation selected the next validated proxy.")
    print(f"Replacement available: {bool(replacement)}")


if __name__ == "__main__":
    asyncio.run(main())
