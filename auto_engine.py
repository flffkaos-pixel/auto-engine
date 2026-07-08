"""
Full Auto Engine — Carousel + Content Pipeline
Runs both TikTok/IG posting AND blog publishing in one shot.
"""
import json, os, sys, logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("auto")

WORKDIR = Path(os.environ.get("AUTO_DIR", Path.home() / ".auto_engine"))
WORKDIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = WORKDIR / ".env"
CONFIG_FILE = WORKDIR / "config.json"

def load_env():
    p = ENV_FILE
    if not p.exists(): return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

def run_carousel():
    """carousel_engine.py --run"""
    script = Path(__file__).parent / "carousel_engine.py"
    if not script.exists():
        log.error("carousel_engine.py not found at %s", script)
        return False
    import subprocess
    r = subprocess.run([sys.executable, str(script), "--run"], capture_output=True, text=True, timeout=180)
    if r.stdout: log.info("Carousel: %s", r.stdout.strip()[-200:])
    if r.returncode != 0: log.warning("Carousel stderr: %s", r.stderr.strip()[-300:])
    return r.returncode == 0

def run_content():
    """content_pipeline.py --run-all"""
    script = Path(__file__).parent / "content_pipeline.py"
    if not script.exists():
        log.error("content_pipeline.py not found at %s", script)
        return False
    import subprocess
    r = subprocess.run([sys.executable, str(script), "--run-all"], capture_output=True, text=True, timeout=180)
    if r.stdout: log.info("Content: %s", r.stdout.strip()[-200:])
    if r.returncode != 0: log.warning("Content stderr: %s", r.stderr.strip()[-300:])
    return r.returncode == 0

def setup_wizard():
    print("=== Full Auto Engine Setup ===")
    print()

    # Carousel config
    url = input("Carousel — Target URL to promote: ").strip()
    gemini_key = input("Carousel — Gemini API key: ").strip()
    up_user = input("Carousel — Upload-Post username: ").strip()
    up_token = input("Carousel — Upload-Post API token: ").strip()

    print()
    # Content pipeline config
    topics = input("Content — Research topics (comma-separated): ").strip()
    ghost_url = input("Content — Ghost URL: ").strip()
    ghost_key = input("Content — Ghost Admin API key: ").strip()
    plausible_key = input("Content — Plausible API key (optional): ").strip()

    CAROUSEL_DIR = Path.home() / ".carousel"
    CAROUSEL_DIR.mkdir(parents=True, exist_ok=True)
    (CAROUSEL_DIR / "config.json").write_text(json.dumps({"url": url, "niche": "auto", "lang": "ko"}, ensure_ascii=False, indent=2), encoding="utf-8")

    PIPELINE_DIR = Path.home() / ".content_pipeline"
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    (PIPELINE_DIR / "config.json").write_text(json.dumps({"topics": [t.strip() for t in topics.split(",") if t.strip()]}, ensure_ascii=False, indent=2), encoding="utf-8")

    env = f"""GEMINI_API_KEY={gemini_key}
UPLOADPOST_USER={up_user}
UPLOADPOST_TOKEN={up_token}
GHOST_URL={ghost_url}
GHOST_ADMIN_API_KEY={ghost_key}
PLAUSIBLE_API_KEY={plausible_key}
CAROUSEL_DIR={CAROUSEL_DIR}
PIPELINE_DIR={PIPELINE_DIR}
"""
    ENV_FILE.write_text(env, encoding="utf-8")
    log.info("Setup complete. Configs at %s, %s", CAROUSEL_DIR, PIPELINE_DIR)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--carousel", action="store_true")
    parser.add_argument("--content", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    load_env()

    if args.setup:
        setup_wizard()
    else:
        if args.all or args.carousel:
            log.info("Running Carousel Engine...")
            run_carousel()
        if args.all or args.content:
            log.info("Running Content Pipeline...")
            run_content()
        log.info("Done at %s", datetime.now().isoformat())
