#!/usr/bin/env python3
"""Admin DB jobs from a JSON ops file (no paid links are ever printed).
ops: [{"op":"subjects","course":"<id>"},
      {"op":"remap","course":"<id>","map":{"old subject":"new/path"}, "default":"optional/path"},
      {"op":"patch","data":{"path":value}}]"""
import json, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("RZP_KEY_ID", "x"); os.environ.setdefault("RZP_KEY_SECRET", "x")
import rzp_verify as v
ops = json.load(open(sys.argv[1], encoding="utf-8"))
for o in ops:
    if o["op"] == "subjects":
        items = v.fb("GET", f"paid_content_v3/{o['course']}") or {}
        c = collections.Counter((it.get("subject") or it.get("sub") or "") for it in items.values() if isinstance(it, dict))
        print("SUBJECTS", o["course"], json.dumps(c, ensure_ascii=False))
        print("TITLES", json.dumps(sorted(set((it.get("subject") or it.get("sub") or "") + " :: " + (it.get("title") or it.get("tit") or "")[:60] for it in items.values() if isinstance(it, dict))), ensure_ascii=False))
    elif o["op"] == "remap":
        items = v.fb("GET", f"paid_content_v3/{o['course']}") or {}
        upd = {}
        for k, it in items.items():
            if not isinstance(it, dict): continue
            s = it.get("subject") or it.get("sub") or ""
            new = o["map"].get(s, o.get("default"))
            if new and new != s:
                upd[f"paid_content_v3/{o['course']}/{k}/subject"] = new
                if "sub" in it: upd[f"paid_content_v3/{o['course']}/{k}/sub"] = None
        if upd: v.fb("PATCH", "", upd)
        print("REMAPPED", o["course"], len(upd))
    elif o["op"] == "review":
        # read-only report for store review prep: counts only, no links / emails printed
        pc = v.fb("GET", "paid_courses_v3", query="shallow=true") or {}
        for cid in sorted(pc):
            items = v.fb("GET", f"paid_content_v3/{cid}", query="shallow=true") or {}
            print("PAIDCOUNT", cid, len(items))
        en_all = v.fb("GET", "enrollments_v3") or {}
        per = collections.Counter(c for u in en_all.values() if isinstance(u, dict) for c in u)
        print("ENROLLCOUNT", json.dumps(per, ensure_ascii=False))
        for u in o.get("uids", []):
            e = v.fb("GET", f"enrollments_v3/{u}") or {}
            print("REVIEWER_ENROLL", json.dumps({k: {"source": x.get("source"), "expiresAt": x.get("expiresAt"), "approvedAt": x.get("approvedAt")} for k, x in e.items() if isinstance(x, dict)}))
    elif o["op"] == "patch":
        v.fb("PATCH", "", o["data"]); print("PATCHED", len(o["data"]))
