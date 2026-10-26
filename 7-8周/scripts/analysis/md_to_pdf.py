#!/usr/bin/env python3
"""Render a Markdown report to PDF through HTML and headless Chrome."""

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

import markdown


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="")
    return parser.parse_args()


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{ size: A4; margin: 18mm 17mm 18mm 17mm; }}
  body {{
    font-family: "PingFang SC", "Songti SC", "Noto Sans CJK SC", serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #111;
  }}
  h1 {{ font-size: 19pt; margin: 0 0 8pt; font-weight: 700; }}
  h2 {{ font-size: 14pt; margin: 16pt 0 6pt; font-weight: 700; border-bottom: 1px solid #ddd; padding-bottom: 3pt; }}
  h3 {{ font-size: 12pt; margin: 11pt 0 4pt; font-weight: 700; }}
  p {{ margin: 0 0 5pt; text-align: justify; }}
  ul, ol {{ margin: 2pt 0 6pt 18pt; padding: 0; }}
  li {{ margin: 1pt 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 5pt 0 9pt; font-size: 8.8pt; page-break-inside: auto; }}
  tr {{ page-break-inside: avoid; }}
  th, td {{ border: 1px solid #bbb; padding: 3pt 4pt; vertical-align: top; }}
  th {{ background: #f0f0f0; font-weight: 600; }}
  code {{ font-family: "SFMono-Regular", Menlo, monospace; font-size: 8.8pt; background: #f6f6f6; padding: 0 2px; }}
  pre {{ font-family: "SFMono-Regular", Menlo, monospace; font-size: 8.5pt; background: #f6f6f6; padding: 6pt; white-space: pre-wrap; }}
  blockquote {{ margin: 5pt 0 7pt 12pt; color: #444; border-left: 3px solid #ccc; padding-left: 8pt; }}
  hr {{ border: 0; border-top: 1px solid #ddd; margin: 10pt 0; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def main():
    args = parse_args()
    text = args.input.read_text(encoding="utf-8")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    html = HTML_TEMPLATE.format(title=args.title or args.input.stem, body=body)
    html_path = Path("/tmp") / (args.output.stem + ".html")
    html_path.write_text(html, encoding="utf-8")

    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    profile = f"/tmp/chrome-{args.output.stem}"
    if args.output.exists():
        args.output.unlink()
    process = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=10000",
            f"--print-to-pdf={args.output}",
            f"file://{html_path}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 120
    last_size = 0
    while time.time() < deadline:
        if args.output.exists():
            size = args.output.stat().st_size
            if size > 0 and size == last_size:
                break
            last_size = size
        time.sleep(1)
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:
        pass
    time.sleep(1)
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        pass
    if not args.output.exists():
        raise SystemExit(f"PDF was not created: {args.output}")
    print(args.output)


if __name__ == "__main__":
    main()
