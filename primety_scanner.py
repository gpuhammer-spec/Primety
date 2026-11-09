#!/usr/bin/env python3
"""
Ежедневный отчёт: самые популярные русскоязычные Shorts про приметы, поверья, мистику.
Только стандартная библиотека Python 3.8+, ничего устанавливать не нужно.
Результат: report.html, письмо (если заданы SMTP_*), Telegram (если заданы TG_*).
"""
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_KEY = os.environ.get("YT_API_KEY", "")
DAYS = int(os.environ.get("DAYS", "7"))
TOP = int(os.environ.get("TOP", "10"))

QUERIES = [
    "приметы",
    "народные приметы на сегодня",
    "поверья",
    "что нельзя делать сегодня",
    "приметы и поверья",
    "мистика приметы",
    "защита от сглаза оберег",
    "что носить с собой для удачи",
    "запреты по народным приметам",
]

API = "https://www.googleapis.com/youtube/v3/"
CYR = re.compile(r"[а-яА-ЯёЁ]")


def call(endpoint, **params):
    params["key"] = API_KEY
    url = API + endpoint + "?" + urlencode(params)
    try:
        with urlopen(url, timeout=30) as r:
            return json.load(r)
    except HTTPError as e:
        sys.exit(f"Ошибка YouTube API {e.code}: {e.read().decode('utf-8', 'ignore')[:400]}")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds(d):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 10**6
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def collect_ids(now):
    ids = set()
    passes = [("viewCount", now - timedelta(days=DAYS)), ("date", now - timedelta(days=2))]
    for q in QUERIES:
        for order, since in passes:
            data = call(
                "search", part="id", q=q, type="video", videoDuration="short",
                order=order, publishedAfter=iso(since), relevanceLanguage="ru",
                regionCode="RU", maxResults=50,
            )
            for it in data.get("items", []):
                ids.add(it["id"]["videoId"])
    return list(ids)


def fetch_videos(ids, now):
    out = []
    for i in range(0, len(ids), 50):
        data = call("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]))
        for v in data.get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            if seconds(v["contentDetails"].get("duration")) > 60:
                continue
            if not CYR.search(sn["title"] + sn.get("description", "")):
                continue
            views = int(st.get("viewCount", 0))
            if views == 0:
                continue
            likes = int(st.get("likeCount", 0))
            comments = int(st.get("commentCount", 0))
            pub = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
            age_h = max((now - pub).total_seconds() / 3600, 1)
            th = sn["thumbnails"]
            thumb = (th.get("high") or th.get("medium") or th["default"])["url"]
            out.append({
                "id": v["id"], "title": sn["title"], "channel": sn["channelTitle"],
                "desc": sn.get("description", "").strip().replace("\n", " ")[:160],
                "views": views, "likes": likes, "comments": comments,
                "age_h": age_h, "vph": views / age_h,
                "er": (likes + comments) / views * 100, "thumb": thumb,
            })
    return out


def fmt_age(h):
    return f"{int(h)} ч назад" if h < 48 else f"{int(h // 24)} дн назад"


def n(x):
    return f"{x:,}".replace(",", " ")


def card(v):
    link = f"https://www.youtube.com/shorts/{v['id']}"
    e = html.escape
    return f"""<div style="display:inline-block;vertical-align:top;width:190px;margin:6px;font-family:Arial,sans-serif;font-size:12px;color:#222">
<a href="{link}"><img src="{v['thumb']}" width="190" height="300" style="object-fit:cover;border-radius:8px;display:block"></a>
<div style="font-weight:bold;margin:6px 0 2px">{e(v['title'][:80])}</div>
<div style="color:#666">{e(v['channel'])} · {fmt_age(v['age_h'])}</div>
<div>👁 {n(v['views'])} · 👍 {n(v['likes'])} · 💬 {n(v['comments'])}</div>
<div>🚀 {n(int(v['vph']))} просм/час · вовлечённость {v['er']:.1f}%</div>
<div style="color:#888;margin-top:2px">{e(v['desc'])}</div>
</div>"""


def section(title, items):
    return f"<h2 style='font-family:Arial'>{title}</h2>" + "".join(card(v) for v in items)


def build_report(videos, now):
    fast = sorted(videos, key=lambda v: v["vph"], reverse=True)[:TOP]
    top = sorted(videos, key=lambda v: v["views"], reverse=True)[:TOP]
    eng = sorted([v for v in videos if v["views"] >= 1000], key=lambda v: v["er"], reverse=True)[:TOP]
    head = f"<h1 style='font-family:Arial'>Приметы и поверья: отчёт за {now.strftime('%d.%m.%Y')}</h1>"
    head += f"<p style='font-family:Arial'>Проверено роликов: {len(videos)}</p>"
    return (
        "<html><body>" + head
        + section("🚀 Взлетают быстрее всего (просмотров в час)", fast)
        + section("👁 Больше всего просмотров", top)
        + section("💬 Лучшая вовлечённость (от 1000 просмотров)", eng)
        + "</body></html>"
    )


def send_mail(body, now):
    user, pwd, to = (os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASS", "MAIL_TO"))
    if not (user and pwd and to):
        print("SMTP_* не заданы, письмо не отправляется")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Приметы: отчёт по Shorts за {now.strftime('%d.%m.%Y')}"
    msg["From"], msg["To"] = user, to
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
    print("Письмо отправлено на", to)


def tg(method, **data):
    token = os.environ["TG_TOKEN"].strip()
    req = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as r:
            return json.load(r)
    except HTTPError as err:
        print("Ошибка Telegram", err.code, err.read().decode("utf-8", "ignore")[:300])


def tg_caption(v):
    e = html.escape
    return (
        f"<b>{e(v['title'][:100])}</b>\n"
        f"{e(v['channel'])} · {fmt_age(v['age_h'])}\n"
        f"👁 {n(v['views'])} · 👍 {n(v['likes'])} · 💬 {n(v['comments'])}\n"
        f"🚀 {n(int(v['vph']))} просм/час · вовлечённость {v['er']:.1f}%\n"
        f"{e(v['desc'][:120])}\n"
        f"https://www.youtube.com/shorts/{v['id']}"
    )


def send_telegram(videos, now):
    if not (os.environ.get("TG_TOKEN") and os.environ.get("TG_CHAT_ID")):
        print("TG_* не заданы, в Telegram не отправляется")
        return
    chat = os.environ["TG_CHAT_ID"].strip()
    k = int(os.environ.get("TG_TOP", "5"))
    fast = sorted(videos, key=lambda v: v["vph"], reverse=True)[:k]
    seen = {v["id"] for v in fast}
    top = [v for v in sorted(videos, key=lambda v: v["views"], reverse=True) if v["id"] not in seen][:k]
    for title, items in (("🚀 Взлетают быстрее всего", fast), ("👁 Больше всего просмотров", top)):
        tg("sendMessage", chat_id=chat, text=f"{title} · {now.strftime('%d.%m.%Y')}")
        for v in items:
            tg("sendPhoto", chat_id=chat, photo=v["thumb"], caption=tg_caption(v), parse_mode="HTML")
            time.sleep(1.2)
    print("Отправлено в Telegram")


def main():
    if not API_KEY:
        sys.exit("Задай переменную YT_API_KEY")
    now = datetime.now(timezone.utc)
    ids = collect_ids(now)
    videos = fetch_videos(ids, now)
    if not videos:
        sys.exit("Подходящих роликов не найдено")
    body = build_report(videos, now)
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Готово: report.html, роликов {len(videos)}")
    send_mail(body, now)
    send_telegram(videos, now)


if __name__ == "__main__":
    main()
