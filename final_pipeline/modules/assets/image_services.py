from __future__ import annotations

from pathlib import Path
import urllib.request


def download_image(url: str, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ModularShorts/0.1"})
    with urllib.request.urlopen(request, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "")
        data = response.read()
    if not data or ("image" not in content_type and len(data) < 1024):
        raise RuntimeError(f"Downloaded response is not a usable image: {content_type}")
    output_path.write_bytes(data)
    return str(output_path)
