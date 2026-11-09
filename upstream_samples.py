#!/usr/bin/env python3
"""Normalize a small local upstream sample for inspection; never write into a MiMo data pool."""
import argparse
from itertools import islice
import json
from pathlib import Path
import re

SOURCES = {
    "webgen": ("luzimu/webgen-agent_train_sft", "b8ffb7fcd9b633e9bdf2f4d47b692a15a58ca2bd", "train"),
    "swe-smith": ("SWE-bench/SWE-smith-trajectories", "08e109b4a59eaeebf80e4675cd125d42e7ac99a4", "tool"),
}
BOLT = re.compile(r'<boltAction\b[^>]*\btype="([^"]+)"[^>]*>', re.IGNORECASE)
FILE_PATH = re.compile(r'\bfilePath="([^"]+)"', re.IGNORECASE)


def webgen(row):
    turns = []
    for message in row["messages"]:
        role, content = message["role"], message["content"]
        actions = []
        if role in {"assistant", "user"}:
            for match in BOLT.finditer(content):
                action = {"type": match[1], "offset": match.start()}
                if path := FILE_PATH.search(match[0]):
                    action["file_path"] = path[1]
                actions.append(action)
        turns.append({"role": role, "content": content, "action_markers": actions})
    return {"sample_id": f"{row['id']}/{row['step']}", "turns": turns,
            "media_status": "NO_IMAGE_PAYLOAD_OR_REFERENCE_IN_MESSAGE_SCHEMA",
            "conversion": "Preserved messages; indexed Bolt tags as text markers, not executed actions."}


def swe_smith(row):
    messages = json.loads(row["messages"])
    turns = [{k: m[k] for k in ("role", "content", "message_type", "agent", "action",
                               "tool_calls", "tool_call_ids") if k in m} for m in messages]
    return {"sample_id": row["traj_id"], "instance_id": row["instance_id"],
            "teacher": row["model"], "reported_resolved": row["resolved"], "patch": row["patch"],
            "turns": turns, "media_status": "TEXT_TOOL_TRACE",
            "conversion": "Decoded messages JSON; retained tool calls and observations in order; omitted separate thought and cache fields."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=SOURCES)
    parser.add_argument("input", type=Path, help="Local JSONL rows from the documented pinned revision")
    parser.add_argument("--out", required=True, type=Path, help="New local inspection JSONL")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    source, revision, split = SOURCES[args.source]
    convert = webgen if args.source == "webgen" else swe_smith
    with args.input.open(encoding="utf-8") as original, args.out.open("x", encoding="utf-8") as output:
        for index, line in enumerate(islice(original, args.limit)):
            row = convert(json.loads(line))
            json.dump({"upstream_source": source, "revision": revision, "split": split, "license": "MIT",
                       "input_row": index, "use": "LOCAL_INSPECTION_ONLY", **row}, output, ensure_ascii=False)
            output.write("\n")


if __name__ == "__main__":
    main()
