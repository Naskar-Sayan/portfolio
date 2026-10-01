#!/usr/bin/env python3
"""Build a notification-ready digest from the government jobs dataset."""
import argparse
import json
from datetime import date, datetime, timezone


def load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def key(job):
    return (job.get("normalized_key") or (str(job.get("organization", "")) + "|" + str(job.get("title", "")))).strip().lower()


def compact(job):
    return {k: job.get(k) for k in ("id", "title", "organization", "deadline", "vacancies", "pay", "url", "application_url", "official_source", "is_update", "notice_type")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jobs", default="data/jobs.json")
    p.add_argument("--state", default="data/alert_state.json")
    p.add_argument("--output", default="data/alerts.json")
    p.add_argument("--deadline-days", type=int, default=3)
    a = p.parse_args()
    now = datetime.now(timezone.utc)
    today = date.today()
    dataset = load(a.jobs, {"jobs": []})
    current = {key(j): j for j in dataset.get("jobs", []) if key(j)}
    old_state = load(a.state, {})
    old = old_state.get("jobs", {})
    baseline = not bool(old_state.get("initialized_at"))
    new_jobs, updated_jobs, deadline_alerts = [], [], []
    fields = ("title", "organization", "deadline", "vacancies", "pay", "qualification", "application_url", "url", "is_update", "notice_type")
    for k, job in current.items():
        prev = old.get(k)
        if prev is None and not baseline:
            new_jobs.append(compact(job))
        elif prev is not None:
            changed = any(str(prev.get(x) or "").strip().lower() != str(job.get(x) or "").strip().lower() for x in fields)
            material = any(str(prev.get(x) or "").strip().lower() != str(job.get(x) or "").strip().lower() for x in ("title", "deadline", "vacancies", "pay", "is_update", "notice_type"))
            if changed and material:
                updated_jobs.append({"previous": compact(prev), "current": compact(job)})
        if job.get("deadline"):
            try:
                days = (date.fromisoformat(job["deadline"]) - today).days
                if 0 <= days <= a.deadline_days:
                    item = compact(job)
                    item["days_left"] = days
                    deadline_alerts.append(item)
            except ValueError:
                pass
    deadline_alerts.sort(key=lambda x: (x["days_left"], x.get("deadline") or ""))
    lines = []
    for j in new_jobs[:20]:
        lines.append(f"NEW: {j.get('title')} | {j.get('organization')} | Last date: {j.get('deadline') or 'N/A'} | {j.get('application_url') or j.get('url')}")
    for u in updated_jobs[:20]:
        j = u["current"]
        lines.append(f"UPDATED: {j.get('title')} | {j.get('organization')} | Last date: {j.get('deadline') or 'N/A'} | {j.get('application_url') or j.get('url')}")
    for j in deadline_alerts[:20]:
        label = "DEADLINE TODAY" if j["days_left"] == 0 else f"DEADLINE IN {j['days_left']} DAY(S)"
        lines.append(f"{label}: {j.get('title')} | {j.get('organization')} | {j.get('application_url') or j.get('url')}")
    digest = {"generated_at": now.isoformat(), "baseline": baseline, "summary": {"new_jobs": len(new_jobs), "updated_jobs": len(updated_jobs), "deadline_alerts": len(deadline_alerts), "total_jobs_checked": len(current)}, "new_jobs": new_jobs, "updated_jobs": updated_jobs, "deadline_alerts": deadline_alerts, "notification_text": "\\n".join(lines)}
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    state = {"initialized_at": old_state.get("initialized_at") or now.isoformat(), "updated_at": now.isoformat(), "jobs": current}
    with open(a.state, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"Alerts: {len(new_jobs)} new, {len(updated_jobs)} updated, {len(deadline_alerts)} closing soon; baseline={baseline}")


if __name__ == "__main__":
    main()
