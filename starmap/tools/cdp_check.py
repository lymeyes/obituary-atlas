#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集星图 · 真机（Chrome CDP）验证脚本

零第三方依赖：用标准库手写最小 WebSocket 客户端连本机 Chrome 调试端口。
既验 http:// 预览，也验 file:// 直开；桌面与手机视口各跑一轮。

用法
----
    python3 starmap/tools/cdp_check.py \
        --url http://127.0.0.1:8899/index.html \
        --file-url "file:///Users/.../驾鹤集星图/index.html" \
        --shot /tmp/starmap.png
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222


# --------------------------------------------------------------- WebSocket --
class WS:
    def __init__(self, url: str, timeout: float = 25):
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=timeout)
        self.s.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n"
               % (u.path, u.hostname, u.port, key))
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError("WS handshake failed: " + buf[:200].decode("utf-8", "replace"))
        self.id = 0
        self.events: list[dict] = []

    def _rd(self, n: int) -> bytes:
        b = b""
        while len(b) < n:
            chunk = self.s.recv(n - len(b))
            if not chunk:
                raise RuntimeError("WS closed")
            b += chunk
        return b

    def send(self, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode()
        mask = os.urandom(4)
        n = len(data)
        hdr = bytearray([0x81])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        h = self._rd(2)
        op = h[0] & 0x0F
        ln = h[1] & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._rd(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._rd(8))[0]
        mask = self._rd(4) if (h[1] & 0x80) else None
        data = self._rd(ln)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op == 9:                       # ping → pong
            self.s.sendall(b"\x8a\x80" + os.urandom(4))
            return None
        if op == 8:
            raise RuntimeError("WS closed by peer")
        if op not in (1, 2):
            return None
        return json.loads(data.decode("utf-8", "replace"))

    def call(self, method: str, params: dict | None = None, timeout: float = 25):
        self.id += 1
        mid = self.id
        self.send({"id": mid, "method": method, "params": params or {}})
        end = time.time() + timeout
        while time.time() < end:
            msg = self.recv()
            if not msg:
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s -> %s" % (method, msg["error"]))
                return msg.get("result", {})
            self.events.append(msg)
        raise TimeoutError(method)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def http_json(path: str, method="GET"):
    url = "http://%s:%d%s" % (CDP_HOST, CDP_PORT, path)
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=8) as f:
        return json.loads(f.read())


def new_tab(url: str) -> str:
    r = http_json("/json/new?" + urllib.parse.quote(url, safe=":/?=&%"), "PUT")
    return r["webSocketDebuggerUrl"]


def evaluate(ws: WS, expr: str, await_promise=False):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                     "awaitPromise": await_promise,
                                     "userGesture": True}, timeout=40)
    if "exceptionDetails" in r:
        return {"__error": str(r["exceptionDetails"].get("text", "")) + " " +
                str(r["exceptionDetails"].get("exception", {}).get("description", ""))[:400]}
    return r.get("result", {}).get("value")


def collect_errors(ws: WS):
    errs = []
    for e in ws.events:
        m = e.get("method", "")
        if m == "Runtime.exceptionThrown":
            errs.append(str(e["params"]["exceptionDetails"].get("text", "")) + " " +
                        str(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:180])
        if m == "Log.entryAdded" and e["params"]["entry"].get("level") == "error":
            errs.append("console: " + e["params"]["entry"].get("text", "")[:180])
    ws.events = []
    return errs


def external_requests(ws: WS, host: str):
    out = []
    for e in ws.events:
        if e.get("method") == "Network.requestWillBeSent":
            u = e["params"]["request"].get("url", "")
            if u.startswith(("data:", "blob:", "about:", "chrome-extension:")):
                continue
            if host in u or u.startswith("file://"):
                continue
            out.append(u[:160])
    return out


# ------------------------------------------------------------------- 检查项 --
def suite(ws: WS, label: str, host: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def ck(name, expr, pred=None, note=""):
        v = evaluate(ws, expr)
        ok = bool(v) if pred is None else pred(v)
        out.append((name, ok, (note or str(v))[:220]))

    ck("数据加载", "window.__STAR && __STAR.data.n>40000", lambda v: v is True)
    ck("首屏可见人数", "__STAR.visible", lambda v: isinstance(v, int) and v > 0)
    ck("首屏星点数", "__STAR.stars", lambda v: isinstance(v, int) and v > 0)
    ck("深链/时间轴", "JSON.stringify(__STAR.jump(2020,6,18,'day'))",
       lambda v: isinstance(v, str) and "2020" in v)
    ck("当期人数(2020-06-18)", "__STAR.visible", lambda v: isinstance(v, int) and v > 0)
    ck("时间轴步进", "JSON.stringify(__STAR.jump(2020,0,0,'year'))",
       lambda v: isinstance(v, str) and "2020" in v)
    ck("年度人数(2020)", "__STAR.visible", lambda v: isinstance(v, int) and v > 1000)

    # 分析面板
    evaluate(ws, "__STAR.setTab('analysis')")
    ck("分析面板卡片数", "document.querySelectorAll('#analysis .acard').length",
       lambda v: v >= 5)
    ck("分析面板条形数", "document.querySelectorAll('#analysis .bar').length",
       lambda v: isinstance(v, int) and v >= 20)
    ck("分析范围切全库", "(function(){document.querySelector('#ascope button[data-s=all]').click();"
       "return document.querySelectorAll('#analysis .bar').length})()", lambda v: isinstance(v, int) and v >= 20)
    ck("死因反筛生效", "(function(){var b=document.querySelector('#analysis .bar[data-k=cause]');"
       "if(!b)return false;b.click();return __STAR.state.cause!==''})()", lambda v: v is True)
    ck("反筛后人数下降", "__STAR.visible", lambda v: isinstance(v, int) and v > 0)
    ck("清除反筛", "(function(){var c=document.querySelector('#afilters [data-clear=cause]');"
       "if(!c)return false;c.click();return __STAR.state.cause===''})()", lambda v: v is True)

    # 数据说明
    evaluate(ws, "__STAR.setTab('quality')")
    ck("数据说明面板", "document.querySelectorAll('#quality .acard').length",
       lambda v: isinstance(v, int) and v >= 4)

    # 完整生平懒加载
    rid = evaluate(ws, "(function(){for(var i=0;i<__STAR.data.rows.length;i++){"
                   "var r=__STAR.data.rows[i];if(r[16]&&r[0].indexOf('邓丽君')>=0)return r[12];}return 0})()")
    if not rid:
        rid = evaluate(ws, "(function(){for(var i=0;i<__STAR.data.rows.length;i++){"
                       "if(__STAR.data.rows[i][16])return __STAR.data.rows[i][12];}return 0})()")
    evaluate(ws, "__STAR.setTab('list');__STAR.openById(%d)" % int(rid))
    t0 = time.time()
    bio = ""
    while time.time() - t0 < 20:
        bio = evaluate(ws, "(document.querySelector('#fullbio')||{}).innerText||''")
        if bio and len(bio) > 200:
            break
        time.sleep(0.4)
    out.append(("完整生平懒加载", len(bio) > 200, "载入 %d 字 / id=%s" % (len(bio), rid)))
    ck("详情浮层可见", "(function(){var d=document.querySelector('#detail');"
       "var r=d.getBoundingClientRect();return d.style.display!=='none'&&r.height>100})()", lambda v: v is True)
    ck("分片按需请求", "document.querySelectorAll('script[src*=\"bio-\"]').length",
       lambda v: isinstance(v, int) and v >= 1)
    evaluate(ws, "document.querySelector('#dclose')&&document.querySelector('#dclose').click()")

    errs = collect_errors(ws)
    out.append(("运行时异常", len(errs) == 0, "; ".join(errs[:3]) if errs else "0"))
    ext = external_requests(ws, host)
    out.append(("外部网络请求", len(ext) == 0, "; ".join(ext[:3]) if ext else "0"))
    return out


def mobile_suite(ws: WS) -> list[tuple[str, bool, str]]:
    out = []

    def ck(name, expr, pred=None):
        v = evaluate(ws, expr)
        ok = bool(v) if pred is None else pred(v)
        out.append((name, ok, str(v)[:180]))

    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True})
    ws.call("Page.reload", {"ignoreCache": False})
    time.sleep(2.2)
    ck("移动端识别", "__STAR.mobile", lambda v: v is True)
    ck("底栏显示", "getComputedStyle(document.querySelector('#mtabs')).display",
       lambda v: v == "flex")
    ck("默认星图视图", "document.body.className", lambda v: "m-map" in str(v))
    ck("无横向溢出", "document.documentElement.scrollWidth<=window.innerWidth+1",
       lambda v: v is True)
    evaluate(ws, "__STAR.setMView('list')")
    ck("名单视图", "(function(){return getComputedStyle(document.querySelector('#stage')).display==='none'"
       "&&getComputedStyle(document.querySelector('aside')).display!=='none'})()", lambda v: v is True)
    evaluate(ws, "__STAR.setMView('analysis')")
    ck("分析视图", "document.querySelectorAll('#analysis .acard').length",
       lambda v: isinstance(v, int) and v >= 5)
    # 打开详情：星图视图下也必须可见
    evaluate(ws, "__STAR.setMView('map')")
    evaluate(ws, "(function(){for(var i=0;i<__STAR.data.rows.length;i++){"
             "if(__STAR.data.rows[i][16])return __STAR.openById(__STAR.data.rows[i][12]);}return -1})()")
    ck("移动端详情浮层", "(function(){var d=document.querySelector('#detail'),r=d.getBoundingClientRect();"
       "return d.style.display!=='none'&&r.width>300&&r.height>200})()", lambda v: v is True)
    ck("遮罩显示", "document.querySelector('#dmask').classList.contains('show')", lambda v: v is True)
    ck("时间轴触控区", "(function(){var t=document.querySelector('#tl');"
       "return t.getBoundingClientRect().height>=20})()", lambda v: v is True)
    errs = collect_errors(ws)
    out.append(("移动端运行时异常", len(errs) == 0, "; ".join(errs[:3]) if errs else "0"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8899/index.html")
    ap.add_argument("--file-url", default="")
    ap.add_argument("--shot", default="")
    ap.add_argument("--mobile-shot", default="")
    ap.add_argument("--mobile-map-shot", default="")
    args = ap.parse_args()

    wsurl = new_tab(args.url)
    ws = WS(wsurl)
    ws.call("Page.enable")
    ws.call("Runtime.enable")
    ws.call("Log.enable")
    ws.call("Network.enable")
    time.sleep(2.6)
    host = urllib.parse.urlparse(args.url).netloc
    print("\n=== 桌面端 / %s ===" % args.url)
    res = suite(ws, "desktop", host)
    for n, ok, note in res:
        print(("  ✅ " if ok else "  ❌ ") + n + "  " + note)
    if args.shot:
        r = ws.call("Page.captureScreenshot", {"format": "png"})
        Path(args.shot).write_bytes(base64.b64decode(r["data"]))
        print("  截图:", args.shot)

    if args.file_url:
        ws.call("Page.navigate", {"url": args.file_url})
        time.sleep(2.8)
        print("\n=== file:// 直开 ===")
        res2 = suite(ws, "file", "")
        for n, ok, note in res2:
            print(("  ✅ " if ok else "  ❌ ") + n + "  " + note)

    print("\n=== 手机视口 390×844 ===")
    ws.call("Page.navigate", {"url": args.url})
    time.sleep(2.2)
    if args.mobile_map_shot:
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True})
        ws.call("Page.reload", {"ignoreCache": False})
        time.sleep(2.4)
        r = ws.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        Path(args.mobile_map_shot).write_bytes(base64.b64decode(r["data"]))
        print("  手机星图截图:", args.mobile_map_shot)
    res3 = mobile_suite(ws)
    for n, ok, note in res3:
        print(("  ✅ " if ok else "  ❌ ") + n + "  " + note)
    if args.mobile_shot:
        r = ws.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        Path(args.mobile_shot).write_bytes(base64.b64decode(r["data"]))
        print("  手机截图:", args.mobile_shot)

    ws.close()
    allres = res + res3
    bad = [n for n, ok, _ in allres if not ok]
    print("\n合计 %d 项，通过 %d，失败 %d %s" %
          (len(allres), len(allres) - len(bad), len(bad), bad if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
