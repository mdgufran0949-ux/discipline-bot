"""
audio_selector.py
Audio strategy for DisciplineFuel reels.

Set  manual_audio_mode: true  in disciplinefuel.json  -> Option B (default)
     manual_audio_mode: false                          -> Option A

Option A — rotating library
  Picks an mp3 from audio_library/, never reusing within NO_REPEAT_WINDOW posts.
  Copies the chosen file to .tmp/disciplinefuel/bgm.mp3 so compose_discipline_reel
  picks it up from its hardcoded path.
  Falls back to procedural BGM if library is empty or absent.

Option B — manual audio (default)
  Deletes .tmp/disciplinefuel/bgm.mp3 so compose_discipline_reel produces a
  silent video (anullsrc fallback).  After composition, call
  queue_for_manual_posting() to upload the silent video to Cloudinary and write
  a queue JSON to queue/pending_audio/.  The user downloads it, adds trending
  audio in the IG app, and posts manually.

Usage in run_discipline_pipeline.py:
    import audio_selector
    audio_selector.prepare_bgm(account, cfg)        # must call before compose
    ...compose...
    if cfg.get("manual_audio_mode", True):
        info = audio_selector.queue_for_manual_posting(video_path, meta, account)
        # skip IG upload, log queue_id instead
"""

import json
import os
import shutil
from datetime import datetime

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

_TOOLS_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT       = os.path.abspath(os.path.join(_TOOLS_DIR, ".."))
_AUDIO_LIB  = os.path.join(_ROOT, "audio_library")
_QUEUE_DIR  = os.path.join(_ROOT, "queue", "pending_audio")
_TMP_BASE   = os.path.join(_ROOT, ".tmp")

NO_REPEAT_WINDOW = 10   # never reuse same audio file within this many posts


# ── Cloudinary init (shared creds from .env) ────────────────────────────────

def _init_cloudinary() -> None:
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    )


# ── Audio history helpers ────────────────────────────────────────────────────

def _history_path(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "audio_history.json")


def _load_history(account: str) -> list:
    path = _history_path(account)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(account: str, history: list) -> None:
    path = _history_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history[-100:], f, indent=2)
    os.replace(tmp, path)


# ── BGM path used by compose_discipline_reel ────────────────────────────────

def _bgm_target(account: str) -> str:
    return os.path.join(_TMP_BASE, account, "bgm.mp3")


# ── Main interface ───────────────────────────────────────────────────────────

def prepare_bgm(account: str, cfg: dict, pillar: str = None) -> bool:
    """
    Prepare .tmp/<account>/bgm.mp3 before calling compose_discipline_reel.

    Returns True  if audio was placed at bgm.mp3 (Option A or procedural fallback).
    Returns False if manual mode is active (bgm.mp3 removed -> silent reel).

    This is the only function run_discipline_pipeline.py needs to call before composing.
    """
    manual_mode = cfg.get("manual_audio_mode", True)
    bgm_path    = _bgm_target(account)

    if manual_mode:
        # Option B: ensure no bgm so compose produces silent video
        if os.path.exists(bgm_path):
            os.remove(bgm_path)
        print("  [AUDIO] Manual mode — composing silent reel for manual IG posting", flush=True)
        return False

    # Option A: pick from managed Jamendo library (with pillar awareness)
    chosen_src = _pick_managed(account, pillar)
    if chosen_src:
        shutil.copy2(chosen_src, bgm_path)
        print(f"  [AUDIO] Library track -> {os.path.basename(chosen_src)}", flush=True)
        return True

    # Fallback: flat audio_library/ scan (legacy / pre-manager files)
    chosen_src = _pick_from_library(account)
    if chosen_src:
        shutil.copy2(chosen_src, bgm_path)
        print(f"  [AUDIO] Flat library track -> {os.path.basename(chosen_src)}", flush=True)
        return True

    # Final fallback: procedural BGM (no caching — generate fresh each time)
    print("  [AUDIO] No library tracks — falling back to procedural BGM", flush=True)
    _generate_procedural(bgm_path)
    return True


def _pick_managed(account: str, pillar: str | None) -> str | None:
    """Delegate to audio_library_manager when manifest.json exists."""
    manifest = os.path.join(_AUDIO_LIB, "manifest.json")
    if not os.path.exists(manifest):
        return None
    try:
        import audio_library_manager as alm
        return alm.get_track_for_post(pillar, account)
    except Exception as exc:
        print(f"  [AUDIO] Library manager error: {exc} — falling back to flat scan", flush=True)
        return None


def _pick_from_library(account: str) -> str | None:
    """Return path of a not-recently-used audio file, or None if library is empty."""
    if not os.path.isdir(_AUDIO_LIB):
        return None
    available = sorted(
        f for f in os.listdir(_AUDIO_LIB)
        if f.lower().endswith((".mp3", ".m4a", ".wav", ".aac"))
    )
    if not available:
        return None

    history        = _load_history(account)
    recently_used  = {h["filename"] for h in history[-NO_REPEAT_WINDOW:]}
    candidates     = [f for f in available if f not in recently_used]

    if not candidates:
        # All tracks used recently — pick least-recently used
        used_order = {h["filename"]: i for i, h in enumerate(history)}
        candidates = sorted(available, key=lambda f: used_order.get(f, -1))

    chosen = candidates[0]
    history.append({"filename": chosen, "used_at": datetime.now().isoformat()})
    _save_history(account, history)
    return os.path.join(_AUDIO_LIB, chosen)


def _generate_procedural(bgm_path: str) -> None:
    import sys
    sys.path.insert(0, _TOOLS_DIR)
    import generate_discipline_bgm as bgm_tool
    bgm_tool.generate_bgm(output_path=bgm_path)


# ── Queue management (Option B only) ────────────────────────────────────────

def queue_for_manual_posting(video_path: str, metadata: dict, account: str) -> dict:
    """
    Upload silent video to Cloudinary (permanent, not deleted after use), write a
    queue JSON to queue/pending_audio/, and print posting instructions.

    Returns a dict with queue_id and cloudinary_url for the pipeline to log.

    metadata should contain: caption, hashtags, pillar, hook_template, series_label,
                              target_post_time (ISO string).
    """
    _init_cloudinary()
    os.makedirs(_QUEUE_DIR, exist_ok=True)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    queue_id = f"{account}_{ts}"

    # Upload to Cloudinary — keep it; user needs to download it
    print(f"  [QUEUE] Uploading silent reel to Cloudinary...", flush=True)
    try:
        result    = cloudinary.uploader.upload(
            video_path,
            public_id=f"queue/{queue_id}",
            resource_type="video",
            overwrite=True,
        )
        video_url = result.get("secure_url", "")
    except Exception as e:
        print(f"  [QUEUE] Cloudinary upload failed: {e}", flush=True)
        video_url = ""

    # Write queue JSON (committed back to repo by GitHub Actions)
    queue_entry = {
        "queue_id":      queue_id,
        "account":       account,
        "cloudinary_url": video_url,
        "queued_at":     datetime.now().isoformat(),
        "status":        "pending",          # update to "posted" after manual posting
        **metadata,
    }
    meta_path = os.path.join(_QUEUE_DIR, f"{queue_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(queue_entry, f, indent=2, ensure_ascii=False)

    _print_posting_instructions(queue_entry)
    return queue_entry


def _print_posting_instructions(entry: dict) -> None:
    print("\n" + "=" * 55, flush=True)
    print("  MANUAL POSTING REQUIRED", flush=True)
    print("=" * 55, flush=True)
    print(f"  Queue ID : {entry['queue_id']}", flush=True)
    if entry.get("cloudinary_url"):
        print(f"  Video    : {entry['cloudinary_url']}", flush=True)
    print(f"  Target   : {entry.get('target_post_time', 'ASAP')}", flush=True)
    print(f"  Caption  : {str(entry.get('caption',''))[:80]}...", flush=True)
    print(f"  Steps    :", flush=True)
    print(f"    1. Download video from URL above", flush=True)
    print(f"    2. Open Instagram app -> New Reel -> select video", flush=True)
    print(f"    3. Tap 'Add audio' -> search trending sound", flush=True)
    print(f"    4. Paste caption from queue/{entry['queue_id']}.json", flush=True)
    print(f"    5. Post", flush=True)
    print("=" * 55 + "\n", flush=True)


# ── Library management helper ────────────────────────────────────────────────

def show_library_status(account: str) -> None:
    """Print current library status. Run manually to check what audio files are available."""
    os.makedirs(_AUDIO_LIB, exist_ok=True)
    files   = sorted(f for f in os.listdir(_AUDIO_LIB) if f.lower().endswith((".mp3", ".m4a", ".wav", ".aac")))
    history = _load_history(account)
    recent  = {h["filename"] for h in history[-NO_REPEAT_WINDOW:]}

    print(f"\nAudio Library — {_AUDIO_LIB}")
    print(f"  {len(files)} files total, {len(recent)} used in last {NO_REPEAT_WINDOW} posts\n")
    for f in files:
        tag = " [recently used]" if f in recent else ""
        print(f"  {'X' if f in recent else 'OK'}  {f}{tag}")
    if not files:
        print("  (empty — drop mp3/m4a files here to enable Option A)")
    print(f"\nAdd files: drop .mp3/.m4a into {_AUDIO_LIB}/")
    print("Sources: Pixabay Music, Free Music Archive, Bensound (attribution-free)\n")


def show_queue_status() -> None:
    """Print pending manual posts."""
    if not os.path.isdir(_QUEUE_DIR):
        print("No queue directory yet.")
        return
    items = sorted(f for f in os.listdir(_QUEUE_DIR) if f.endswith(".json"))
    pending = []
    for fn in items:
        try:
            with open(os.path.join(_QUEUE_DIR, fn), "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("status") == "pending":
                pending.append(d)
        except Exception:
            pass
    print(f"\nPending manual posts: {len(pending)}")
    for d in pending:
        print(f"  [{d['queued_at'][:16]}] {d['queue_id']}")
        if d.get("cloudinary_url"):
            print(f"    Video: {d['cloudinary_url']}")
        print(f"    Caption: {str(d.get('caption',''))[:60]}...")
    print()


if __name__ == "__main__":
    import sys
    account = sys.argv[1] if len(sys.argv) > 1 else "disciplinefuel"
    show_library_status(account)
    show_queue_status()
