"""One-time manual login to Priority; saves the session for later runs.

You log in yourself, in a real browser window, including MFA. Nothing about
your credentials touches this code, the config, or the disk beyond the cookie
jar Playwright writes.

    python login.py --url https://your-priority-host/...

Afterwards, navigate to the ORDERS screen before pressing Enter: the script
records the URL you ended on, which is the one the loader will use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from discovery.browser import Session
from discovery.frames import format_tree, frame_records
from discovery.util import now_iso, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual Priority login -> storage_state.json")
    parser.add_argument("--url", required=True, help="Priority login URL")
    parser.add_argument("--state", default="storage_state.json", help="Where to save the session")
    parser.add_argument("--channel", default=None,
                        help="Browser channel, e.g. 'msedge' or 'chrome' (default: bundled Chromium)")
    args = parser.parse_args()

    state_path = Path(args.state)
    print("=" * 70)
    print("Priority — manual login")
    print("=" * 70)
    print("A browser window will open. Log in normally, complete MFA, pick the")
    print("company if you are asked to, and then NAVIGATE TO THE ORDERS SCREEN.")
    print("Only then come back here and press Enter.\n")

    with Session(storage_state=None, start_url=args.url, browser_channel=args.channel) as session:
        input("Press Enter once you are logged in and standing on the ORDERS screen... ")

        page = session.page
        frames = frame_records(page)
        saved = session.save_state(state_path)

        info = {
            "saved_at": now_iso(),
            "login_url": args.url,
            "final_url": page.url,
            "page_title": page.title(),
            "frames": frames,
        }
        write_json(Path("session-info.json"), info)

        print(f"\nSession saved to: {saved.resolve()}")
        print("Session details saved to: session-info.json")
        print(f"\nURL you ended on (this is your orders_url):\n  {page.url}\n")
        print("Frame tree:")
        print(format_tree(frames) or "  (single frame)")
        print("\nBoth files contain live session cookies. They are in .gitignore —")
        print("do not commit them and do not paste their contents anywhere.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
