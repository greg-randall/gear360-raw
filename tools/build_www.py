#!/usr/bin/env python3
"""Build the camera web UI into camera-www/dist/ (ready to copy to the SD card's mods/www/).

Inlines Bootstrap (camera-www/vendor), app.css and app.js into a single index.html, so the page
works offline on the camera hotspot regardless of the busybox httpd's MIME types. The command menu
is generated from commands.csv. CGI scripts are copied from camera-www/cgi-bin.

Deploy: copy everything in camera-www/dist/ into /sdcard/mods/www/ on the camera's SD card
(index.html replaces the old frameset; the old top.html stays reachable as a "classic" page).
"""
import csv
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(ROOT, "camera-www")
DIST = os.path.join(WWW, "dist")
FIELDS = ["family", "command", "run", "description", "risk", "tested", "result_notes"]


def read(*parts):
    with open(os.path.join(WWW, *parts), encoding="utf-8") as fh:
        return fh.read()


def script_safe(text, what):
    if "</script" in text.lower():
        raise SystemExit(f"{what} contains '</script', which would break inlining")
    return text


def main():
    with open(os.path.join(ROOT, "commands.csv"), newline="", encoding="utf-8") as fh:
        rows = [{k: (r.get(k) or "").strip() for k in FIELDS} for r in csv.DictReader(fh)]
    commands = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")

    html = read("src", "index.html")
    for marker, content in [
        ("/*BOOTSTRAP_CSS*/", read("vendor", "bootstrap.min.css")),
        ("/*APP_CSS*/", read("src", "app.css")),
        ("/*BOOTSTRAP_JS*/", script_safe(read("vendor", "bootstrap.bundle.min.js"), "bootstrap js")),
        ("/*COMMANDS_JSON*/", commands),
        ("/*APP_JS*/", script_safe(read("src", "app.js"), "app.js")),
    ]:
        if marker not in html:
            raise SystemExit(f"marker {marker} missing from src/index.html")
        html = html.replace(marker, content, 1)

    os.makedirs(os.path.join(DIST, "cgi-bin"), exist_ok=True)
    with open(os.path.join(DIST, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    for name in os.listdir(os.path.join(WWW, "cgi-bin")):
        src = os.path.join(WWW, "cgi-bin", name)
        dst = os.path.join(DIST, "cgi-bin", name)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o755)
    print(f"wrote {os.path.relpath(DIST, ROOT)}/index.html ({len(html):,} bytes, {len(rows)} commands) "
          f"and cgi-bin/{', cgi-bin/'.join(sorted(os.listdir(os.path.join(WWW, 'cgi-bin'))))}")


if __name__ == "__main__":
    main()
