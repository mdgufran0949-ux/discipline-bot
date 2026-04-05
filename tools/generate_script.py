"""
generate_script.py
Generates a viral 30-second YouTube Short script with 6 scene image prompts.
Uses Groq Llama 3.3 70B (free, 1000 req/day — console.groq.com).
Usage: python tools/generate_script.py "topic here"
Output: JSON with narration + scene prompts.
"""

import json
import sys
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE_URL = "https://api.groq.com/openai/v1"
MODEL = "llama-3.3-70b-versatile"

PROMPT_TEMPLATE = """You are a viral YouTube Shorts scriptwriter. Write a 30-second script about: {topic}

Return ONLY valid JSON with this exact structure:
{{
  "narration": "The full voiceover text. Must be 75-85 words. Start with a shocking hook. Build tension. End with a strong statement.",
  "scenes": [
    {{"id": 1, "image_prompt": "cinematic photo description for scene 1, vivid detail, vertical portrait orientation, 4K quality"}},
    {{"id": 2, "image_prompt": "cinematic photo description for scene 2"}},
    {{"id": 3, "image_prompt": "cinematic photo description for scene 3"}},
    {{"id": 4, "image_prompt": "cinematic photo description for scene 4"}},
    {{"id": 5, "image_prompt": "cinematic photo description for scene 5"}},
    {{"id": 6, "image_prompt": "cinematic photo description for scene 6"}}
  ]
}}

Rules for narration:
- 75-85 words, punchy sentences
- Hook in first sentence (shocking stat or question)
- Each sentence matches a scene visually
- No hashtags, no calls to action, no filler

Rules for image_prompt:
- Each prompt should be vivid, cinematic, visually stunning
- Describe lighting, colors, mood, and subject clearly
- Must be portrait/vertical orientation
- Add style tags: "dramatic lighting, vibrant colors, cinematic, photorealistic, 4K"
- Vary styles: some wide shots, some close-ups, some aerial views

Return ONLY the JSON object, no markdown, no explanation."""

def generate_script(topic: str) -> dict:
    client = OpenAI(api_key=GROQ_API_KEY, base_url=BASE_URL)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a viral YouTube Shorts scriptwriter. Always return valid JSON only."},
            {"role": "user", "content": PROMPT_TEMPLATE.format(topic=topic)}
        ],
        temperature=0.85,
        max_tokens=600,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    result["topic"] = topic
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/generate_script.py \"topic here\"")
        sys.exit(1)
    topic = " ".join(sys.argv[1:])
    result = generate_script(topic)
    print(json.dumps(result, indent=2))
