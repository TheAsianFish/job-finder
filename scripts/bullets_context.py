"""Print the previous resume entry, talk tracks and Patrick's comments from the
builder's run context as a prompt section for the bullets sessions (AD-45).

Usage: bullets_context.py CONTEXT_JSON. Stdlib only (runs before uv sync).
"""

import json
import sys


def main(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        history = json.load(fh).get("bullets_history") or {}
    print("## Previous version and Patrick's feedback\n")
    if not history.get("entry") and not history.get("feedback"):
        print("None yet: this is the first version of this project's entry.")
        return
    print(f"From {history.get('source', 'the private repo')}.\n")
    if history.get("entry"):
        print("### Entry\n\n```latex\n" + history["entry"].strip() + "\n```\n")
    if history.get("talk_tracks"):
        print("### Talk tracks\n\n" + history["talk_tracks"].strip() + "\n")
    comments = history.get("feedback") or []
    print("### Patrick's comments on the bullets PR\n")
    print("\n\n".join(f"- {c}" for c in comments) if comments else "None.")


if __name__ == "__main__":
    main(sys.argv[1])
