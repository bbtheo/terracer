#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import sys

import httpx


DEFAULT_OUTPUT_DIR = pathlib.Path("data/raw")


def _stream_download(url: str, output_path: pathlib.Path, verify: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=60.0,
        verify=verify,
    ) as response:
        response.raise_for_status()
        with output_path.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Helsinki 3D City Model data to data/raw.",
    )
    parser.add_argument(
        "--url",
        help="Direct download URL for the CityGML/3D Tiles asset.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to store downloaded assets (default: data/raw).",
    )
    parser.add_argument(
        "--filename",
        help="Optional filename to save the download as.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (use only if the host cert is expired).",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output)
    if not args.url:
        print(
            "No --url provided. Download the CityGML dataset manually and place it in "
            f"{output_dir.resolve()} before running the parser.",
            file=sys.stderr,
        )
        return 2

    filename = args.filename or pathlib.Path(httpx.URL(args.url).path).name
    if not filename:
        print("Unable to infer filename from URL; provide --filename.", file=sys.stderr)
        return 2

    output_path = output_dir / filename
    _stream_download(args.url, output_path, verify=not args.insecure)
    print(f"Downloaded to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
