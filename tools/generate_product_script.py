"""
generate_product_script.py
Generates a punchy Hinglish product review script using Groq Llama 3.3 70B.
Script segments align with video scenes: hook -> 360-degree showcase -> 3 features -> CTA.

Usage: python tools/generate_product_script.py --product product.json
       python tools/generate_product_script.py --product products.json  (takes first item)
Output: JSON with full_script, segments, hook, title, hashtags, caption.
"""

import json
import re
import sys
import os
import argparse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE_URL = "https://api.groq.com/openai/v1"
MODEL = "llama-3.3-70b-versatile"

PROMPT_TEMPLATE = """You are a viral product review scriptwriter for YouTube Shorts and Instagram Reels. Write an English product review script.

Product:
- Name: {title}
- Price: Rs.{price}
- Original price: Rs.{original_price}
- Rating: {rating}/5 ({review_count} reviews)
- Platform: {source}
- Features: {features}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "hook": "Opening line. English. Price shock or FOMO. Max 12 words. Example: 'This gadget for only Rs.499? You need to see this!'",
  "hook_text_overlay": "Max 5 words for big on-screen text. Price + reaction. Example: 'ONLY Rs.499?! SERIOUSLY?'",
  "full_script": "Complete voiceover. 90-110 words. Clean English. No hashtags. Starts with hook. Ends with CTA mentioning {source_label}. Conversational, energetic tone.",
  "segments": [
    {{"id": 1, "text": "Hook (0-3s). Mention price. Pure FOMO opener.", "image_index": 0, "duration": 3}},
    {{"id": 2, "text": "360-degree showcase narration (3-11s). 'Look at this product from every angle — premium quality at an insane price!'", "image_index": null, "duration": 8}},
    {{"id": 3, "text": "Feature 1 (11-15s). One benefit, punchy.", "image_index": 1, "duration": 4}},
    {{"id": 4, "text": "Feature 2 (15-19s). Second benefit, why it matters.", "image_index": 2, "duration": 4}},
    {{"id": 5, "text": "Feature 3 (19-23s). Wow factor or value comparison.", "image_index": 3, "duration": 4}},
    {{"id": 6, "text": "CTA (23-26s). 'Only Rs.{price} on {source_label}! Link in bio!'", "image_index": 0, "duration": 3}}
  ],
  "use_case_keywords": ["3 short Pexels search terms for product use-case context, e.g. 'travel packing', 'desk organization', 'outdoor adventure'"],
  "use_case_scene_text": "Short label shown on use-case scene. Max 4 words. Example: 'Perfect for Travel!'",
  "title": "Video title. English. Include price. Max 60 chars. Example: 'This Rs.499 Gadget is INSANE! | Under999'",
  "hashtags": ["#Under999", "#AmazonFinds", "#GadgetReview", "#BudgetTech", "#TechShorts", "#UsefulGadgets", "#MustHave", "#ProductReview", "#AmazonDeals"],
  "caption": "2-3 lines English caption. Product name + price + 'link in bio'. Then hashtags on new line."
}}

Script rules:
- Pure English, clean and energetic
- Hook must mention price: 'Only Rs.X...', 'Rs.X for this?', 'This Rs.X gadget...'
- hook_text_overlay: all caps, punchy, max 5 words — this appears as a big text overlay on screen
- use_case_keywords: real-world scenarios where this product shines — used to find stock video (e.g. "cable organizer travel", "LED light bedroom", "phone stand desk")
- use_case_scene_text: short, bold label like "Perfect for Travel!" or "Ideal for WFH!"
- Segment 2 is for 360-degree image showcase — describe product visually, build desire
- Feature segments: benefit first, one punchy line each
- CTA must say 'link in bio'
- Sound like a friend recommending, NOT a salesperson
- NO filler openers like 'today', 'basically', 'so basically', 'hey guys'"""

HASHTAG_POOL = {
    "amazon": [
        "#AmazonFinds", "#AmazonIndia", "#AmazonDeals", "#TechUnder999",
        "#GadgetReview", "#TechIndia", "#BudgetTech", "#GadgetLover",
        "#TechShorts", "#IndianTech", "#UsefulGadgets", "#MustHaveGadgets",
        "#TechTips", "#PhoneAccessories", "#SmartGadgets",
    ],
    "flipkart": [
        "#FlipkartDeals", "#FlipkartFinds", "#TechUnder999", "#GadgetReview",
        "#TechIndia", "#BudgetTech", "#GadgetLover", "#TechShorts",
        "#IndianTech", "#UsefulGadgets", "#MustHaveGadgets", "#TechTips",
        "#PhoneAccessories", "#FlipkartSale", "#SmartGadgets",
    ],
}


def _safe_json_loads(raw: str) -> dict:
    """Parse JSON from LLM output, handling literal control characters in strings."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Walk character-by-character and escape control chars inside string values
    out = []
    in_string = False
    escaped = False
    for ch in raw:
        code = ord(ch)
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\" and in_string:
            out.append(ch)
            escaped = True
        elif ch == '"':
            out.append(ch)
            in_string = not in_string
        elif in_string and 0x00 <= code <= 0x1F:
            # Replace literal control chars with their JSON escape sequences
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(" ")
        else:
            out.append(ch)
    return json.loads("".join(out))


def generate_product_script(product: dict) -> dict:
    client = OpenAI(api_key=GROQ_API_KEY, base_url=BASE_URL)

    source = product.get("source", "amazon")
    price = int(product.get("price", 499))
    original_price = int(product.get("original_price", price))
    rating = product.get("rating", 4.0)
    review_count = product.get("review_count", 100)
    title = product.get("title", "Tech gadget")[:100]

    features = product.get("features", [])
    if not features:
        features = ["Compact and portable", "Easy to use", "Great build quality"]
    features_str = " | ".join(str(f) for f in features[:5])

    source_label = "Amazon" if source == "amazon" else "Flipkart"

    prompt = PROMPT_TEMPLATE.format(
        title=title,
        price=price,
        original_price=original_price,
        rating=rating,
        review_count=review_count,
        source=source,
        source_label=source_label,
        features=features_str,
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a viral Indian social media scriptwriter. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
        max_tokens=1200,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.M).strip("`").strip()

    result = _safe_json_loads(raw)

    # Pad hashtags from our pool
    pool = HASHTAG_POOL.get(source, HASHTAG_POOL["amazon"])
    existing = set(result.get("hashtags", []))
    for tag in pool:
        if len(existing) >= 15:
            break
        existing.add(tag)
    result["hashtags"] = list(existing)[:15]

    # Attach product metadata for downstream tools
    result["product_title"] = title
    result["product_price"] = price
    result["product_source"] = source
    result["product_url"] = product.get("product_url", "")
    result["rating"] = rating
    result["review_count"] = review_count

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Hinglish product review script")
    parser.add_argument(
        "--product",
        required=True,
        help="Path to product JSON file (single dict or list)",
    )
    parser.add_argument("--output", default=None, help="Save JSON to file")
    args = parser.parse_args()

    with open(args.product, "r", encoding="utf-8") as f:
        product = json.load(f)
    if isinstance(product, list):
        product = product[0]

    result = generate_product_script(product)
    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[OK] Script saved to {args.output}", file=sys.stderr)
    else:
        print(output)
