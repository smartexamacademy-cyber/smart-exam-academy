#!/usr/bin/env python3
"""Smart Exam Academy - Razorpay auto-verifier.
Polls Razorpay for payments made from the app (notes.uid + notes.courseId),
checks amount against paid_courses_v3/{courseId}/price, captures if needed,
then writes enrollments_v3/{uid}/{courseId} and marks the purchase request approved.
Env: RZP_KEY_ID, RZP_KEY_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD, RUN_MINUTES (default 345), POLL_SECONDS (15)."""
import base64, json, os, sys, time, urllib.request, urllib.parse, urllib.error

DB = "https://smart-exam-academy-b7101-default-rtdb.firebaseio.com"
KID, KSEC = os.environ["RZP_KEY_ID"].strip(), os.environ["RZP_KEY_SECRET"].strip()
ADMIN_EMAIL, ADMIN_PASS = os.environ.get("ADMIN_EMAIL", "").strip(), os.environ.get("ADMIN_PASSWORD", "")
WEB_KEY = "AIzaSyAmBGqLzAyMyYgADKOOZIv8GQm6fxxNdw4"  # public Firebase web API key
RUN = int(os.environ.get("RUN_MINUTES", "345")) * 60
POLL = int(os.environ.get("POLL_SECONDS", "15"))
AUTH = "Basic " + base64.b64encode(f"{KID}:{KSEC}".encode()).decode()

def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read().decode()
            return json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {url.split('?')[0]} {e.read().decode()[:200]}") from None

def rzp(method, path, body=None):
    return http(method, "https://api.razorpay.com/v1" + path, body, {"Authorization": AUTH})

_tok = {"id": None, "exp": 0}
FBS = os.environ.get("FB_DB_SECRET", "").strip()
def token():
    """Database secret if set, else admin Firebase Auth ID token (refreshed every ~50 min)."""
    if FBS: return FBS
    if _tok["id"] and time.time() < _tok["exp"]: return _tok["id"]
    r = http("POST", "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + WEB_KEY,
             {"email": ADMIN_EMAIL, "password": ADMIN_PASS, "returnSecureToken": True})
    _tok["id"], _tok["exp"] = r["idToken"], time.time() + int(r.get("expiresIn", "3600")) - 600
    return _tok["id"]

def fb(method, path, body=None, query=""):
    q = "auth=" + urllib.parse.quote(token()) + (("&" + query) if query else "")
    return http(method, f"{DB}/{path}.json?{q}", body)

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

done = set()

def handle(p):
    pid = p["id"]
    if pid in done: return
    notes = p.get("notes") or {}
    if isinstance(notes, list): notes = {}
    uid, cid = str(notes.get("uid", "")).strip(), str(notes.get("courseId", "")).strip()
    if not uid or not cid or "/" in uid + cid or "." in uid + cid:
        done.add(pid); return
    if p.get("status") not in ("authorized", "captured"):
        return  # created/failed: check again later (failed ones just stay ignored)
    if fb("GET", f"razorpay_payments/{pid}") is not None:
        done.add(pid); return
    course = fb("GET", f"paid_courses_v3/{cid}")
    if not course or course.get("active") is False:
        log("skip", pid, "course missing/inactive", cid); done.add(pid); return
    want = int(round(float(course.get("price", 0)) * 100))
    if p.get("currency") != "INR" or int(p.get("amount", 0)) != want:
        log("skip", pid, "amount mismatch", p.get("amount"), want); done.add(pid)
        fb("PUT", f"razorpay_payments/{pid}", {"uid": uid, "courseId": cid, "amount": p.get("amount"), "result": "amount_mismatch", "at": int(time.time()*1000)})
        return
    if p["status"] == "authorized":
        rzp("POST", f"/payments/{pid}/capture", {"amount": want, "currency": "INR"})
        log("captured", pid)
    now = int(time.time() * 1000)
    enr = {"approvedAt": now, "source": "razorpay", "paymentId": pid}
    vd = course.get("validityDays")
    try:
        if vd and int(vd) > 0: enr["expiresAt"] = now + int(vd) * 86400000
    except Exception: pass
    existing = fb("GET", f"enrollments_v3/{uid}/{cid}")
    update = {f"razorpay_payments/{pid}": {"uid": uid, "courseId": cid, "amount": want, "result": "enrolled", "at": now,
                                           "email": p.get("email") or "", "contact": p.get("contact") or ""}}
    if not (existing and not existing.get("expiresAt")):  # keep an existing lifetime enrollment as is
        update[f"enrollments_v3/{uid}/{cid}"] = enr
    reqs = fb("GET", f"purchase_requests_v3/{uid}") or {}
    for rk, rv in reqs.items():
        if isinstance(rv, dict) and rv.get("utr") == pid and rv.get("status") == "pending":
            update[f"purchase_requests_v3/{uid}/{rk}/status"] = "approved"
            update[f"purchase_requests_v3/{uid}/{rk}/reviewedAt"] = now
            update[f"purchase_requests_v3/{uid}/{rk}/note"] = "Razorpay se auto-verify"
    fb("PATCH", "", update)
    done.add(pid)
    log("ENROLLED", uid, cid, pid)

def main():
    # sanity checks (no secrets printed)
    rzp("GET", "/payments?count=1"); log("razorpay ok", KID[:9])
    fb("GET", "paid_courses_v3", query="shallow=true"); fb("GET", "enrollments_v3", query="shallow=true"); log("firebase ok")
    end = time.time() + RUN
    since = int(time.time()) - 3 * 86400
    while time.time() < end:
        try:
            skip = 0
            while True:
                r = rzp("GET", f"/payments?from={since}&count=100&skip={skip}")
                items = r.get("items", [])
                for p in items:
                    try: handle(p)
                    except Exception as e: log("err", p.get("id"), type(e).__name__, str(e)[:200])
                if len(items) < 100: break
                skip += 100
        except Exception as e:
            log("poll err", type(e).__name__, str(e)[:200])
        if os.environ.get("ONCE"): break
        time.sleep(POLL)

if __name__ == "__main__":
    main()
