#!/usr/bin/env python3
"""
配信後にエピソードをWebページとして出力し、GitHub Pagesにpushするスクリプト。

使い方:
  python export_episode.py              # 今日の配信を処理
  python export_episode.py 2026-05-08   # 指定日を処理
  python export_episode.py --no-push    # HTML生成のみ（git pushしない）
"""
import json
import os
import sys
import re
import base64
import subprocess
from datetime import datetime
from html import escape

import ollama

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EPISODES_DIR = os.path.join(BASE_DIR, "episodes")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
MODEL_NAME = "gemma4:e4b"


def load_events(date_str):
    path = os.path.join(EPISODES_DIR, f"{date_str}.jsonl")
    if not os.path.exists(path):
        print(f"エラー: {path} が見つかりません")
        sys.exit(1)
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def generate_novel_and_title(events, date_str):
    lines = []
    for ev in events:
        if ev["type"] == "intro":
            lines.append(f"[物語の始まり] {ev.get('text', '')}")
        elif ev["type"] == "comment":
            lines.append(f"[視聴者の指示: {ev.get('message', '')}] アリアの行動: {ev.get('reply', '')}")
        elif ev["type"] == "auto":
            lines.append(f"[アリアの自律行動] {ev.get('reply', '')}")

    timeline_text = "\n".join(lines)

    prompt = f"""以下はファンタジー冒険者アリアの今回の配信での出来事です。

{timeline_text}

これをもとに、以下のJSON形式で出力してください。余計な文字は一切含めず、JSONのみを返してください。

{{
  "title": "（この回の冒険を一言で表すタイトル、15文字以内）",
  "novel": "（ノベル形式のあらすじ。読みやすい文章で600〜900文字程度。段落は空行で区切る）"
}}"""

    response = ollama.chat(model=MODEL_NAME, messages=[
        {"role": "user", "content": prompt}
    ])
    raw = response["message"]["content"].strip()

    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        return data.get("title", f"冒険 {date_str}"), data.get("novel", "")
    except Exception:
        print(f"⚠️ JSON解析失敗、テキストをそのまま使用します")
        first_line = raw.splitlines()[0] if raw else f"冒険"
        return first_line[:15], raw


def save_images(events, ep_dir):
    enriched = []
    for i, ev in enumerate(events):
        ev = dict(ev)
        b64 = ev.pop("image_b64", None)
        if b64:
            fname = f"img_{i:03d}.jpg"
            with open(os.path.join(ep_dir, fname), "wb") as f:
                f.write(base64.b64decode(b64))
            ev["image_file"] = fname
        else:
            ev["image_file"] = None
        enriched.append(ev)
    return enriched


def fmt_time(ts_str):
    try:
        return datetime.fromisoformat(ts_str).strftime("%H:%M")
    except Exception:
        return ""


def novel_to_html(text):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    return "\n".join(f"<p>{escape(p)}</p>" for p in paragraphs)


def build_episode_html(date_str, title, novel_text, events):
    items = []
    for ev in events:
        ev_type = ev["type"]
        img = ev.get("image_file")
        time_str = fmt_time(ev.get("timestamp", ""))

        if img:
            img_html = f'<div class="event-image"><img src="{img}" alt="" loading="lazy"></div>'
        else:
            img_html = '<div class="event-no-image">✦</div>'

        if ev_type == "intro":
            body = f'''<div class="event-body">
  <div class="event-label">物語の始まり</div>
  <div class="event-reply">{escape(ev.get("text", ""))}</div>
  <div class="event-time">{time_str}</div>
</div>'''
        elif ev_type == "comment":
            body = f'''<div class="event-body">
  <div class="event-comment"><span class="commenter">@{escape(ev.get("username", ""))}：</span>{escape(ev.get("message", ""))}</div>
  <div class="event-reply">{escape(ev.get("reply", ""))}</div>
  <div class="event-time">{time_str}</div>
</div>'''
        elif ev_type == "auto":
            body = f'''<div class="event-body">
  <div class="event-label">アリアの自律行動</div>
  <div class="event-reply">{escape(ev.get("reply", ""))}</div>
  <div class="event-time">{time_str}</div>
</div>'''
        else:
            continue

        items.append(f'<div class="event">{img_html}{body}</div>')

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} — アリアの冒険記録</title>
  <link rel="stylesheet" href="../../assets/style.css">
</head>
<body>
  <nav>
    <div class="nav-inner">
      <span class="nav-logo">⚔ アリアの冒険記録</span>
      <div class="nav-links">
        <a href="../../" class="nav-link">← エピソード一覧</a>
      </div>
    </div>
  </nav>
  <header class="ep-header">
    <a class="back-link" href="../../">← エピソード一覧に戻る</a>
    <h1>{escape(title)}</h1>
    <div class="page-date">{date_str}</div>
  </header>
  <main class="ep-main">
    <section class="ep-section">
      <h2>あらすじ</h2>
      <div class="novel-text">{novel_to_html(novel_text)}</div>
    </section>
    <section class="ep-section">
      <h2>タイムライン</h2>
      <div class="timeline">{"".join(items)}</div>
    </section>
  </main>
</body>
</html>'''


def collect_all_episodes():
    ep_root = os.path.join(DOCS_DIR, "episodes")
    if not os.path.exists(ep_root):
        return []

    episodes = []
    for name in sorted(os.listdir(ep_root), reverse=True):
        ep_dir = os.path.join(ep_root, name)
        if not os.path.isdir(ep_dir):
            continue

        meta_path = os.path.join(ep_dir, "meta.json")
        title, event_count = name, 0
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            title = meta.get("title", name)
            event_count = meta.get("event_count", 0)

        imgs = sorted(f for f in os.listdir(ep_dir) if f.endswith(".jpg"))
        thumb = imgs[0] if imgs else None
        episodes.append((name, title, thumb, event_count))

    return episodes


def build_index_html(episodes):
    cards = []
    for date_str, title, thumb, count in episodes:
        if thumb:
            img_tag = f'<img src="episodes/{date_str}/{thumb}" alt="" loading="lazy">'
        else:
            img_tag = '<div class="card-thumb-placeholder">✦</div>'

        cards.append(f'''<a href="episodes/{date_str}/index.html" class="episode-card">
  {img_tag}
  <div class="card-info">
    <div class="card-date">{date_str}</div>
    <div class="card-title">{escape(title)}</div>
    <div class="card-count">{count}シーン</div>
  </div>
</a>''')

    grid = '\n'.join(cards) if cards else '<div class="no-episodes">まだエピソードがありません。配信後に更新されます。</div>'

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>アリアの冒険記録 — リスナーと紡ぐリアルタイムファンタジー</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>

  <nav>
    <div class="nav-inner">
      <span class="nav-logo">⚔ アリアの冒険記録</span>
      <div class="nav-links">
        <a href="#about" class="nav-link">このコンテンツについて</a>
        <a href="#character" class="nav-link">キャラクター</a>
        <a href="#episodes" class="nav-link">エピソード</a>
      </div>
    </div>
  </nav>

  <section class="hero">
    <div class="hero-bg"></div>
    <div class="hero-grid-overlay"></div>
    <div class="hero-content">
      <div class="hero-badge">LIVE × AI × FANTASY</div>
      <h1 class="hero-title"><span>アリア</span>の<br>冒険記録</h1>
      <p class="hero-lead">
        リスナーの指示が物語を動かす。<br>
        ローカルAIがリアルタイムでシナリオと画像を生成する、<br>
        参加型インタラクティブファンタジー配信。
      </p>
      <div class="hero-actions">
        <a href="#episodes" class="btn-primary">冒険を読む</a>
        <a href="https://twitch.tv/nakamu1770" target="_blank" rel="noopener" class="btn-secondary">Twitchで観る</a>
      </div>
    </div>
  </section>

  <section class="concept" id="about">
    <div class="inner">
      <h2 class="section-title">このコンテンツについて</h2>
      <p class="section-sub">配信はリスナー全員が参加できるインタラクティブな体験です</p>
      <div class="concept-grid">
        <div class="concept-card">
          <div class="concept-icon">💬</div>
          <div class="concept-head">リスナーが物語を操る</div>
          <p>配信中に「@〇〇して」とコメントすると、それがアリアへの行動指示になります。あなたの言葉が物語を変えます。</p>
        </div>
        <div class="concept-card">
          <div class="concept-icon">🤖</div>
          <div class="concept-head">AIがリアルタイム生成</div>
          <p>ローカルLLM（Gemma4）がアリアの返答と場面描写を即座に生成。毎回まったく異なる物語が生まれます。</p>
        </div>
        <div class="concept-card">
          <div class="concept-icon">🎨</div>
          <div class="concept-head">画像も自動生成</div>
          <p>Stable Diffusionがシーンに合わせた背景画像をリアルタイム生成。アリアの冒険が映像として展開されます。</p>
        </div>
        <div class="concept-card">
          <div class="concept-icon">📖</div>
          <div class="concept-head">配信後はノベルで読める</div>
          <p>各配信終了後、その回の物語がAIによってノベル形式にまとめられ、このサイトで閲覧できます。</p>
        </div>
      </div>
    </div>
  </section>

  <section class="character" id="character">
    <div class="inner">
      <h2 class="section-title">主人公：アリア</h2>
      <p class="section-sub">エルドリア大陸を旅する銀髪の冒険者</p>
      <div class="char-layout">
        <div class="char-img-box">⚔</div>
        <div>
          <div class="char-name">アリア</div>
          <div class="char-subtitle">20歳 ／ 銀髪・革鎧の女性冒険者</div>
          <div class="char-stats">
            <div class="char-stat">
              <div class="char-stat-label">所属</div>
              <div class="char-stat-value">冒険者ギルド（王都レギオス）</div>
            </div>
            <div class="char-stat">
              <div class="char-stat-label">世界</div>
              <div class="char-stat-value">エルドリア大陸</div>
            </div>
            <div class="char-stat">
              <div class="char-stat-label">故郷</div>
              <div class="char-stat-value">ハルン村（東部農村）</div>
            </div>
            <div class="char-stat">
              <div class="char-stat-label">武装</div>
              <div class="char-stat-value">剣・魔法</div>
            </div>
          </div>
          <p class="char-desc">
            故郷ハルン村を飛び出し、冒険の夢を胸に王都レギオスへたどり着いた若き女性冒険者。
            直感と行動力で数々の試練を乗り越えてきた。<br>
            この世界は魔法と剣が共存し、各地に古代文明の遺跡が眠る中世風ファンタジー大陸——
            今日もリスナーの声に従い、未知の物語へと踏み出していく。
          </p>
          <div class="char-tags">
            <span class="tag">勇敢</span>
            <span class="tag">好奇心旺盛</span>
            <span class="tag">義理堅い</span>
            <span class="tag">銀髪・革鎧</span>
            <span class="tag">AI生成キャラクター</span>
          </div>
        </div>
      </div>
    </div>
  </section>

  <section class="episodes-section" id="episodes">
    <div class="inner">
      <h2 class="section-title">冒険の記録</h2>
      <p class="section-sub">全{len(episodes)}エピソード — タイムラインとAI生成のあらすじを収録</p>
      <div class="episode-grid">{grid}</div>
    </div>
  </section>

  <footer>
    <div class="footer-inner">
      <span class="footer-logo">⚔ アリアの冒険記録</span>
      <div class="footer-links">
        <a href="https://twitch.tv/nakamu1770" target="_blank" rel="noopener" class="footer-link">Twitch</a>
      </div>
      <span class="footer-copy">AI生成コンテンツ — Gemma4 × Stable Diffusion</span>
    </div>
  </footer>

</body>
</html>'''


CSS = """\
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --surface2: #1c2128;
  --border: #30363d;
  --text: #e6edf3;
  --text-muted: #8b949e;
  --accent: #e3b341;
  --accent-dim: rgba(227,179,65,0.15);
  --accent2: #a371f7;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', 'Meiryo', sans-serif; line-height: 1.7; }
nav { position: sticky; top: 0; z-index: 100; background: rgba(13,17,23,0.92); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border); }
.nav-inner { max-width: 1100px; margin: 0 auto; padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; }
.nav-logo { font-size: 1rem; color: var(--accent); font-weight: bold; letter-spacing: 0.04em; }
.nav-links { display: flex; gap: 24px; }
.nav-link { color: var(--text-muted); text-decoration: none; font-size: 0.9rem; transition: color 0.2s; }
.nav-link:hover { color: var(--accent); }
.hero { position: relative; min-height: 520px; display: flex; align-items: center; overflow: hidden; border-bottom: 1px solid var(--border); }
.hero-bg { position: absolute; inset: 0; background: radial-gradient(ellipse 80% 60% at 60% 40%, rgba(163,113,247,0.12) 0%, transparent 70%), radial-gradient(ellipse 50% 80% at 20% 80%, rgba(227,179,65,0.08) 0%, transparent 60%), var(--bg); }
.hero-grid-overlay { position: absolute; inset: 0; background-image: linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px); background-size: 60px 60px; opacity: 0.15; }
.hero-content { position: relative; max-width: 1100px; margin: 0 auto; padding: 72px 24px; }
.hero-badge { display: inline-block; background: var(--accent-dim); border: 1px solid rgba(227,179,65,0.4); color: var(--accent); font-size: 0.75rem; letter-spacing: 0.15em; padding: 4px 12px; border-radius: 999px; margin-bottom: 20px; }
.hero-title { font-size: clamp(2.4rem, 6vw, 4rem); color: var(--text); line-height: 1.2; margin-bottom: 20px; }
.hero-title span { color: var(--accent); }
.hero-lead { font-size: clamp(1rem, 2vw, 1.2rem); color: var(--text-muted); max-width: 480px; margin-bottom: 36px; line-height: 1.8; }
.hero-actions { display: flex; gap: 16px; flex-wrap: wrap; }
.btn-primary { display: inline-block; background: var(--accent); color: #0d1117; font-weight: bold; font-size: 0.95rem; padding: 12px 28px; border-radius: 6px; text-decoration: none; transition: opacity 0.2s; }
.btn-primary:hover { opacity: 0.85; }
.btn-secondary { display: inline-block; border: 1px solid var(--border); color: var(--text-muted); font-size: 0.95rem; padding: 12px 28px; border-radius: 6px; text-decoration: none; transition: border-color 0.2s, color 0.2s; }
.btn-secondary:hover { border-color: var(--accent); color: var(--accent); }
.inner { max-width: 1100px; margin: 0 auto; padding: 64px 24px; }
.section-title { font-size: 1.4rem; color: var(--accent); margin-bottom: 8px; }
.section-sub { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 32px; }
.concept { background: var(--surface); border-bottom: 1px solid var(--border); }
.concept-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px; margin-top: 32px; }
.concept-card { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 24px; transition: border-color 0.2s; }
.concept-card:hover { border-color: rgba(227,179,65,0.4); }
.concept-icon { font-size: 2rem; margin-bottom: 12px; }
.concept-head { font-size: 1rem; color: var(--text); font-weight: bold; margin-bottom: 8px; }
.concept-card p { color: var(--text-muted); font-size: 0.9rem; line-height: 1.7; }
.character { border-bottom: 1px solid var(--border); }
.char-layout { display: grid; grid-template-columns: 280px 1fr; gap: 40px; align-items: start; margin-top: 32px; }
.char-img-box { border-radius: 8px; overflow: hidden; border: 1px solid var(--border); background: #1a1a2e; aspect-ratio: 2/3; display: flex; align-items: center; justify-content: center; color: var(--accent); font-size: 3rem; }
.char-img-box img { width: 100%; height: 100%; object-fit: cover; display: block; }
.char-name { font-size: 2rem; color: var(--accent); font-weight: bold; margin-bottom: 4px; }
.char-subtitle { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 20px; }
.char-desc { color: var(--text); line-height: 1.8; margin-bottom: 20px; }
.char-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.tag { background: var(--accent-dim); border: 1px solid rgba(227,179,65,0.3); color: var(--accent); font-size: 0.8rem; padding: 3px 10px; border-radius: 999px; }
.char-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 20px; }
.char-stat { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; }
.char-stat-label { font-size: 0.7rem; color: var(--text-muted); letter-spacing: 0.08em; text-transform: uppercase; }
.char-stat-value { font-size: 0.95rem; color: var(--text); margin-top: 2px; }
.episodes-section { background: var(--surface); border-bottom: 1px solid var(--border); }
.episode-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px; margin-top: 32px; }
.episode-card { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; text-decoration: none; color: var(--text); transition: border-color 0.2s, transform 0.2s; display: block; }
.episode-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.episode-card img { width: 100%; height: 160px; object-fit: cover; display: block; background: #222; }
.card-thumb-placeholder { width: 100%; height: 160px; background: #1a1a2e; display: flex; align-items: center; justify-content: center; color: var(--accent); font-size: 2rem; }
.card-info { padding: 12px 16px; }
.card-date { color: var(--text-muted); font-size: 0.8rem; }
.card-title { font-size: 1rem; margin-top: 4px; color: var(--accent); }
.card-count { color: var(--text-muted); font-size: 0.8rem; margin-top: 4px; }
.no-episodes { text-align: center; padding: 48px 24px; color: var(--text-muted); border: 1px dashed var(--border); border-radius: 8px; }
footer { border-top: 1px solid var(--border); }
.footer-inner { max-width: 1100px; margin: 0 auto; padding: 32px 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.footer-logo { color: var(--accent); font-weight: bold; font-size: 0.95rem; }
.footer-links { display: flex; gap: 20px; }
.footer-link { color: var(--text-muted); text-decoration: none; font-size: 0.85rem; transition: color 0.2s; }
.footer-link:hover { color: var(--accent); }
.footer-copy { color: var(--text-muted); font-size: 0.8rem; }
.ep-header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 24px 32px; }
.ep-header h1 { font-size: 1.6rem; color: var(--accent); }
.back-link { color: var(--text-muted); text-decoration: none; font-size: 0.9rem; display: inline-block; margin-bottom: 8px; transition: color 0.2s; }
.back-link:hover { color: var(--text); }
.page-date { color: var(--text-muted); font-size: 0.9rem; margin-top: 4px; }
.ep-main { max-width: 1100px; margin: 0 auto; padding: 32px 16px; }
.ep-section { margin-bottom: 48px; }
.ep-section h2 { font-size: 1.2rem; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 20px; }
.novel-text p { margin-bottom: 1em; }
.timeline { display: flex; flex-direction: column; gap: 20px; }
.event { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; display: flex; }
.event-image { width: 240px; flex-shrink: 0; }
.event-image img { width: 100%; height: 100%; object-fit: cover; display: block; }
.event-no-image { width: 240px; flex-shrink: 0; background: #1a1a2e; display: flex; align-items: center; justify-content: center; color: var(--accent); font-size: 2rem; }
.event-body { padding: 16px 20px; flex: 1; }
.event-label { font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
.event-comment { background: rgba(227,179,65,0.08); border-left: 3px solid var(--accent); padding: 8px 12px; border-radius: 4px; margin-bottom: 10px; font-size: 0.9rem; }
.commenter { color: var(--accent); font-weight: bold; }
.event-reply { font-size: 1rem; line-height: 1.6; }
.event-time { color: var(--text-muted); font-size: 0.75rem; margin-top: 8px; }
@media (max-width: 700px) {
  .char-layout { grid-template-columns: 1fr; }
  .char-img-box { aspect-ratio: 3/2; }
  .hero-title { font-size: 2rem; }
  .event { flex-direction: column; }
  .event-image, .event-no-image { width: 100%; height: 180px; }
  .footer-inner { flex-direction: column; align-items: flex-start; }
  .nav-links { gap: 14px; }
}
"""


def git_push(date_str):
    try:
        subprocess.run(["git", "add", "docs/", "episodes/"], check=True, cwd=BASE_DIR)
        subprocess.run(["git", "commit", "-m", f"Add episode {date_str}"], check=True, cwd=BASE_DIR)
        subprocess.run(["git", "push"], check=True, cwd=BASE_DIR)
        print("✅ GitHub Pagesにpushしました")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ git操作に失敗: {e}")
        print("手動で以下を実行してください:")
        print("  git add docs/ episodes/")
        print(f"  git commit -m 'Add episode {date_str}'")
        print("  git push")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_push = "--no-push" in sys.argv

    date_str = args[0] if args else datetime.now().strftime("%Y-%m-%d")

    print(f"📅 エピソード {date_str} を処理中...")
    events = load_events(date_str)
    print(f"  {len(events)}件のイベントを読み込みました")

    ep_dir = os.path.join(DOCS_DIR, "episodes", date_str)
    os.makedirs(ep_dir, exist_ok=True)
    os.makedirs(os.path.join(DOCS_DIR, "assets"), exist_ok=True)

    print("🖼️  画像を保存中...")
    enriched = save_images(events, ep_dir)

    print("📝 ノベルを生成中（Ollama）...")
    title, novel_text = generate_novel_and_title(events, date_str)
    print(f"  タイトル: {title}")

    scene_count = len([e for e in events if e["type"] in ("comment", "intro", "auto")])
    with open(os.path.join(ep_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"title": title, "date": date_str, "event_count": scene_count}, f, ensure_ascii=False)

    print("🌐 HTMLを生成中...")
    ep_html = build_episode_html(date_str, title, novel_text, enriched)
    with open(os.path.join(ep_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(ep_html)

    episodes = collect_all_episodes()
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_index_html(episodes))
    print(f"  index.html を更新（{len(episodes)}エピソード）")

    with open(os.path.join(DOCS_DIR, "assets", "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)

    if no_push:
        print("✅ HTML生成完了（--no-push のため git push はスキップ）")
        print(f"   確認: docs/episodes/{date_str}/index.html")
    else:
        print("🚀 GitHub Pagesにpush中...")
        git_push(date_str)


if __name__ == "__main__":
    main()
