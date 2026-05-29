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
from urllib.parse import urlparse, urlencode

import feedparser
import requests
from dateutil import parser as date_parser

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "state.json"
SENT_FILE = DATA_DIR / "sent_promos.json"
LATEST_REPORT_FILE = DATA_DIR / "latest_report.md"

DEFAULT_KEYWORDS = [
    # ================= 中文：通用优惠 / 免费 / 福利 =================
    r"免费.*token", r"赠送.*token", r"白送.*token", r"送.*tokens?", r"领.*tokens?",
    r"免费.*tokens?", r"tokens?.*免费", r"tokens?.*赠送", r"token.*额度", r"tokens?.*额度",
    r"免费额度", r"赠送额度", r"新人额度", r"新用户额度", r"注册.*额度", r"注册送.*额度",
    r"调用额度", r"API额度", r"推理额度", r"模型额度", r"试用额度", r"每月额度",
    r"免费调用", r"免费推理", r"免费生成", r"免费对话", r"免费问答", r"免费使用",
    r"限时免费", r"限免", r"限时开放", r"免费开放", r"开放免费", r"免费上线",
    r"免费体验", r"体验资格", r"体验名额", r"试用资格", r"免费试用", r"公测免费",
    r"内测资格", r"公测资格", r"开放体验", r"免费申请", r"申请入口", r"领取入口",
    r"活动入口", r"一键领取", r"免费领取", r"开放领取", r"限量领取",

    # ================= 中文：优惠券 / 折扣 / 代金券 =================
    r"优惠券", r"代金券", r"抵扣券", r"折扣券", r"算力券", r"资源券", r"云券",
    r"体验券", r"兑换券", r"领取券", r"满减券", r"折扣码", r"优惠码", r"兑换码",
    r"邀请码", r"领取码", r"促销码", r"邀请码.*额度", r"兑换码.*额度",
    r"折扣", r"打折", r"半价", r"低至", r"立减", r"满减", r"减免", r"补贴",
    r"返现", r"充值返", r"买赠", r"限时折扣", r"限时优惠", r"特惠", r"促销",
    r"价格优惠", r"套餐优惠", r"订阅优惠", r"会员优惠",

    # ================= 中文：羊毛 / 福利常见说法 =================
    r"白嫖", r"羊毛", r"薅羊毛", r"捡漏", r"福利", r"福利包", r"礼包",
    r"新手礼包", r"开发者礼包", r"学生礼包", r"AI福利", r"大模型福利",
    r"模型福利", r"算力福利", r"API福利", r"开发者福利", r"限时福利",
    r"免费福利", r"官方福利", r"隐藏福利", r"领取教程", r"申请教程",

    # ================= 中文：学生 / 教育 / 校园 =================
    r"学生优惠", r"教育优惠", r"校园优惠", r"高校优惠", r"学生认证", r"教育认证",
    r"学术认证", r"高校认证", r"edu认证", r"学生免费", r"学生专享", r"学生福利",
    r"学生套餐", r"学生计划", r"校园计划", r"高校计划", r"教育计划", r"学术计划",
    r"大学生.*免费", r"大学生.*优惠", r"高校学生.*免费", r"高校学生.*优惠",
    r"教师优惠", r"教师认证", r"科研优惠", r"科研额度", r"学术额度",
    r"实验室.*额度", r"课题组.*额度",

    # ================= 中文：开发者 / 创业 / 开源 / 比赛 =================
    r"开发者计划", r"开发者活动", r"开发者优惠", r"开发者免费", r"开发者.*额度",
    r"开发者.*token", r"开发者.*credits?", r"开发者.*福利", r"开发者补贴",
    r"创业扶持", r"创业计划", r"初创.*额度", r"初创.*免费", r"初创.*优惠",
    r"startup.*credits?", r"开源.*免费", r"开源项目.*额度", r"开源项目.*免费",
    r"黑客松.*额度", r"黑客松.*算力", r"hackathon.*credits?", r"竞赛.*算力",
    r"比赛.*算力", r"大赛.*算力", r"挑战赛.*额度", r"训练营.*免费",

    # ================= 中文：API / 模型 / 推理 / 训练 =================
    r"免费.*API", r"API.*免费", r"API.*福利", r"API.*优惠", r"API.*折扣", r"API.*额度",
    r"免费.*模型", r"模型.*免费", r"模型.*福利", r"模型.*优惠", r"模型.*额度",
    r"免费.*推理", r"推理.*免费", r"推理.*额度", r"推理.*福利", r"推理.*优惠",
    r"免费.*训练", r"训练.*免费", r"训练.*额度", r"训练.*算力", r"训练.*优惠",
    r"免费.*微调", r"微调.*免费", r"微调.*额度", r"微调.*优惠",
    r"免费.*embedding", r"embedding.*免费", r"embedding.*额度", r"向量.*免费",
    r"向量库.*免费", r"RAG.*免费", r"Agent.*免费", r"智能体.*免费",

    # ================= 中文：算力 / GPU / 云资源 =================
    r"免费.*算力", r"算力.*免费", r"算力.*福利", r"算力.*优惠", r"算力.*补贴", r"算力.*额度",
    r"免费.*GPU", r"GPU.*免费", r"GPU.*福利", r"GPU.*优惠", r"GPU.*额度",
    r"免费.*云服务器", r"免费.*云资源", r"云资源.*免费", r"云资源.*优惠",
    r"免费.*云主机", r"云主机.*免费", r"云服务器.*试用", r"云服务器.*免费",
    r"免费.*Notebook", r"Notebook.*免费", r"免费.*开发环境", r"免费.*实验环境",
    r"Colab.*免费", r"Kaggle.*免费", r"免费.*显卡", r"显卡.*免费",

    # ================= English: token / credit / quota =================
    r"free\s+tokens?", r"bonus\s+tokens?", r"complimentary\s+tokens?", r"token\s+giveaway",
    r"tokens?\s+giveaway", r"tokens?\s+credit", r"free\s+token\s+credits?",
    r"free\s+credits?", r"bonus\s+credits?", r"promo\s+credits?", r"trial\s+credits?",
    r"cloud\s+credits?", r"compute\s+credits?", r"genai\s+credits?", r"ai\s+credits?",
    r"monthly\s+credits?", r"usage\s+credits?", r"api\s+credits?", r"inference\s+credits?",
    r"free\s+quota", r"free\s+allowance", r"free\s+usage", r"free\s+calls?",
    r"free\s+api\s+calls?", r"free\s+inference", r"free\s+compute",

    # ================= English: free / discount / coupon =================
    r"free\s+tier", r"free\s+plan", r"free\s+access", r"free\s+trial",
    r"limited\s+time\s+free", r"limited-time\s+free", r"free\s+for\s+limited\s+time",
    r"trial\s+offer", r"special\s+offer", r"launch\s+offer", r"early\s+access",
    r"discount", r"discounted", r"coupon", r"voucher", r"promo\s+code",
    r"coupon\s+code", r"redeem\s+code", r"promotion\s+code", r"referral\s+code",
    r"deal", r"deals", r"offer", r"offers", r"giveaway", r"grant", r"subsidy",
    r"limited\s+offer", r"student\s+deal", r"developer\s+deal",

    # ================= English: student / education / developer =================
    r"student\s+discount", r"student\s+offer", r"student\s+free", r"free\s+for\s+students?",
    r"student\s+credits?", r"student\s+plan", r"student\s+pack", r"student\s+developer\s+pack",
    r"education\s+discount", r"education\s+offer", r"academic\s+discount", r"academic\s+credits?",
    r"edu\s+discount", r"edu\s+offer", r"campus\s+offer",
    r"developer\s+credits?", r"developer\s+offer", r"developer\s+program", r"developer\s+grant",
    r"startup\s+credits?", r"startup\s+program", r"startup\s+offer",
    r"research\s+credits?", r"research\s+grant", r"open\s+source\s+credits?",

    # ================= English: API / model / GPU / cloud =================
    r"free\s+api", r"free\s+models?", r"free\s+llm", r"free\s+ai\s+model",
    r"free\s+gpu", r"free\s+compute", r"free\s+cloud", r"free\s+cloud\s+credits?",
    r"gpu\s+credits?", r"compute\s+credits?", r"inference\s+credits?",
    r"model\s+credits?", r"api\s+discount", r"gpu\s+discount", r"cloud\s+discount",
    r"free\s+notebook", r"free\s+workspace", r"free\s+developer\s+account",

    # ================= 国内平台 / 产品 + 优惠词 =================
    r"(?:阿里云|百炼|灵积|DashScope|Model\s*Studio).*(?:免费|优惠|折扣|额度|token|tokens|福利|代金券|试用|补贴)",
    r"(?:腾讯云|混元|Hunyuan).*(?:免费|优惠|折扣|额度|token|tokens|福利|代金券|试用|补贴)",
    r"(?:百度|千帆|文心|ERNIE).*(?:免费|优惠|折扣|额度|token|tokens|福利|代金券|试用|补贴)",
    r"(?:火山|火山方舟|豆包|Volcengine|Ark).*(?:免费|优惠|折扣|额度|token|tokens|福利|代金券|试用)",
    r"(?:华为云|盘古|昇腾|ModelArts).*(?:免费|优惠|折扣|额度|token|tokens|福利|算力券|试用)",
    r"(?:讯飞|星火|Spark).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:智谱|GLM|BigModel).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:Kimi|月之暗面|Moonshot).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:DeepSeek|深度求索).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:通义|千问|Qwen).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:硅基流动|SiliconFlow).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:魔搭|ModelScope).*(?:免费|优惠|折扣|额度|token|tokens|福利|算力|试用)",
    r"(?:MiniMax|海螺|abab).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:零一万物|01\.?AI|Yi).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:阶跃星辰|StepFun|Step).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:百川|Baichuan).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:商汤|日日新|SenseNova).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:天工|昆仑万维).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:Xiaomi\s*Mimo|小米\s*Mimo|Mimo).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",
    r"(?:秘塔|元宝|豆包|可灵|即梦).*(?:免费|优惠|折扣|额度|token|tokens|福利|试用)",

    # ================= 国外平台 / 产品 + 优惠词 =================
    r"(?:Gemini|Google\s*AI|AI\s*Studio|Vertex\s*AI|Google\s*Cloud).*(?:free|discount|credits?|tokens?|student|education|trial|offer|coupon|promo)",
    r"(?:OpenAI|ChatGPT|GPT-?4|GPT-?5).*(?:free|discount|credits?|tokens?|student|education|trial|offer|coupon|promo)",
    r"(?:Claude|Anthropic).*(?:free|discount|credits?|tokens?|student|education|trial|offer|coupon|promo)",
    r"(?:GitHub|Copilot|Student\s*Developer\s*Pack).*(?:free|discount|credits?|student|education|trial|offer)",
    r"(?:Microsoft|Azure|Azure\s*AI).*(?:free|discount|credits?|student|education|trial|offer)",
    r"(?:AWS|Bedrock|SageMaker|Educate).*(?:free|discount|credits?|student|education|trial|offer)",
    r"(?:Hugging\s*Face|HF).*(?:free|discount|credits?|tokens?|student|education|trial|offer|inference)",
    r"(?:Replicate|Together\s*AI|Fireworks|Groq|Cerebras).*(?:free|discount|credits?|tokens?|student|education|trial|offer|inference)",
    r"(?:RunPod|Modal|Lambda\s*Labs|Vast\.ai|Paperspace).*(?:free|discount|credits?|student|education|trial|offer|GPU|compute)",
    r"(?:Colab|Kaggle|NotebookLM|Perplexity|Cursor|Windsurf|Trae|Devin).*(?:free|discount|credits?|student|education|trial|offer|coupon|promo)",
    r"(?:Mistral|Cohere|xAI|Grok|DeepL|Notion\s*AI).*(?:free|discount|credits?|tokens?|student|education|trial|offer|coupon|promo)",
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

def get_bilibili_uids() -> List[str]:
    """读取 GitHub Secret / 环境变量 BILIBILI_UIDS，每行一个 B站 UP 主 UID。"""
    raw = os.getenv("BILIBILI_UIDS", "")
    uids = []
    seen = set()
    for item in split_env_list(raw):
        uid = re.sub(r"\D", "", item)
        if uid and uid not in seen:
            seen.add(uid)
            uids.append(uid)
    return uids


def bili_headers(uid: str = "") -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Referer": f"https://space.bilibili.com/{uid}" if uid else "https://www.bilibili.com/",
        "Origin": "https://space.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    }


def bili_api_json(url: str, params: dict, uid: str) -> dict:
    resp = requests.get(url, params=params, headers=bili_headers(uid), timeout=25)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Bilibili API code={data.get('code')} message={data.get('message')}")
    return data


def fetch_bilibili_dynamic(uid: str, max_items: int) -> Tuple[List[dict], Optional[str]]:
    """尝试从 B站空间动态 API 抓取 UP 主最新动态/视频。"""
    url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
    params = {
        "host_mid": uid,
        "platform": "web",
        "features": "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote",
        "timezone_offset": "-480",
    }

    try:
        data = bili_api_json(url, params, uid)
        items = data.get("data", {}).get("items", []) or []
        rows: List[dict] = []

        for it in items[:max_items]:
            modules = it.get("modules", {}) or {}
            author = modules.get("module_author", {}) or {}
            dynamic = modules.get("module_dynamic", {}) or {}
            major = dynamic.get("major") or {}
            desc_obj = dynamic.get("desc") or {}

            pub_ts = author.get("pub_ts") or it.get("pub_ts") or int(time.time())
            pub = datetime.fromtimestamp(int(pub_ts), tz=timezone.utc)

            source_name = clean_text(author.get("name", f"B站UP主{uid}"), 100)
            dyn_id = str(it.get("id_str") or it.get("id") or "")

            title = ""
            link = f"https://t.bilibili.com/{dyn_id}" if dyn_id else f"https://space.bilibili.com/{uid}/dynamic"
            parts = []

            archive = major.get("archive") if isinstance(major, dict) else None
            opus = major.get("opus") if isinstance(major, dict) else None
            article = major.get("article") if isinstance(major, dict) else None

            if archive:
                title = archive.get("title") or ""
                bvid = archive.get("bvid") or ""
                link = archive.get("jump_url") or (f"https://www.bilibili.com/video/{bvid}" if bvid else link)
                parts.extend([title, archive.get("desc") or ""])

            elif opus:
                title = opus.get("title") or ""
                summary = opus.get("summary", {}) if isinstance(opus.get("summary"), dict) else {}
                parts.extend([title, summary.get("text") or ""])
                if opus.get("jump_url"):
                    link = "https:" + opus["jump_url"] if opus["jump_url"].startswith("//") else opus["jump_url"]

            elif article:
                title = article.get("title") or ""
                link = article.get("jump_url") or link
                parts.extend([title, article.get("desc") or ""])

            desc_text = desc_obj.get("text") if isinstance(desc_obj, dict) else ""
            if not title:
                title = clean_text(desc_text, 80) or f"B站动态 {dyn_id or uid}"

            parts.append(desc_text or "")
            text = clean_text(" ".join([p for p in parts if p]), 6000)

            uniq = hashlib.sha256((link or title + pub.isoformat()).encode("utf-8", "ignore")).hexdigest()[:24]

            rows.append({
                "id": uniq,
                "title": clean_text(title, 300) or "无标题",
                "link": link,
                "published_dt": pub,
                "published": pub.isoformat(),
                "source_url": f"bilibili-api:dynamic:{uid}",
                "source_name": source_name,
                "text": text,
            })

        return rows, None

    except Exception as exc:
        return [], str(exc)


def fetch_bilibili_app_videos(uid: str, max_items: int) -> Tuple[List[dict], Optional[str]]:
    """备用：尝试 B站 APP 空间投稿接口，不依赖 RSSHub。"""
    url = "https://api.bilibili.com/x/v2/space/archive/cursor"
    params = {
        "vmid": uid,
        "ps": min(max_items, 30),
        "pn": 1,
        "order": "pubdate",
    }

    try:
        data = bili_api_json(url, params, uid)
        vlist = data.get("data", {}).get("item", []) or []
        rows: List[dict] = []

        for v in vlist[:max_items]:
            pub_ts = v.get("ctime") or v.get("created") or int(time.time())
            pub = datetime.fromtimestamp(int(pub_ts), tz=timezone.utc)

            title = clean_text(v.get("title", ""), 300) or "无标题"
            bvid = v.get("bvid") or ""
            aid = v.get("param") or v.get("aid") or ""

            if bvid:
                link = f"https://www.bilibili.com/video/{bvid}"
            elif aid:
                link = f"https://www.bilibili.com/video/av{aid}"
            else:
                link = f"https://space.bilibili.com/{uid}"

            desc = clean_text(v.get("desc", "") or v.get("intro", ""), 3000)
            author = clean_text(v.get("author", f"B站UP主{uid}"), 100)
            text = clean_text(" ".join([title, desc]), 6000)

            uniq = hashlib.sha256((link or title + pub.isoformat()).encode("utf-8", "ignore")).hexdigest()[:24]

            rows.append({
                "id": uniq,
                "title": title,
                "link": link,
                "published_dt": pub,
                "published": pub.isoformat(),
                "source_url": f"bilibili-api:archive:{uid}",
                "source_name": author,
                "text": text,
            })

        return rows, None

    except Exception as exc:
        return [], str(exc)


def fetch_bilibili_api(uid: str, max_items: int) -> Tuple[List[dict], Optional[str]]:
    """B站 API 抓取入口：先动态，失败再尝试投稿接口。"""
    rows, err1 = fetch_bilibili_dynamic(uid, max_items)
    if rows:
        return rows, None

    rows, err2 = fetch_bilibili_app_videos(uid, max_items)
    if rows:
        return rows, None

    return [], f"dynamic: {err1}; archive: {err2}"

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
    bilibili_uids = get_bilibili_uids()
    
    if not rss_urls and not bilibili_uids:
        # No sources: fail clearly because there is nothing useful to do.
        raise RuntimeError("未配置数据源。请在 GitHub Secrets 中添加 RSS_URLS 或 BILIBILI_UIDS。")

    last_check = get_last_check()
    max_items = int(os.getenv("MAX_ITEMS_PER_FEED", "40"))
    print(f"[INFO] RSS sources: {len(rss_urls)}")
    print(f"[INFO] Bilibili API UIDs: {len(bilibili_uids)}")
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

    # Extra source: fetch Bilibili directly by API.
    # This does not remove RSS; it only adds another data source.
    for idx, uid in enumerate(bilibili_uids, 1):
        print(f"[INFO] Fetching Bilibili API {idx}/{len(bilibili_uids)}: {uid}")
        rows, err = fetch_bilibili_api(uid, max_items=max_items)
        if err:
            msg = f"bilibili-api:{uid} -> {err}"
            print(f"[WARN] {msg}")
            errors.append(msg)
        raw_items.extend(rows)
        time.sleep(0.5)

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
