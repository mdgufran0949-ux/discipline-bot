"""
run_original_pipeline.py
Orchestrates the full original content pipeline for any Instagram account.
Generates 100% original AI content: script → voice → visuals → video → upload.

Usage:
  python tools/run_original_pipeline.py --account factsflash --count 3
  python tools/run_original_pipeline.py --account factsflash --count 1 --dry-run

Steps per video:
  1. generate_niche_script.py   → .tmp/script.json
  2. generate_elevenlabs_tts.py → .tmp/voiceover.mp3 + .tmp/captions.srt
  3. fetch_broll_clips.py       → .tmp/broll_1.mp4 .. broll_3.mp4
  4. generate_visuals.py        → .tmp/scene_1.png .. scene_3.png
  5. compose_niche_video.py     → .tmp/output_reel.mp4
  6. upload_reel.py             → live on Instagram
"""

import argparse, datetime, json, os, subprocess, sys, time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOLS_DIR    = os.path.dirname(__file__)
CONFIG_DIR   = os.path.join(PROJECT_ROOT, "config", "accounts")
TMP          = os.path.join(PROJECT_ROOT, ".tmp")

sys.path.insert(0, TOOLS_DIR)
try:
    from daily_review import daily_review
    from account_memory import AccountMemory
except Exception:
    daily_review = None
    AccountMemory = None

# ElevenLabs voice IDs per account
ACCOUNT_VOICES = {
    "factsflash":      "pNInz6obpgDQGcFmaJgB",  # Adam
    "techmindblown":   "ErXwobaYiN019PkySvjV",  # Antoni
    "coresteelfitness":"VR6AewLTigWG4xSOukaG",  # Arnold
    "cricketcuts":     "TxGEqnHWrfWFTfGW9XjX",  # Josh
}
DEFAULT_VOICE    = "pNInz6obpgDQGcFmaJgB"
UPLOAD_PAUSE_SEC = 180  # 3 minutes between uploads (Instagram rate limit)


_QUESTION_WORDS   = {"what", "why", "how", "when", "where", "who", "did", "is", "are", "can", "do", "does"}
_IMPERATIVE_WORDS = {"stop", "start", "never", "always", "watch", "listen", "try", "don't", "remember"}


def _classify_hook(text: str) -> str:
    if not text:
        return ""
    t = text.strip().lower()
    first = t.split()[0] if t.split() else ""
    if "?" in t or first in _QUESTION_WORDS:
        return "question"
    if first in _IMPERATIVE_WORDS:
        return "imperative"
    if any(c.isdigit() for c in t[:40]) or any(w in t[:40] for w in ("fact", "did you know", "truth")):
        return "fact"
    return "story"


def _tool(name: str) -> str:
    return os.path.join(TOOLS_DIR, name)


def _load_config(account: str) -> dict:
    path = os.path.join(CONFIG_DIR, f"{account}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Account config not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _pick_caption(cfg: dict) -> str:
    templates = cfg.get("caption_templates")
    if templates and isinstance(templates, list) and len(templates) > 0:
        day_index = datetime.datetime.now().weekday()
        return templates[day_index % len(templates)]
    return cfg.get("caption_template", "")


def _run_step(label: str, cmd: list, extra_env: dict = None) -> bool:
    print(f"\n[{label}]", flush=True)
    env = None
    if extra_env:
        import copy
        env = copy.copy(os.environ)
        env.update(extra_env)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    if result.returncode != 0:
        print(f"  [FAIL] {label} exited with code {result.returncode}", flush=True)
        return False
    return True


def run_original_pipeline(account: str, count: int = 1, dry_run: bool = False) -> dict:
    cfg       = _load_config(account)
    page_name = cfg.get("ig_page_name", f"@{account}")
    voice_id  = cfg.get("elevenlabs_voice_id") or ACCOUNT_VOICES.get(account, DEFAULT_VOICE)

    print(f"\n{'='*55}", flush=True)
    print(f"  Original Pipeline | {page_name}", flush=True)
    print(f"  Target: {count} video(s) | Voice: {voice_id}", flush=True)
    if dry_run:
        print(f"  [DRY RUN] — will not upload", flush=True)
    print(f"{'='*55}", flush=True)

    # Step 0: Daily review (self-improvement loop)
    if daily_review is not None:
        try:
            print(f"\n[0/6 Daily Review]", flush=True)
            daily_review(account)
        except Exception as e:
            print(f"  [WARN] daily review failed: {e}", flush=True)

    memory = AccountMemory(account) if AccountMemory else None

    uploaded = 0
    failed   = 0

    for i in range(count):
        print(f"\n{'-'*55}", flush=True)
        print(f"  Video {i+1}/{count}", flush=True)
        print(f"{'-'*55}", flush=True)

        try:
            # Step 1: Generate script
            ok = _run_step("1/6 Script", [
                sys.executable, _tool("generate_niche_script.py"),
                "--account", account
            ])
            if not ok:
                failed += 1
                continue

            # Load narration for B-roll fetch
            script_path = os.path.join(TMP, "script.json")
            with open(script_path, encoding="utf-8") as f:
                script_data = json.load(f)
            narration = script_data.get("narration", "")

            # Step 2: Generate voiceover (ElevenLabs)
            ok = _run_step("2/6 Voiceover", [
                sys.executable, _tool("generate_elevenlabs_tts.py"),
                "--account", account,
                "--voice_id", voice_id,
            ])
            if not ok:
                failed += 1
                continue

            # Step 3: Fetch B-roll clips (3 clips from Pexels)
            ok = _run_step("3/6 B-roll", [
                sys.executable, _tool("fetch_broll_clips.py"),
                narration, "3"
            ])
            if not ok:
                print("  [WARN] B-roll fetch failed — continuing with AI images only", flush=True)

            # Step 4: Generate AI images (3 scenes via Pollinations.ai)
            ok = _run_step("4/6 AI Images", [
                sys.executable, _tool("generate_visuals.py"),
                script_path
            ])
            if not ok:
                print("  [WARN] AI image generation failed — continuing with B-roll only", flush=True)

            # Step 5: Compose video
            ok = _run_step("5/6 Compose", [
                sys.executable, _tool("compose_niche_video.py"),
                "--account", account,
                "--page",    page_name,
                "--output",  "output_reel.mp4",
            ])
            if not ok:
                failed += 1
                continue

            output_reel = os.path.join(TMP, "output_reel.mp4")
            if not os.path.exists(output_reel):
                print("  [FAIL] output_reel.mp4 not found after compose step", flush=True)
                failed += 1
                continue

            size_mb = os.path.getsize(output_reel) / 1024 / 1024
            print(f"  [OK] Video ready: {size_mb:.1f}MB", flush=True)

            # Step 6: Upload (unless dry-run)
            upload_result_path = os.path.join(TMP, "upload_result.json")
            if dry_run:
                print(f"\n  [DRY RUN] Skipping upload. Video saved at: {output_reel}", flush=True)
                uploaded += 1
                if memory:
                    memory.add_post({
                        "topic":          script_data.get("topic", ""),
                        "hook":           script_data.get("hook", ""),
                        "hook_type":      _classify_hook(script_data.get("hook", "")),
                        "caption":        script_data.get("caption", ""),
                        "scene_prompts":  [s.get("image_prompt", "") for s in script_data.get("scenes", [])],
                        "format":         "video",
                        "posted_at":      datetime.datetime.now().isoformat(),
                    })
            else:
                caption = script_data.get("caption") or _pick_caption(cfg)
                ok = _run_step("6/6 Upload", [
                    sys.executable, _tool("upload_reel.py"),
                    output_reel, caption,
                    "--out", upload_result_path,
                ], extra_env={
                    "IG_USER_ID":      cfg["ig_user_id"],
                    "IG_ACCESS_TOKEN": cfg["ig_access_token"],
                })
                if ok:
                    uploaded += 1
                    print(f"  [OK] Uploaded! ({uploaded}/{count})", flush=True)
                    # Log to memory
                    if memory:
                        ig_media_id = ""
                        if os.path.exists(upload_result_path):
                            try:
                                with open(upload_result_path, encoding="utf-8") as _f:
                                    ur = json.load(_f)
                                ig_media_id = ur.get("ig_media_id", "")
                            except Exception:
                                pass
                        memory.add_post({
                            "ig_media_id":   ig_media_id,
                            "topic":         script_data.get("topic", ""),
                            "hook":          script_data.get("hook", ""),
                            "hook_type":     _classify_hook(script_data.get("hook", "")),
                            "caption":       caption,
                            "scene_prompts": [s.get("image_prompt", "") for s in script_data.get("scenes", [])],
                            "format":        "video",
                            "posted_at":     datetime.datetime.now().isoformat(),
                        })
                    if i < count - 1:
                        print(f"  [WAIT] Pausing {UPLOAD_PAUSE_SEC}s before next upload...", flush=True)
                        time.sleep(UPLOAD_PAUSE_SEC)
                else:
                    failed += 1

        except Exception as e:
            print(f"  [ERROR] Video {i+1} failed: {e}", flush=True)
            failed += 1

    print(f"\n{'='*55}", flush=True)
    print(f"  [{account}] Done!", flush=True)
    print(f"  Uploaded : {uploaded}/{count}", flush=True)
    print(f"  Failed   : {failed}", flush=True)
    print(f"{'='*55}\n", flush=True)

    return {"account": account, "uploaded": uploaded, "failed": failed, "total": count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run original AI content pipeline")
    parser.add_argument("--account",  required=True,        help="Account name (e.g. factsflash)")
    parser.add_argument("--count",    default=1, type=int,  help="Number of videos to generate")
    parser.add_argument("--dry-run",  action="store_true",  help="Generate but do not upload")
    args = parser.parse_args()

    result = run_original_pipeline(args.account, args.count, args.dry_run)
    sys.exit(0 if result["failed"] == 0 else 1)
