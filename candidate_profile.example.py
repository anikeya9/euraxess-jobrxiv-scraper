"""
profile.py — Your personal agent prompts
==========================================
Setup instructions:

STEP 1 — Generate your Agent 1 prompt (technical screen):
  1. Open any chatbot (Claude, Gemini, ChatGPT)
  2. Paste your CV and send this message:
       "Based on my CV, extract a candidate profile for a job screening agent.
        Include: education, core professional identity, primary tech stack,
        acceptable job roles/domains, unacceptable roles, and 2-3 evaluation rules.
        Format it as a clear text block I can paste into a prompt."
  3. Copy the output and paste it into AGENT1_PROMPT below,
     replacing everything between the triple quotes.

STEP 2 — Generate your Agent 2 prompt (life situation / chill factor):
  1. In the same or a new chatbot session, send this message:
       "I need a job evaluation prompt for an AI agent that scores jobs
        based on my current life situation. Here is my situation:
        [describe your location, commute limits, WLB priorities, salary target,
         family situation, stress tolerance, preferred company types, etc.]
        The agent should output a chill_score from 1-10, green_flags, red_flags,
        location_verdict (GREAT/OK/RISKY/DEALBREAKER), a verdict summary,
        and an approved boolean. Format this as a prompt I can paste directly."
  2. Copy the output and paste it into AGENT2_PROMPT below.

STEP 3 — Save as profile.py (this file stays private — it is in .gitignore)
  cp profile.example.py profile.py
  # then edit profile.py with your real prompts

NOTE: Do not change the variable names AGENT1_PROMPT and AGENT2_PROMPT.
      The rest of the text is entirely yours to customise.
"""

# ─────────────────────────────────────────────────────────────
# AGENT 1 — TECHNICAL SCREENING PROMPT
# ─────────────────────────────────────────────────────────────
# Paste your chatbot-generated technical profile here.
# This tells Agent 1 WHO the candidate is and WHAT roles to accept or reject.

AGENT1_PROMPT = """
You are an expert Technical Recruitment Screener. Your sole objective is to
evaluate job descriptions and determine if they technically align with the
candidate's skill set. Do not evaluate work-life balance, salary, or culture.

[PASTE YOUR CHATBOT-GENERATED AGENT 1 PROMPT HERE]

Replace this entire block with the output from your chatbot.
Keep everything between the triple quotes — just replace this text.
"""

# ─────────────────────────────────────────────────────────────
# AGENT 2 — LIFE SITUATION / CHILL FACTOR PROMPT  (optional)
# ─────────────────────────────────────────────────────────────
# Paste your chatbot-generated life situation prompt here.
# This tells Agent 2 what makes a job a good fit for your current life phase.
# Agent 2 only runs on jobs that passed Agent 1.

AGENT2_PROMPT = """
You are an expert Career Filtering Agent. Analyze this job and determine
if it is a strong fit for the candidate's current life phase and priorities.

[PASTE YOUR CHATBOT-GENERATED AGENT 2 PROMPT HERE]

Replace this entire block with the output from your chatbot.
Keep everything between the triple quotes — just replace this text.
"""
