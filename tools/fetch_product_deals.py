"""
fetch_product_deals.py
Fetches trending tech gadgets under Rs.999 from Amazon India (RapidAPI) + Flipkart (scraping).
Returns all product angle images for cinematic 360-degree video showcase.

Usage: python tools/fetch_product_deals.py --source amazon --count 5 --max-price 999
Output: JSON list of products with all angle images saved to --output or stdout.
"""

import json
import sys
import os
import re
import math
import time
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
TMP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

AMAZON_QUERIES = [
    "tech gadgets under 999",
    "useful phone accessories",
    "smart gadgets mini usb",
    "portable gadgets everyday",
]

FLIPKART_QUERIES = [
    "tech gadgets",
    "usb accessories",
    "smart home gadgets",
]


def normalize_price(price_str) -> float:
    """Extract numeric price from strings like Rs.499, 499.00, 1,299."""
    if not price_str:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(price_str).replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def upgrade_amazon_image_url(url: str) -> str:
    """Strip Amazon size suffixes to get the highest-res image."""
    if not url:
        return url
    # Remove modifier codes like ._AC_SY300_SX300_ or ._SL160_
    url = re.sub(r"\._[A-Z0-9_,]+_\.", ".", url)
    # Insert SL1500 for large size before extension
    if re.search(r"\.(jpg|jpeg|png|webp)$", url, re.I):
        url = re.sub(r"(\.(jpg|jpeg|png|webp))$", r"._AC_SL1500_\1", url, flags=re.I)
    return url


# ── Amazon via RapidAPI ──────────────────────────────────────────────────────

def search_amazon_rapidapi(query: str, max_price: int, count: int) -> list:
    """Search Amazon India products via RapidAPI Real-Time Amazon Data."""
    url = "https://real-time-amazon-data.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "real-time-amazon-data.p.rapidapi.com",
    }
    params = {
        "query": query,
        "page": "1",
        "country": "IN",
        "sort_by": "REVIEWS",
        "product_condition": "NEW",
        "max_price": str(max_price),
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("data", {}).get("products", [])
        results = []
        for p in raw:
            price = normalize_price(p.get("product_price", ""))
            if price == 0 or price > max_price:
                continue
            rating = float(p.get("product_star_rating") or 0)
            reviews = int(p.get("product_num_ratings") or 0)
            if rating < 4.0 or reviews < 50:
                continue
            results.append({
                "asin": p.get("asin", ""),
                "title": p.get("product_title", "")[:120],
                "price": price,
                "original_price": normalize_price(p.get("product_original_price") or price),
                "rating": rating,
                "review_count": reviews,
                "_main_img": p.get("product_photo", ""),
                "product_url": p.get("product_url", ""),
                "source": "amazon",
            })
        return results[: count * 2]
    except Exception as e:
        print(f"[WARN] RapidAPI search failed: {e}", file=sys.stderr)
        return []


def get_amazon_all_images(asin: str) -> tuple:
    """Fetch all angle images + about_product features via RapidAPI product details."""
    if not RAPIDAPI_KEY or not asin:
        return [], []
    url = "https://real-time-amazon-data.p.rapidapi.com/product-details"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "real-time-amazon-data.p.rapidapi.com",
    }
    params = {"asin": asin, "country": "IN"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        photos = data.get("product_photos", [])
        if not photos:
            main = data.get("product_photo", "")
            photos = [main] if main else []
        photos = [upgrade_amazon_image_url(u) for u in photos if u]
        features = data.get("about_product", [])[:5]
        return photos, [str(f) for f in features]
    except Exception as e:
        print(f"[WARN] RapidAPI details failed ({asin}): {e}", file=sys.stderr)
        return [], []


def get_curated_fallback(max_price: int, count: int) -> list:
    """Fallback: curated list of popular Amazon India gadgets under Rs.999.
    Used when RapidAPI is unavailable (not subscribed / quota exceeded).
    Images are fetched live from Amazon CDN using known ASINs.
    """
    curated = [
        {
            "asin": "B0BTHK3TWP",
            "title": "Portronics Konnect L POR-1081 Fast Charging USB Type C Cable 3A",
            "price": 299, "original_price": 699,
            "rating": 4.2, "review_count": 28500,
            "product_url": "https://www.amazon.in/dp/B0BTHK3TWP",
            "source": "amazon",
        },
        {
            "asin": "B09XQMCLN5",
            "title": "STRIFF Adjustable Mobile Stand Holder for Desk Foldable Portable",
            "price": 349, "original_price": 999,
            "rating": 4.3, "review_count": 45200,
            "product_url": "https://www.amazon.in/dp/B09XQMCLN5",
            "source": "amazon",
        },
        {
            "asin": "B07PXGQC3Q",
            "title": "AmazonBasics AA Performance Alkaline Batteries 10-Pack",
            "price": 449, "original_price": 649,
            "rating": 4.4, "review_count": 62000,
            "product_url": "https://www.amazon.in/dp/B07PXGQC3Q",
            "source": "amazon",
        },
        {
            "asin": "B091G3WT74",
            "title": "Gizga Essentials Cable Management Zip Ties Reusable Nylon Straps",
            "price": 199, "original_price": 499,
            "rating": 4.1, "review_count": 18900,
            "product_url": "https://www.amazon.in/dp/B091G3WT74",
            "source": "amazon",
        },
        {
            "asin": "B08KH71VN6",
            "title": "Portronics Clap 3 Portable USB LED Light Flexible Neck Laptop Light",
            "price": 399, "original_price": 799,
            "rating": 4.2, "review_count": 22100,
            "product_url": "https://www.amazon.in/dp/B08KH71VN6",
            "source": "amazon",
        },
        {
            "asin": "B09B8YWXDF",
            "title": "Amazon Brand Solimo Laptop Cooling Pad with 3 USB Fans",
            "price": 799, "original_price": 999,
            "rating": 4.0, "review_count": 9800,
            "product_url": "https://www.amazon.in/dp/B09B8YWXDF",
            "source": "amazon",
        },
    ]
    # Filter by price and return up to count*2
    filtered = [p for p in curated if p["price"] <= max_price]
    results = []
    for p in filtered[: count * 2]:
        # Build Amazon image URLs from ASIN (standard CDN pattern)
        asin = p["asin"]
        main_img = f"https://m.media-amazon.com/images/P/{asin}.jpg"
        p["_main_img"] = main_img
        results.append(p)
    return results


def fetch_amazon(max_price: int, count: int) -> list:
    """Fetch Amazon products + enrich with all angle images."""
    import random

    products = []
    if RAPIDAPI_KEY:
        query = random.choice(AMAZON_QUERIES)
        products = search_amazon_rapidapi(query, max_price, count)

    if not products:
        print("[INFO] RapidAPI unavailable — using curated product list...", file=sys.stderr)
        products = get_curated_fallback(max_price, count)

    enriched = []
    for p in products[:count]:
        angles, features = [], []
        if p.get("asin") and RAPIDAPI_KEY:
            time.sleep(0.5)
            angles, features = get_amazon_all_images(p["asin"])

        main_img = p.pop("_main_img", "")
        all_imgs = list(dict.fromkeys(filter(None, [main_img] + angles)))
        p["images"] = {
            "main": all_imgs[0] if all_imgs else "",
            "angles": all_imgs[1:],
            "all": all_imgs,
        }
        p["features"] = features
        enriched.append(p)

    return enriched


# ── Flipkart via scraping ────────────────────────────────────────────────────

def get_flipkart_product_images(product_url: str) -> list:
    """Fetch all carousel images from a Flipkart product page."""
    if not product_url:
        return []
    try:
        from bs4 import BeautifulSoup

        resp = requests.get(product_url, headers=HEADERS_BROWSER, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        images = []

        # Method 1: JSON-LD structured data (most reliable)
        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script_tag.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Product":
                        img = item.get("image", [])
                        if isinstance(img, list):
                            images.extend(img)
                        elif img:
                            images.append(img)
            except Exception:
                pass

        # Method 2: Carousel image tags
        if not images:
            for img in soup.select("li._20Gt85 img, li img._396cs4"):
                src = img.get("src", "") or img.get("data-src", "")
                if src:
                    src = re.sub(r"/\d+/\d+/", "/832/832/", src)
                    images.append(src)

        # Method 3: Any Flipkart CDN image
        if not images:
            for img in soup.find_all(
                "img", src=re.compile(r"rukminim|flipkart", re.I)
            ):
                src = img.get("src", "")
                if src and not src.endswith(".svg") and "logo" not in src.lower():
                    src = re.sub(r"/\d+/\d+/", "/832/832/", src)
                    images.append(src)

        return list(dict.fromkeys(images))[:8]
    except Exception as e:
        print(f"[WARN] Flipkart image fetch failed: {e}", file=sys.stderr)
        return []


def fetch_flipkart(max_price: int, count: int) -> list:
    """Scrape Flipkart search results for trending gadgets."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print(
            "[ERROR] beautifulsoup4 not installed. Run: pip install beautifulsoup4",
            file=sys.stderr,
        )
        return []

    results = []
    for query in FLIPKART_QUERIES:
        if len(results) >= count * 2:
            break
        url = (
            f"https://www.flipkart.com/search?q={query.replace(' ', '+')}"
            f"&sort=popularity_desc"
            f"&p[]=facets.price_range.from%3D0"
            f"&p[]=facets.price_range.to%3D{max_price}"
        )
        try:
            resp = requests.get(url, headers=HEADERS_BROWSER, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            cards = (
                soup.select("div._75nlfW")
                or soup.select("div[data-id]")
                or soup.select("div._1AtVbE")
            )

            for card in cards[: count * 4]:
                title_el = (
                    card.select_one("div.KzDlHZ")
                    or card.select_one("div._4rR01T")
                    or card.select_one("a.s1Q9rs")
                )
                price_el = (
                    card.select_one("div.Nx9bqj")
                    or card.select_one("div._30jeq3")
                )
                img_el = card.select_one("img.DByuf4, img._396cs4, img")
                link_el = card.select_one("a[href*='/p/']")
                rating_el = (
                    card.select_one("div.XQDdHH") or card.select_one("div._3LWZlK")
                )

                if not title_el or not price_el:
                    continue
                price = normalize_price(price_el.get_text())
                if price == 0 or price > max_price:
                    continue

                try:
                    rating_text = re.search(r"[\d.]+", rating_el.get_text())
                    rating = float(rating_text.group()) if rating_text else 4.0
                except Exception:
                    rating = 4.0
                if rating < 4.0:
                    continue

                href = link_el.get("href", "") if link_el else ""
                product_url = (
                    "https://www.flipkart.com" + href
                    if href.startswith("/")
                    else href
                )
                product_id = ""
                m = re.search(r"/p/([a-zA-Z0-9]+)", product_url)
                if m:
                    product_id = m.group(1)

                main_img = ""
                if img_el:
                    main_img = img_el.get("src", "") or img_el.get("data-src", "")
                    main_img = re.sub(r"\?.*$", "", main_img)
                    main_img = (
                        main_img.replace("{@width}", "612")
                        .replace("{@height}", "816")
                    )

                results.append({
                    "asin": product_id,
                    "title": title_el.get_text(strip=True)[:120],
                    "price": price,
                    "original_price": price,
                    "rating": rating,
                    "review_count": 200,
                    "_main_img": main_img,
                    "_product_url": product_url,
                    "product_url": product_url,
                    "source": "flipkart",
                })

                if len(results) >= count * 2:
                    break

            time.sleep(1.0)
        except Exception as e:
            print(f"[WARN] Flipkart scrape failed ({query}): {e}", file=sys.stderr)

    enriched = []
    for p in results[:count]:
        product_url = p.pop("_product_url", "")
        main_img = p.pop("_main_img", "")
        angles = get_flipkart_product_images(product_url)

        all_imgs = list(dict.fromkeys(filter(None, [main_img] + angles)))
        p["images"] = {
            "main": all_imgs[0] if all_imgs else "",
            "angles": all_imgs[1:],
            "all": all_imgs,
        }
        p["features"] = []
        enriched.append(p)
        time.sleep(0.8)

    return enriched


# ── Main ─────────────────────────────────────────────────────────────────────

def fetch_products(source: str = "both", max_price: int = 999, count: int = 5) -> list:
    products = []

    if source in ("amazon", "both"):
        print("[INFO] Fetching from Amazon...", file=sys.stderr)
        amz = fetch_amazon(max_price, count)
        products.extend(amz)
        print(f"[INFO] Amazon: {len(amz)} products", file=sys.stderr)

    if source in ("flipkart", "both"):
        print("[INFO] Fetching from Flipkart...", file=sys.stderr)
        fk = fetch_flipkart(max_price, count)
        products.extend(fk)
        print(f"[INFO] Flipkart: {len(fk)} products", file=sys.stderr)

    # Score by rating * log10(review_count + 1), then sort descending
    for p in products:
        p["_score"] = p["rating"] * math.log10(p["review_count"] + 1)
    products.sort(key=lambda x: x["_score"], reverse=True)
    for p in products:
        del p["_score"]

    return products[:count]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch trending product deals")
    parser.add_argument(
        "--source", choices=["amazon", "flipkart", "both"], default="both"
    )
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--max-price", type=int, default=999, dest="max_price")
    parser.add_argument("--output", default=None, help="Save JSON to file")
    args = parser.parse_args()

    os.makedirs(TMP, exist_ok=True)
    results = fetch_products(args.source, args.max_price, args.count)
    output = json.dumps(results, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[OK] {len(results)} products saved to {args.output}", file=sys.stderr)
    else:
        print(output)
