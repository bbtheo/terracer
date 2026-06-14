#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the preprocessing pipeline.")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip the download step and assume data/raw is populated.",
    )
    parser.add_argument(
        "--url",
        help="Download URL for CityGML/3D Tiles data (passed to download step).",
    )
    parser.add_argument(
        "--filename",
        help="Optional filename to save the download as.",
    )
    parser.add_argument(
        "--skip-unzip",
        action="store_true",
        help="Skip unzipping downloaded archives.",
    )
    parser.add_argument(
        "--max-buildings",
        type=int,
        help="Optional cap on buildings parsed (for quick runs).",
    )
    args = parser.parse_args()

    if not args.skip_download:
        download_cmd = [
            sys.executable,
            "-m",
            "src.preprocessing.download_3d_model",
        ]
        if args.url:
            download_cmd.extend(["--url", args.url])
        if args.filename:
            download_cmd.extend(["--filename", args.filename])
        result = subprocess.run(download_cmd, check=False)
        if result.returncode != 0:
            return result.returncode

    if not args.skip_unzip:
        raw_dir = pathlib.Path("data/raw")
        for archive in raw_dir.glob("*.zip"):
            target_dir = raw_dir / archive.stem
            if target_dir.exists() and any(target_dir.iterdir()):
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive, "r") as zip_handle:
                zip_handle.extractall(target_dir)

    parse_cmd = [
        sys.executable,
        "-m",
        "src.preprocessing.parse_citygml",
    ]
    if args.max_buildings is not None:
        parse_cmd.extend(["--max-buildings", str(args.max_buildings)])
    result = subprocess.run(parse_cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
