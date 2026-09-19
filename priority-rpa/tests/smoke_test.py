"""Smoke test for the discovery toolkit against a local mock Priority screen.

Run it to prove the toolkit works on your machine before pointing it at the
real system:

    python tests/smoke_test.py

It never touches Priority — it drives a static HTML file in tests/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from discovery.differ import diff, format_diff, snapshot  # noqa: E402
from discovery.elements import best_frame, harvest_all_frames  # noqa: E402
from discovery.frames import format_tree, frame_records  # noqa: E402
from discovery.recorder import Recorder, format_events  # noqa: E402
from discovery.report import write_dump  # noqa: E402

MOCK = Path(__file__).resolve().parent / "mock-priority.html"
HEADLESS = "--headed" not in sys.argv
# Optional escape hatch for environments where the bundled browser build does
# not match the installed playwright package.
EXECUTABLE = os.environ.get("PW_CHROMIUM_EXECUTABLE") or None

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  PASS  " if condition else "  FAIL  ") + message)
    if not condition:
        failures.append(message)


def main() -> int:
    out_dir = Path(__file__).resolve().parent / "_smoke-out"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS, executable_path=EXECUTABLE)
        page = browser.new_context().new_page()
        page.goto(MOCK.as_uri(), wait_until="load")
        page.wait_for_selector("#mainFrame")

        print("\n[1] frame tree")
        frames = frame_records(page)
        print(format_tree(frames))
        check(len(frames) == 2, "two frames detected (shell + screen iframe)")
        inner = next((f for f in frames if f["parent_index"] == 0), None)
        check(bool(inner and inner["iframe_css"] == "#mainFrame"),
              "iframe addressed as #mainFrame")

        print("\n[2] harvest + selector verification")
        harvests = harvest_all_frames(page)
        main_frame = best_frame(harvests)
        check(main_frame is not None and main_frame["frame_index"] == 1,
              "the screen frame is identified as the one with the fields")
        elements = main_frame["elements"]
        by_name = {e["name"]: e for e in elements if e["name"]}
        check("REFERENCE" in by_name, "reference field found")
        check(bool(by_name["REFERENCE"]["selectors"]),
              "reference field has a verified unique selector: "
              + (by_name["REFERENCE"]["selectors"][0]["selector"] if by_name["REFERENCE"]["selectors"] else "-"))
        check(by_name["REFERENCE"]["label"] == "אסמכתא",
              f"reference label read from <label>: {by_name['REFERENCE']['label']!r}")
        check("reference" in by_name["REFERENCE"]["field_hints"], "reference field classified")
        check(by_name["PARTNAME_1"]["label"] == 'מק"ט',
              f"grid cell labelled from its column header: {by_name['PARTNAME_1']['label']!r}")
        new_button = next((e for e in elements if e["id"] == "btnNew"), None)
        check(bool(new_button) and "new_record" in new_button["action_hints"],
              "'רשומה חדשה' button classified as new_record")
        grid = next((g for g in main_frame["grids"] if g["id"] == "lines"), None)
        check(bool(grid) and grid["input_count"] >= 6, "editable grid detected")
        check(bool(grid) and grid["headers"] == ['מק"ט', "כמות", "מחיר"],
              f"grid headers read: {grid['headers'] if grid else None}")

        print("\n[3] report files")
        write_dump(out_dir, page, frames, harvests, label="smoke")
        for name in ("report.md", "elements.json", "config-draft.yaml", "screenshot.png"):
            check((out_dir / name).exists(), f"{name} written")
        draft = (out_dir / "config-draft.yaml").read_text(encoding="utf-8")
        parsed = None
        try:
            import yaml
            parsed = yaml.safe_load(draft)
            check(isinstance(parsed, dict), "config draft is valid YAML")
        except ImportError:
            print("  SKIP  YAML validity (PyYAML not installed)")
        if isinstance(parsed, dict):
            check(parsed.get("frame", {}).get("selector") == "#mainFrame",
                  f"frame selector survives YAML parsing: {parsed.get('frame', {}).get('selector')!r}")
            check(parsed["orders"]["fields"]["reference"] == "#fRef",
                  f"reference selector in draft: {parsed['orders']['fields']['reference']!r}")
            check(parsed["orders"]["new_record_button"] == "#btnNew",
                  f"new-record button in draft: {parsed['orders']['new_record_button']!r}")
            check(parsed["order_items"]["line_entry_mode"] == "grid",
                  "grid line-entry mode detected")
            check(parsed["order_items"]["columns"]["item_code"] == 'מק"ט',
                  f"line columns mapped by header: {parsed['order_items']['columns']}")

        print("\n[4] diff around a user action")
        before = snapshot(page)
        page.frame_locator("#mainFrame").locator("#btnNew").click()  # stands in for the user
        report = diff(before, snapshot(page))
        text = format_diff(report)
        print(text[:600])
        check("btnConfirm" in text or "אישור" in text, "newly revealed control shows up in the diff")
        check("rows:" in text, "added grid row shows up in the diff")

        print("\n[5] passive recorder")
        recorder = Recorder(page)
        recorder.install()
        page.frame_locator("#mainFrame").locator("#btnSave").click()
        page.frame_locator("#mainFrame").locator("#fRef").press("Control+Enter")
        events = recorder.drain()
        print(format_events(events))
        check(any(e["kind"] == "click" for e in events), "click recorded")
        check(any(e["kind"] == "key" and e.get("ctrl") for e in events),
              "Ctrl shortcut recorded")
        click = next((e for e in events if e["kind"] == "click"), None)
        check(bool(click and (click.get("host") or click["target"]).get("selectors")),
              "recorded click carries a verified selector")

        browser.close()

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("All checks passed.")
    print(f"Sample output written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
