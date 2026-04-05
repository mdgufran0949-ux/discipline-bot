"""
fetch_broll_clips.py
Extracts visual themes from a motivation script using Kimi K2,
then downloads matching B-roll clips from Pexels.
Usage: python tools/fetch_broll_clips.py "narration text" [num_clips=3]
Output: .tmp/broll_1.mp4, .tmp/broll_2.mp4, .tmp/broll_3.mp4 + JSON with paths
"""

import json, os, re, sys, glob
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP            = os.path.join(PROJECT_ROOT, ".tmp")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KIMI_API_KEY   = os.getenv("KIMI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
KIMI_BASE_URL  = "https://integrate.api.nvidia.com/v1"
KIMI_MODEL     = "moonshotai/kimi-k2-instruct"

FALLBACK_QUERIES = [
    "gym workout intensity",
    "morning sunrise motivation",
    "city hustle ambition",
    "running sprint determination",
    "mountains nature perseverance",
]


def _extract_visual_queries(narration: str, num: int) -> list:
    """Use Kimi K2 (primary) or Gemini to extract Pexels search queries from narration."""
    prompt = (
        f'Narration: "{narration}"\n\n'
        f"Return exactly {num} Pexels video search queries (2-4 words each) as a JSON array. "
        f"Each query should match a distinct visual theme from a different part of the script. "
        f"Use concrete, cinematic visuals: gym, running, alarm clock, mirror, city, sunrise, "
        f"mountains, books, hands, athlete, crowd, office, etc. "
        f'Return ONLY the JSON array. Example: ["gym workout", "alarm clock morning", "mirror reflection"]'
    )

    # Try Kimi K2 first (generous rate limits, no quota issues)
    if KIMI_API_KEY:
        try:
            client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
            resp = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=120,
            )
            raw = resp.choices[0].message.content.strip()
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            return json.loads(match.group() if match else raw)
        except Exception as e:
            print(f"  [Kimi K2 failed] {str(e)[:60]} — trying Gemini...", flush=True)

    # Fallback: Gemini
    if GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"temperature": 0.2, "max_output_tokens": 120}
            )
            raw = resp.text.strip()
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            return json.loads(match.group() if match else raw)
        except Exception as e:
            print(f"  [Gemini failed] {str(e)[:60]}", flush=True)

    raise RuntimeError("No AI provider available for query extraction")


def _search_pexels(query: str, min_dur: int = 8) -> str | None:
    """Return download URL for best matching Pexels portrait clip."""
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


def fetch_broll_clips(narration: str, num_clips: int = 3) -> dict:
    os.makedirs(TMP, exist_ok=True)

    # Clean up old broll clips
    for old in glob.glob(os.path.join(TMP, "broll_*.mp4")):
        os.remove(old)

    # Extract visual queries from script
    try:
        queries = _extract_visual_queries(narration, num_clips)
        print(f"  Visual queries: {queries}", flush=True)
    except Exception as e:
        print(f"  [WARN] Query extraction failed ({e}) — using fallback queries", flush=True)
        queries = FALLBACK_QUERIES[:num_clips]

    clip_paths = []
    for i, query in enumerate(queries[:num_clips], start=1):
        out_path = os.path.join(TMP, f"broll_{i}.mp4")
        print(f"  [{i}/{num_clips}] Downloading: '{query}'...", flush=True)

        url = _search_pexels(query)
        if not url:
            fallback = FALLBACK_QUERIES[(i - 1) % len(FALLBACK_QUERIES)]
            print(f"  [WARN] No result for '{query}', trying '{fallback}'...", flush=True)
            url = _search_pexels(fallback)
        if not url:
            print(f"  [WARN] Skipping clip {i} — no Pexels result", flush=True)
            continue

        _download(url, out_path)
        clip_paths.append(out_path)
        print(f"  [OK] {os.path.basename(out_path)}", flush=True)

    return {"clips": clip_paths, "queries": queries[:num_clips]}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/fetch_broll_clips.py "narration text" [num_clips]')
        sys.exit(1)
    narration = sys.argv[1]
    num       = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    result    = fetch_broll_clips(narration, num)
    print(json.dumps(result, indent=2))
