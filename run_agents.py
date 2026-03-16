"""
LinkedIn Agent Runner — Chunked & Resumable
=============================================
Two modes:

  SCREEN mode:  Runs Agent 1 on unprocessed jobs, stops after N passes.
                Progress is saved — resume any time from where you left off.

  EVALUATE mode: Runs Agent 2 on all Agent 1 passes (or a chunk of them).
                 Reads descriptions from linkedin_jobs.json — no re-screening needed.
                 Each run saves to a new named CSV for easy comparison.

Usage:
  # Screen next 100 jobs (Agent 1 only), stop after 100 passes
  python run_agents.py --mode screen --chunk 100

  # Resume screening from where you left off
  python run_agents.py --mode screen --chunk 100

  # Run Agent 2 on all Agent 1 passes, save to named file
  python run_agents.py --mode evaluate --output results_chill7.csv

  # Re-run Agent 2 with looser threshold
  python run_agents.py --mode evaluate --chill-threshold 6 --output results_chill6.csv

  # Screen + evaluate in one go (100 pass chunk, then Agent 2 on those 100)
  python run_agents.py --mode both --chunk 100 --output results_batch1.csv
"""

import json
import csv
import time
import os
import sys
import argparse
from datetime import datetime
from typing import Optional

import google.generativeai as genai

# Import your personal prompts (copy profile.example.py → profile.py and fill it in)
try:
    from candidate_profile import AGENT1_PROMPT, AGENT2_PROMPT
except ImportError:
    print("❌ candidate_profile.py not found.")
    print("   Copy candidate_profile.example.py to candidate_profile.py and paste in your prompts.")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

INPUT_JSON      = "linkedin_jobs.json"
PROGRESS_FILE   = "progress.json"
DEFAULT_OUTPUT  = "linkedin_results.csv"
GEMINI_MODEL    = "gemini-3.1-flash-lite"
API_DELAY       = 4.0
CHILL_THRESHOLD = 7


# ─────────────────────────────────────────────────────────────
# ARG PARSING
# ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Job Finder Agent Runner — Chunked & Resumable",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  screen    Run Agent 1 on unprocessed jobs. Stops after --chunk passes.
  evaluate  Run Agent 2 on all Agent 1 passes. Saves to --output file.
  both      Screen a chunk, then immediately evaluate those jobs.

Examples:
  python run_agents.py --mode screen --chunk 100
  python run_agents.py --mode screen --chunk 100 --input jobrxiv_jobs.json
  python run_agents.py --mode evaluate --output results_strict.csv
  python run_agents.py --mode evaluate --chill-threshold 6 --output results_loose.csv
  python run_agents.py --mode both --chunk 50 --output batch1.csv
  python run_agents.py --mode both --chunk 50 --input euraxess_jobs.json --output euraxess_batch1.csv
        """
    )
    parser.add_argument("--mode",            choices=["screen", "evaluate", "both"],
                        default="both",      help="Run mode (default: both)")
    parser.add_argument("--input",           default=INPUT_JSON,
                        help=f"Input JSON file (default: {INPUT_JSON})")
    parser.add_argument("--progress",        default=PROGRESS_FILE,
                        help=f"Progress tracking file (default: {PROGRESS_FILE})")
    parser.add_argument("--output",          default=None,
                        help="Output CSV filename (prompted if not provided in evaluate/both mode)")
    parser.add_argument("--chunk",           default=100, type=int,
                        help="Number of Agent 1 passes before stopping (default: 100)")
    parser.add_argument("--chill-threshold", default=CHILL_THRESHOLD, type=int,
                        help=f"Min chill score for Agent 2 approval (default: {CHILL_THRESHOLD})")
    return parser.parse_args()

# ─────────────────────────────────────────────────────────────
# PROGRESS TRACKING
# ─────────────────────────────────────────────────────────────

def load_progress(progress_file: str) -> dict:
    """Load progress from file, or return fresh state."""
    if os.path.isfile(progress_file):
        with open(progress_file, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  📂 Resuming from progress file: {progress_file}")
        print(f"     Jobs already processed: {len(data.get('agent1_results', {}))}")
        print(f"     Last index processed:   {data.get('last_processed_index', -1) + 1}")
        return data
    print(f"  🆕 No progress file found — starting fresh.")
    return {
        "last_processed_index": -1,
        "agent1_results": {}   # job_id → {result, reason}
    }


def save_progress(progress: dict, progress_file: str):
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def get_pass_count(progress: dict) -> int:
    return sum(
        1 for v in progress["agent1_results"].values()
        if v.get("result") == "PASS"
    )


def get_passed_job_ids(progress: dict) -> list[str]:
    return [
        jid for jid, v in progress["agent1_results"].items()
        if v.get("result") == "PASS"
    ]

# ─────────────────────────────────────────────────────────────
# GEMINI
# ─────────────────────────────────────────────────────────────

def setup_gemini():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("\n⚠️  GEMINI_API_KEY not set.")
        print("   Get free key: https://aistudio.google.com/app/apikey")
        api_key = input("   Paste key: ").strip()
        if not api_key:
            sys.exit("No API key provided.")
    genai.configure(api_key=api_key)


def call_gemini(prompt: str, retries: int = 3) -> Optional[str]:
    model = genai.GenerativeModel(GEMINI_MODEL)
    for attempt in range(retries):
        try:
            resp = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1, max_output_tokens=1200
                )
            )
            return resp.text
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "quota" in err or "rate" in err:
                wait = 30 * (attempt + 1)
                print(f"    ⏳ Rate limit — waiting {wait}s...")
                time.sleep(wait)
            elif "blocked" in err or "safety" in err:
                return None
            elif attempt < retries - 1:
                time.sleep(5)
            else:
                print(f"    ❌ API failed: {e}")
    return None


def parse_json_response(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    if "```" in text:
        for chunk in text.split("```"):
            chunk = chunk.strip().lstrip("json").strip()
            if chunk.startswith("{"):
                try:
                    return json.loads(chunk)
                except Exception:
                    continue
    try:
        return json.loads(text)
    except Exception:
        pass
    s, e = text.find("{"), text.rfind("}") + 1
    if 0 <= s < e:
        try:
            return json.loads(text[s:e])
        except Exception:
            pass
    return None

# ─────────────────────────────────────────────────────────────
# AGENT 1 — TECHNICAL SCREENER
# ─────────────────────────────────────────────────────────────

def agent1_screen(job: dict) -> dict:
    prompt = f"""{AGENT1_PROMPT}

## JOB TO EVALUATE:
Title:    {job.get('title', 'N/A')}
Company:  {job.get('company', 'N/A')}
Location: {job.get('location', 'N/A')}

Description:
{(job.get('description') or 'No description available.')[:2500]}

## TASK:
Reply with ONLY raw JSON — no markdown, no explanation:
{{"result": "PASS", "reason": "one sentence explaining the decision"}}

result: exactly PASS or REJECT"""

    raw = call_gemini(prompt)
    result = parse_json_response(raw)

    if result and result.get("result") in ("PASS", "REJECT"):
        return {"result": result["result"], "reason": result.get("reason", "")}

    if raw:
        print(f"    ⚠️  Agent 1 parse failed: {raw[:120]}")
        upper = raw.upper()
        if "REJECT" in upper:
            return {"result": "REJECT", "reason": "Parse failed — inferred REJECT"}
        if "PASS" in upper:
            return {"result": "PASS", "reason": "Parse failed — inferred PASS"}

    return {"result": "REJECT", "reason": "No response from model"}

# ─────────────────────────────────────────────────────────────
# AGENT 2 — CHILL FACTOR SCORER
# ─────────────────────────────────────────────────────────────

def agent2_chill(job: dict, chill_threshold: int) -> dict:
    prompt = f"""{AGENT2_PROMPT}

## JOB TO EVALUATE:
Title:    {job.get('title', 'N/A')}
Company:  {job.get('company', 'N/A')}
Location: {job.get('location', 'N/A')}

Description:
{(job.get('description') or 'No description available.')[:2500]}

## TASK:
Reply with ONLY raw JSON — no markdown, no explanation:
{{"chill_score": 8, "approved": true, "verdict": "2-3 sentence summary", "green_flags": ["flag 1"], "red_flags": ["flag 1"], "location_verdict": "GREAT"}}

chill_score: integer 1-10
  9-10 = dream job for this life phase
  7-8  = good fit, minor concerns
  5-6  = possible but notable WLB risks
  1-4  = poor fit, significant red flags
approved: true if chill_score >= {chill_threshold} AND no hard red flags
location_verdict: GREAT (remote or easy commute) | OK (flexible hybrid) | RISKY (far, unclear remote) | DEALBREAKER (full on-site, far away)"""

    raw = call_gemini(prompt)
    result = parse_json_response(raw)

    if result:
        result.setdefault("chill_score", 0)
        result.setdefault("approved", False)
        result.setdefault("verdict", "")
        result.setdefault("green_flags", [])
        result.setdefault("red_flags", [])
        result.setdefault("location_verdict", "UNKNOWN")
        if result["chill_score"] < chill_threshold:
            result["approved"] = False
        return result

    if raw:
        print(f"    ⚠️  Agent 2 parse failed: {raw[:120]}")
    return {"chill_score": 0, "approved": False, "verdict": "Parse error",
            "green_flags": [], "red_flags": [], "location_verdict": "UNKNOWN"}

# ─────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "job_id", "title", "company", "location", "date_posted", "url",
    "agent1_result", "agent1_reason",
    "agent2_chill_score", "agent2_approved", "agent2_verdict",
    "agent2_green_flags", "agent2_red_flags", "agent2_location_verdict",
    "evaluated_at",
]


def save_to_csv(job: dict, a1: dict, a2: Optional[dict], output_csv: str):
    exists = os.path.isfile(output_csv)
    with open(output_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not exists:
            w.writeheader()
        w.writerow({
            "job_id":                  job.get("job_id", ""),
            "title":                   job.get("title", ""),
            "company":                 job.get("company", ""),
            "location":                job.get("location", ""),
            "date_posted":             job.get("date_posted", ""),
            "url":                     job.get("url", ""),
            "agent1_result":           a1.get("result", ""),
            "agent1_reason":           a1.get("reason", ""),
            "agent2_chill_score":      a2.get("chill_score", "") if a2 else "",
            "agent2_approved":         a2.get("approved", "") if a2 else "",
            "agent2_verdict":          a2.get("verdict", "") if a2 else "",
            "agent2_green_flags":      " | ".join(a2.get("green_flags", [])) if a2 else "",
            "agent2_red_flags":        " | ".join(a2.get("red_flags", [])) if a2 else "",
            "agent2_location_verdict": a2.get("location_verdict", "") if a2 else "",
            "evaluated_at":            datetime.now().isoformat(),
        })

# ─────────────────────────────────────────────────────────────
# MODE: SCREEN
# ─────────────────────────────────────────────────────────────

def run_screen(jobs: list, jobs_by_id: dict, progress: dict,
               progress_file: str, chunk: int):
    """
    Run Agent 1 on unprocessed jobs.
    Stops after `chunk` new passes. Saves progress after every job.
    """
    already_processed = set(progress["agent1_results"].keys())
    passes_this_run   = 0
    stats = dict(screened=0, passed=0, rejected=0)

    print(f"\n🔬 SCREEN MODE — stopping after {chunk} new Agent 1 passes")
    print(f"   Already processed: {len(already_processed)} jobs")
    print(f"   Remaining in JSON: {len(jobs) - len(already_processed)} jobs\n")
    print("─"*62)

    for i, job in enumerate(jobs):
        job_id = job.get("job_id", str(i))

        # Skip already processed
        if job_id in already_processed:
            continue

        # Stop if we've hit the chunk pass limit
        if passes_this_run >= chunk:
            print(f"\n✅ Chunk limit reached ({chunk} passes). Run again to continue.")
            break

        title   = (job.get('title','')[:52]+"…") if len(job.get('title',''))>53 else job.get('title','')
        company = job.get('company', '')
        print(f"\n[job {i+1}/{len(jobs)}] {title} @ {company}")

        a1 = agent1_screen(job)
        stats["screened"] += 1

        # Save to progress immediately
        progress["agent1_results"][job_id] = {
            "result": a1["result"],
            "reason": a1["reason"],
        }
        progress["last_processed_index"] = i
        save_progress(progress, progress_file)

        if a1["result"] == "PASS":
            stats["passed"] += 1
            passes_this_run += 1
            print(f"  ✅ PASS ({passes_this_run}/{chunk} this run) — {a1['reason']}")
        else:
            stats["rejected"] += 1
            print(f"  ❌ REJECT — {a1['reason']}")

        time.sleep(API_DELAY)

    else:
        print(f"\n✅ All unprocessed jobs have been screened.")

    # Summary
    total_passes = get_pass_count(progress)
    print("\n" + "═"*62)
    print("  📈  SCREEN SUMMARY")
    print("═"*62)
    print(f"  Screened this run:   {stats['screened']}")
    print(f"  Passed this run:     {stats['passed']}")
    print(f"  Rejected this run:   {stats['rejected']}")
    print(f"  Total passes so far: {total_passes}")
    remaining = len([j for j in jobs if j.get("job_id", str(jobs.index(j))) not in progress["agent1_results"]])
    print(f"  Unprocessed jobs:    {remaining}")
    if remaining > 0:
        print(f"\n  ▶  Run again to continue: python run_agents.py --mode screen --chunk {chunk}")
    print(f"\n  ▶  Ready to evaluate:     python run_agents.py --mode evaluate --output my_results.csv")

    return stats

# ─────────────────────────────────────────────────────────────
# MODE: EVALUATE
# ─────────────────────────────────────────────────────────────

def run_evaluate(jobs_by_id: dict, progress: dict, output_csv: str,
                 chill_threshold: int, chunk: int):
    """
    Run Agent 2 on Agent 1 passes.
    Reads descriptions from jobs_by_id (linked by job_id).
    Saves ALL passes to CSV regardless of Agent 2 result.
    """
    passed_ids = get_passed_job_ids(progress)

    if not passed_ids:
        print("\n⚠️  No Agent 1 passes found in progress file.")
        print("   Run screen mode first: python run_agents.py --mode screen --chunk 100")
        return

    # Limit to chunk size if specified
    ids_to_evaluate = passed_ids[:chunk] if chunk else passed_ids

    print(f"\n😎 EVALUATE MODE")
    print(f"   Agent 1 passes available: {len(passed_ids)}")
    print(f"   Evaluating this run:      {len(ids_to_evaluate)}")
    print(f"   Chill threshold:          {chill_threshold}/10")
    print(f"   Output:                   {output_csv}\n")
    print("─"*62)

    stats = dict(evaluated=0, approved=0, not_approved=0, missing=0)

    for idx, job_id in enumerate(ids_to_evaluate, 1):
        job = jobs_by_id.get(job_id)

        if not job:
            print(f"\n[{idx}/{len(ids_to_evaluate)}] ⚠️  job_id {job_id} not found in JSON — skipping")
            stats["missing"] += 1
            continue

        title   = (job.get('title','')[:52]+"…") if len(job.get('title',''))>53 else job.get('title','')
        company = job.get('company', '')
        print(f"\n[{idx}/{len(ids_to_evaluate)}] {title} @ {company}")

        a1 = progress["agent1_results"][job_id]

        print("  😎 Agent 2 (chill factor)...")
        a2 = agent2_chill(job, chill_threshold)
        stats["evaluated"] += 1

        score    = a2.get("chill_score", 0)
        approved = a2.get("approved", False)
        loc      = a2.get("location_verdict", "")
        icon     = "✅" if approved else "⚠️ "
        print(f"  {icon} Chill: {score}/10 | Location: {loc}")
        if a2.get("verdict"):
            print(f"  💬 {a2['verdict']}")
        if a2.get("red_flags"):
            print(f"  🚩 {' | '.join(a2['red_flags'])}")

        if approved:
            stats["approved"] += 1
        else:
            stats["not_approved"] += 1

        # Save ALL — approved and not
        save_to_csv(job, a1, a2, output_csv)
        print(f"  💾 Saved → {output_csv}")

        time.sleep(API_DELAY)

    # Summary
    print("\n" + "═"*62)
    print("  📈  EVALUATE SUMMARY")
    print("═"*62)
    print(f"  Jobs evaluated:      {stats['evaluated']}")
    print(f"  Agent 2 approved:    {stats['approved']}  (chill ≥ {chill_threshold})")
    print(f"  Saved but flagged:   {stats['not_approved']}  (review manually)")
    if stats["missing"]:
        print(f"  Missing in JSON:     {stats['missing']}")
    print(f"\n  Output file: {output_csv}")
    print()
    print("  Tips for reviewing:")
    print("  • Filter agent2_approved = TRUE for best picks")
    print("  • Sort agent2_chill_score descending for ranked list")
    print("  • Filter agent2_location_verdict = GREAT for easy commutes")
    print("  • Review agent2_approved = FALSE manually — may be too strict")
    if len(passed_ids) > len(ids_to_evaluate):
        remaining = len(passed_ids) - len(ids_to_evaluate)
        print(f"\n  ▶  {remaining} more passes not yet evaluated.")
        print(f"     Run: python run_agents.py --mode evaluate --chunk {len(ids_to_evaluate)} --output next_batch.csv")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    args           = parse_args()
    mode           = args.mode
    input_json     = args.input
    progress_file  = args.progress
    chunk          = args.chunk
    chill_threshold = args.chill_threshold
    output_csv     = args.output

    # Prompt for output filename in evaluate/both mode if not provided
    if mode in ("evaluate", "both") and not output_csv:
        print("\n📁 Output CSV filename not specified.")
        print("   Tip: use a descriptive name, e.g. 'results_chill7_batch1.csv'")
        output_csv = input("   Enter filename: ").strip()
        if not output_csv:
            timestamp  = datetime.now().strftime("%Y%m%d_%H%M")
            output_csv = f"results_{timestamp}.csv"
            print(f"   Using: {output_csv}")
        if not output_csv.endswith(".csv"):
            output_csv += ".csv"

    print("\n" + "═"*62)
    print("  🤖  JOB FINDER AGENT RUNNER")
    print(f"  Mode:      {mode.upper()}")
    print(f"  Input:     {input_json}")
    print(f"  Progress:  {progress_file}")
    if mode in ("evaluate", "both"):
        print(f"  Output:    {output_csv}")
    print(f"  Chunk:     {chunk}")
    print(f"  Model:     {GEMINI_MODEL}")
    print(f"  API delay: {API_DELAY}s")
    if mode in ("evaluate", "both"):
        print(f"  Chill ≥:   {chill_threshold}/10 for approval")
    print("═"*62)

    # Load jobs
    if not os.path.isfile(input_json):
        sys.exit(f"\n❌ File not found: {input_json}\n   Run scraper.py first.")

    with open(input_json, encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs", [])
    if not jobs:
        sys.exit("❌ No jobs found in JSON file.")

    # Build lookup dict by job_id for fast access in evaluate mode
    jobs_by_id = {j.get("job_id", str(i)): j for i, j in enumerate(jobs)}

    print(f"\n📂 Loaded {len(jobs)} jobs from {input_json}")
    print(f"   Scraped at: {data.get('scraped_at', 'unknown')}\n")

    setup_gemini()

    # Load progress
    print()
    progress = load_progress(progress_file)
    print()

    # Run selected mode
    if mode == "screen":
        run_screen(jobs, jobs_by_id, progress, progress_file, chunk)

    elif mode == "evaluate":
        run_evaluate(jobs_by_id, progress, output_csv, chill_threshold, chunk)

    elif mode == "both":
        print("─"*62)
        print("  STEP 1: Screening with Agent 1")
        print("─"*62)
        run_screen(jobs, jobs_by_id, progress, progress_file, chunk)

        print("\n" + "─"*62)
        print("  STEP 2: Evaluating passes with Agent 2")
        print("─"*62)
        # In 'both' mode, evaluate only the passes from THIS run
        # (the ones just added, not previously existing passes)
        run_evaluate(jobs_by_id, progress, output_csv, chill_threshold, chunk)


if __name__ == "__main__":
    main()
