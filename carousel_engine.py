"""Carousel Growth Engine — 자동 캐러셀 생성 + TikTok/Instagram 포스팅"""

import json, os, time, logging, argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("carousel")

WORKDIR = Path(os.environ.get("CAROUSEL_DIR", Path.home() / ".carousel"))
WORKDIR.mkdir(parents=True, exist_ok=True)

ENV_FILE = WORKDIR / ".env"
CONFIG_FILE = WORKDIR / "config.json"
LEARNINGS_FILE = WORKDIR / "learnings.json"
ANALYSIS_FILE = WORKDIR / "analysis.json"
POST_INFO_FILE = WORKDIR / "post-info.json"

def load_env():
    """Load .env file manually (no python-dotnet needed)"""
    path = ENV_FILE
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

def load_config():
    cfg = {"url": "", "niche": "auto", "lang": "ko"}
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    cfg["gemini_key"] = os.environ.get("GEMINI_API_KEY", "")
    cfg["uploadpost_token"] = os.environ.get("UPLOADPOST_TOKEN", "")
    cfg["uploadpost_user"] = os.environ.get("UPLOADPOST_USER", "")
    return cfg

def save_learnings(key, value):
    data = {}
    if LEARNINGS_FILE.exists():
        data = json.loads(LEARNINGS_FILE.read_text(encoding="utf-8"))
    data[key] = value
    data["_updated"] = datetime.now().isoformat()
    LEARNINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def step_analyze(url):
    """scrapling으로 URL 분석"""
    log.info("Analyzing %s ...", url)
    from scrapling import StealthyFetcher
    f = StealthyFetcher()
    page = f.fetch(url)
    text = page.text
    title = page.css("title").text.strip() if page.css("title") else url
    h1 = page.css("h1").text.strip() if page.css("h1") else ""
    meta_desc = page.css('meta[name="description"]').attribs.get("content", "")
    analysis = {
        "url": url,
        "title": title,
        "headline": h1,
        "description": meta_desc,
        "content_length": len(text),
        "analyzed_at": datetime.now().isoformat(),
    }
    ANALYSIS_FILE.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    save_learnings("last_analysis", analysis)
    log.info("Analysis saved: %s", title)
    return analysis

def step_generate(analysis):
    """Gemini API로 6장 슬라이드 생성"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        log.error("GEMINI_API_KEY not set. Get one at https://aistudio.google.com/app/apikey")
        return False

    from google import genai
    client = genai.Client(api_key=key)
    title = analysis.get("title", "Unknown")
    desc = analysis.get("description", "")
    headline = analysis.get("headline", "")

    # ponytail: 6-slide narrative, fixed structure — add variation via learnings later
    slides = [
        f"눈길을 끄는 질문: '{title}'에 대해 당신이 모르는 사실",
        f"문제점:许多人이 겪는 {title} 관련 어려움",
        f"왜 중요한가: 이 문제를 방치하면 생기는 일",
        f"해결책: {title}이 제공하는 가치",
        f"핵심 기능: {title}의 주요 장점들",
        f"지금 시작하세요: {title}로 변화를 경험하세요"
    ]
    if desc:
        slides[1] = f"문제점: {desc[:100]}"

    # ponytail: Gemini generate_content with image output. Falls back to text if model unavailable.
    prompt = f"""Create 6 vertical carousel slides (9:16, 768x1376) for a social media post about:
Title: {title}
Description: {desc}

Slide 1: Hook - grab attention with a bold question or stat
Slide 2: Problem - what pain point does this solve?
Slide 3: Agitation - why this problem matters
Slide 4: Solution - how {title} solves it
Slide 5: Features - key capabilities
Slide 6: CTA - call to action

Make each slide visually striking with clean typography.
Return 6 images in JPG format."""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=[prompt],
            config={"response_modalities": ["Text", "Image"]}
        )
        images_saved = 0
        for i, part in enumerate(response.candidates[0].content.parts):
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                ext = part.inline_data.mime_type.split("/")[-1]
                fpath = WORKDIR / f"slide-{images_saved+1}.{ext}"
                fpath.write_bytes(part.inline_data.data)
                images_saved += 1
                log.info("Slide %d saved: %s", images_saved, fpath.name)
        if images_saved == 0:
            log.warning("No images in response, saving text output")
            text_out = response.text if hasattr(response, 'text') else str(response)
            (WORKDIR / "response.txt").write_text(text_out, encoding="utf-8")
        return images_saved > 0
    except Exception as e:
        log.warning("Image generation failed: %s", e)
        log.info("Falling back to text-based slide content...")
        return _fallback_text_slides(title, desc, headline)

def _fallback_text_slides(title, desc, headline):
    """Gemini text-only fallback: generate slide copy"""
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""Write 6 short slide texts (max 80 chars each) for a TikTok carousel about:
Title: {title}
Description: {desc}
Headline: {headline}

Format: one line per slide, numbered 1-6.
Slide 1 = hook (attention grabber)
Slide 2 = problem
Slide 3 = why it matters
Slide 4 = solution
Slide 5 = features
Slide 6 = CTA"""
    resp = client.models.generate_content(model="gemini-2.0-flash", contents=[prompt])
    text = resp.text if hasattr(resp, 'text') else str(resp)
    (WORKDIR / "slide-texts.txt").write_text(text, encoding="utf-8")
    log.info("Slide texts generated (text mode):\n%s", text)
    return True

def step_publish():
    """Upload-Post API로 TikTok/Instagram 자동 업로드"""
    token = os.environ.get("UPLOADPOST_TOKEN", "")
    user = os.environ.get("UPLOADPOST_USER", "")
    if not token or not user:
        log.warning("UPLOADPOST_TOKEN or UPLOADPOST_USER not set. Sign up at https://upload-post.com")
        return False

    import requests
    slides = sorted(WORKDIR.glob("slide-*.*"))
    if not slides:
        log.error("No slide images found to publish")
        return False
    if len(slides) > 6:
        slides = slides[:6]

    files = [("photos[]", (s.name, s.read_bytes(), "image/jpeg")) for s in slides]
    data = {"platform[]": ["tiktok", "instagram"], "auto_add_music": "true", "privacy_level": "PUBLIC_TO_EVERYONE",
            "caption": f"Check this out! #fyp #viral #carousel", "async_upload": "true"}
    headers = {"Authorization": f"Bearer {token}", "X-User": user}

    try:
        resp = requests.post("https://api.upload-post.com/api/upload_photos", headers=headers, data=data, files=files, timeout=120)
        result = resp.json()
        POST_INFO_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
        log.info("Published! Response: %s", json.dumps(result, ensure_ascii=False)[:500])
        save_learnings("last_publish", {"time": datetime.now().isoformat(), "request_id": result.get("request_id", "")})
        return True
    except Exception as e:
        log.error("Publish failed: %s", e)
        return False

def step_analytics():
    """Upload-Post analytics 수집"""
    user = os.environ.get("UPLOADPOST_USER", "")
    token = os.environ.get("UPLOADPOST_TOKEN", "")
    if not user or not token:
        return
    import requests
    headers = {"Authorization": f"Bearer {token}", "X-User": user}
    try:
        resp = requests.get(f"https://api.upload-post.com/api/analytics/{user}?platforms=tiktok", headers=headers, timeout=30)
        data = resp.json()
        save_learnings("last_analytics", data)
        log.info("Analytics: %s", json.dumps(data, ensure_ascii=False)[:300])
    except Exception as e:
        log.warning("Analytics fetch failed: %s", e)

def run_once(url=None):
    """Full pipeline: analyze → generate → publish → analyze"""
    load_env()
    cfg = load_config()
    url = url or cfg.get("url", "")
    if not url:
        log.error("No URL. Set in %s or pass --url", CONFIG_FILE)
        return False

    analysis = step_analyze(url)
    ok = step_generate(analysis)
    if not ok:
        log.warning("Generation had issues, continuing...")
    pub_ok = step_publish()
    if pub_ok:
        time.sleep(5)
        step_analytics()
    log.info("Pipeline complete.")
    return True

def schedule_daily():
    """Windows Task Scheduler 등록 (하루 1회)"""
    script = Path(__file__).resolve()
    task_name = "CarouselGrowthEngine"
    cmd = f'schtasks /Create /SC DAILY /TN "{task_name}" /TR "python \\"{script}\\" --run" /ST 10:00 /F'
    log.info("Run this as Administrator to schedule daily:\n  %s", cmd)
    print(f"\nTo schedule: {cmd}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carousel Growth Engine")
    parser.add_argument("--run", action="store_true", help="Run full pipeline once")
    parser.add_argument("--url", help="Target URL (overrides config)")
    parser.add_argument("--schedule", action="store_true", help="Register daily task")
    parser.add_argument("--setup", action="store_true", help="Run setup wizard")
    args = parser.parse_args()

    if args.setup:
        print("=== Carousel Engine Setup ===")
        url = input("Target URL to promote: ").strip()
        key = input("Gemini API key (https://aistudio.google.com/app/apikey): ").strip()
        up_user = input("Upload-Post username (https://upload-post.com): ").strip()
        up_token = input("Upload-Post API token: ").strip()
        env_content = f"""GEMINI_API_KEY={key}
UPLOADPOST_USER={up_user}
UPLOADPOST_TOKEN={up_token}
"""
        ENV_FILE.write_text(env_content, encoding="utf-8")
        CONFIG_FILE.write_text(json.dumps({"url": url, "niche": "auto", "lang": "ko"}, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Setup complete. Config saved to %s", WORKDIR)
    elif args.schedule:
        schedule_daily()
    elif args.run or args.url:
        run_once(args.url)
    else:
        parser.print_help()
        print("\nQuick start: python carousel_engine.py --setup")
