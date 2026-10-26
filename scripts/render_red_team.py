"""Problem 7: render the two red-team documents the way a person sees them (offline, no API).

  output/red_team_a1_render.png   the PDF page (pypdfium2)
  output/red_team_a2_render.png   the email's HTML part in a headless Chrome or Edge window

Both images show an ordinary quote: the injected text is hidden under a white box (PDF) or drawn in the
background colour (email). If no Chrome/Edge is found, the email image is skipped with a message.

Usage:  python scripts/render_red_team.py
"""

from __future__ import annotations

import email
import shutil
import subprocess
import tempfile
from email import policy
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent
ATTACKS = ROOT / "data" / "my_attacks"
OUT = ROOT / "output"
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str | None:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    return next((shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge")
                 if shutil.which(n)), None)


def render_pdf() -> None:
    page = pdfium.PdfDocument(str(ATTACKS / "a1_maplemills_quote.pdf"))[0]
    page.render(scale=1.3).to_pil().save(OUT / "red_team_a1_render.png")
    print("wrote output/red_team_a1_render.png")


def render_email() -> None:
    browser = find_browser()
    if not browser:
        print("no Chrome/Edge found: skipped output/red_team_a2_render.png")
        return
    msg = email.message_from_bytes((ATTACKS / "a2_westville_email.eml").read_bytes(), policy=policy.default)
    html = next(p.get_content() for p in msg.walk() if p.get_content_type() == "text/html")
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "a2.html"
        page.write_text('<meta charset="utf-8"><body style="margin:0;background:#fff">' + html, encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=800,560",
                        f"--screenshot={OUT / 'red_team_a2_render.png'}", page.as_uri()],
                       check=True, capture_output=True, timeout=60)
    print("wrote output/red_team_a2_render.png")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    render_pdf()
    render_email()
