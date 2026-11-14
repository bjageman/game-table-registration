"""Enforce the repository's under-1,000-line source and test file limit."""

import subprocess
from pathlib import Path

SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".sh"}
LIMIT = 1000


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    failures = []
    for name in sorted(set(result.stdout.decode().split("\0")) - {""}):
        path = root / name
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        count = len(path.read_text().splitlines())
        if count >= LIMIT:
            failures.append(f"{name}: {count} lines (must be below {LIMIT})")
    if failures:
        print("\n".join(failures))
        return 1
    print("All source and test files are below 1,000 lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
