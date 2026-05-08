"""
audio_library_manager.py
Automated audio library using Jamendo API (free, CC licensed).

LICENSING NOTE:
  Most Jamendo tracks are CC BY-NC (non-commercial use only).
  This is acceptable while the account is non-monetized.
  TODO: When account begins monetizing (ads, brand deals, etc.),
  set "monetization_active": true in config/accounts/disciplinefuel.json.
  This will auto-filter to commercial-safe licenses only (CC BY / CC BY-SA / CC0).
  See LICENSING_NOTES.md for full details.

CLI:
  python tools/audio_library_manager.py --bootstrap [--dry-run] [--pillar hard_truth]
  python tools/audio_library_manager.py --refresh   [--dry-run]
  python tools/audio_library_manager.py --status
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────

_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LIB_ROOT  = os.path.join(_ROOT, "audio_library")
_MANIFEST  = os.path.join(_LIB_ROOT, "manifest.json")
_LOG_DIR   = os.path.join(_ROOT, "logs")
_TMP_BASE  = os.path.join(_ROOT, ".tmp")
_CFG_DIR   = os.path.join(_ROOT, "config", "accounts")

# ── Constants ────────────────────────────────────────────────────────────────

JAMENDO_BASE        = "https://api.jamendo.com/v3.0"
CCMIXTER_BASE       = "https://ccmixter.org/api/query"
RATE_LIMIT_SECS     = 2.0   # Jamendo fair-use: 1 call per 2 seconds
MAX_RETRIES         = 3
TRACKS_PER_PILLAR   = 15    # bootstrap target
REFRESH_COUNT       = 5     # tracks replaced per pillar per weekly refresh
NO_REPEAT_WINDOW    = 10    # never reuse same track within this many posts
PREFERRED_DUR_MIN   = 20    # seconds — ideal BGM length range
PREFERRED_DUR_MAX   = 90

# Default pillar -> Jamendo fuzzytags mapping
DEFAULT_PILLAR_TAGS: dict[str, list[str]] = {
    "hard_truth":  ["dark", "cinematic", "epic", "dramatic"],
    "tactical":    ["focus", "driving", "minimal", "rhythmic"],
    "reframe":     ["ambient", "contemplative", "atmospheric"],
    "story_proof": ["emotional", "inspiring", "uplifting", "orchestral"],
}

# License filtering for commercial mode
COMMERCIAL_BLOCKED = ["nc", "nd"]  # exclude if these appear in license URL

# ── Logging ──────────────────────────────────────────────────────────────────

os.makedirs(_LOG_DIR, exist_ok=True)
_log_file = os.path.join(_LOG_DIR, f"audio_library_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("audio_library")

# ── Rate limiter ─────────────────────────────────────────────────────────────

_last_api_call: float = 0.0


def _rate_limited_get(url: str, params: dict = None, timeout: int = 20) -> requests.Response:
    """GET with enforced >= RATE_LIMIT_SECS gap between calls."""
    global _last_api_call
    gap = RATE_LIMIT_SECS - (time.time() - _last_api_call)
    if gap > 0:
        time.sleep(gap)
    resp = requests.get(url, params=params, timeout=timeout)
    _last_api_call = time.time()
    return resp


# ── Manifest helpers ─────────────────────────────────────────────────────────

def _load_manifest() -> dict:
    if not os.path.exists(_MANIFEST):
        return {"version": 1, "last_updated": None, "tracks": []}
    try:
        with open(_MANIFEST, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"version": 1, "last_updated": None, "tracks": []}
    except Exception:
        return {"version": 1, "last_updated": None, "tracks": []}


def _save_manifest(manifest: dict) -> None:
    os.makedirs(_LIB_ROOT, exist_ok=True)
    manifest["last_updated"] = datetime.now().isoformat()
    tmp = _MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _MANIFEST)


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_config(account: str) -> dict:
    path = os.path.join(_CFG_DIR, f"{account}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _audio_history_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "audio_history.json")


def _load_history(account: str) -> list:
    path = _audio_history_path(account)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ── Jamendo API ───────────────────────────────────────────────────────────────

def _fetch_jamendo_tracks(
    pillar: str,
    client_id: str,
    monetization_active: bool,
    limit: int = 30,
    exclude_jamendo_ids: set = None,
) -> list[dict]:
    """
    Fetch tracks from Jamendo for a given pillar.
    Returns list of filtered track dicts, sorted by duration-preference then popularity.
    Retries up to MAX_RETRIES with exponential backoff.
    """
    tags      = " ".join(DEFAULT_PILLAR_TAGS.get(pillar, ["ambient"]))
    exclude   = exclude_jamendo_ids or set()
    last_err  = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = _rate_limited_get(
                f"{JAMENDO_BASE}/tracks/",
                params={
                    "client_id":              client_id,
                    "format":                 "json",
                    "limit":                  limit,
                    "fuzzytags":              tags,
                    "audioformat":            "mp32",
                    "audiodownload_allowed":  "true",
                    "include":                "licenses",
                    "order":                  "popularity_week",
                },
            )
            resp.raise_for_status()
            raw = resp.json()
            if raw.get("headers", {}).get("status") == "error":
                raise ValueError(f"Jamendo error: {raw['headers'].get('error_message')}")
            tracks = raw.get("results", [])
            break
        except Exception as exc:
            last_err = exc
            wait = 2 ** attempt
            log.warning(f"Jamendo attempt {attempt + 1}/{MAX_RETRIES} failed: {exc} — retry in {wait}s")
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
    else:
        log.error(f"All Jamendo retries exhausted for pillar={pillar}: {last_err}")
        return []

    filtered = []
    for t in tracks:
        jid = str(t.get("id", ""))
        if jid in exclude:
            continue
        if not t.get("audiodownload"):
            continue
        if not t.get("audiodownload_allowed", False):
            continue

        license_url = t.get("license_ccurl", "")
        if monetization_active:
            if any(b in license_url.lower() for b in COMMERCIAL_BLOCKED):
                log.debug(f"Skipping {jid} — non-commercial license in monetized mode")
                continue

        duration = int(t.get("duration", 0))
        # Prefer 20-90s tracks (ideal BGM) but don't exclude others
        t["_in_preferred_range"] = PREFERRED_DUR_MIN <= duration <= PREFERRED_DUR_MAX
        filtered.append(t)

    # Sort: preferred duration range first, then popularity (order is already by popularity_week)
    filtered.sort(key=lambda t: (0 if t["_in_preferred_range"] else 1))
    log.info(f"  [{pillar}] Jamendo returned {len(tracks)} tracks, {len(filtered)} after filter")
    return filtered


def _download_track(track: dict, pillar: str, client_id: str, dry_run: bool = False) -> dict | None:
    """
    Download a single Jamendo track to audio_library/<pillar>/<jamendo_id>.mp3.
    Returns a manifest entry dict, or None on failure.
    """
    jid      = str(track["id"])
    dl_url   = track["audiodownload"]
    pillar_dir = os.path.join(_LIB_ROOT, pillar)
    dest       = os.path.join(pillar_dir, f"{jid}.mp3")

    if dry_run:
        return {
            "track_id":      f"{pillar}_{jid}",
            "jamendo_id":    jid,
            "pillar":        pillar,
            "title":         track.get("name", ""),
            "artist_name":   track.get("artist_name", ""),
            "license_url":   track.get("license_ccurl", ""),
            "duration":      int(track.get("duration", 0)),
            "downloaded_at": None,
            "file_path":     os.path.relpath(dest, _ROOT),
            "dry_run":       True,
        }

    os.makedirs(pillar_dir, exist_ok=True)
    try:
        resp = requests.get(dl_url, params={"client_id": client_id}, stream=True, timeout=60)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        size_kb = os.path.getsize(dest) // 1024
        log.info(f"    Downloaded: {track.get('name', jid)} ({size_kb} KB) -> {os.path.relpath(dest, _ROOT)}")
        return {
            "track_id":      f"{pillar}_{jid}",
            "jamendo_id":    jid,
            "pillar":        pillar,
            "title":         track.get("name", ""),
            "artist_name":   track.get("artist_name", ""),
            "license_url":   track.get("license_ccurl", ""),
            "duration":      int(track.get("duration", 0)),
            "downloaded_at": datetime.now().isoformat(),
            "file_path":     os.path.relpath(dest, _ROOT),
        }
    except Exception as exc:
        log.error(f"    Download failed for {jid}: {exc}")
        if os.path.exists(dest):
            os.remove(dest)
        return None


# ── ccMixter fallback ─────────────────────────────────────────────────────────

def _fetch_ccmixter_tracks(pillar: str, limit: int = 5) -> list[dict]:
    """
    ccMixter fallback when Jamendo is unavailable.
    Returns lightweight track dicts compatible with Jamendo format.
    """
    tag_map = {
        "hard_truth":  "dark",
        "tactical":    "electronic",
        "reframe":     "ambient",
        "story_proof": "orchestral",
    }
    tag = tag_map.get(pillar, "ambient")
    try:
        resp = _rate_limited_get(
            CCMIXTER_BASE,
            params={"f": "json", "sinby": "score", "limit": limit, "tags": tag, "lic": "c"},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json()
        results = []
        for item in items:
            for fobj in item.get("files", []):
                if "mp3" in fobj.get("file_type", "").lower():
                    results.append({
                        "id":                 item.get("upload_id", ""),
                        "name":               item.get("upload_name", ""),
                        "artist_name":        item.get("user_name", ""),
                        "audiodownload":      fobj.get("download_url", ""),
                        "audiodownload_allowed": True,
                        "license_ccurl":      item.get("license_url", ""),
                        "duration":           0,
                        "_in_preferred_range": False,
                        "_source":            "ccmixter",
                    })
                    break
        log.info(f"  [{pillar}] ccMixter fallback: {len(results)} tracks")
        return results
    except Exception as exc:
        log.error(f"  ccMixter fallback failed for {pillar}: {exc}")
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def bootstrap_library(account: str, cfg: dict, dry_run: bool = False, only_pillar: str = None) -> dict:
    """
    First-run library build. Downloads TRACKS_PER_PILLAR tracks per pillar.
    Returns summary dict with per-pillar counts and any errors.
    """
    client_id = os.getenv("JAMENDO_CLIENT_ID") or cfg.get("jamendo_client_id", "")
    if not client_id:
        log.error("JAMENDO_CLIENT_ID not set. Add to .env or GitHub secrets.")
        return {"error": "missing_client_id"}

    monetization_active = cfg.get("monetization_active", False)
    pillar_tags         = cfg.get("audio_pillars", DEFAULT_PILLAR_TAGS)
    manifest            = _load_manifest()
    existing_ids        = {t["jamendo_id"] for t in manifest["tracks"]}
    pillars             = [only_pillar] if only_pillar else list(pillar_tags.keys())

    summary: dict = {"pillars": {}, "total_downloaded": 0, "errors": []}

    for pillar in pillars:
        log.info(f"\n[bootstrap] Pillar: {pillar}")
        existing_for_pillar = sum(1 for t in manifest["tracks"] if t["pillar"] == pillar)

        if existing_for_pillar >= TRACKS_PER_PILLAR and not dry_run:
            log.info(f"  Already have {existing_for_pillar} tracks — skipping")
            summary["pillars"][pillar] = {"status": "already_complete", "count": existing_for_pillar}
            continue

        needed = TRACKS_PER_PILLAR - existing_for_pillar
        tracks = _fetch_jamendo_tracks(pillar, client_id, monetization_active,
                                       limit=50, exclude_jamendo_ids=existing_ids)

        if len(tracks) < needed:
            log.warning(f"  Jamendo only returned {len(tracks)} for {pillar}, trying ccMixter")
            tracks += _fetch_ccmixter_tracks(pillar, limit=10)

        if not tracks:
            err = f"No tracks available for pillar={pillar}"
            log.error(f"  {err}")
            summary["errors"].append(err)
            summary["pillars"][pillar] = {"status": "failed", "count": 0}
            continue

        downloaded, failed = 0, 0
        for track in tracks[:needed]:
            entry = _download_track(track, pillar, client_id, dry_run=dry_run)
            if entry:
                if not dry_run:
                    manifest["tracks"].append(entry)
                    existing_ids.add(entry["jamendo_id"])
                downloaded += 1

                if dry_run:
                    _print_track_preview(entry, track)
            else:
                failed += 1

        summary["pillars"][pillar] = {"status": "ok", "downloaded": downloaded, "failed": failed}
        summary["total_downloaded"] += downloaded

        if not dry_run:
            _save_manifest(manifest)

    if not dry_run:
        log.info(f"\n[bootstrap] Complete. Total downloaded: {summary['total_downloaded']}")
    else:
        log.info(f"\n[DRY RUN] Would download {summary['total_downloaded']} tracks total")

    return summary


def refresh_library(account: str, cfg: dict, count_per_pillar: int = REFRESH_COUNT,
                    dry_run: bool = False) -> dict:
    """
    Weekly maintenance: replace the N oldest tracks per pillar with fresh ones.
    """
    client_id = os.getenv("JAMENDO_CLIENT_ID") or cfg.get("jamendo_client_id", "")
    if not client_id:
        log.error("JAMENDO_CLIENT_ID not set.")
        return {"error": "missing_client_id"}

    monetization_active = cfg.get("monetization_active", False)
    manifest            = _load_manifest()
    existing_ids        = {t["jamendo_id"] for t in manifest["tracks"]}
    summary             = {"pillars": {}, "replaced": 0}

    for pillar in DEFAULT_PILLAR_TAGS:
        pillar_tracks = sorted(
            [t for t in manifest["tracks"] if t["pillar"] == pillar],
            key=lambda t: t.get("downloaded_at", ""),
        )
        to_remove = pillar_tracks[:count_per_pillar]

        if not to_remove:
            continue

        log.info(f"\n[refresh] Pillar: {pillar} — replacing {len(to_remove)} oldest tracks")

        # Fetch replacements
        new_tracks = _fetch_jamendo_tracks(
            pillar, client_id, monetization_active,
            limit=30, exclude_jamendo_ids=existing_ids,
        )
        if not new_tracks:
            new_tracks = _fetch_ccmixter_tracks(pillar, limit=10)

        added = 0
        for track in new_tracks[:count_per_pillar]:
            entry = _download_track(track, pillar, client_id, dry_run=dry_run)
            if entry and not dry_run:
                manifest["tracks"].append(entry)
                existing_ids.add(entry["jamendo_id"])
                added += 1

        # Remove old tracks
        if not dry_run:
            for old in to_remove[:added]:
                fp = os.path.join(_ROOT, old["file_path"])
                if os.path.exists(fp):
                    os.remove(fp)
                    log.info(f"  Removed: {old['file_path']}")
                manifest["tracks"] = [t for t in manifest["tracks"] if t["track_id"] != old["track_id"]]

            _save_manifest(manifest)

        summary["pillars"][pillar] = {"removed": len(to_remove[:added]), "added": added}
        summary["replaced"] += added

    return summary


def get_track_for_post(pillar: str | None, account: str) -> str | None:
    """
    Return path to a local MP3 suitable for the given pillar, not used in last
    NO_REPEAT_WINDOW posts. Falls back to any pillar if pillar is None or empty.

    Called by audio_selector.prepare_bgm when manual_audio_mode is False.
    Returns None if no tracks are available (triggers procedural BGM fallback).
    """
    manifest = _load_manifest()
    history  = _load_history(account)
    recently_used_files = {
        os.path.basename(h.get("filename", ""))
        for h in history[-NO_REPEAT_WINDOW:]
    }

    # Build candidate pool
    candidates = [
        t for t in manifest["tracks"]
        if (pillar is None or t["pillar"] == pillar)
        and os.path.exists(os.path.join(_ROOT, t["file_path"]))
        and os.path.basename(t["file_path"]) not in recently_used_files
    ]

    if not candidates and pillar is not None:
        # Widen to any pillar
        log.warning(f"No unused tracks for pillar={pillar}, widening to full library")
        candidates = [
            t for t in manifest["tracks"]
            if os.path.exists(os.path.join(_ROOT, t["file_path"]))
            and os.path.basename(t["file_path"]) not in recently_used_files
        ]

    if not candidates:
        # All tracks recently used — pick least-recently-used
        used_order = {os.path.basename(h.get("filename", "")): i for i, h in enumerate(history)}
        all_present = [
            t for t in manifest["tracks"]
            if os.path.exists(os.path.join(_ROOT, t["file_path"]))
        ]
        all_present.sort(key=lambda t: used_order.get(os.path.basename(t["file_path"]), -1))
        candidates = all_present[:5]

    if not candidates:
        # Library empty — check if bootstrap is needed
        _emergency_bootstrap_check(pillar, account)
        return None

    chosen = random.choice(candidates)
    track_path = os.path.join(_ROOT, chosen["file_path"])
    filename   = os.path.basename(track_path)

    # Update history
    history.append({"filename": filename, "used_at": datetime.now().isoformat(), "pillar": pillar})
    _save_history_data(account, history)

    log.info(f"  [AUDIO] Selected: {chosen['title']} ({chosen['artist_name']}) [{chosen['pillar']}]")
    return track_path


def _save_history_data(account: str, history: list) -> None:
    path = _audio_history_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history[-100:], f, indent=2)
    os.replace(tmp, path)


def _emergency_bootstrap_check(pillar: str | None, account: str) -> None:
    """Warn when a pillar has < 5 tracks — triggers on next run."""
    manifest = _load_manifest()
    p_count  = sum(1 for t in manifest["tracks"] if t["pillar"] == pillar)
    if p_count < 5:
        log.warning(
            f"LIBRARY WARNING: pillar={pillar} has only {p_count} tracks. "
            f"Run: python tools/audio_library_manager.py --bootstrap --pillar {pillar or 'all'}"
        )


def show_status(account: str) -> None:
    """Print library status to stdout."""
    manifest = _load_manifest()
    history  = _load_history(account)
    recently_used = {os.path.basename(h.get("filename", "")) for h in history[-NO_REPEAT_WINDOW:]}

    print(f"\nAudio Library Status — {_LIB_ROOT}")
    print(f"  Total tracks in manifest: {len(manifest['tracks'])}")
    print(f"  Last updated: {manifest.get('last_updated', 'never')}\n")

    for pillar in DEFAULT_PILLAR_TAGS:
        ptracks  = [t for t in manifest["tracks"] if t["pillar"] == pillar]
        present  = [t for t in ptracks if os.path.exists(os.path.join(_ROOT, t["file_path"]))]
        recent   = sum(1 for t in present if os.path.basename(t["file_path"]) in recently_used)
        available = len(present) - recent
        print(f"  {pillar:15s}  {len(present):2d} tracks  ({available} available, {recent} recently used)")

    print()


def _print_track_preview(entry: dict, raw: dict) -> None:
    """Pretty-print one track record during dry-run."""
    dur   = entry["duration"]
    m, s  = divmod(dur, 60)
    pref  = "[OK]" if raw.get("_in_preferred_range") else "[--]"
    lic   = entry["license_url"].split("/")[-2] if "/" in entry["license_url"] else entry["license_url"]
    print(
        f"    {pref} [{entry['pillar'][:10]:10s}] "
        f"{entry['title'][:40]:40s} | "
        f"{entry['artist_name'][:20]:20s} | "
        f"{m}m{s:02d}s | {lic}"
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DisciplineFuel audio library manager")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bootstrap", action="store_true", help="First-run library build")
    group.add_argument("--refresh",   action="store_true", help="Weekly library refresh")
    group.add_argument("--status",    action="store_true", help="Print library status")
    parser.add_argument("--account",  default="disciplinefuel")
    parser.add_argument("--pillar",   default=None, help="Limit bootstrap to one pillar")
    parser.add_argument("--dry-run",  action="store_true", help="Fetch metadata only, no downloads")
    args = parser.parse_args()

    cfg = {}
    cfg_path = os.path.join(_CFG_DIR, f"{args.account}.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)

    if args.bootstrap:
        result = bootstrap_library(args.account, cfg, dry_run=args.dry_run, only_pillar=args.pillar)
        if result.get("error"):
            sys.exit(1)
        if args.dry_run:
            print(f"\n[DRY RUN] Summary: {result['total_downloaded']} tracks would be downloaded")
            for p, info in result.get("pillars", {}).items():
                print(f"  {p}: {info}")
        else:
            print(f"\nBootstrap complete: {result['total_downloaded']} tracks downloaded")

    elif args.refresh:
        result = refresh_library(args.account, cfg, dry_run=args.dry_run)
        print(f"\nRefresh complete: {result.get('replaced', 0)} tracks replaced")

    elif args.status:
        show_status(args.account)
