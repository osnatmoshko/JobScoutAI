"""Job Scout AI: agent loop powered by Groq + public job APIs.

The agent fetches live public job feeds, ranks candidates with Python, asks the
external Groq model to evaluate results and decide whether to broaden the search,
and stops when its goal is met or its round limit is reached.
"""

from __future__ import annotations

import json
import os
import re
import html
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urlencode

import requests
from groq import Groq

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
MIN_GOOD_JOBS = 4
MAX_ROUNDS_HARD_LIMIT = 3
REQUEST_TIMEOUT = 20

REMOTIVE_API = "https://remotive.com/api/remote-jobs"
ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"


def validate_api_key_presence(api_key: str) -> bool:
    return bool((api_key or os.environ.get("GROQ_API_KEY", "")).strip())


def split_terms(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\n]", text or "") if part.strip()]


def clean_html(value: str, max_length: int = 1400) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_length]


def _get_json(url: str, params: Optional[dict] = None) -> dict:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "JobScoutAI/1.0 (educational project)"},
        verify=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected response from {url}: expected JSON object")
    return payload


def fetch_remotive_jobs() -> tuple[list[dict], list[str]]:
    """Fetch the public Remotive feed. No API key required; remote roles only."""
    payload = _get_json(REMOTIVE_API, {"limit": 100})
    jobs: list[dict] = []
    for raw in payload.get("jobs", []) or []:
        if not isinstance(raw, dict):
            continue
        job_url = str(raw.get("url") or "").strip()
        if not job_url.startswith("https://"):
            continue
        description = clean_html(str(raw.get("description") or ""))
        technologies = []
        category = str(raw.get("category") or "")
        if category:
            technologies.append(category)
        jobs.append({
            "id": f"remotive-{raw.get('id', job_url)}",
            "title": str(raw.get("title") or "Unknown title").strip(),
            "company": str(raw.get("company_name") or "Unknown company").strip(),
            "location": str(raw.get("candidate_required_location") or "Remote; location not specified").strip(),
            "seniority": "",
            "technologies": technologies,
            "summary": description,
            "requirements": [],
            "posted_date": str(raw.get("publication_date") or ""),
            "job_url": job_url,
            "source_url": job_url,
            "source_name": "Remotive",
            "salary": str(raw.get("salary") or ""),
            "job_type": str(raw.get("job_type") or ""),
        })
    return jobs, [f"Remotive: {len(jobs)} מודעות מרחוק נטענו"]


def fetch_arbeitnow_jobs(max_pages: int = 1) -> tuple[list[dict], list[str]]:
    """Fetch up to three pages from the public Arbeitnow feed; no key required."""
    jobs: list[dict] = []
    notes: list[str] = []
    for page in range(1, max(1, min(max_pages, 3)) + 1):
        payload = _get_json(ARBEITNOW_API, {"page": page})
        rows = payload.get("data", []) or []
        if not rows:
            break
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            job_url = str(raw.get("url") or "").strip()
            if not job_url.startswith("https://"):
                continue
            tags = raw.get("tags") or []
            if not isinstance(tags, list):
                tags = []
            created = raw.get("created_at")
            posted_date = ""
            if isinstance(created, (int, float)) and created > 0:
                posted_date = datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d")
            description = clean_html(str(raw.get("description") or ""))
            jobs.append({
                "id": f"arbeitnow-{raw.get('slug') or job_url}",
                "title": str(raw.get("title") or "Unknown title").strip(),
                "company": str(raw.get("company_name") or "Unknown company").strip(),
                "location": str(raw.get("location") or ("Remote" if raw.get("remote") else "Location not specified")).strip(),
                "seniority": "",
                "technologies": [str(tag) for tag in tags if str(tag).strip()],
                "summary": description,
                "requirements": [],
                "posted_date": posted_date,
                "job_url": job_url,
                "source_url": job_url,
                "source_name": "Arbeitnow",
                "salary": "",
                "job_type": ", ".join(str(item) for item in (raw.get("job_types") or [])),
                "remote": bool(raw.get("remote")),
            })
        notes.append(f"Arbeitnow עמוד {page}: {len(rows)} מודעות התקבלו")
        if not payload.get("links", {}).get("next"):
            break
    return jobs, notes


def fetch_job_tool(on_event: Optional[Callable[[str], None]] = None) -> tuple[list[dict], list[str], list[str]]:
    """External tool: fetch job listings from public APIs and normalize them."""
    all_jobs: list[dict] = []
    notes: list[str] = []
    errors: list[str] = []
    sources = [
        {"title": "Remotive public remote jobs API", "url": "https://remotive.com/remote-jobs/api"},
        {"title": "Arbeitnow public job board API", "url": "https://www.arbeitnow.com/api/job-board-api"},
    ]
    for source_name, fetcher in [
        ("Remotive", fetch_remotive_jobs),
        ("Arbeitnow", fetch_arbeitnow_jobs),
    ]:
        try:
            jobs, source_notes = fetcher()
            all_jobs.extend(jobs)
            notes.extend(source_notes)
            if on_event:
                on_event(f"כלי חיצוני {source_name}: נטענו {len(jobs)} משרות.")
        except requests.RequestException as exc:
            errors.append(f"{source_name}: שגיאת רשת ({exc})")
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"{source_name}: תשובה לא צפויה מהמקור ({exc})")
    unique: dict[str, dict] = {}
    for job in all_jobs:
        key = job.get("job_url", "").lower().rstrip("/")
        if key and key not in unique:
            unique[key] = job
    return list(unique.values()), notes, errors


def _contains_any(text: str, terms: list[str]) -> int:
    lower = (text or "").lower()
    return sum(1 for term in terms if term and term.lower() in lower)


def score_job(job: dict, profile: dict, search_terms: list[str]) -> dict:
    """Deterministic Python tool: score each job out of 100."""
    title = job.get("title", "")
    technologies = job.get("technologies") or []
    description = job.get("summary", "")
    location = job.get("location", "")
    combined = " ".join([
        title, description, " ".join(technologies), job.get("company", ""), location
    ]).lower()

    skills = [item.lower() for item in profile.get("skills", []) if item.strip()]
    roles = [item.lower() for item in profile.get("roles", []) if item.strip()]
    skill_matches = [skill for skill in skills if skill in combined]
    role_matches = [role for role in roles if role in title.lower()]
    keyword_matches = [term for term in search_terms if term.lower() in combined]

    skill_score = min(40, round(40 * len(set(skill_matches)) / max(1, min(len(set(skills)), 6))))
    role_score = 20 if role_matches else (12 if _contains_any(combined, ["developer", "engineer", "software", "programmer", "frontend", "backend", "full stack"]) else 4)

    seniority_text = (title + " " + description[:500]).lower()
    if any(term in seniority_text for term in ["senior", "lead developer", "principal", "head of", "manager", "ראש צוות", "בכיר"]):
        level_score = 0
    elif any(term in seniority_text for term in ["junior", "entry-level", "entry level", "graduate", "student", "intern", "trainee", "ג׳וניור", "סטודנט"]):
        level_score = 20
    else:
        level_score = 12 if profile.get("experience_level") == "פתוחה גם למשרות אחרות" else 8

    requested_location = profile.get("location", "").lower()
    location_lower = location.lower()
    if any(term in profile.get("remote", "").lower() for term in ["מרחוק", "remote"]):
        location_score = 10 if any(term in location_lower for term in ["remote", "worldwide", "anywhere", "מרחוק"]) or job.get("remote") else 4
    elif requested_location and any(term in location_lower for term in requested_location.split() if len(term) > 2):
        location_score = 10
    elif any(term in location_lower for term in ["israel", "ישראל", "tel aviv", "jerusalem", "תל אביב", "ירושלים"]):
        location_score = 8
    else:
        location_score = 4

    posted = job.get("posted_date", "")
    freshness_score = 8 if posted and posted[:4] == str(datetime.now().year) else (4 if posted else 2)
    score = max(0, min(100, skill_score + role_score + level_score + location_score + freshness_score))

    exclusions = (profile.get("exclusions") or "").lower()
    if any(term in exclusions for term in ["senior", "בכיר", "ניהול", "manager", "lead"]) and any(term in seniority_text for term in ["senior", "lead", "principal", "manager", "בכיר"]):
        score = max(0, score - 25)

    result = dict(job)
    result.update({
        "score": score,
        "matched_skills": skill_matches,
        "keyword_matches": keyword_matches,
        "match_reason": "",
        "gaps": "",
        "confidence_note": "הציון מחושב אוטומטית מהמידע הזמין; יש לבדוק את המודעה המקורית.",
    })
    return result


def filter_jobs(jobs: list[dict], profile: dict, search_terms: list[str]) -> list[dict]:
    """Search tool: apply the agent's current keywords to fetched job listings."""
    terms = list(dict.fromkeys([t.strip().lower() for t in search_terms if t.strip()]))
    scored = []
    for job in jobs:
        result = score_job(job, profile, terms)
        searchable = " ".join([
            result.get("title", ""), result.get("company", ""), result.get("location", ""),
            " ".join(result.get("technologies") or []), result.get("summary", "")
        ]).lower()
        if any(term in searchable for term in terms) or result["score"] >= 20:
            scored.append(result)
    scored.sort(key=lambda item: (item["score"], bool(item.get("job_url"))), reverse=True)
    return scored


def _parse_json_response(text: str) -> dict:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("מודל Groq לא החזיר JSON תקין.")
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("תשובת Groq אינה אובייקט JSON.")
    return value


def ask_agent_to_evaluate(client: Groq, profile: dict, round_number: int, search_terms: list[str], candidates: list[dict], prior_count: int) -> dict:
    """External AI reasoning step: select evidence-backed jobs and choose next action."""
    compact_jobs = []
    for job in candidates[:22]:
        compact_jobs.append({
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "technologies": job.get("technologies", [])[:12],
            "summary": job.get("summary", "")[:650],
            "posted_date": job.get("posted_date", ""),
            "score": job.get("score", 0),
            "url": job.get("job_url", ""),
            "source": job.get("source_name", ""),
        })
    payload = {
        "candidate_profile": profile,
        "round": round_number,
        "current_search_terms": search_terms,
        "jobs_already_selected_in_prior_rounds": prior_count,
        "goal": f"Find at least {MIN_GOOD_JOBS} relevant, evidence-backed early-career software jobs if the available feeds contain them.",
        "candidates_from_external_job_apis": compact_jobs,
    }
    system_message = (
        "You are Job Scout AI, an autonomous job-search agent. Use only the supplied job records. "
        "Never invent job IDs, companies, requirements, URLs, or facts. The numeric score is a Python-produced signal, "
        "not a guarantee. Decide whether the search goal has been met. If fewer than 4 credible matches are available, "
        "usually broaden the search with adjacent technologies/role synonyms, unless the data is clearly exhausted. "
        "Return ONLY valid JSON with keys: selected_jobs (array of objects with id, match_reason, gaps), "
        "decision (stop or broaden), decision_reason (string), additional_keywords (array of 3-8 short strings), "
        "summary (string). Only select IDs that appear in candidates_from_external_job_apis. "
        "Do not claim a job is open beyond what its feed entry indicates."
    )
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=3000,
    )
    content = completion.choices[0].message.content or "{}"
    return _parse_json_response(content)


def _initial_terms(profile: dict) -> list[str]:
    terms = profile.get("roles", [])[:5] + profile.get("skills", [])[:8]
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))


def _merge_job_details(existing: dict, update: dict) -> dict:
    merged = dict(existing)
    for field in ["match_reason", "gaps"]:
        if update.get(field):
            merged[field] = str(update[field])
    return merged


def run_job_agent(
    api_key: str,
    profile: dict,
    max_rounds: int = 2,
    on_event: Optional[Callable[[str], None]] = None,
) -> dict:
    """Run the bounded agent loop and return jobs, decisions, sources, and trace."""
    key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()
    if not key:
        raise ValueError("חסר מפתח Groq API. הזיני מפתח Groq, לא מפתח Gemini.")
    max_rounds = max(1, min(MAX_ROUNDS_HARD_LIMIT, int(max_rounds)))
    client = Groq(api_key=key)
    trace: list[str] = []

    def emit(message: str) -> None:
        trace.append(message)
        if on_event:
            on_event(message)

    emit("שלב 1: הפעלת כלי חיפוש חיצוני לטעינת מודעות ממקורות ציבוריים.")
    raw_jobs, source_notes, fetch_errors = fetch_job_tool(on_event=on_event)
    for note in source_notes:
        emit(note)
    for error in fetch_errors:
        emit("אזהרה: " + error)
    if not raw_jobs:
        raise RuntimeError(
            "לא הצלחנו לטעון מודעות מאף מקור חיצוני. בדקי חיבור לאינטרנט ונסי שוב. "
            + " | ".join(fetch_errors)
        )
    emit(f"כלי החיפוש החזיר {len(raw_jobs)} מודעות ייחודיות לפני סינון.")

    terms = _initial_terms(profile)
    selected_by_id: dict[str, dict] = {}
    all_sources = [
        {"title": "Remotive public remote jobs API", "url": "https://remotive.com/remote-jobs/api"},
        {"title": "Arbeitnow public job board API", "url": "https://www.arbeitnow.com/api/job-board-api"},
    ]
    decision_summary = ""
    rounds_done = 0

    for round_number in range(1, max_rounds + 1):
        rounds_done = round_number
        emit(f"סבב {round_number}: חיפוש לפי מילות המפתח: {', '.join(terms[:12])}.")
        candidates = filter_jobs(raw_jobs, profile, terms)
        emit(f"כלי Python דירג {len(candidates)} מודעות לפי טכנולוגיות, תפקיד, רמה, מיקום ותאריך.")

        try:
            evaluation = ask_agent_to_evaluate(
                client=client,
                profile=profile,
                round_number=round_number,
                search_terms=terms,
                candidates=candidates,
                prior_count=len(selected_by_id),
            )
        except Exception as api_err:
            emit(f"אזהרה בקריאת LLM ({api_err}), מעבר למצב חירום אוטומטי (Python Scoring fallback).")
            evaluation = {
                "selected_jobs": [{"id": j["id"], "match_reason": "הותאם אוטומטית לפי מילות מפתח וציון פייתון.", "gaps": ""} for j in candidates[:5]],
                "decision": "stop",
                "decision_reason": "נבחר אוטומטית עקב מגבלת תקשורת עם המודל.",
                "additional_keywords": [],
                "summary": "החיפוש הושלם בהצלחה באמצעות מנוע הדירוג של פייתון."
            }
        candidate_by_id = {job["id"]: job for job in candidates}
        chosen = evaluation.get("selected_jobs", [])
        if not isinstance(chosen, list):
            chosen = []
        newly_selected = 0
        for item in chosen:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("id", ""))
            if job_id not in candidate_by_id:
                continue
            enriched = _merge_job_details(candidate_by_id[job_id], item)
            if job_id not in selected_by_id:
                newly_selected += 1
            selected_by_id[job_id] = enriched

        if not selected_by_id:
            for job in candidates[:10]:
                selected_by_id[job["id"]] = job
            emit("לא התקבלו מזהי משרות תקינים מהמודל; נשמרו התוצאות המובילות של כלי Python.")

        promising_count = sum(1 for job in selected_by_id.values() if job.get("score", 0) >= 45 and job.get("job_url"))
        decision = str(evaluation.get("decision", "broaden")).lower().strip()
        reason = str(evaluation.get("decision_reason", "ההחלטה התקבלה לפי איכות התוצאות הזמינות."))
        additional = evaluation.get("additional_keywords", [])
        if not isinstance(additional, list):
            additional = []
        additional = [str(item).strip() for item in additional if str(item).strip()][:8]

        emit(f"בדיקת תוצאה: {len(selected_by_id)} משרות ייחודיות נבחרו; {promising_count} עם ציון 45 ומעלה וקישור למודעה.")
        emit(f"החלטת Groq: {decision}. נימוק: {reason}")
        decision_summary = str(evaluation.get("summary", "")) or reason

        if promising_count >= MIN_GOOD_JOBS:
            decision_summary = f"האג'נט מצא {promising_count} משרות מבטיחות עם קישורים, ולכן עצר. {reason}"
            emit("תנאי עצירה הושג: נמצאו לפחות 4 משרות מבטיחות.")
            break
        if decision == "stop":
            decision_summary = f"האג'נט החליט לעצור כי {reason}"
            emit("האג'נט בחר לעצור לפי הערכת המודל, אף שהיעד הכמותי לא הושג.")
            break
        if round_number >= max_rounds:
            decision_summary = f"האג'נט עצר לאחר {round_number} סבבים. {reason}"
            emit("תנאי עצירה: מוצתה מגבלת הסבבים.")
            break

        if not additional:
            additional = ["entry level", "graduate developer", "associate software engineer", "application developer"]
        terms = list(dict.fromkeys(terms + additional))
        emit("האג'נט החליט להרחיב את החיפוש בסבב הבא עם מילות מפתח נוספות.")

    final_jobs = sorted(
        selected_by_id.values(),
        key=lambda item: (item.get("score", 0), bool(item.get("job_url"))),
        reverse=True,
    )[:15]
    for job in final_jobs:
        job.pop("id", None)

    return {
        "jobs": final_jobs,
        "sources": all_sources,
        "rounds": rounds_done,
        "trace": trace,
        "decision_summary": decision_summary or "האג'נט סיים את החיפוש.",
        "source_notes": source_notes,
        "fetch_errors": fetch_errors,
    }