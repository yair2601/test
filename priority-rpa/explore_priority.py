"""Interactive, read-only explorer for the Priority Web UI.

    python explore_priority.py --url https://your-priority-host/...

This tool NEVER clicks, types, saves or submits anything in Priority. You drive
the browser by hand; it observes and reports. That is deliberate — there is no
test environment, so nothing automated is allowed to touch live data.

Console output is English on purpose: Windows terminals mangle Hebrew. The
Hebrew content of the screen is preserved correctly in the report files, which
are written as UTF-8.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from discovery.browser import Session, has_saved_state
from discovery.differ import diff, format_diff, snapshot
from discovery.elements import harvest_all_frames
from discovery.frames import format_tree, frame_records
from discovery.netlog import NetLog, format_entries
from discovery.recorder import Recorder, format_events
from discovery.report import write_dump
from discovery.util import safe_name, stamp, write_json

HELP = """
Commands (you navigate Priority yourself; this tool only looks):

  frames              Show the frame tree (which iframe the screen lives in)
  dump [label]        Full capture of the current screen ->
                        report.md, elements.json, config-draft.yaml,
                        screenshot.png, html/ per frame
  pick                Start recording YOUR clicks and shortcuts
  stop                Stop recording and print the verified selectors
  snap                Take a "before" snapshot
  diff                Compare the current screen to the last snapshot
                        (snap -> do the thing by hand -> diff)
  net on|off          Toggle network (XHR) logging
  net show            Print what has been logged so far
  url                 Print the current URL of every frame
  help                This text
  quit                Close the browser and exit

Typical session:
  1. frames                      - learn the frame layout
  2. dump orders-empty           - baseline capture of the ORDERS screen
  3. snap                        - then click "new record" YOURSELF
  4. diff                        - see exactly what that button did
  5. pick                        - then click the button again, plus the fields
  6. stop                        - get verified selectors for all of them
  7. dump orders-new-record      - capture the screen in its new state
"""


class Explorer:
    def __init__(self, session: Session, out_root: Path, capture_values: bool,
                 capture_payloads: bool):
        self.session = session
        self.page = session.page
        self.out_root = out_root
        self.capture_values = capture_values
        self.recorder = Recorder(self.page)
        self.netlog = NetLog(self.page, capture_payloads=capture_payloads)
        self.baseline: dict | None = None
        self.recording = False
        self.dump_index = 0

    # -- commands ---------------------------------------------------------

    def cmd_frames(self, _arg: str = "") -> None:
        records = frame_records(self.page)
        print(f"\n{len(records)} frame(s):")
        print(format_tree(records) or "  (single frame)")
        print("\nSelectors are always relative to a frame. Note the index you need.")

    def cmd_url(self, _arg: str = "") -> None:
        for index, frame in enumerate(self.page.frames):
            print(f"  [{index}] {frame.url}")

    def cmd_dump(self, arg: str = "") -> None:
        label = arg.strip()
        self.dump_index += 1
        name = f"{self.dump_index:02d}-{safe_name(label) if label else 'dump'}"
        out_dir = self.out_root / name

        print("Harvesting frames (verifying every selector against the live page)...")
        frames = frame_records(self.page)
        harvests = harvest_all_frames(self.page, capture_values=self.capture_values)
        net_entries = self.netlog.drain() if self.netlog.enabled else []

        write_dump(out_dir, self.page, frames, harvests, label=label, net_entries=net_entries)

        total = sum(len(h.get("elements", [])) for h in harvests)
        inputs = sum(h.get("input_count", 0) for h in harvests)
        print(f"\nWrote {out_dir}")
        print(f"  {total} elements across {len(harvests)} frame(s), {inputs} visible inputs")
        print(f"  Start with {out_dir / 'report.md'}")

    def cmd_pick(self, _arg: str = "") -> None:
        installed = self.recorder.install()
        self.recorder.drain(verify=False)  # clear anything buffered earlier
        self.recording = True
        print(f"\nRecording in {installed} frame(s).")
        print("Go to the browser and click the controls you want selectors for.")
        print("Keyboard shortcuts are recorded too (only keys with modifiers and")
        print("special keys such as F1-F12/Enter/Esc - never what you type).")
        print("Come back and run `stop` when you are done.")

    def cmd_stop(self, _arg: str = "") -> None:
        if not self.recording:
            print("Not recording. Run `pick` first.")
            return
        # Re-install first: a navigation may have created frames mid-recording.
        self.recorder.install()
        events = self.recorder.drain()
        self.recording = False
        print(f"\n{len(events)} event(s) recorded:\n")
        print(format_events(events))
        if events:
            path = self.out_root / f"picks-{stamp()}.json"
            write_json(path, events)
            print(f"\nSaved to {path}")

    def cmd_snap(self, _arg: str = "") -> None:
        self.baseline = snapshot(self.page)
        nodes = sum(len(f["nodes"]) for f in self.baseline.values())
        print(f"Snapshot taken: {len(self.baseline)} frame(s), {nodes} nodes.")
        print("Now perform the action in the browser yourself, then run `diff`.")

    def cmd_diff(self, _arg: str = "") -> None:
        if self.baseline is None:
            print("No baseline. Run `snap` first.")
            return
        after = snapshot(self.page)
        report = diff(self.baseline, after)
        print(format_diff(report))
        path = self.out_root / f"diff-{stamp()}.json"
        write_json(path, report)
        print(f"\nSaved to {path}")
        self.baseline = after
        print("(The new state is now the baseline, so you can chain steps.)")

    def cmd_net(self, arg: str = "") -> None:
        arg = arg.strip().lower()
        if arg == "on":
            self.netlog.start()
            print("Network logging ON (XHR/fetch/document only).")
        elif arg == "off":
            self.netlog.stop()
            print("Network logging OFF.")
        elif arg == "show":
            print(format_entries(self.netlog.entries))
        else:
            print("Usage: net on | net off | net show")

    def cmd_help(self, _arg: str = "") -> None:
        print(HELP)

    # -- loop -------------------------------------------------------------

    COMMANDS = {
        "frames": cmd_frames, "dump": cmd_dump, "pick": cmd_pick, "stop": cmd_stop,
        "snap": cmd_snap, "diff": cmd_diff, "net": cmd_net, "url": cmd_url,
        "help": cmd_help, "?": cmd_help,
    }

    def run(self) -> None:
        print(HELP)
        while True:
            try:
                raw = input("\npriority> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                return
            if not raw:
                continue
            command, _, arg = raw.partition(" ")
            command = command.lower()
            if command in ("quit", "exit", "q"):
                print("Closing the browser.")
                return
            handler = self.COMMANDS.get(command)
            if not handler:
                print(f"Unknown command {command!r}. Type `help`.")
                continue
            try:
                handler(self, arg)
            except Exception:
                print("Command failed:")
                traceback.print_exc()
                print("\nThe browser is still open; nothing in Priority was changed.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only explorer for the Priority Web UI")
    parser.add_argument("--url", default=None,
                        help="URL to open (defaults to the session's saved final_url)")
    parser.add_argument("--state", default="storage_state.json",
                        help="Saved session from login.py")
    parser.add_argument("--out", default="discovery-out", help="Output directory")
    parser.add_argument("--channel", default=None, help="Browser channel, e.g. 'msedge'")
    parser.add_argument("--slow-mo", type=int, default=0, help="Playwright slow_mo, ms")
    parser.add_argument("--capture-values", action="store_true",
                        help="Include current field values in dumps (OFF by default: "
                             "this is production data)")
    parser.add_argument("--capture-payloads", action="store_true",
                        help="Include XHR request bodies in the network log (OFF by default)")
    args = parser.parse_args()

    state = Path(args.state)
    if not has_saved_state(state):
        print(f"No saved session at {state}. Run login.py first:")
        print("  python login.py --url https://your-priority-host/...")
        return 1

    url = args.url
    if not url:
        info = Path("session-info.json")
        if info.exists():
            import json
            url = json.loads(info.read_text(encoding="utf-8")).get("final_url")
    if not url:
        print("No --url given and no final_url in session-info.json.")
        return 1

    out_root = Path(args.out) / stamp()
    out_root.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Priority explorer — READ ONLY")
    print("=" * 70)
    print("This tool does not click, type or save anything in Priority.")
    print("You drive the browser; it observes.\n")
    print(f"Opening: {url}")
    print(f"Output:  {out_root.resolve()}")

    with Session(storage_state=state, start_url=url, slow_mo=args.slow_mo,
                 browser_channel=args.channel) as session:
        if "login" in session.page.url.lower() and session.page.url != url:
            print("\nWARNING: you appear to have been redirected to a login page.")
            print("The saved session has probably expired — re-run login.py.")
        Explorer(session, out_root, args.capture_values, args.capture_payloads).run()

    print(f"\nEverything written to: {out_root.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
