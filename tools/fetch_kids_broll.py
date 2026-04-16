"""
fetch_kids_broll.py
Fetches kid-safe B-roll video clips from Pexels for the Biscuit & Zara pipeline.
Uses LLM to extract visual queries from the script, then downloads portrait clips.

Usage: python tools/fetch_kids_broll.py "narration text" [--topic "animals"] [--num 3]
Output: .tmp/kids_broll_1.mp4 ... kids_broll_3.mp4 + JSON with paths
"""

import json, os, re, sys, glob, argparse
import requests
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP            = os.path.join(PROJECT_ROOT, ".tmp")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

GROQ_BASE_URL  = "https://api.groq.com/openai/v1"
GROQ_MODEL     = "llama-3.3-70b-versatile"

# Kid-safe fallback queries when LLM extraction fails
FALLBACK_QUERIES = [
    "cute animals playing",
    "colorful nature flowers",
    "ocean underwater fish",
    "butterfly garden",
    "baby animals farm",
]


def _extract_kids_queries(narration: str, topic: str, num: int) -> list:
    """Use Groq (primary) or Gemini to extract kid-safe Pexels search queries."""
    prompt = (
        f'Topic: "{topic}"\nNarration: "{narration}"\n\n'
        f"Return exactly {num} Pexels video search queries (2-4 words each) as a JSON array. "
        f"Each query MUST be child-safe and visually appealing for kids ages 3-10. "
        f"Use concrete, colorful visuals: cute animals, bright flowers, ocean fish, "
        f"rainbow sky, baby birds, playful puppies, butterflies, jungle, snow, etc. "
        f"NO violence, NO scary content, NO adult themes. "
        f'Return ONLY the JSON array. Example: ["cute puppy playing", "colorful rainbow sky", "ocean fish swimming"]'
    )

    # Try Groq first (free, fast)
    if GROQ_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=120,
            )
            raw = resp.choices[0].message.content.strip()
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            return json.loads(match.group() if match else raw)
        except Exception as e:
            print(f"  [Groq failed] {str(e)[:60]} — trying Gemini...", flush=True)

    # Fallback: Gemini
    if GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"temperature": 0.3, "max_output_tokens": 120}
            )
            raw = resp.text.strip()
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            return json.loads(match.group() if match else raw)
        except Exception as e:
            print(f"  [Gemini failed] {str(e)[:60]}", flush=True)

    raise RuntimeError("No AI provider available for query extraction")


def _search_pexels(query: str, min_dur: int = 6) -> str | None:
    """Return download URL for best matching Pexels portrait clip."""
    if not PEXELS_API_KEY:
        return None
    headers = {"Authorization": PEXELS_API_KEY}
    params  = {"query": query, "per_page": 15, "orientation": "portrait", "size": "medium"}
    r = requests.get("https://api.pexels.com/videos/search",
                     headers=headers, params=params, timeout=15)
    r.raise_for_status()
    for v in r.json().get("videos", []):
        if v.get("duration", 0) >= min_dur:
            files = sorted(v.get("video_files", []),
                           key=lambda f: f.get("height", 0), reverse=True)
            for f in files:
                if f.get("height", 0) >= 720:
                    return f["link"]
    return None


def _download(url: str, out_path: str) -> None:
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(65536):
            f.write(chunk)


def fetch_kids_broll(narration: str, topic: str = "", num_clips: int = 3) -> dict:
    os.makedirs(TMP, exist_ok=True)

    # Clean up old kids broll clips
    for old in glob.glob(os.path.join(TMP, "kids_broll_*.mp4")):
        os.remove(old)

    if not PEXELS_API_KEY:
        print("  [WARN] No PEXELS_API_KEY — skipping B-roll", flush=True)
        return {"clips": [], "queries": []}

    # Extract visual queries from script
    try:
        queries = _extract_kids_queries(narration, topic or "kids learning", num_clips)
        print(f"  Kids B-roll queries: {queries}", flush=True)
    except Exception as e:
        print(f"  [WARN] Query extraction failed ({e}) — using fallback queries", flush=True)
        queries = FALLBACK_QUERIES[:num_clips]

    clip_paths = []
    for i, query in enumerate(queries[:num_clips], start=1):
        out_path = os.path.join(TMP, f"kids_broll_{i}.mp4")
        print(f"  [{i}/{num_clips}] Searching Pexels: '{query}'...", flush=True)

        url = _search_pexels(query)
        if not url:
            fallback = FALLBACK_QUERIES[(i - 1) % len(FALLBACK_QUERIES)]
            print(f"  [WARN] No result for '{query}', trying '{fallback}'...", flush=True)
            url = _search_pexels(fallback)
        if not url:
            print(f"  [WARN] Skipping clip {i} — no Pexels result", flush=True)
            continue

        _download(url, out_path)
        size_kb = os.path.getsize(out_path) // 1024
        clip_paths.append(out_path)
        print(f"  [OK] kids_broll_{i}.mp4 ({size_kb}KB)", flush=True)

    return {"clips": clip_paths, "queries": queries[:num_clips]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch kid-safe B-roll clips from Pexels")
    parser.add_argument("narration", help="Narration text to extract visual queries from")
    parser.add_argument("--topic", default="", help="Topic for better query extraction")
    parser.add_argument("--num", default=3, type=int, help="Number of clips to fetch")
    args = parser.parse_args()

    result = fetch_kids_broll(args.narration, topic=args.topic, num_clips=args.num)
    print(json.dumps(result, indent=2))
