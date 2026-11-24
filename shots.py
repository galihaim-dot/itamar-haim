"""Screenshots of a built page with headless Edge, for the visual check.

Usage: python shots.py PAGE.html WIDTH OUT.png [HEIGHT]
"""
import subprocess
import sys
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def shoot(html: Path, width: int, out: Path, height: int = 3200) -> Path:
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--virtual-time-budget=6000", f"--window-size={width},{height}",
                    f"--screenshot={out}", Path(html).resolve().as_uri()],
                   check=True, capture_output=True, timeout=120)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    print(shoot(Path(a[0]), int(a[1]), Path(a[2]), int(a[3]) if len(a) > 3 else 3200))
