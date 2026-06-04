#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博热榜自动推送脚本 - Server酱Turbo / 企业微信群机器人 双通道版
GitHub Actions 云端版 - 适配 Linux 环境

功能：从 tophub.today 抓取微博热搜榜 TOP50，格式化后推送
通道1：Server酱 Turbo (sct.ftqq.com) - 推送到微信/企业微信/钉钉等
通道2：企业微信群机器人 Webhook

用法：
  python weibo_hotbot.py --sendkey "YOUR_SENDKEY" --top 50

  # 测试模式（不发送，只打印）
  python weibo_hotbot.py --dry-run --top 10
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
import urllib.parse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# ============== 配置区 ==============
DEFAULT_SENDKEY = ""          # Server酱 SendKey（通过环境变量或参数传入，不硬编码）
DEFAULT_WEBHOOK_URL = ""      # 企业微信群机器人 Webhook URL
DEFAULT_TOP_COUNT = 50        # 默认推送条数（全量50条）
TOPHUB_URL = "https://tophub.today/n/KqndgxeLl9"
SCT_API_URL = "https://sctapi.ftqq.com/{}.send"
# 时区：北京时间 UTC+8
CST = timezone(timedelta(hours=8))
# ====================================


def fetch_weibo_hot_list():
    """从今日热榜获取微博热搜数据"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = Request(TOPHUB_URL, headers=headers)

    with urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    return parse_tophub_html(html)


def parse_tophub_html(html):
    """解析今日热榜页面，提取热搜列表"""
    items = []

    # 方法1: 匹配表格中的热搜行
    pattern = r'<td[^>]*class="[^"]*al[^"]*"[^>]*><a[^>]*href="[^"]*"[^>]*>([^<]+)</a></td>\s*<td[^>]*>([^<]+)</td>'
    matches = re.findall(pattern, html)
    if matches:
        for title, hot in matches:
            title = title.strip()
            hot = hot.strip()
            if title and hot:
                items.append({"title": title, "hot": hot})
        return items[:50]

    # 方法2: 更宽泛的匹配
    pattern2 = r'<a[^>]*href="[^"]*"[^>]*target="_blank"[^>]*>([^<]{2,40})</a>\s*</td>\s*<td[^>]*>([\d\.万]+)</td>'
    matches2 = re.findall(pattern2, html)
    if matches2:
        for title, hot in matches2:
            title = title.strip()
            hot = hot.strip()
            if title and hot:
                items.append({"title": title, "hot": hot})
        return items[:50]

    # 方法3: 最宽泛匹配
    lines = html.split('\n')
    for line in lines:
        if 'al' in line.lower() and ('万' in line or any(c.isdigit() for c in line)):
            title_match = re.search(r'>([^<]{2,50})</a>', line)
            hot_match = re.search(r'>(\d+\.?\d*万?)</', line)
            if title_match and hot_match:
                items.append({
                    "title": title_match.group(1).strip(),
                    "hot": hot_match.group(1).strip()
                })

    return items[:50]


def format_message(items, top_n=50):
    """将热搜列表格式化为 Markdown 消息"""
    now = datetime.now(CST)
    date_str = now.strftime("%Y年%m月%d日")
    time_str = now.strftime("%H:%M")

    hour = now.hour
    if 6 <= hour < 12:
        period = "早间版"
    elif 12 <= hour < 14:
        period = "午间版"
    elif 14 <= hour < 18:
        period = "下午版"
    else:
        period = "晚间版"

    lines = []
    lines.append(f"## 微博热榜 {period} {time_str}")
    lines.append(f"> {date_str} | 共 {len(items)} 条热搜 | 数据源: tophub.today")
    lines.append("")

    display_items = items[:top_n]
    for idx, item in enumerate(display_items, 1):
        medal = ""
        if idx == 1:
            medal = ""
        elif idx == 2:
            medal = ""
        elif idx == 3:
            medal = ""

        lines.append(f"**{idx}. {item['title']}** {medal}")
        lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;热度: `{item['hot']}`")
        lines.append("")

    if len(items) > top_n:
        lines.append(f"\n---\n*还有 **{len(items) - top_n}** 条未显示...*")

    return "\n".join(lines)


def send_via_serverchan(sendkey, title, content):
    """通过 Server酱 Turbo 发送消息"""
    url = SCT_API_URL.format(sendkey)
    params = {
        "title": title,
        "desp": content,
    }

    encoded_params = "&".join(
        f"{k}={urllib.parse.quote(v.encode('utf-8'))}" for k, v in params.items()
    )
    full_url = f"{url}?{encoded_params}"

    req = Request(full_url, method="GET")

    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            code = result.get("code", -1)
            if code == 0:
                print("Server酱推送成功！")
                return True
            else:
                msg = result.get("message", "未知错误")
                print(f"Server酱推送失败 [code={code}]: {msg}")
                return False
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        print(f"Server酱 HTTP错误 {e.code}: {error_body}")
        return False
    except URLError as e:
        print(f"Server酱网络错误: {e.reason}")
        return False
    except Exception as e:
        print(f"Server酱未知错误: {e}")
        return False


def send_via_webhook(webhook_url, content):
    """发送消息到企业微信群机器人 Webhook"""
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": content
        }
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errcode") == 0:
                print("企微群机器人推送成功！")
                return True
            else:
                print(f"企微群机器人推送失败: {result}")
                return False
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        print(f"企微群机器人HTTP错误 {e.code}: {error_body}")
        return False
    except URLError as e:
        print(f"企微群机器人网络错误: {e.reason}")
        return False
    except Exception as e:
        print(f"企微群机器人未知错误: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="微博热榜自动推送 (Server酱/企微双通道) - GitHub Actions 云端版")
    parser.add_argument("--sendkey", "-s",
                        default=os.environ.get("SCT_SENDKEY", ""),
                        help="Server酱 Turbo 的 SendKey (推荐)")
    parser.add_argument("--webhook", "-w",
                        default=os.environ.get("WECHAT_WEBHOOK", ""),
                        help="企业微信群机器人 Webhook URL")
    parser.add_argument("--top", "-n", type=int, default=DEFAULT_TOP_COUNT,
                        help=f"推送TOP N条 (默认{DEFAULT_TOP_COUNT})")
    parser.add_argument("--dry-run", action="store_true", help="只打印内容，不实际发送")
    args = parser.parse_args()

    if not args.sendkey and not args.webhook and not args.dry_run:
        print("=" * 60)
        print("  微博热榜推送脚本 v3.0 (GitHub Actions 云端版)")
        print("=" * 60)
        print("\n请选择一种推送方式:\n")
        print("  [方式1] Server酱 Turbo (推荐，推送到微信)")
        print('    python weibo_hotbot.py --sendkey "YOUR_SENDKEY"\n')
        print("  [方式2] 企业微信群机器人")
        print('    python weibo_hotbot.py --webhook "WEBHOOK_URL"\n')
        print("  [测试] 不发送，仅预览内容:")
        print("    python weibo_hotbot.py --dry-run\n")
        print("-" * 60)
        print("Server酱注册地址: https://sct.ftqq.com")
        print("=" * 60)
        sys.exit(1)

    print(f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}] 正在抓取微博热榜...")

    items = fetch_weibo_hot_list()

    if not items:
        print("错误：未能获取到热榜数据！")
        sys.exit(1)

    print(f"成功获取 {len(items)} 条热搜")

    now = datetime.now(CST)
    hour = now.hour
    if 6 <= hour < 12:
        period = "早间版"
    elif 12 <= hour < 14:
        period = "午间版"
    elif 14 <= hour < 18:
        period = "下午版"
    else:
        period = "晚间版"

    title = f"微博热榜{period} {now.strftime('%H:%M')}"
    content = format_message(items, args.top)

    if args.dry_run:
        print("\n" + "=" * 50)
        print(content)
        print("=" * 50)
        return

    success = True

    if args.sendkey:
        print(f"正在通过 Server酱 推送 TOP{args.top}...")
        if not send_via_serverchan(args.sendkey, title, content):
            success = False

    if args.webhook:
        print(f"正在通过 企微群机器人 推送 TOP{args.top}...")
        if not send_via_webhook(args.webhook, content):
            success = False

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
