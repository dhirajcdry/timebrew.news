#!/usr/bin/env python3
"""Create offline HTML/plain-text previews. Does not import or call AWS/LLMs.

Usage: python scripts/email_preview.py --output /tmp/timebrew-email-preview
Custom drafts: --draft /path/to/editorial.json --brew-name "My brew"
The default fixture is a clearly labelled historical sample, not live news.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from shared.utils.html_email import format_email_html, format_email_text  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, default=ROOT / "scripts/fixtures/email-draft.json")
    parser.add_argument("--output", type=Path, default=Path("/tmp/timebrew-email-preview"))
    parser.add_argument("--brew-name", default="The curious mind")
    parser.add_argument("--date", default="2024-10-15T08:00:00+00:00", help="Fixed ISO issue date for reproducible previews")
    args = parser.parse_args()
    draft = json.loads(args.draft.read_text(encoding="utf-8"))
    current_time = datetime.fromisoformat(args.date.replace("Z", "+00:00"))
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    args.output.mkdir(parents=True, exist_ok=True)
    paths = {
        "index.html": format_email_html(draft, args.brew_name, current_time),
        "index.txt": format_email_text(draft, args.brew_name, current_time),
        "empty-state.html": format_email_html({"articles": []}, args.brew_name, current_time),
    }
    for filename, content in paths.items():
        path = args.output / filename
        path.write_text(content, encoding="utf-8")
        print(path.resolve())
    print("Offline preview only. No email was sent and no external service was contacted.")


if __name__ == "__main__":
    main()
