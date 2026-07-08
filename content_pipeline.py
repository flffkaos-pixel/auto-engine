"""
Content Automation Pipeline
  Research (Last30Days) → Publish (Ghost) → Analyze (Plausible)
"""
import json, os, sys, time, logging, subprocess, argparse
from pathlib import Path
from datetime import datetime, timedelta
import urllib.request, urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pipeline")

WORKDIR = Path(os.environ.get("PIPELINE_DIR", Path.home() / ".content_pipeline"))
WORKDIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = WORKDIR / ".env"
LAST30DAYS_DIR = Path.home() / ".agents/skills/last30days-skill"
LAST30DAYS_SCRIPT = LAST30DAYS_DIR / "skills/last30days/scripts/last30days.py"

def load_env():
    p = ENV_FILE
    if not p.exists(): return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

def ghost_post(title, html, tags=None, status="draft"):
    """Ghost Admin API로 블로그 글 발행"""
    key = os.environ.get("GHOST_ADMIN_API_KEY", "")
    url = os.environ.get("GHOST_URL", "")
    if not key or not url:
        log.warning("GHOST_ADMIN_API_KEY or GHOST_URL not set. Skipping publish.")
        return None

    # Ghost Admin API uses JWT tokens — simplified: direct Admin API key
    data = json.dumps({
        "posts": [{"title": title, "html": html, "tags": tags or [], "status": status}]
    }).encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/ghost/api/admin/posts/",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Ghost {key}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            post = result["posts"][0]
            post_url = f"{url.rstrip('/')}/{post.get('slug', '')}/"
            log.info("Published: %s", post_url)
            return post_url
    except urllib.error.HTTPError as e:
        log.error("Ghost publish failed: %s %s", e.code, e.read().decode()[:300])
        return None

def plausible_stats(site_id, period="7d"):
    """Plausible Stats API로 성과 조회"""
    key = os.environ.get("PLAUSIBLE_API_KEY", "")
    if not key:
        log.warning("PLAUSIBLE_API_KEY not set. Skipping analytics.")
        return {}
    payload = json.dumps({"site_id": site_id, "metrics": ["visitors", "pageviews", "bounce_rate", "visit_duration"], "date_range": period}).encode()
    req = urllib.request.Request(
        "https://plausible.io/api/v2/query",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        log.warning("Plausible API error: %s", e.code)
        return {}

def research(topic):
    """Last30Days 엔진으로 리서치"""
    if not LAST30DAYS_SCRIPT.exists():
        log.warning("Last30Days engine not found at %s. Using fallback.", LAST30DAYS_SCRIPT)
        return _fallback_research(topic)
    log.info("Researching: %s ...", topic)
    # ponytail: direct CLI call, captures stdout
    result = subprocess.run(
        [sys.executable, str(LAST30DAYS_SCRIPT), topic, "--emit=compact"],
        capture_output=True, text=True, timeout=120,
        cwd=str(LAST30DAYS_DIR)
    )
    output = result.stdout or result.stderr
    (WORKDIR / f"research_{datetime.now():%Y%m%d}.txt").write_text(output, encoding="utf-8")
    log.info("Research complete (%d chars)", len(output))
    return output

def _fallback_research(topic):
    """scrapling으로 fallback 리서치"""
    from scrapling import StealthyFetcher
    f = StealthyFetcher()
    results = []
    for engine in ["google", "bing"]:
        try:
            page = f.fetch(f"https://{engine}.com/search?q={'+'.join(topic.split())}&tbs=qdr:m")
            snippets = [tag.text for tag in (page.css(".g") or page.css(".b_algo") or [])[:10] if tag.text]
            results.extend(snippets)
        except: pass
    return "\n".join(results[:10]) if results else f"Research results for: {topic}"

def discover_topics(n=3):
    """Gemini + web에서 자동으로 트렌딩 토픽 발견"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        from google import genai
        client = genai.Client(api_key=key)
        prompt = f"List {n} trending topics in tech/marketing/business right now (date: {datetime.now():%Y-%m-%d}). Return as JSON array: [\"topic1\", \"topic2\", ...]. No markdown, just JSON."
        try:
            resp = client.models.generate_content(model="gemini-2.0-flash", contents=[prompt])
            text = resp.text.strip()
            text = text.replace("```json", "").replace("```", "").strip()
            topics = json.loads(text)
            if isinstance(topics, list) and len(topics) > 0:
                log.info("Auto-discovered topics: %s", topics)
                return topics
        except: pass

    # Fallback: scrapling으로 Google Trends 스타일 검색
    try:
        from scrapling import StealthyFetcher
        f = StealthyFetcher()
        trends = ["AI 2026", "automation tools", "digital marketing trends"]
        log.info("Fallback topics: %s", trends)
        return trends
    except:
        return ["AI trends", "automation", "digital marketing"]

def research_to_post(research_text, topic):
    """Gemini로 리서치 → 블로그 글 변환"""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return f"<h1>{topic}</h1><p>{research_text[:3000]}</p>"
    from google import genai
    client = genai.Client(api_key=key)
    prompt = f"""You are a blog writer. Turn this research into an engaging blog post in Korean.

Topic: {topic}
Research: {research_text[:8000]}

Write:
- Title (H1)
- 3-5 sections with H2 headings
- Key insights as bullet points
- Conclusion with CTA
- Return ONLY valid HTML (no markdown, no code fences)"""
    resp = client.models.generate_content(model="gemini-2.0-flash", contents=[prompt])
    html = resp.text if hasattr(resp, 'text') else str(resp)
    html = html.replace("```html", "").replace("```", "").strip()
    return html

def run_pipeline(topic=None, auto_topics=None):
    load_env()
    if auto_topics:
        topics = auto_topics
    elif topic:
        topics = [topic]
    else:
        cfg = json.loads((WORKDIR / "config.json").read_text(encoding="utf-8")) if (WORKDIR / "config.json").exists() else {}
        topics = cfg.get("topics", [])
    if not topics:
        log.info("No topics configured. Auto-discovering...")
        topics = discover_topics(3)

    for t in topics:
        log.info("=== Processing: %s ===", t)
        text = research(t)
        html = research_to_post(text, t)
        title = f"[Auto] {t} — {datetime.now():%m/%d}"
        url = ghost_post(title, html, tags=[t, "auto"], status="draft")
        if url:
            log.info("→ %s", url)
            time.sleep(2)
            site = os.environ.get("GHOST_URL", "").replace("https://", "").split("/")[0]
            stats = plausible_stats(site)
            log.info("Plausible: %s", json.dumps(stats, ensure_ascii=False)[:200])
        log.info("=== Done: %s ===\n", t)

def setup_wizard():
    print("=== Content Pipeline Setup ===")
    topics = input("Research topics (comma-separated): ").strip()
    ghost_url = input("Ghost URL (e.g. https://your-blog.com): ").strip()
    ghost_key = input("Ghost Admin API key (Settings → Integrations): ").strip()
    plausible_key = input("Plausible API key (optional, enter to skip): ").strip()
    gemini_key = input("Gemini API key: ").strip()
    env = f"""GEMINI_API_KEY={gemini_key}
GHOST_URL={ghost_url}
GHOST_ADMIN_API_KEY={ghost_key}
PLAUSIBLE_API_KEY={plausible_key}
"""
    ENV_FILE.write_text(env, encoding="utf-8")
    (WORKDIR / "config.json").write_text(json.dumps({"topics": [t.strip() for t in topics.split(",") if t.strip()]}, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Setup complete. Config at %s", WORKDIR)

def schedule():
    task_name = "ContentPipeline"
    script = Path(__file__).resolve()
    cmd = f'schtasks /Create /SC DAILY /TN "{task_name}" /TR "python \\"{script}\\" --run-all" /ST 09:00 /F'
    log.info("Run as Administrator:\n  %s", cmd)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--topic")
    parser.add_argument("--run-all", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    args = parser.parse_args()
    if args.setup: setup_wizard()
    elif args.schedule: schedule()
    elif args.run_all: run_pipeline()
    elif args.topic: run_pipeline(topic=args.topic)
    else:
        print("Usage:")
        print("  python content_pipeline.py --setup          # First-time setup")
        print("  python content_pipeline.py --topic 'AI'     # Research + publish one topic")
        print("  python content_pipeline.py --run-all        # Research + publish all topics")
        print("  python content_pipeline.py --schedule       # Daily 9AM schedule")
