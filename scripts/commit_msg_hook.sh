#!/bin/sh
# commit-msg hook for agent-built repos: Patrick's commits carry no AI
# attribution (CLAUDE.md standing rule), whatever the agent writes.
grep -v -e '^Co-[Aa]uthored-[Bb]y:' -e 'Generated with \[Claude' -e '🤖 Generated' "$1" > "$1.clean"
mv "$1.clean" "$1"
