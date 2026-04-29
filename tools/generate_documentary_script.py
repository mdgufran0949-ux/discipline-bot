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

def resolve_output_file(out_dir: str | None) -> str:
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, "script.json")
    return OUTPUT_FILE

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE    = "https://api.groq.com/openai/v1"
MODEL        = "llama-3.3-70b-versatile"

SYSTEM = """You are a master documentary scriptwriter for Hindi YouTube.
You write deeply researched, cinematic, emotionally engaging scripts
in the tradition of National Geographic and BBC Documentaries — but in Hindi.
Every sentence is vivid, factual, and pulls the viewer deeper.
You never use filler. Every word earns its place.

You also write image prompts like a top Hollywood cinematographer.
Every prompt specifies: camera body, lens, lighting, film stock, era-accurate
details, and composition — like a real shot list for a documentary."""

# Cinematic suffix appended to every image_prompt so the LLM cannot skip it.
# Drives Imagen 3 / FLUX toward "real historical photograph" look, not AI slop.
STYLE_SUFFIX = (
    ", shot on ARRI Alexa 65, 85mm f/1.4 lens, shallow depth of field, "
    "golden hour dramatic chiaroscuro lighting, dust-filtered sunbeams, "
    "sepia-toned wet plate collodion photograph aesthetic, "
    "Kodak Portra 400 film grain, period-accurate clothing and architecture, "
    "correct human anatomy, detailed hands, National Geographic photojournalism, "
    "ultra-detailed, 8k, photorealistic, no modern elements, no text, no watermark"
)

PROMPT = """विषय (Topic): {topic}

एक 10-scene AI Historical Documentary script बनाओ Hindi YouTube के लिए।

प्रत्येक scene में होगा:
1. Hindi narration: 3-5 sentences, 35-55 words, cinematic + factual tone
2. English image_prompt: written as a cinematographer's shot description
3. pan: one of "zoom_in", "zoom_out", "pan_left", "pan_right" (alternate them)

IMAGE PROMPT RULES (follow every one — this is critical for quality):
- Open with the SPECIFIC SCENE: subject, action, location, time of day.
  Example: "Wide establishing shot of Shahjahanabad Delhi at dawn, Red Fort's
  massive red sandstone walls rising above the Yamuna river..."
- Include these elements, always:
  * Era-specific architecture with material details (sandstone, marble jali, etc.)
  * Humans in period-accurate dress (angarkha, shalwar, turbans, armor)
  * Atmosphere (dust haze, mist, torchlight, monsoon rain)
  * Time of day + light direction (golden hour, blue hour, high noon)
- DO NOT say "photorealistic historical painting style" — that's generic AI slop.
  Instead say "sepia wet plate collodion photograph, 1870s albumen print"
  or "Kodak Portra 400 documentary photograph, warm amber grade".
- NO modern elements (cars, phones, plastic, digital clocks, street signs in English).
- NO cartoon, no anime, no illustration. Always photorealistic historical photograph.

Return ONLY valid JSON (no markdown, no explanation):
{{
  "title": "Hindi documentary title (catchy, 50-60 chars)",
  "youtube_title": "YouTube clickbait title (max 60 chars, Hindi)",
  "topic": "{topic}",
  "scenes": [
    {{
      "scene_num": 1,
      "narration": "Hindi narration text — 35-55 words, 3-5 sentences",
      "image_prompt": "Cinematographer's shot description — specific subject, location, era-accurate details, lighting",
      "pan": "zoom_in"
    }}
  ],
  "caption": "YouTube/Instagram caption in Hindi with 8 relevant hashtags",
  "youtube_description": "200-word Hindi description with historical context"
}}

Do NOT append camera/lens/film-stock language yourself — the pipeline appends
a standardized cinematic suffix to every image_prompt. Your job is to write
the SCENE-SPECIFIC part only."""


def generate_script(topic: str, out_dir: str | None = None) -> dict:
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

            # Append cinematic suffix + annotate word counts
            for s in data["scenes"]:
                prompt_text = (s.get("image_prompt") or "").strip().rstrip(".,;")
                s["image_prompt"] = prompt_text + STYLE_SUFFIX
                s["word_count"]   = len(s["narration"].split())

            data["total_words"]  = sum(s["word_count"] for s in data["scenes"])
            data["total_scenes"] = len(data["scenes"])

            out_file = resolve_output_file(out_dir)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"  [OK] {data['total_scenes']} scenes, {data['total_words']} words", flush=True)
            print(f"  [OK] Saved: {out_file}", flush=True)
            return data

        except json.JSONDecodeError as e:
            print(f"  JSON parse error (attempt {attempt}): {e}", flush=True)
        except Exception as e:
            print(f"  Error (attempt {attempt}): {e}", flush=True)
            if attempt == 3:
                raise

    raise RuntimeError("Failed to generate script after 3 attempts")


if __name__ == "__main__":
    args    = sys.argv[1:]
    out_dir = None

    if "--out-dir" in args:
        idx     = args.index("--out-dir")
        out_dir = args[idx + 1]
        args    = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    if not args:
        print('Usage: python tools/generate_documentary_script.py "1800 की दिल्ली" [--out-dir .tmp/insmind_documentary]')
        sys.exit(1)

    topic  = " ".join(args)
    result = generate_script(topic, out_dir=out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
