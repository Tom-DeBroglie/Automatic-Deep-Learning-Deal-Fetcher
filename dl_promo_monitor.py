#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deep Learning Promo Monitor for GitHub Actions

功能：
1. 读取 RSS_URLS 环境变量中的 RSS 源，包括 WeWe RSS 生成的微信公众号 RSS、RSSHub 等。
2. 筛选与深度学习/AI/大模型优惠、免费 token、学生优惠、算力福利相关的帖子。
3. 对同一活动的多篇帖子聚类去重，保留更权威、更有价值的一条。
4. 通过 PushPlus 推送到微信。
5. 写入 data/state.json 和 data/sent_promos.json，GitHub Actions 会自动提交，避免重复推送。

运行：
  python dl_promo_monitor.py --send-now
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import feedparser
import requests
from dateutil import parser as date_parser

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "state.json"
SENT_FILE = DATA_DIR / "sent_promos.json"
LATEST_REPORT_FILE = DATA_DIR / "latest_report.md"

DEFAULT_KEYWORDS = [
    # 中文优惠/福利
    r"免费.*token", r"赠送.*token", r"免费.*tokens", r"白送.*token",
    r"免费额度", r"免费调用", r"免费试用", r"限时免费", r"免费开放",
    r"学生优惠", r"教育优惠", r"学生认证", r"校园优惠",
    r"优惠券", r"折扣", r"羊毛", r"薅羊毛", r"福利", r"大放送",
    r"免费.*API", r"API.*免费", r"免费.*模型", r"模型.*免费",
    r"免费.*算力", r"免费算力", r"免费.*GPU", r"GPU.*免费",
    r"注册送", r"新用户.*送", r"开发者.*免费", r"公测.*免费", r"内测.*免费",
    # 英文优惠/福利
    r"free\s+tokens?", r"free\s+credits?", r"student\s+discount",
    r"education\s+discount", r"free\s+trial", r"limited\s+time\s+free",
    r"free\s+api", r"free\s+gpu", r"free\s+compute",
    # 具体产品/平台关键词常与优惠组合出现
    r"Gemini.*(?:免费|优惠|student|free|token|credit)",
    r"Xiaomi\s*Mimo.*(?:免费|token|credit|福利)",
    r"Mimo.*(?:免费|token|credit|福利)",
    r"Claude.*(?:免费|优惠|student|free|token|credit)",
    r"ChatGPT.*(?:免费|优惠|student|free|token|credit)",
    r"OpenAI.*(?:免费|优惠|student|free|token|credit)",
    r"DeepSeek.*(?:免费|优惠|free|token|credit)",
    r"通义.*(?:免费|优惠|token|福利)",
    r"千问.*(?:免费|优惠|token|福利)",
    r"智谱.*(?:免费|优惠|token|福利)",
    r"Kimi.*(?:免费|优惠|token|福利)",
    r"硅基流动.*(?:免费|优惠|token|福利)",
    r"火山方舟.*(?:免费|优惠|token|福利)",
]

PRODUCT_PATTERNS = {
    "Gemini": [r"gemini", r"google\s+ai"],
    "Xiaomi Mimo": [r"xiaomi\s*mimo", r"小米\s*mimo", r"mimo"],
    "OpenAI/ChatGPT": [r"openai", r"chatgpt", r"gpt-?4", r"gpt-?5"],
    "Claude": [r"claude", r"anthropic"],
    "DeepSeek": [r"deepseek", r"深度求索"],
    "Qwen/通义千问": [r"qwen", r"通义", r"千问"],
    "Kimi/月之暗面": [r"kimi", r"月之暗面"],
    "智谱/GLM": [r"智谱", r"glm"],
    "硅基流动": [r"硅基流动", r"siliconflow"],
    "火山方舟": [r"火山方舟", r"volcengine"],
    "百度/文心": [r"文心", r"百度智能云", r"ernie"],
    "讯飞星火": [r"讯飞", r"星火"],
    "GitHub/Copilot": [r"github", r"copilot"],
    "Cursor": [r"cursor"],
    "Trae": [r"trae"],
    "Perplexity": [r"perplexity"],
}

OFFICIAL_DOMAINS = [
    "google.com", "ai.google", "makersuite.google.com", "aistudio.google.com",
    "openai.com", "chatgpt.com",
    "anthropic.com", "claude.ai",
    "deepseek.com", "platform.deepseek.com",
    "mi.com", "xiaomi.com",
    "dashscope.aliyun.com", "aliyun.com",
    "zhipuai.cn", "bigmodel.cn",
    "moonshot.cn", "kimi.com",
    "siliconflow.cn", "volcengine.com",
    "baidu.com", "cloud.baidu.com",
    "xfyun.cn", "github.com", "cursor.com", "trae.ai", "perplexity.ai",
]

BASE_AUTHORITY = {
    # 关键词命中 source_name 或 source_url 即加权
    "官方": 12, "Google": 12, "OpenAI": 12, "Anthropic": 12, "小米": 11,
    "机器之心": 10, "量子位": 10, "新智元": 9, "AI科技评论": 8, "AI前线": 8,
    "PaperWeekly": 8, "极客公园": 8, "机器之能": 7, "夕小瑶": 7,
    "跟李沐学AI": 10, "李沐": 10,
    "bilibili": 4, "zhihu": 3, "xiaohongshu": 2,
    "MP_WXS": 6, "wewe": 6,
}

USER_AGENT = "Mozilla/5.0 (compatible; dl-promo-monitor/1.0; +https://github.com/)"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Failed to read {path}: {exc}")
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def split_env_list(value: str) -> List[str]:
    if not value:
        return []
    parts: List[str] = []
    for chunk in value.replace(";", "\n").replace(",", "\n").splitlines():
        item = chunk.strip()
        if item and not item.startswith("#"):
            parts.append(item)
    return parts


def get_rss_urls() -> List[str]:
    urls = split_env_list(os.getenv("RSS_URLS", ""))
    # fallback: local config/feeds.txt for local testing; GitHub Actions normally uses secrets.RSS_URLS
    local_feed_file = ROOT / "config" / "feeds.txt"
    if not urls and local_feed_file.exists():
        urls = split_env_list(local_feed_file.read_text(encoding="utf-8"))
    # de-duplicate preserving order
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def get_keywords() -> List[re.Pattern]:
    extra = split_env_list(os.getenv("KEYWORDS_EXTRA", ""))
    all_patterns = DEFAULT_KEYWORDS + extra
    compiled = []
    for p in all_patterns:
        try:
            compiled.append(re.compile(p, re.I | re.S))
        except re.error as exc:
            print(f"[WARN] Bad keyword regex ignored: {p!r}: {exc}")
    return compiled


def get_authority_rules() -> Dict[str, int]:
    rules = dict(BASE_AUTHORITY)
    raw = os.getenv("AUTHORITY_RULES_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k, v in data.items():
                    try:
                        rules[str(k)] = int(v)
                    except Exception:
                        pass
        except Exception as exc:
            print(f"[WARN] AUTHORITY_RULES_JSON ignored: {exc}")
    return rules


def parse_dt(entry) -> Optional[datetime]:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                dt = date_parser.parse(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def clean_text(text: str, max_len: int = 5000) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


@dataclass
class FeedItem:
    id: str
    title: str
    link: str
    published: str
    source_url: str
    source_name: str
    text: str
    matched_keywords: List[str]
    product: str
    authority_score: int
    credibility_score: int
    verification_note: str


def source_name_from_feed(feed, url: str) -> str:
    for key in ("title", "subtitle", "description"):
        v = feed.feed.get(key)
        if v:
            return clean_text(v, 100)
    host = urlparse(url).netloc
    return host or url


def fetch_feed(url: str, max_items: int) -> Tuple[List[dict], Optional[str]]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            return [], f"RSS parse error: {getattr(parsed, 'bozo_exception', '')}"
        src_name = source_name_from_feed(parsed, url)
        rows = []
        for entry in parsed.entries[:max_items]:
            pub = parse_dt(entry)
            if not pub:
                pub = now_utc()
            title = clean_text(entry.get("title", ""), 300)
            link = entry.get("link", "") or ""
            summary = clean_text(entry.get("summary", "") or entry.get("description", ""), 3000)
            content = ""
            if entry.get("content") and isinstance(entry.content, list):
                content = " ".join(clean_text(c.get("value", ""), 3000) for c in entry.content[:2])
            text = clean_text(" ".join([title, summary, content]), 6000)
            uniq = hashlib.sha256((link or title + pub.isoformat()).encode("utf-8", "ignore")).hexdigest()[:24]
            rows.append({
                "id": uniq, "title": title or "无标题", "link": link,
                "published_dt": pub, "published": pub.isoformat(),
                "source_url": url, "source_name": src_name, "text": text,
            })
        return rows, None
    except Exception as exc:
        return [], str(exc)


def detect_product(text: str) -> str:
    lower = text.lower()
    for product, patterns in PRODUCT_PATTERNS.items():
        for p in patterns:
            if re.search(p, lower, re.I):
                return product
    return "AI/深度学习工具"


def authority_score(source_name: str, source_url: str, link: str, rules: Dict[str, int]) -> int:
    hay = f"{source_name} {source_url} {link}"
    score = 1
    for k, v in rules.items():
        if str(k).lower() in hay.lower():
            score = max(score, int(v))
    host = urlparse(link).netloc.lower()
    if any(d in host for d in OFFICIAL_DOMAINS):
        score = max(score, 12)
    return score


def official_domain_found(text: str, link: str) -> bool:
    hay = f"{text} {link}".lower()
    return any(d.lower() in hay for d in OFFICIAL_DOMAINS)


def credibility_score(item: dict, auth_score: int) -> Tuple[int, str]:
    score = auth_score
    notes = []
    text = item.get("text", "")
    link = item.get("link", "")
    if official_domain_found(text, link):
        score += 5
        notes.append("含官方域名/官方链接")
    if re.search(r"官方|官网|公告|活动页|领取入口|申请入口|学生认证|开发者平台", text, re.I):
        score += 2
        notes.append("文本包含官方/领取/认证线索")
    if re.search(r"过期|已结束|失效|翻车|不可用", text, re.I):
        score -= 5
        notes.append("疑似过期或失效风险")
    if not notes:
        notes.append("未发现官方验证线索，按来源权威性判断")
    return max(score, 0), "；".join(notes)


def filter_promos(raw_items: List[dict], last_check: datetime) -> List[FeedItem]:
    patterns = get_keywords()
    rules = get_authority_rules()
    results = []
    for item in raw_items:
        pub = item.get("published_dt") or now_utc()
        if pub < last_check:
            continue
        text = item.get("text", "")
        matches = []
        for p in patterns:
            if p.search(text):
                matches.append(p.pattern)
        if not matches:
            continue
        auth = authority_score(item.get("source_name", ""), item.get("source_url", ""), item.get("link", ""), rules)
        cred, note = credibility_score(item, auth)
        product = detect_product(text)
        results.append(FeedItem(
            id=item["id"], title=item["title"], link=item["link"], published=item["published"],
            source_url=item["source_url"], source_name=item["source_name"], text=text[:1200],
            matched_keywords=matches[:5], product=product, authority_score=auth,
            credibility_score=cred, verification_note=note
        ))
    return results


def normalize_title(s: str) -> str:
    s = s.lower()
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[\s\-_/|:：,，.。!！?？'\"“”‘’（）()\[\]【】]+", "", s)
    return s


def title_similarity(a: str, b: str) -> float:
    # Lightweight char n-gram similarity, works better than whitespace tokenization for Chinese titles.
    def grams(s: str, n: int = 2):
        s = normalize_title(s)
        if len(s) <= n:
            return {s} if s else set()
        return {s[i:i+n] for i in range(len(s)-n+1)}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def event_key(item: FeedItem) -> str:
    text = f"{item.product} {item.title}"
    # 如果明确产品名相同，聚类更容易。
    return item.product


def dedup_best(items: List[FeedItem]) -> List[FeedItem]:
    clusters: List[List[FeedItem]] = []
    used = set()
    for i, item in enumerate(items):
        if i in used:
            continue
        cluster = [item]
        used.add(i)
        for j, other in enumerate(items):
            if j in used:
                continue
            same_product = item.product == other.product and item.product != "AI/深度学习工具"
            sim = title_similarity(item.title, other.title)
            if (same_product and sim >= 0.16) or sim >= 0.34:
                cluster.append(other)
                used.add(j)
        clusters.append(cluster)

    best: List[FeedItem] = []
    for cluster in clusters:
        cluster.sort(key=lambda x: (x.credibility_score, x.authority_score, x.published), reverse=True)
        chosen = cluster[0]
        # 多源报道加分和备注
        if len(cluster) > 1:
            chosen.verification_note = f"多源报道 {len(cluster)} 条，已按权威性/官方线索筛选；" + chosen.verification_note
            chosen.credibility_score += min(len(cluster), 5)
        best.append(chosen)
    best.sort(key=lambda x: (x.credibility_score, x.published), reverse=True)
    return best


def should_send_item(item: FeedItem, cluster_count_hint: int = 1) -> bool:
    require = os.getenv("REQUIRE_VERIFIED_FOR_LOW_AUTHORITY_SINGLE_SOURCE", "true").lower() in {"1", "true", "yes"}
    if not require:
        return True
    # 权威来源 >= 6 可发；低权威单源必须有官方线索/高可信度，否则跳过，降低假消息。
    if item.authority_score >= 6:
        return True
    if official_domain_found(item.text, item.link):
        return True
    if item.credibility_score >= 8:
        return True
    return False


def get_last_check() -> datetime:
    state = load_json(STATE_FILE, {})
    raw = state.get("last_check_utc")
    if raw:
        try:
            return date_parser.parse(raw).astimezone(timezone.utc)
        except Exception:
            pass
    days = int(os.getenv("LOOKBACK_DAYS_FIRST_RUN", "7"))
    return now_utc() - timedelta(days=days)


def get_sent_ids() -> set:
    data = load_json(SENT_FILE, {"sent_ids": []})
    return set(data.get("sent_ids", []))


def save_state(sent_ids: set) -> None:
    save_json(SENT_FILE, {"sent_ids": sorted(sent_ids)})
    save_json(STATE_FILE, {"last_check_utc": now_utc().isoformat(), "updated_at_utc": now_utc().isoformat()})


def format_report(items: List[FeedItem], skipped_count: int, errors: List[str]) -> str:
    local_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    if not items:
        lines = [
            "# 📭 深度学习优惠活动日报",
            "",
            "今天没有发现新的、可信度足够高的深度学习/AI优惠活动。",
            "",
            f"- 跳过的低可信单源信息：{skipped_count} 条",
            f"- RSS 抓取异常源：{len(errors)} 个",
            f"- 运行时间：{local_time}",
        ]
    else:
        lines = [
            "# 🎉 深度学习优惠活动日报",
            "",
            f"本次筛选出 **{len(items)}** 个新活动。",
            "",
        ]
        for idx, item in enumerate(items, 1):
            title = item.title.strip()
            product = item.product
            source = item.source_name or "未知来源"
            pub = item.published[:10]
            lines.extend([
                f"## {idx}. {title}",
                f"- 活动/产品：{product}",
                f"- 来源：{source}",
                f"- 发布时间：{pub}",
                f"- 可信度：{item.credibility_score}；{item.verification_note}",
            ])
            if item.link:
                lines.append(f"- 链接：{item.link}")
            lines.append("")
        lines.extend([
            "---",
            f"运行时间：{local_time}",
        ])
    if errors:
        lines.extend(["", "## RSS 异常源", ""])
        for e in errors[:10]:
            lines.append(f"- {e}")
    return "\n".join(lines)


def push_plus(title: str, content: str) -> bool:
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing PUSHPLUS_TOKEN. 请在 GitHub Secrets 中添加 PUSHPLUS_TOKEN。")
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "markdown",
    }
    resp = requests.post("https://www.pushplus.plus/send", json=payload, timeout=20)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        raise RuntimeError(f"PushPlus HTTP {resp.status_code}: {data}")
    # PushPlus commonly returns code 200 on success; tolerate unknown response but log it.
    if isinstance(data, dict) and data.get("code") not in (None, 200):
        raise RuntimeError(f"PushPlus returned non-success: {data}")
    print(f"[INFO] PushPlus response: {data}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-now", action="store_true", help="run once and send report")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    rss_urls = get_rss_urls()
    if not rss_urls:
        # No RSS sources: fail clearly because there is nothing useful to do.
        raise RuntimeError("未配置 RSS_URLS。请在 GitHub Secrets 中添加 RSS_URLS，每行一个 RSS 链接。")

    last_check = get_last_check()
    max_items = int(os.getenv("MAX_ITEMS_PER_FEED", "40"))
    print(f"[INFO] RSS sources: {len(rss_urls)}")
    print(f"[INFO] Last check UTC: {last_check.isoformat()}")

    raw_items: List[dict] = []
    errors: List[str] = []
    for idx, url in enumerate(rss_urls, 1):
        print(f"[INFO] Fetching {idx}/{len(rss_urls)}: {url}")
        rows, err = fetch_feed(url, max_items=max_items)
        if err:
            msg = f"{url} -> {err}"
            print(f"[WARN] {msg}")
            errors.append(msg)
        raw_items.extend(rows)
        time.sleep(0.3)

    print(f"[INFO] Raw items fetched: {len(raw_items)}")
    promos = filter_promos(raw_items, last_check)
    print(f"[INFO] Promo candidates: {len(promos)}")
    best = dedup_best(promos)
    print(f"[INFO] Deduplicated activities: {len(best)}")

    sent_ids = get_sent_ids()
    new_items = [x for x in best if x.id not in sent_ids]
    skipped_low = 0
    verified_new: List[FeedItem] = []
    for x in new_items:
        if should_send_item(x):
            verified_new.append(x)
        else:
            skipped_low += 1
            print(f"[INFO] Skipped low-confidence single-source item: {x.title}")

    send_empty = os.getenv("SEND_EMPTY_REPORT", "false").lower() in {"1", "true", "yes"}
    report = format_report(verified_new, skipped_low, errors)
    LATEST_REPORT_FILE.write_text(report, encoding="utf-8")

    if verified_new or send_empty:
        push_plus("深度学习优惠活动日报", report)
    else:
        print("[INFO] No new verified items; not sending empty report.")

    for x in verified_new:
        sent_ids.add(x.id)
    # Keep sent id list bounded to prevent repository file growing forever.
    if len(sent_ids) > 2000:
        sent_ids = set(list(sorted(sent_ids))[-2000:])
    save_state(sent_ids)
    print("[INFO] Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        # Give GitHub Actions a clear red failure when required configuration is missing or PushPlus fails.
        raise
