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
            main="campus_market.entry:run",
            compressed=True,
        )
    subprocess.run(
        [sys.executable, str(destination), "--help"], check=True, stdout=subprocess.DEVNULL
    )
    with tempfile.TemporaryDirectory(prefix="campus-exit-check-") as temporary:
        denied = subprocess.run(
            [
                sys.executable,
                str(destination),
                "--db",
                str(Path(temporary) / "test.sqlite3"),
                "--session-file",
                str(Path(temporary) / "missing.json"),
                "me",
            ],
            capture_output=True,
            check=False,
        )
        if denied.returncode != 2:
            raise SystemExit("打包程序未保留业务错误退出码")
    result = {
        "artifact": str(destination.relative_to(root)),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "bytes": destination.stat().st_size,
        "python": sys.version.split()[0],
        "compile": "PASS",
        "packaged_help": "PASS",
        "packaged_error_exit_code": "PASS",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
