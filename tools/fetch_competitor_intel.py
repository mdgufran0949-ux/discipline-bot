"""
fetch_competitor_intel.py
Competitor Intelligence for DisciplineFuel.

Uses Instagram Graph API `ig_hashtag_search` + `/{hashtag-id}/top_media` to scan
the top posts on 5 discipline-niche hashtags per day. Extracts hooks, power
words, winning structures, media type mix, and caption length patterns.

Rate limit: 30 unique hashtags / 7-day rolling window. We rotate 5 hashtags/day
from a pool of 10 with 48h cache → safely under the limit.

Usage:
  python tools/fetch_competitor_intel.py --account disciplinefuel [--force]
Output: .tmp/disciplinefuel/competitor_intel.json
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_BASE   = "https://graph.facebook.com/v19.0"
CONFIG_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "accounts"))
TMP_BASE     = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp"))

DEFAULT_HASHTAGS = [
    "discipline", "selfdiscipline", "disciplinequotes", "mentality",
    "mindsetmatters", "grindmode", "hardworkpaysoff", "motivationdaily",
    "selfimprovementtips", "stoicmindset"
]

STOPWORDS = {
    "the","a","an","and","or","but","if","then","so","to","of","in","on","at",
    "by","for","with","from","is","are","was","were","be","been","being","am",
    "i","you","your","yours","he","she","it","its","we","they","them","their",
    "this","that","these","those","my","me","mine","our","ours","us","as",
    "not","no","yes","do","does","did","done","have","has","had","will","would",
    "can","could","should","shall","may","might","must","just","about","into",
    "out","up","down","over","under","again","more","most","some","any","all",
    "what","which","who","whom","when","where","why","how","because","than",
    "too","very","also","only","own","same","so","such","here","there","now",
    "one","two","three","im","dont","cant","youre","its","hes","shes","lets",
    "via","get","got","go","goes","going","gonna","wanna","gotta","like","li",
}

# Non-English function words — block to keep power words focused on English
NON_ENGLISH_STOPWORDS = {
    # German
    "das","dass","der","die","den","dem","des","ein","eine","einen","einem","einer","eines",
    "und","oder","aber","ich","du","er","sie","es","wir","ihr","sein","ist","bin","bist",
    "sind","war","waren","haben","hat","hast","hatte","nicht","nein","ja","auch","nur",
    "mit","von","bei","aus","nach","vor","auf","fur","fuer","uber","ueber","leben","mensch",
    "menschen","zeit","jahr","tag","mann","frau","kind","welt","leute","wenn","dann","weil",
    # Spanish
    "que","con","por","para","pero","como","esto","esta","este","esa","ese","mas","soy",
    "eres","son","eso","ella","ellos","tambien","tiene","tenemos","vida","tiempo","tengo",
    "sobre","hacer","hace","nada","todo","todos","muy","bien","gran","porque","cuando",
    # French
    "les","des","une","dans","pour","avec","sans","mais","comme","tout","tous","tres",
    "mais","leur","nous","vous","notre","votre","suis","etes","sont","etait","etre","avoir",
    "alors","donc","aussi","meme","quand","parce","faire","vie","jour","temps","homme","femme",
    # Portuguese / Italian common
    "sua","seu","dela","dele","isso","isto","esse","essa","aqui","ali","entao","porque",
    "sono","sei","siamo","siete","anche","questo","questa","quella","quello","molto","perche",
}


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_path(account: str) -> str:
    return os.path.join(TMP_BASE, account, "competitor_intel.json")


def _load_cache(account: str, max_hours: int) -> dict | None:
    path = _cache_path(account)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("last_updated", "2000-01-01"))
        if datetime.now() - cached_at < timedelta(hours=max_hours):
            return data
    except Exception:
        return None
    return None


def _save_cache(account: str, data: dict) -> None:
    path = _cache_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Graph API calls ────────────────────────────────────────────────────────────

def _get_hashtag_id(hashtag: str, ig_user_id: str, access_token: str) -> str:
    resp = requests.get(
        f"{GRAPH_BASE}/ig_hashtag_search",
        params={"user_id": ig_user_id, "q": hashtag, "access_token": access_token},
        timeout=20
    )
    if not resp.ok:
        return ""
    data = resp.json().get("data", [])
    return data[0].get("id", "") if data else ""


def _fetch_top_media(hashtag_id: str, ig_user_id: str, access_token: str, limit: int = 25) -> list:
    resp = requests.get(
        f"{GRAPH_BASE}/{hashtag_id}/top_media",
        params={
            "user_id":      ig_user_id,
            "fields":       "id,caption,like_count,comments_count,media_type,permalink,timestamp",
            "limit":        limit,
            "access_token": access_token
        },
        timeout=30
    )
    if not resp.ok:
        return []
    return resp.json().get("data", [])


# ── Pattern extractors ─────────────────────────────────────────────────────────

def _extract_hook(caption: str) -> str:
    if not caption:
        return ""
    # Strip hashtags & mentions
    clean = re.sub(r'[#@]\S+', '', caption).strip()
    # First line or first sentence
    first_line = clean.split("\n")[0].strip()
    if not first_line:
        # Fall back to stripped second chunk
        for line in clean.split("\n"):
            if line.strip():
                first_line = line.strip()
                break
    # Further trim to first sentence
    m = re.split(r'(?<=[.!?])\s+', first_line, maxsplit=1)
    hook = m[0] if m else first_line
    return hook[:100].strip()


def _extract_power_words(captions: list) -> list:
    counts = Counter()
    for cap in captions:
        if not cap:
            continue
        text = re.sub(r'[#@]\S+', ' ', cap.lower())
        words = re.findall(r"[a-z]{3,}", text)
        for w in words:
            if w in STOPWORDS or w in NON_ENGLISH_STOPWORDS:
                continue
            counts[w] += 1
    return [w for w, _ in counts.most_common(20)]


def _classify_quote_structure(caption: str) -> str:
    if not caption:
        return "unknown"
    text = caption.strip()
    first = re.sub(r'[#@]\S+', '', text).strip().split("\n")[0].lower()
    if "?" in first:
        return "question"
    # Contrast: "not X. Y" / "they X, you Y"
    if re.search(r"\bnot\b.*[.,]", first) or " but " in first or re.search(r"\byou\b.*\bthey\b|\bthey\b.*\byou\b", first):
        return "contrast"
    # Command: imperative first word
    first_word = first.split(" ")[0] if first else ""
    if first_word in {"stop","start","wake","get","do","stand","fight","build","break","read","save","bookmark","remember","quit","kill","burn"}:
        return "command"
    # Pain-driven: keywords
    if any(w in first for w in ["pain","fear","regret","broke","lonely","tired","weak","scared","lost","failed","hurt","cry"]):
        return "pain_driven"
    # Identity
    if re.search(r"\byou are\b|\byou're\b|\bi am\b|\bi'm\b", first):
        return "identity"
    return "statement"


def _caption_length_bucket(caption: str) -> str:
    n = len(caption or "")
    if n < 80:
        return "short"
    if n < 250:
        return "medium"
    return "long"


def _extract_username(permalink: str) -> str:
    """Extract Instagram username from a post permalink URL (legacy — no longer works)."""
    m = re.search(r'instagram\.com/([^/?#]+)/p/', permalink or "")
    if not m:
        return ""
    candidate = m.group(1).lower()
    if candidate in {"p", "reel", "reels", "tv", "stories", "explore"}:
        return ""
    return candidate


# Cache for permalink -> creator_name lookups (session-local, avoids re-fetching)
_CREATOR_NAME_CACHE: dict[str, str] = {}


def _fetch_creator_name(permalink: str, timeout: int = 8) -> str:
    """
    Fetch the Instagram post page and extract the creator's display name
    from the og:title meta tag. Instagram blocks real usernames in public HTML,
    but display names are served to search crawlers in og:title like:
        "{Display Name} on Instagram: \"{caption}\""
    Returns a lowercase display name, or empty string on failure.
    Uses Googlebot UA because Instagram serves different HTML to crawlers.
    """
    if not permalink:
        return ""
    if permalink in _CREATOR_NAME_CACHE:
        return _CREATOR_NAME_CACHE[permalink]

    try:
        resp = requests.get(
            permalink,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
            timeout=timeout,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            _CREATOR_NAME_CACHE[permalink] = ""
            return ""
        m = re.search(r'<meta property="og:title" content="([^"]+?) on Instagram:', resp.text)
        if not m:
            _CREATOR_NAME_CACHE[permalink] = ""
            return ""
        name = m.group(1).strip()
        # HTML-decode common entities
        name = (name.replace("&amp;", "&").replace("&quot;", '"')
                    .replace("&#x27;", "'").replace("&#39;", "'"))
        # Collapse whitespace, lowercase for dedupe
        name = re.sub(r"\s+", " ", name).strip().lower()
        # Reject obviously generic names
        if len(name) < 3 or len(name) > 80:
            _CREATOR_NAME_CACHE[permalink] = ""
            return ""
        _CREATOR_NAME_CACHE[permalink] = name
        return name
    except Exception:
        _CREATOR_NAME_CACHE[permalink] = ""
        return ""


def _build_creator_profiles(posts: list, min_appearances: int = 2) -> list:
    """
    Group top posts by creator display name (fetched from og:title of each
    permalink). Only includes creators appearing >= min_appearances times.
    Returns list sorted by avg_engagement descending.
    """
    from collections import defaultdict
    creators: dict = defaultdict(list)

    print(f"  [Creators] Fetching display names for {len(posts)} posts...", flush=True)
    for p in posts:
        permalink = p.get("permalink", "")
        creator_name = _fetch_creator_name(permalink)
        if not creator_name:
            continue
        creators[creator_name].append(p)

    profiles = []
    found = sum(1 for posts_list in creators.values() if len(posts_list) >= min_appearances)
    print(f"  [Creators] {len(creators)} unique creators found, {found} with {min_appearances}+ posts", flush=True)

    for creator_name, creator_posts in creators.items():
        if len(creator_posts) < min_appearances:
            continue

        engagements = [p.get("engagement_score", 0) for p in creator_posts]
        avg_eng     = round(sum(engagements) / len(engagements)) if engagements else 0

        struct_counts = Counter(
            p.get("detected_structure") or _classify_quote_structure(p.get("caption", ""))
            for p in creator_posts
        )
        dominant_structure = struct_counts.most_common(1)[0][0] if struct_counts else "statement"

        length_counts = Counter(
            _caption_length_bucket(p.get("caption", ""))
            for p in creator_posts
        )
        dominant_length = length_counts.most_common(1)[0][0] if length_counts else "medium"

        sorted_posts = sorted(creator_posts, key=lambda x: x.get("engagement_score", 0), reverse=True)
        sample_hooks = [
            p.get("hook_line") or _extract_hook(p.get("caption", ""))
            for p in sorted_posts[:3]
        ]
        sample_hooks = [h for h in sample_hooks if h and len(h) >= 15][:3]

        captions    = [p.get("caption", "") for p in creator_posts]
        power_words = _extract_power_words(captions)[:8]

        profiles.append({
            "display_name":       creator_name,
            "appearances":        len(creator_posts),
            "avg_engagement":     avg_eng,
            "top_engagement":     max(engagements) if engagements else 0,
            "dominant_structure": dominant_structure,
            "dominant_length":    dominant_length,
            "sample_hooks":       sample_hooks,
            "power_words":        power_words,
        })

    # Sort by avg_engagement, cap at top 10
    profiles.sort(key=lambda x: x["avg_engagement"], reverse=True)
    return profiles[:10]


def analyze_top_posts(posts: list) -> dict:
    if not posts:
        return {}

    hooks         = []
    captions      = []
    media_types   = Counter()
    length_mix    = Counter()
    structures    = Counter()
    engagements   = []

    for p in posts:
        cap = p.get("caption", "") or ""
        captions.append(cap)
        hooks.append(p.get("hook_line", "") or _extract_hook(cap))
        mt = p.get("media_type", "IMAGE")
        media_types[mt] += 1
        length_mix[_caption_length_bucket(cap)] += 1
        structures[p.get("detected_structure") or _classify_quote_structure(cap)] += 1
        engagements.append(p.get("engagement_score", 0))

    # Dedupe hooks, keep top 10 by engagement
    seen = set()
    ranked_hooks = []
    for p in sorted(posts, key=lambda x: x.get("engagement_score", 0), reverse=True):
        h = p.get("hook_line") or _extract_hook(p.get("caption", ""))
        key = h.lower().strip()
        if not key or key in seen or len(key) < 15:
            continue
        seen.add(key)
        ranked_hooks.append(h)
        if len(ranked_hooks) >= 10:
            break

    def _normalize(counter: Counter) -> dict:
        total = sum(counter.values()) or 1
        return {k: round(v / total, 3) for k, v in counter.items()}

    engagements.sort(reverse=True)
    top25 = engagements[:25] or [0]
    avg_eng = sum(top25) / len(top25)
    median_eng = top25[len(top25) // 2]

    # Build creator profiles from posts that have permalinks
    creator_profiles = _build_creator_profiles(posts, min_appearances=2)

    return {
        "top_hooks":              ranked_hooks,
        "power_words":            _extract_power_words(captions),
        "best_media_types":       _normalize(media_types),
        "caption_length_winners": _normalize(length_mix),
        "top_quote_structures":   _normalize(structures),
        "avg_engagement_top_25":  round(avg_eng, 0),
        "median_engagement_top_25": round(median_eng, 0),
        "top_creators":           creator_profiles,
    }


# ── Main entry ─────────────────────────────────────────────────────────────────

def _pick_hashtags(pool: list, per_day: int) -> list:
    """Rotate through the pool so different hashtags get scanned on different days."""
    if not pool:
        return []
    offset = datetime.now().day % len(pool)
    rotated = pool[offset:] + pool[:offset]
    return rotated[:per_day]


def fetch_competitor_intel(ig_user_id: str, access_token: str, account: str = "disciplinefuel",
                           force: bool = False) -> dict:
    cfg = _load_config(account)
    intel_cfg  = cfg.get("competitor_intel", {})
    pool       = intel_cfg.get("hashtags_pool", DEFAULT_HASHTAGS)
    per_day    = intel_cfg.get("scan_hashtags_per_day", 5)
    cache_hrs  = intel_cfg.get("cache_hours", 48)
    min_likes  = intel_cfg.get("min_likes_threshold", 1000)

    if not force:
        cached = _load_cache(account, cache_hrs)
        if cached:
            print(f"[OK] Using cached competitor intel (< {cache_hrs}h old)", flush=True)
            return cached

    if not ig_user_id or not access_token:
        print("[WARN] Missing IG user_id or token — cannot fetch competitor intel.", flush=True)
        return {}

    hashtags = _pick_hashtags(pool, per_day)
    print(f"Scanning {len(hashtags)} competitor hashtags: {hashtags}", flush=True)

    all_posts = []
    for tag in hashtags:
        hid = _get_hashtag_id(tag, ig_user_id, access_token)
        if not hid:
            print(f"  [SKIP] #{tag}: no hashtag_id", flush=True)
            continue
        media = _fetch_top_media(hid, ig_user_id, access_token, limit=25)
        print(f"  [#{tag}] {len(media)} posts", flush=True)
        for m in media:
            likes = m.get("like_count", 0) or 0
            comments = m.get("comments_count", 0) or 0
            if likes < min_likes:
                continue
            caption = m.get("caption", "") or ""
            all_posts.append({
                "media_id":           m.get("id", ""),
                "permalink":          m.get("permalink", ""),
                "hashtag_source":     tag,
                "media_type":         m.get("media_type", "IMAGE"),
                "like_count":         likes,
                "comments_count":     comments,
                "engagement_score":   likes + comments,
                "hook_line":          _extract_hook(caption),
                "caption_length":     len(caption),
                "detected_structure": _classify_quote_structure(caption),
                "caption":            caption[:500],  # cap for storage
            })

    if not all_posts:
        print("[WARN] No competitor posts collected.", flush=True)
        return {}

    # Keep only top 50 by engagement for storage / analysis
    all_posts.sort(key=lambda x: x["engagement_score"], reverse=True)
    top_posts = all_posts[:50]

    patterns = analyze_top_posts(top_posts)

    result = {
        "last_updated":         datetime.now().isoformat(),
        "hashtags_scanned":     hashtags,
        "total_posts_analyzed": len(top_posts),
        "top_posts":            [{k: v for k, v in p.items() if k != "caption"} for p in top_posts[:25]],
        "patterns":             patterns,
    }

    _save_cache(account, result)
    print(f"[OK] Competitor intel saved: {len(top_posts)} posts, avg_engagement={patterns.get('avg_engagement_top_25', 0):.0f}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="disciplinefuel")
    parser.add_argument("--force",   action="store_true")
    args = parser.parse_args()

    cfg = _load_config(args.account)
    result = fetch_competitor_intel(
        ig_user_id=cfg.get("ig_user_id", ""),
        access_token=cfg.get("ig_access_token", ""),
        account=args.account,
        force=args.force
    )
    print(json.dumps(result.get("patterns", {}), indent=2))
