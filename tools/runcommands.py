#!/usr/bin/env python3
"""Run camera commands from commands.csv and record the results.

For each selected row (a row needs an exact command in its `run` column):
  1. snapshot the tail of the A7 capture log (`st cap log`),
  2. send the command through the mod's CGI (http://CAMERA:8888/cgi-bin/execute),
  3. collect the reply plus any NEW A7 log lines (some RTOS commands print there, not in the reply);
     for `st app ...` rows (or all rows with --dlog) also any NEW Linux dlog lines, because the camera
     app prints its output there (`dlogutil -d -v time '*:V'`: dump without blocking, all levels),
  4. save everything to the next free camera-logs/NN_<slug>.txt,
  5. only with --haiku: ask Claude Haiku (`claude -p --model haiku`) to classify the output (30-60 s per row;
     the default is to run and log only, and classify the logs in one go afterwards),
  6. write tested / tested_date / result_notes / log back to commands.csv straight away.

Safety: only `read` rows run by default. `set` / `action` rows need --allow and a y/n
confirmation per command (unless --yes). `never` and `unknown` rows are never run.
Commands Haiku spots in help output are appended to the CSV with risk `unknown`.

Examples:
  python3 tools/runcommands.py --dry-run
  python3 tools/runcommands.py --family "st cap" --match help
  python3 tools/runcommands.py --family "st top level" --skip "^st (misc|thread|log afinfo|firmware|readl|dump)"

Timeouts/errors: if a camera request fails, the row is marked `failed`, a camera-logs file records
the error, and the camera is probed with `echo ok`. If the probe answers, the run continues;
if not, the CSV is saved and the runner exits naming the command.
"""
import argparse
import csv
import datetime
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "commands.csv")
LOG_DIR = os.path.join(ROOT, "camera-logs")
CAMERA = "192.168.43.1:8888"
COLS = ["family", "command", "run", "description", "risk", "source",
        "tested", "tested_date", "result_notes", "log"]
NEVER_RUN = {"never", "unknown", ""}

HAIKU_SCHEMA = {
    "type": "object",
    "properties": {
        "tested": {"type": "string", "enum": ["yes", "partial", "failed"]},
        "result_notes": {"type": "string"},
        "new_commands": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tested", "result_notes", "new_commands"],
}

HAIKU_INSTRUCTIONS = """You are helping catalogue debug commands on a hacked Samsung Gear 360 (2017) camera.
A command was run on the camera. Below (on stdin) are: the command, what our catalogue says it does,
the camera's reply, and any NEW lines that appeared in the A7 RTOS capture log after it ran
(some RTOS commands print their help/output only to that log). For `st app` commands there may also be
NEW Linux dlog lines: the camera app prints its output there. Background noise in dlog (DLNA_STACK alive
messages, battery/DEVICED polling) is unrelated to the command.

Classify the run:
- tested: "yes" if it ran and produced the expected kind of output; "partial" if the output was empty,
  only usage/help, an error message, or otherwise unexpected; "failed" if it errored badly or the
  camera stopped responding.
- result_notes: ONE line, plain English, saying concretely what came back (key values, the help it printed,
  argument formats revealed, or "no output"). Mention if output went to the A7 log or dlog rather than the reply.
- new_commands: any concrete command strings revealed by help/usage output that are NOT just the command
  that was run, written as full commands starting with "st " (e.g. "st cap cis expinfo"). Empty list if none.
Respond only with the structured result."""


def now_date():
    return datetime.date.today().isoformat()


def load_rows():
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for c in COLS:
            r.setdefault(c, "")
    return rows


def save_rows(rows):
    tmp = CSV_PATH + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, CSV_PATH)


def cam(cmd, timeout):
    """Run a shell command on the camera via the CGI; return cleaned text output."""
    url = f"http://{CAMERA}/cgi-bin/execute?" + urllib.parse.urlencode({"rawcmd": cmd})
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    html = html.replace("\x00", "").replace("\r", "")
    m = re.search(r"<pre>(.*?)</pre>", html, re.S)
    text = m.group(1) if m else html
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = text.replace("T2EX >> ", "")
    return "".join(ch for ch in text if ch in "\t\n" or 32 <= ord(ch) < 127 or ord(ch) > 159)


CAM_ERRORS = (OSError, http.client.HTTPException)


def handle_camera_error(rows, r, stage, err, took, timeout):
    """Log a failed camera request, mark the row failed, then probe the camera.

    Returns if the camera still answers; saves the CSV and exits if it doesn't."""
    n = next_log_number()
    log_name = f"{n:02d}_{slug(r['run'])}.txt"
    kind = "TIMEOUT" if "timed out" in str(err).lower() else "ERROR"
    with open(os.path.join(LOG_DIR, log_name), "w", encoding="utf-8") as fh:
        fh.write(f"# command: {r['run']}\n# run at: {datetime.datetime.now().isoformat(timespec='seconds')}"
                 f" ({took:.1f}s)\n\n=== {kind} ===\nwhile {stage} (timeout {timeout}s): "
                 f"{type(err).__name__}: {err}\n")
    print(f"  {kind} while {stage}: {type(err).__name__}: {err} -> camera-logs/{log_name}", flush=True)
    r["tested"] = "failed"
    r["tested_date"] = now_date()
    r["log"] = ",".join(x for x in [r["log"], f"{n:02d}"] if x)
    note = f"{kind.lower()} while {stage} after {took:.0f}s ({type(err).__name__}: {err})"
    print("  probing camera with 'echo ok' (15 s) ...", flush=True)
    try:
        cam("echo ok", 15)
    except CAM_ERRORS as probe_err:
        r["result_notes"] = note + "; camera did NOT answer the follow-up 'echo ok' probe"
        save_rows(rows)
        sys.exit(f"\nSTOPPED: camera stopped responding after '{r['run']}' "
                 f"(probe error: {type(probe_err).__name__}: {probe_err}). commands.csv saved.")
    r["result_notes"] = note + "; camera still answered 'echo ok' afterwards"
    save_rows(rows)
    print("  camera still answers; continuing", flush=True)


def a7_log_lines(timeout):
    return cam("st cap log", timeout).splitlines()


DLOG_CMD = "dlogutil -d -v time '*:V'"


def dlog_lines(timeout):
    """Full dump of the Linux main log ring buffer (about 500 KB); diffed before/after, never tailed."""
    return cam(DLOG_CMD, timeout).splitlines()


def next_log_number():
    nums = [int(m.group(1)) for f in os.listdir(LOG_DIR) if (m := re.match(r"^(\d+)_", f))]
    return max(nums, default=0) + 1


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:60]


def ask_haiku(row, reply, new_log, model, new_dlog=None):
    payload = (f"COMMAND: {row['run']}\n"
               f"CATALOGUE DESCRIPTION: {row['description']}\n\n"
               f"=== CAMERA REPLY ===\n{reply}\n\n"
               f"=== NEW A7 LOG LINES ===\n{new_log or '(none)'}\n")
    if new_dlog is not None:
        payload += f"\n=== NEW LINUX DLOG LINES (camera app output goes here) ===\n{new_dlog or '(none)'}\n"
    cmd = ["claude", "-p", HAIKU_INSTRUCTIONS, "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(HAIKU_SCHEMA), "--tools", "", "--no-session-persistence"]
    proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    # Where the structured result lives isn't documented in --help; try the likely places
    # and show the raw response if none parse, rather than guessing silently.
    for candidate in (data.get("structured_output"), data.get("result")):
        if isinstance(candidate, dict):
            return candidate
        if isinstance(candidate, str):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    raise RuntimeError("could not find structured output in claude response:\n" + proc.stdout)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", help="only rows whose family starts with this")
    ap.add_argument("--match", help="only rows whose run command matches this regex")
    ap.add_argument("--skip", help="leave out rows whose run command matches this regex")
    ap.add_argument("--allow", default="", help="extra risk classes to allow, e.g. 'set' or 'set,action'")
    ap.add_argument("--retest", action="store_true", help="also re-run rows that already have a tested value")
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation on set/action rows")
    ap.add_argument("--dry-run", action="store_true", help="list what would run, then stop")
    ap.add_argument("--haiku", dest="no_haiku", action="store_false", default=True,
                    help="classify each row with Claude Haiku as it runs (slow: 30-60 s per row)")
    ap.add_argument("--no-haiku", dest="no_haiku", action="store_true",
                    help="just run and log, don't classify (the default; kept for old commands)")
    ap.add_argument("--model", default="haiku", help="claude model alias (default haiku)")
    ap.add_argument("--dlog", action="store_true",
                    help="capture new dlog lines for every row (default: only rows starting with 'st app')")
    ap.add_argument("--timeout", type=int, default=120, help="seconds per camera request")
    args = ap.parse_args()
    os.makedirs(LOG_DIR, exist_ok=True)

    allowed = {"read"} | {a.strip() for a in args.allow.split(",") if a.strip()}
    allowed -= NEVER_RUN
    rows = load_rows()
    todo = [r for r in rows
            if r["run"].strip()
            and r["risk"] in allowed
            and (args.retest or not r["tested"])
            and (not args.family or r["family"].startswith(args.family))
            and (not args.match or re.search(args.match, r["run"]))
            and (not args.skip or not re.search(args.skip, r["run"]))]

    print(f"{len(todo)} command(s) selected (risk allowed: {', '.join(sorted(allowed))})")
    for r in todo:
        print(f"  [{r['risk']:6}] {r['run']}")
    if args.dry_run or not todo:
        return

    print(f"checking camera at {CAMERA} ...", flush=True)
    try:
        cam("echo ok", 15)
    except CAM_ERRORS as e:
        sys.exit(f"camera not reachable: {e}")

    for i, r in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {r['run']}", flush=True)
        if r["risk"] != "read" and not args.yes:
            if input(f"  risk is '{r['risk']}'. Run it? [y/N] ").strip().lower() != "y":
                print("  skipped")
                continue
        want_dlog = args.dlog or r["run"].startswith("st app")
        start = time.time()
        stage = "reading A7 log before the command"
        new_dlog = None
        try:
            before = set(a7_log_lines(args.timeout))
            if want_dlog:
                stage = "reading dlog before the command"
                dlog_before = set(dlog_lines(args.timeout))
            stage = "sending the command"
            reply = cam(r["run"], args.timeout)
            time.sleep(1)
            stage = "reading A7 log after the command"
            new_log = "\n".join(line for line in a7_log_lines(args.timeout) if line not in before)
            if want_dlog:
                stage = "reading dlog after the command"
                new_dlog = "\n".join(line for line in dlog_lines(args.timeout) if line not in dlog_before)
        except CAM_ERRORS as e:
            handle_camera_error(rows, r, stage, e, time.time() - start, args.timeout)
            continue
        took = time.time() - start

        n = next_log_number()
        log_name = f"{n:02d}_{slug(r['run'])}.txt"
        with open(os.path.join(LOG_DIR, log_name), "w", encoding="utf-8") as fh:
            fh.write(f"# command: {r['run']}\n# run at: {datetime.datetime.now().isoformat(timespec='seconds')}"
                     f" ({took:.1f}s)\n\n=== CAMERA REPLY ===\n{reply}\n\n=== NEW A7 LOG LINES ===\n{new_log}\n")
            if new_dlog is not None:
                fh.write(f"\n=== NEW DLOG LINES ({DLOG_CMD}) ===\n{new_dlog}\n")
        dlog_info = "" if new_dlog is None else f", {len(new_dlog.splitlines())} new dlog lines"
        print(f"  saved camera-logs/{log_name} ({len(reply)} chars reply, "
              f"{len(new_log.splitlines())} new A7 log lines{dlog_info}, {took:.1f}s)", flush=True)

        r["tested_date"] = now_date()
        r["log"] = ",".join(x for x in [r["log"], f"{n:02d}"] if x)
        if args.no_haiku:
            r["tested"] = r["tested"] or "partial"
            r["result_notes"] = "(not classified; see log)"
        else:
            print(f"  asking {args.model} ...", flush=True)
            try:
                verdict = ask_haiku(r, reply, new_log, args.model, new_dlog)
                r["tested"] = verdict["tested"]
                r["result_notes"] = verdict["result_notes"]
                print(f"  -> {verdict['tested']}: {verdict['result_notes']}")
                known = {x["run"] for x in rows} | {x["command"] for x in rows}
                for c in verdict.get("new_commands", []):
                    if c not in known:
                        rows.append({"family": r["family"], "command": c, "run": "", "description":
                                     f"seen in output of '{r['run']}'", "risk": "unknown", "source": "help output",
                                     "tested": "", "tested_date": "", "result_notes": "", "log": f"{n:02d}"})
                        known.add(c)
                        print(f"  + new command added (risk unknown): {c}")
            except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
                r["tested"] = r["tested"] or "partial"
                r["result_notes"] = "(haiku classification failed; see log)"
                print(f"  haiku failed: {e}")
        save_rows(rows)
    print("\ndone; commands.csv updated")


if __name__ == "__main__":
    main()
