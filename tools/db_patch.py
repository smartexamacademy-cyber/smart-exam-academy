#!/usr/bin/env python3
"""Apply a multi-path PATCH to the RTDB as the admin. Usage: db_patch.py <file.json>
File: {"path/a": value, "path/b": null, ...} (null deletes)."""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("RZP_KEY_ID", "x"); os.environ.setdefault("RZP_KEY_SECRET", "x")
import rzp_verify as v
data = json.load(open(sys.argv[1], encoding="utf-8"))
v.fb("PATCH", "", data)
print("applied", len(data), "paths")
