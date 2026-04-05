"""
generate_canva_post.py
Design Engine (Canva) for DisciplineFuel.
Uses Canva Connect API to autofill pre-made templates with quotes,
series labels, and branding. Exports as JPG/PNG.

Supports: single image post + carousel (multiple slides)

Usage: python tools/generate_canva_post.py --quote "..." --series "Discipline Rule #7" --style dark
Output: JSON with file path(s)

Requires: CANVA_CLIENT_ID, CANVA_CLIENT_SECRET in .env
          canva_auth.py for OAuth token management
          Template IDs configured in config/accounts/disciplinefuel.json
"""

import json
import os
import random
import sys
import time
import requests
import argparse
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from canva_auth import get_auth_headers

CANVA_API_BASE = "https://api.canva.com/rest/v1"
TMP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp", "disciplinefuel", "canva"))
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts", "disciplinefuel.json"))

# ── Config ─────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Canva API helpers ──────────────────────────────────────────────────────────

def _api_get(path: str) -> dict:
    resp = requests.get(f"{CANVA_API_BASE}{path}", headers=get_auth_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _api_post(path: str, payload: dict) -> dict:
    resp = requests.post(
        f"{CANVA_API_BASE}{path}",
        headers={**get_auth_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()


def _poll_export(job_id: str, timeout: int = 120) -> str:
    """Poll an export job until complete. Returns download URL."""
    start = time.time()
    while time.time() - start < timeout:
        resp = _api_get(f"/exports/{job_id}")
        status = resp.get("job", {}).get("status", "")
        if status == "success":
            urls = resp["job"].get("urls", [])
            if urls:
                return urls[0]
            raise RuntimeError("Export succeeded but no URL returned")
        if status == "failed":
            raise RuntimeError(f"Canva export failed: {resp}")
        print(f"  [Canva] Export status: {status}...", flush=True)
        time.sleep(3)
    raise TimeoutError(f"Canva export timed out after {timeout}s")


def _download_file(url: str, out_path: str) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)


# ── Design creation ────────────────────────────────────────────────────────────

def _create_design_from_template(template_id: str) -> str:
    """Create a new design from a template. Returns design_id."""
    print(f"  Creating design from template {template_id}...", flush=True)
    resp = _api_post("/designs", {
        "design_type": {"type": "preset", "name": "InstagramPost"},
        "asset_id": template_id
    })
    return resp["design"]["id"]


def _autofill_template(template_id: str, fields: dict) -> str:
    """
    Use Canva Autofill API to populate a template.
    fields: {"quote_text": "...", "series_label": "...", "page_name": "..."}
    Returns new design_id.
    """
    print(f"  Autofilling template {template_id}...", flush=True)

    data_items = []
    if fields.get("quote_text"):
        data_items.append({
            "name": "quote_text",
            "type": "text",
            "text": fields["quote_text"]
        })
    if fields.get("series_label"):
        data_items.append({
            "name": "series_label",
            "type": "text",
            "text": fields["series_label"]
        })
    if fields.get("page_name"):
        data_items.append({
            "name": "page_name",
            "type": "text",
            "text": fields["page_name"]
        })

    resp = _api_post("/autofills", {
        "brand_template_id": template_id,
        "data": data_items,
        "title": f"DisciplineFuel_{int(time.time())}"
    })

    # Poll for autofill job completion
    job_id = resp.get("job", {}).get("id")
    if not job_id:
        raise RuntimeError(f"Autofill job not started: {resp}")

    start = time.time()
    while time.time() - start < 120:
        status_resp = _api_get(f"/autofills/{job_id}")
        status = status_resp.get("job", {}).get("status", "")
        if status == "success":
            design_id = status_resp["job"]["result"]["design"]["id"]
            print(f"  [OK] Autofill complete → design {design_id}", flush=True)
            return design_id
        if status == "failed":
            raise RuntimeError(f"Autofill job failed: {status_resp}")
        print(f"  [Canva] Autofill status: {status}...", flush=True)
        time.sleep(3)

    raise TimeoutError("Canva autofill timed out")


def _export_design(design_id: str, out_path: str, format: str = "jpg") -> str:
    """Export a Canva design to JPG/PNG and download it."""
    print(f"  Exporting design {design_id} as {format.upper()}...", flush=True)
    resp = _api_post("/exports", {
        "design_id": design_id,
        "format":    format.upper(),
        "pages":     [1]
    })
    job_id = resp.get("job", {}).get("id")
    if not job_id:
        raise RuntimeError(f"Export job not started: {resp}")

    download_url = _poll_export(job_id)
    _download_file(download_url, out_path)
    print(f"  [OK] Downloaded → {out_path}", flush=True)
    return out_path


# ── Fallback: Pillow-based composer ───────────────────────────────────────────

def _compose_with_pillow(
    quote: str,
    series_label: str,
    page_name: str,
    design_style: str,
    bg_image_path: str,
    out_path: str
) -> str:
    """
    Fallback composer using Pillow when Canva API/template is unavailable.
    Overlays bold typography on an AI-generated background image.
    """
    from PIL import Image, ImageDraw, ImageFont

    # Style configs
    styles = {
        "dark":    {"overlay_alpha": 160, "text_color": (255, 255, 255), "accent_color": (255, 200, 50),  "bg_color": (0, 0, 0)},
        "minimal": {"overlay_alpha": 200, "text_color": (10,  10,  10),  "accent_color": (50,  50,  50),  "bg_color": (255, 255, 255)},
        "bold":    {"overlay_alpha": 120, "text_color": (255, 255, 255), "accent_color": (255, 50,  50),  "bg_color": (20,  20,  20)},
        "luxury":  {"overlay_alpha": 150, "text_color": (212, 175, 55),  "accent_color": (255, 215, 0),   "bg_color": (0,   0,   0)},
    }
    cfg = styles.get(design_style, styles["dark"])

    # Load or create background
    if bg_image_path and os.path.exists(bg_image_path):
        img = Image.open(bg_image_path).convert("RGBA").resize((1080, 1920))
    else:
        img = Image.new("RGBA", (1080, 1920), (*cfg["bg_color"], 255))

    # Dark gradient overlay (bottom 60%)
    overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    grad_start = 700
    for y in range(grad_start, 1920):
        alpha = int(cfg["overlay_alpha"] * (y - grad_start) / (1920 - grad_start))
        draw_ov.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    # Load fonts — try Linux paths first, then Windows, then default
    def load_font(size):
        candidates = [
            # Linux (GitHub Actions / Ubuntu)
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            # Windows
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "C:/Windows/Fonts/verdanab.ttf",
        ]
        for font_path in candidates:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        return ImageFont.load_default(size=size)

    font_series = load_font(42)
    font_quote  = load_font(96)
    font_brand  = load_font(36)

    # ── Full dark overlay for text readability ──────────────────────────
    overlay2 = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d2 = ImageDraw.Draw(overlay2)
    d2.rectangle([(0, 600), (1080, 1400)], fill=(0, 0, 0, 140))
    img = Image.alpha_composite(img.convert("RGBA"), overlay2).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Series label ─────────────────────────────────────────────────────
    series_text = series_label.upper() if series_label else ""
    if series_text:
        bbox = draw.textbbox((0, 0), series_text, font=font_series)
        sw = bbox[2] - bbox[0]
        sx = (1080 - sw) // 2
        draw.text((sx + 2, 702), series_text, font=font_series, fill=(0, 0, 0))
        draw.text((sx, 700), series_text, font=font_series, fill=cfg["accent_color"])

    # ── Divider line ──────────────────────────────────────────────────────
    draw.line([(300, 760), (780, 760)], fill=cfg["accent_color"], width=3)

    # ── Quote text (word-wrapped, large) ──────────────────────────────────
    max_width = 960
    words = quote.split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font_quote)
        if bbox[2] - bbox[0] > max_width:
            if current:
                lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    line_height = draw.textbbox((0, 0), "A", font=font_quote)[3] + 24
    total_h = line_height * len(lines)
    y_start = 800

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_quote)
        lw = bbox[2] - bbox[0]
        x  = (1080 - lw) // 2
        # Multi-layer shadow for crisp contrast
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4)]:
            draw.text((x + dx, y_start + dy), line, font=font_quote, fill=(0, 0, 0))
        draw.text((x, y_start), line, font=font_quote, fill=cfg["text_color"])
        y_start += line_height

    # ── Bottom divider ─────────────────────────────────────────────────────
    draw.line([(300, y_start + 20), (780, y_start + 20)], fill=cfg["accent_color"], width=2)

    # ── Branding watermark ────────────────────────────────────────────────
    brand_bbox = draw.textbbox((0, 0), page_name, font=font_brand)
    bw = brand_bbox[2] - brand_bbox[0]
    draw.text((1080 - bw - 40 + 2, 1920 - 72 + 2), page_name, font=font_brand, fill=(0, 0, 0))
    draw.text((1080 - bw - 40, 1920 - 72), page_name, font=font_brand, fill=cfg["accent_color"])

    img.save(out_path, "JPEG", quality=95)
    return out_path


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_canva_post(
    quote: str,
    series_label: str,
    design_style: str = "dark",
    bg_image_path: str = None,
    output_path: str = None,
    use_canva: bool = True
) -> dict:
    """
    Generate a single DisciplineFuel image post.
    Tries Canva API first; falls back to Pillow composer.
    Returns: {file, tool, design_style}
    """
    os.makedirs(TMP_DIR, exist_ok=True)
    if output_path is None:
        output_path = os.path.join(TMP_DIR, f"post_{int(time.time())}.jpg")

    cfg         = _load_config()
    canva_cfg   = cfg.get("canva", {})
    pools       = canva_cfg.get("template_pools", {})
    pool        = pools.get(design_style) or next((v for v in pools.values() if v), [])
    template_id = random.choice(pool) if pool else ""
    page_name   = cfg.get("ig_page_name", "@DisciplineFuel")

    if use_canva and template_id:
        try:
            fields = {
                "quote_text":   quote,
                "series_label": series_label,
                "page_name":    page_name
            }
            design_id = _autofill_template(template_id, fields)
            _export_design(design_id, output_path, format="jpg")
            return {"file": output_path, "tool": "canva", "design_style": design_style}
        except Exception as e:
            print(f"  [Canva] failed: {e}. Falling back to Pillow...", flush=True)

    # Fallback: Pillow
    _compose_with_pillow(quote, series_label, page_name, design_style, bg_image_path, output_path)
    return {"file": output_path, "tool": "pillow", "design_style": design_style}


def generate_canva_carousel(
    slides: list,
    design_style: str = "dark",
    bg_image_paths: list = None
) -> dict:
    """
    Generate multiple carousel slides.
    slides: list of {quote, series_label}
    bg_image_paths: list of background image paths (optional, same length as slides)
    Returns: {files: [...], tool, count}
    """
    os.makedirs(TMP_DIR, exist_ok=True)
    files = []
    bg_paths = bg_image_paths or []

    cfg           = _load_config()
    canva_cfg     = cfg.get("canva", {})
    car_pools     = canva_cfg.get("carousel_template_pools", {})
    car_pool      = car_pools.get(design_style) or next((v for v in car_pools.values() if v), [])
    template_id   = random.choice(car_pool) if car_pool else ""

    for i, slide in enumerate(slides):
        out_path = os.path.join(TMP_DIR, f"carousel_{int(time.time())}_{i+1:02d}.jpg")
        bg = bg_paths[i] if i < len(bg_paths) else None
        result = generate_canva_post(
            quote=slide["quote"],
            series_label=slide.get("series_label", ""),
            design_style=design_style,
            bg_image_path=bg,
            output_path=out_path,
            use_canva=bool(template_id)
        )
        files.append(result["file"])
        print(f"  [slide {i+1}/{len(slides)}] done", flush=True)
        time.sleep(1)  # avoid hammering Canva API

    return {"files": files, "tool": "canva" if template_id else "pillow", "count": len(files)}


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quote",  required=True, help="Quote text")
    parser.add_argument("--series", default="Discipline Rule #1", help="Series label")
    parser.add_argument("--style",  default="dark", help="dark|minimal|bold|luxury")
    parser.add_argument("--bg",     default=None, help="Background image path")
    parser.add_argument("--no-canva", action="store_true", help="Skip Canva, use Pillow only")
    args = parser.parse_args()

    result = generate_canva_post(
        quote=args.quote,
        series_label=args.series,
        design_style=args.style,
        bg_image_path=args.bg,
        use_canva=not args.no_canva
    )
    print(json.dumps(result, indent=2))
