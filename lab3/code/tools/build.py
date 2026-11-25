"""Compile the source and produce a portable, dependency-free Python zipapp."""

import compileall
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path


def main():
    """Build from an explicit source allowlist, then execute the packaged help."""
    root = Path(__file__).resolve().parents[1]
    source = root / "campus_market"
    if not compileall.compile_dir(source, quiet=1):
        raise SystemExit("Python 编译检查失败")
    destination = root / "dist" / "campus-market.pyz"
    destination.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="campus-build-") as temporary:
        staging = Path(temporary)
        shutil.copytree(
            source, staging / "campus_market", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        zipapp.create_archive(
            staging,
            destination,
            interpreter="/usr/bin/env python3",
            main="campus_market.cli:main",
            compressed=True,
        )
    subprocess.run(
        [sys.executable, str(destination), "--help"], check=True, stdout=subprocess.DEVNULL
    )
    result = {
        "artifact": str(destination.relative_to(root)),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "bytes": destination.stat().st_size,
        "python": sys.version.split()[0],
        "compile": "PASS",
        "packaged_help": "PASS",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
