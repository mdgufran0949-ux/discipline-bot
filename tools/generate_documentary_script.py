"""
generate_documentary_script.py
Generates a scene-by-scene Hindi documentary script for AI Historical videos.
Each scene includes Hindi narration + English image prompt for AI generation.

Usage: python tools/generate_documentary_script.py "1800 की दिल्ली"
Output: .tmp/documentary_script.json
Requires: GROQ_API_KEY in .env (free at console.groq.com)
"""

import json
import os
import sys

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

TMP         = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))
OUTPUT_FILE = os.path.join(TMP, "documentary_script.json")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE    = "https://api.groq.com/openai/v1"
MODEL        = "llama-3.3-70b-versatile"

SYSTEM = """You are a master documentary scriptwriter for Hindi YouTube.
You write deeply researched, cinematic, emotionally engaging scripts
in the tradition of National Geographic and BBC Documentaries — but in Hindi.
Every sentence is vivid, factual, and pulls the viewer deeper.
You never use filler. Every word earns its place."""

PROMPT = """विषय (Topic): {topic}

एक 10-scene AI Historical Documentary script बनाओ Hindi YouTube के लिए।

प्रत्येक scene में होगा:
1. Hindi narration: 3-5 sentences, 35-55 words, cinematic + factual tone
2. English image_prompt: detailed photorealistic historical scene description
3. pan: one of "zoom_in", "zoom_out", "pan_left", "pan_right" (alternate them)

Image prompt rules:
- Photorealistic historical accuracy
- Include: lighting, architecture, people, atmosphere, time of day
- Always end with: "cinematic lighting, ultra-detailed, photorealistic, historical painting style"
- No modern elements

Return ONLY valid JSON (no markdown, no explanation):
{{
  "title": "Hindi documentary title (catchy, 50-60 chars)",
  "youtube_title": "YouTube clickbait title (max 60 chars, Hindi)",
  "topic": "{topic}",
  "scenes": [
    {{
      "scene_num": 1,
      "narration": "Hindi narration text...",
      "image_prompt": "English image generation prompt, cinematic lighting, ultra-detailed, photorealistic, historical painting style",
      "pan": "zoom_in"
    }}
  ],
  "caption": "YouTube/Instagram caption in Hindi with 8 relevant hashtags",
  "youtube_description": "200-word Hindi description with historical context"
}}"""


def generate_script(topic: str) -> dict:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not found in .env — get free key at console.groq.com")

    client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE)

    for attempt in range(1, 4):
        try:
            print(f"  Generating script (attempt {attempt})...", flush=True)
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user",   "content": PROMPT.format(topic=topic)}
                ],
                temperature=0.75,
                max_tokens=4000,
                response_format={"type": "json_object"}
            )
            data = json.loads(resp.choices[0].message.content)

            if "scenes" not in data or len(data["scenes"]) < 5:
                print(f"  Too few scenes ({len(data.get('scenes', []))}), retrying...", flush=True)
                continue

            # Annotate word counts
            for s in data["scenes"]:
                s["word_count"] = len(s["narration"].split())

            data["total_words"]  = sum(s["word_count"] for s in data["scenes"])
            data["total_scenes"] = len(data["scenes"])

            os.makedirs(TMP, exist_ok=True)
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"  [OK] {data['total_scenes']} scenes, {data['total_words']} words", flush=True)
            print(f"  [OK] Saved: {OUTPUT_FILE}", flush=True)
            return data

        except json.JSONDecodeError as e:
            print(f"  JSON parse error (attempt {attempt}): {e}", flush=True)
        except Exception as e:
            print(f"  Error (attempt {attempt}): {e}", flush=True)
            if attempt == 3:
                raise

    raise RuntimeError("Failed to generate script after 3 attempts")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python tools/generate_documentary_script.py "1800 की दिल्ली"')
        sys.exit(1)
    topic  = " ".join(sys.argv[1:])
    result = generate_script(topic)
    print(json.dumps(result, ensure_ascii=False, indent=2))
