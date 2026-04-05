"""
setup_canva_templates.py
Canva Template Setup Tool for DisciplineFuel.

Fetches all brand templates from your Canva account, auto-maps them to
design styles (dark/minimal/bold/luxury) by name keywords, and saves IDs
to config/accounts/disciplinefuel.json.

Also provides step-by-step instructions for turning any free Canva template
into a brand template usable by the pipeline.

Usage:
  python tools/setup_canva_templates.py --list          # list all brand templates
  python tools/setup_canva_templates.py --auto-map      # auto-map + save to config
  python tools/setup_canva_templates.py --instructions  # show setup guide
"""

import argparse
import json
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from canva_auth import get_auth_headers

CANVA_API_BASE = "https://api.canva.com/rest/v1"
CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "config", "accounts", "disciplinefuel.json")
)

# Keywords used to auto-map templates to styles
STYLE_KEYWORDS = {
    "dark":    ["dark", "black", "night", "shadow", "moody", "bold dark", "glow", "neon"],
    "minimal": ["minimal", "clean", "simple", "white", "light", "elegant", "modern"],
    "bold":    ["bold", "strong", "power", "impact", "graphic", "loud", "vivid"],
    "luxury":  ["luxury", "gold", "premium", "royal", "elegant", "rich", "elite"],
}

# Also map carousel templates separately
CAROUSEL_KEYWORDS = ["carousel", "slide", "series", "multi", "swipe"]


# ── Canva API ──────────────────────────────────────────────────────────────────

def _list_brand_templates(query: str = "", limit: int = 50) -> list:
    """Fetch all brand templates from the user's Canva account."""
    params = {"limit": limit}
    if query:
        params["query"] = query
    resp = requests.get(
        f"{CANVA_API_BASE}/brand-templates",
        headers=get_auth_headers(),
        params=params,
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", [])


def _get_all_templates() -> list:
    """Fetch all brand templates (paginated)."""
    all_templates = []
    # Search for quote/motivation templates
    for query in ["quote", "motivation", "discipline", "dark", ""]:
        try:
            items = _list_brand_templates(query=query, limit=50)
            for item in items:
                if item not in all_templates:
                    all_templates.append(item)
        except Exception as e:
            print(f"  [WARN] Search '{query}' failed: {e}", flush=True)
    # Deduplicate by ID
    seen = set()
    unique = []
    for t in all_templates:
        tid = t.get("id", "")
        if tid and tid not in seen:
            seen.add(tid)
            unique.append(t)
    return unique


# ── Auto-mapping ───────────────────────────────────────────────────────────────

def _detect_style(name: str) -> str | None:
    """Guess design style from template name."""
    name_lower = name.lower()
    for style, keywords in STYLE_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return style
    return None


def _is_carousel(name: str) -> bool:
    name_lower = name.lower()
    return any(kw in name_lower for kw in CAROUSEL_KEYWORDS)


def auto_map_templates(templates: list) -> dict:
    """
    Auto-map templates to design styles.
    Returns:
    {
      "templates":          {dark: id, minimal: id, bold: id, luxury: id},
      "carousel_templates": {dark: id, minimal: id, bold: id, luxury: id},
      "unmapped": [...]
    }
    """
    mapped          = {"dark": "", "minimal": "", "bold": "", "luxury": ""}
    carousel_mapped = {"dark": "", "minimal": "", "bold": "", "luxury": ""}
    unmapped        = []

    for t in templates:
        tid   = t.get("id", "")
        name  = t.get("title", t.get("name", ""))
        style = _detect_style(name)
        is_car = _is_carousel(name)

        if style:
            if is_car:
                if not carousel_mapped[style]:
                    carousel_mapped[style] = tid
            else:
                if not mapped[style]:
                    mapped[style] = tid
        else:
            unmapped.append({"id": tid, "name": name})

    return {
        "templates":          mapped,
        "carousel_templates": carousel_mapped,
        "unmapped":           unmapped
    }


# ── Config update ──────────────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(cfg: dict) -> None:
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def save_template_ids(mapping: dict) -> None:
    cfg = _load_config()
    cfg["canva"]["templates"]          = mapping["templates"]
    cfg["canva"]["carousel_templates"] = mapping["carousel_templates"]
    _save_config(cfg)
    print(f"[OK] Template IDs saved to config.", flush=True)


# ── Instructions ───────────────────────────────────────────────────────────────

INSTRUCTIONS = """
╔══════════════════════════════════════════════════════════════════╗
║         HOW TO USE FREE CANVA TEMPLATES WITH DISCIPLINEFUEL     ║
╚══════════════════════════════════════════════════════════════════╝

The pipeline needs 8 Brand Templates total:
  • 4 image post templates  (dark / minimal / bold / luxury)
  • 4 carousel slide templates (same 4 styles)

Each template needs 3 named text fields. Here's how to set them up:

─────────────────────────────────────────────────────────────────
STEP 1: Find a free template on Canva
─────────────────────────────────────────────────────────────────
1. Go to canva.com → Templates
2. Search: "Instagram post motivation quote dark"
3. Filter: Free | Instagram Post (1080×1080)
4. Pick one you like for each style

─────────────────────────────────────────────────────────────────
STEP 2: Duplicate + customize it
─────────────────────────────────────────────────────────────────
1. Click "Customize this template"
2. Delete existing text boxes (keep background/style)
3. Add 3 new text boxes, naming each one:

   Text 1 — the quote (large, center)
     → Double click → App menu → click the "Data" icon
     → Enter field name: quote_text

   Text 2 — series label (smaller, above quote)
     → Field name: series_label

   Text 3 — page handle (small, bottom right)
     → Field name: page_name

─────────────────────────────────────────────────────────────────
STEP 3: Save as Brand Template
─────────────────────────────────────────────────────────────────
1. Click "Share" → "Brand Template"
2. Name it with the style so auto-mapping works:
   Examples:
   • "DisciplineFuel Dark Quote"    → maps to: dark
   • "DisciplineFuel Minimal Quote" → maps to: minimal
   • "DisciplineFuel Bold Quote"    → maps to: bold
   • "DisciplineFuel Luxury Quote"  → maps to: luxury
   • "DisciplineFuel Dark Carousel" → maps to: dark carousel
   • "DisciplineFuel Minimal Carousel" → maps to: minimal carousel

─────────────────────────────────────────────────────────────────
STEP 4: Auto-map templates to config
─────────────────────────────────────────────────────────────────
Once all templates are saved, run:
  python tools/setup_canva_templates.py --auto-map

This fetches all your brand templates, maps them by name,
and saves the IDs to disciplinefuel.json automatically.

─────────────────────────────────────────────────────────────────
STYLE NAMING GUIDE (auto-mapping keywords)
─────────────────────────────────────────────────────────────────
  dark    → dark, black, night, shadow, moody, glow, neon
  minimal → minimal, clean, simple, white, light, elegant
  bold    → bold, strong, power, impact, graphic, vivid
  luxury  → luxury, gold, premium, royal, rich, elite

Include the style keyword in the template name and it maps automatically.
═══════════════════════════════════════════════════════════════════
"""


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list",         action="store_true", help="List all brand templates")
    parser.add_argument("--auto-map",     action="store_true", help="Auto-map + save to config")
    parser.add_argument("--instructions", action="store_true", help="Show setup guide")
    args = parser.parse_args()

    if args.instructions:
        print(INSTRUCTIONS)

    elif args.list:
        print("Fetching brand templates from Canva...", flush=True)
        templates = _get_all_templates()
        if not templates:
            print("\nNo brand templates found.")
            print("Run: python tools/setup_canva_templates.py --instructions")
        else:
            print(f"\nFound {len(templates)} brand template(s):\n")
            for t in templates:
                tid  = t.get("id", "")
                name = t.get("title", t.get("name", "(unnamed)"))
                style = _detect_style(name) or "?"
                is_car = "(carousel)" if _is_carousel(name) else ""
                print(f"  [{style}] {name} {is_car}")
                print(f"       ID: {tid}\n")

    elif args.auto_map:
        print("Fetching brand templates from Canva...", flush=True)
        templates = _get_all_templates()
        if not templates:
            print("\nNo brand templates found. See setup instructions:")
            print("  python tools/setup_canva_templates.py --instructions")
            sys.exit(1)

        mapping = auto_map_templates(templates)
        print(f"\nAuto-mapping result:")
        print(f"  Image templates:")
        for style, tid in mapping["templates"].items():
            status = f"→ {tid}" if tid else "→ NOT FOUND"
            print(f"    {style:8s}: {status}")
        print(f"  Carousel templates:")
        for style, tid in mapping["carousel_templates"].items():
            status = f"→ {tid}" if tid else "→ NOT FOUND"
            print(f"    {style:8s}: {status}")
        if mapping["unmapped"]:
            print(f"\n  Unmapped templates ({len(mapping['unmapped'])}):")
            for t in mapping["unmapped"]:
                print(f"    {t['name']} ({t['id']})")

        save_template_ids(mapping)

        missing = [s for s, tid in mapping["templates"].items() if not tid]
        if missing:
            print(f"\n[WARN] Missing image templates for: {', '.join(missing)}")
            print("  The pipeline will use Pillow fallback for missing styles.")
            print("  Run --instructions to set up the missing templates.")

    else:
        parser.print_help()
