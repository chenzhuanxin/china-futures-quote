# -*- coding: utf-8 -*-
"""
纯碱(或其他期货品种)行情面板 —— Python 后端服务（仅用标准库，无需 pip install）

数据源：新浪财经期货接口
  - 分时/分钟K线(1/5/15/30/60/120分钟)  getFewMinLine
  - 日K线(含持仓量 p、结算价 s)         getDailyKLine
  - 周K/月K/年K                         由日K线合成
  - 实时行情                            由1分钟线末条 + 当日聚合得到

启动：  python server.py
访问：  浏览器打开 http://127.0.0.1:8100
"""
import json
import os
import sys
import re
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8100
# 支持 PyInstaller 打包：exe 运行时资源在 sys._MEIPASS，源码运行时在同目录
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SYMBOL = "SA2701"          # 默认品种合约（纯碱2701）
DEFAULT_VARIETY = "SA"             # 同品种探测的品种代码

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SINA_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://finance.sina.com.cn",
    "Accept": "*/*",
}

SINA_MIN_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
                "var%20x=/InnerFuturesNewService.getFewMinLine?symbol={s}&type={t}")
SINA_DAY_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
                "var%20x=/InnerFuturesNewService.getDailyKLine?symbol={s}")
SINA_RT_URL = "https://hq.sinajs.cn/list=nf_{s}"   # 新浪实时盘口（nf_ 前缀）

MINUTE_TYPES = {"1", "5", "15", "30", "60", "120"}
PERIODS = ["1", "5", "15", "30", "60", "120", "day", "week", "month", "year"]

# 合约名映射（用于友好显示，可扩展）
# 国内期货品种总表：代码 -> {名称, 交易所}
# 交易所：SHFE 上期所 / INE 能源中心 / DCE 大商所 / CZCE 郑商所 / CFFEX 中金所
VARIETIES = {
    # ---- 上期所 SHFE ----
    "AU": {"name": "沪金", "ex": "SHFE"}, "AG": {"name": "沪银", "ex": "SHFE"},
    "CU": {"name": "沪铜", "ex": "SHFE"}, "AL": {"name": "沪铝", "ex": "SHFE"},
    "ZN": {"name": "沪锌", "ex": "SHFE"}, "PB": {"name": "沪铅", "ex": "SHFE"},
    "NI": {"name": "沪镍", "ex": "SHFE"}, "SN": {"name": "沪锡", "ex": "SHFE"},
    "RB": {"name": "螺纹钢", "ex": "SHFE"}, "HC": {"name": "热卷", "ex": "SHFE"},
    "WR": {"name": "线材", "ex": "SHFE"}, "SS": {"name": "不锈钢", "ex": "SHFE"},
    "RU": {"name": "橡胶", "ex": "SHFE"}, "BU": {"name": "沥青", "ex": "SHFE"},
    "FU": {"name": "燃油", "ex": "SHFE"}, "SP": {"name": "纸浆", "ex": "SHFE"},
    "AO": {"name": "氧化铝", "ex": "SHFE"}, "BR": {"name": "丁二烯橡胶", "ex": "SHFE"},
    "AD": {"name": "铸造铝合金", "ex": "SHFE"},
    # ---- 能源中心 INE ----
    "SC": {"name": "原油", "ex": "INE"}, "LU": {"name": "低硫燃油", "ex": "INE"},
    "NR": {"name": "20号胶", "ex": "INE"}, "BC": {"name": "国际铜", "ex": "INE"},
    "EC": {"name": "集运指数", "ex": "INE"},
    # ---- 大商所 DCE ----
    "A": {"name": "豆一", "ex": "DCE"}, "B": {"name": "豆二", "ex": "DCE"},
    "M": {"name": "豆粕", "ex": "DCE"}, "Y": {"name": "豆油", "ex": "DCE"},
    "P": {"name": "棕榈油", "ex": "DCE"}, "C": {"name": "玉米", "ex": "DCE"},
    "CS": {"name": "玉米淀粉", "ex": "DCE"}, "JD": {"name": "鸡蛋", "ex": "DCE"},
    "LH": {"name": "生猪", "ex": "DCE"}, "RR": {"name": "粳米", "ex": "DCE"},
    "LG": {"name": "原木", "ex": "DCE"}, "L": {"name": "塑料", "ex": "DCE"},
    "PP": {"name": "聚丙烯", "ex": "DCE"}, "V": {"name": "PVC", "ex": "DCE"},
    "EG": {"name": "乙二醇", "ex": "DCE"}, "EB": {"name": "苯乙烯", "ex": "DCE"},
    "PG": {"name": "液化气", "ex": "DCE"}, "I": {"name": "铁矿石", "ex": "DCE"},
    "J": {"name": "焦炭", "ex": "DCE"}, "JM": {"name": "焦煤", "ex": "DCE"},
    "FB": {"name": "纤维板", "ex": "DCE"}, "BB": {"name": "胶合板", "ex": "DCE"},
    # ---- 郑商所 CZCE ----
    "CF": {"name": "棉花", "ex": "CZCE"}, "CY": {"name": "棉纱", "ex": "CZCE"},
    "SR": {"name": "白糖", "ex": "CZCE"}, "TA": {"name": "PTA", "ex": "CZCE"},
    "OI": {"name": "菜油", "ex": "CZCE"}, "RM": {"name": "菜粕", "ex": "CZCE"},
    "FG": {"name": "玻璃", "ex": "CZCE"}, "SA": {"name": "纯碱", "ex": "CZCE"},
    "MA": {"name": "甲醇", "ex": "CZCE"}, "AP": {"name": "苹果", "ex": "CZCE"},
    "CJ": {"name": "红枣", "ex": "CZCE"}, "UR": {"name": "尿素", "ex": "CZCE"},
    "PF": {"name": "短纤", "ex": "CZCE"}, "PK": {"name": "花生", "ex": "CZCE"},
    "SH": {"name": "烧碱", "ex": "CZCE"}, "PX": {"name": "对二甲苯", "ex": "CZCE"},
    # ---- 中金所 CFFEX ----
    "IF": {"name": "沪深300", "ex": "CFFEX"}, "IH": {"name": "上证50", "ex": "CFFEX"},
    "IC": {"name": "中证500", "ex": "CFFEX"}, "IM": {"name": "中证1000", "ex": "CFFEX"},
    "T": {"name": "十年国债", "ex": "CFFEX"}, "TF": {"name": "五年国债", "ex": "CFFEX"},
    "TS": {"name": "两年国债", "ex": "CFFEX"}, "TL": {"name": "三十年期国债", "ex": "CFFEX"},
}
EX_NAMES = {"SHFE": "上期所", "INE": "能源中心", "DCE": "大商所",
            "CZCE": "郑商所", "CFFEX": "中金所"}
CFFEX_CODES = {"IF", "IH", "IC", "IM", "T", "TF", "TS", "TL"}

# 有夜盘且夜盘收于次日凌晨的品种 -> 夜盘收盘时刻(HH:MM)；未列出的有夜盘品种统一收于23:00
NIGHT_END = {
    "SC": "02:30", "AU": "02:30", "AG": "02:30",
    "CU": "01:00", "AL": "01:00", "ZN": "01:00", "PB": "01:00",
    "NI": "01:00", "SN": "01:00", "BC": "01:00", "AO": "01:00", "AD": "01:00",
}


def variety_of(symbol):
    """返回合约所属品种代码（大写字母部分）。"""
    m = re.match(r"^([A-Za-z]+)\d+$", symbol)
    return m.group(1).upper() if m else ""


def get_varieties():
    """返回品种总表，按交易所分组。"""
    by_ex = {}
    for code, v in sorted(VARIETIES.items(), key=lambda kv: kv[0]):
        by_ex.setdefault(v["ex"], []).append(
            {"code": code, "name": v["name"], "ex": v["ex"],
             "ex_name": EX_NAMES.get(v["ex"], v["ex"])})
    order = ["SHFE", "INE", "DCE", "CZCE", "CFFEX"]
    return [{"ex": ex, "ex_name": EX_NAMES.get(ex, ex), "items": by_ex.get(ex, [])}
            for ex in order if ex in by_ex]

# ---------------------------------------------------------------------------
# 内存缓存（线程安全）
# ---------------------------------------------------------------------------
_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fetcher):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fetcher()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


# ---------------------------------------------------------------------------
# 底层网络 + 解析
# ---------------------------------------------------------------------------
def http_get(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=headers or SINA_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def parse_jsonp_array(text):
    """解析新浪 JSONP：去掉 /*...*/ 头与 var x= 包装，取出 JSON 数组。"""
    if not text:
        return None
    i = text.find("[")
    j = text.rfind("]")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except Exception:
        return None


def _fnum(v):
    """字符串数值 -> float；失败返回 None。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 数据获取
# ---------------------------------------------------------------------------
def fetch_minutes(symbol, mtype):
    """获取分钟K线 [{d,o,h,l,c,v,p}]。"""
    url = SINA_MIN_URL.format(s=urllib.parse.quote(symbol), t=mtype)
    ttl = 12  # 秒

    def do():
        arr = parse_jsonp_array(http_get(url))
        return arr or []

    return cached("min:%s:%s" % (symbol, mtype), ttl, do)


def fetch_daily(symbol, ttl=40):
    """获取日K线 [{d,o,h,l,c,v,p,s}]。"""
    url = SINA_DAY_URL.format(s=urllib.parse.quote(symbol))

    def do():
        arr = parse_jsonp_array(http_get(url))
        return arr or []

    return cached("day:%s" % symbol, ttl, do)


def fetch_realtime(symbol, ttl=6):
    """获取新浪实时盘口（nf_ 前缀）。返回字段字典或 None。"""
    url = SINA_RT_URL.format(s=urllib.parse.quote(symbol))

    def do():
        text = http_get(url)
        m = re.search(r'="(.*)"', text)
        if not m:
            return None
        f = m.group(1).split(",")
        if not f or not f[0]:
            return None
        def g(i):
            try:
                return float(f[i])
            except (ValueError, IndexError, TypeError):
                return None
        time_str = f[1] if len(f) > 1 else ""
        date_str = f[17] if len(f) > 17 else ""
        hm = ""
        if len(time_str) == 6:
            hm = "%s:%s:%s" % (time_str[0:2], time_str[2:4], time_str[4:6])
        return {
            "name": f[0],
            "time": hm,
            "date": date_str,
            "update": (date_str + " " + hm).strip(),
            "open": g(2), "high": g(3), "low": g(4), "last": g(5),
            "buy1": g(6), "sell1": g(7),
            "settle": g(9), "prev_settle": g(10),
            "buy_vol": g(11), "sell_vol": g(12),
            "position": g(13), "volume": g(14),
        }

    return cached("rt:%s" % symbol, ttl, do)


def get_line(symbol):
    """分时数据：从上一交易日/当日夜盘(21:00)开盘起，到最新，含均价 avg。"""
    raw = fetch_minutes(symbol, "1")
    bars = [norm_bar(b) for b in raw if b.get("d")]
    bars.sort(key=lambda b: b["date"])
    if not bars:
        return []
    last = bars[-1]
    try:
        ldt = datetime.strptime(last["date"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            ldt = datetime.strptime(last["date"], "%Y-%m-%d")
        except ValueError:
            return bars
    # 起点：若最新bar在日盘(<21点)，夜盘属前一天；否则属当天21点
    start_date = ldt.date()
    if ldt.hour < 21:
        start_date -= timedelta(days=1)
    start_key = start_date.strftime("%Y-%m-%d") + " 21:00:00"
    line = [b for b in bars if b["date"] >= start_key]
    # 计算均价（VWAP）
    cs = 0.0
    cv = 0
    for b in line:
        cs += (b["close"] or 0) * b["volume"]
        cv += b["volume"]
        b["avg"] = cs / cv if cv else None
    return line


def _hm_min(h):
    """HH:MM -> 当日分钟数；凌晨(<09)视为次日(加1440)。"""
    try:
        a, b = h.split(":"); m = int(a) * 60 + int(b)
        return m + 1440 if int(a) < 9 else m
    except Exception:
        return 0


def _min_hm(m):
    return "%02d:%02d" % ((m % 1440) // 60, m % 60)


def line_meta(symbol, data):
    """分时会话元数据：昨结算价(base)、横轴起点(start)、终点(end)、是否跨日、分钟数(duration)。"""
    if not data:
        return {"base": None, "start": None, "end": None, "cross_day": False, "duration": 0}
    today = data[0]["date"][:10]
    base = None
    daily = fetch_daily(symbol)
    for d in daily:
        if d.get("d") and d["d"] < today:
            base = _fnum(d.get("s"))
            if base is None:
                base = _fnum(d.get("c"))
            break
    v = variety_of(symbol)
    start = data[0]["date"][11:16]
    first_hour = int(data[0]["date"][11:13])
    last = data[-1]["date"][11:16]
    if v in ("IF", "IH", "IC", "IM"):
        cand = "15:00"
    elif v in ("T", "TF", "TS", "TL"):
        cand = "15:15"
    elif first_hour >= 21:
        cand = NIGHT_END.get(v, "23:00")
    else:
        cand = "15:00"
    start_min = _hm_min(start)
    end_abs = max(_hm_min(cand), _hm_min(last))
    if end_abs < start_min:
        end_abs += 1440
    duration = end_abs - start_min + 1  # 含起点与终点的分钟槽数
    cross_day = end_abs >= 1440
    return {"base": base, "start": start, "end": _min_hm(end_abs),
            "cross_day": cross_day, "duration": duration}


def norm_bar(b):
    """把新浪字段标准化为数值字典。"""
    return {
        "date": b.get("d", ""),
        "open": _fnum(b.get("o")),
        "high": _fnum(b.get("h")),
        "low": _fnum(b.get("l")),
        "close": _fnum(b.get("c")),
        "volume": int(_fnum(b.get("v")) or 0),
        "position": int(_fnum(b.get("p")) or 0),      # 持仓量
        "settle": _fnum(b.get("s")),                  # 结算价（日K才有）
    }


def aggregate_daily(daily, mode):
    """把日K按 周/月/年 合成。返回新K线列表（升序）。"""
    groups = {}
    for b in daily:
        try:
            dt = datetime.strptime(b["date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if mode == "week":
            iso = dt.isocalendar()
            key = (iso[0], iso[1])
            label = "%04d-W%02d" % key
        elif mode == "month":
            key = (dt.year, dt.month)
            label = "%04d-%02d" % key
        elif mode == "year":
            key = dt.year
            label = "%04d" % key
        else:
            continue
        g = groups.setdefault(key, {"label": label, "last_date": b["date"],
                                    "bars": []})
        g["bars"].append(b)
        if b["date"] > g["last_date"]:
            g["last_date"] = b["date"]

    out = []
    for key in sorted(groups.keys()):
        g = groups[key]
        bs = g["bars"]
        out.append({
            "date": g["last_date"],
            "label": g["label"],
            "open": bs[0]["open"],
            "high": max(x["high"] for x in bs),
            "low": min(x["low"] for x in bs),
            "close": bs[-1]["close"],
            "volume": sum(x["volume"] for x in bs),
            "position": bs[-1]["position"],
            "settle": bs[-1]["settle"],
        })
    return out


def get_kline(symbol, period):
    """返回指定周期的K线数据列表。"""
    if period in MINUTE_TYPES:
        raw = fetch_minutes(symbol, period)
        bars = [norm_bar(b) for b in raw if b.get("d")]
    elif period == "day":
        raw = fetch_daily(symbol)
        bars = [norm_bar(b) for b in raw if b.get("d")]
    elif period in ("week", "month", "year"):
        raw = fetch_daily(symbol, ttl=300)
        daily = [norm_bar(b) for b in raw if b.get("d")]
        bars = aggregate_daily(daily, period)
    else:
        return []
    # 排序 + 过滤无效
    bars = [b for b in bars if b["open"] is not None and b["close"] is not None]
    bars.sort(key=lambda b: b["date"])
    return bars


def get_quote(symbol):
    """实时行情：主数据用分钟+日K聚合（各品种可靠）；商品期货再用新浪盘口补充买/卖价量。"""
    raw = fetch_minutes(symbol, "1")
    if not raw:
        return None
    bars = [norm_bar(b) for b in raw if b.get("d")]
    bars.sort(key=lambda b: b["date"])
    if not bars:
        return None
    last = bars[-1]
    today = last["date"][:10]
    today_bars = [b for b in bars if b["date"][:10] == today]
    if not today_bars:
        today_bars = [last]

    price = last["close"]
    o = today_bars[0]["open"]
    hi = max(b["high"] for b in today_bars)
    lo = min(b["low"] for b in today_bars)
    vol = sum(b["volume"] for b in today_bars)
    pos = last["position"]

    # 昨收 / 昨结算 / 今日结算：来自日K
    daily = fetch_daily(symbol)
    daily = [d for d in daily if d.get("d")]
    daily.sort(key=lambda d: d["d"])
    prev_close = prev_settle = today_settle = None
    for d in daily:
        if d["d"] < today:
            prev_close = _fnum(d.get("c"))
            prev_settle = _fnum(d.get("s"))
        elif d["d"] == today:
            today_settle = _fnum(d.get("s"))
    base = prev_settle if prev_settle is not None else prev_close
    change = change_pct = None
    if base:
        change = price - base
        change_pct = change / base * 100.0

    quote = {
        "symbol": symbol,
        "name": friendly_name(symbol),
        "price": price,
        "prev_close": prev_close,
        "prev_settle": prev_settle,
        "settle": today_settle,
        "change": change,
        "change_pct": change_pct,
        "open": o,
        "high": hi,
        "low": lo,
        "volume": vol,
        "position": pos,
        "buy1": None, "sell1": None, "buy_vol": None, "sell_vol": None,
        "update": last["date"],
    }
    # 商品期货：用新浪盘口接口补充买/卖价量（中金所字段格式不同，暂不取盘口）
    if variety_of(symbol) not in CFFEX_CODES:
        rt = fetch_realtime(symbol)
        if rt:
            quote["buy1"] = rt.get("buy1")
            quote["sell1"] = rt.get("sell1")
            quote["buy_vol"] = rt.get("buy_vol")
            quote["sell_vol"] = rt.get("sell_vol")
            if rt.get("update"):
                quote["update"] = rt.get("update")
    return quote


def friendly_name(symbol):
    m = re.match(r"^([A-Za-z]+)(\d+)$", symbol)
    if not m:
        return symbol
    var, num = m.group(1).upper(), m.group(2)
    base = VARIETIES.get(var, {}).get("name", var)
    return "%s%s" % (base, num)


# ---------------------------------------------------------------------------
# 同品种合约列表（探测日K接口，返回存在的合约及其最新报价）
# ---------------------------------------------------------------------------
def _candidate_codes(variety, start_year, end_year):
    codes = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            codes.append("%s%02d%02d" % (variety, y % 100, m))
    return codes


def _delivery_ym(symbol):
    """从合约代码提取交割年月，如 SA2701 -> (2027, 1)。"""
    m = re.match(r"^[A-Za-z]+(\d{4})$", symbol)
    if not m:
        return None
    yy = int(m.group(1)[:2])
    mm = int(m.group(1)[2:])
    if mm < 1 or mm > 12:
        return None
    return (2000 + yy, mm)


def get_contracts(variety):
    def build():
        this_year = datetime.now().year
        cur_ym = (datetime.now().year, datetime.now().month)
        codes = _candidate_codes(variety, this_year - 2, this_year + 2)
        result = []
        for code in codes:
            dym = _delivery_ym(code)
            if dym is None or dym < cur_ym:
                continue          # 交割月份已过 -> 已到期合约，不展示
            daily = fetch_daily(code, ttl=1800)
            if not daily:
                continue          # 尚未挂牌
            last = daily[-1]
            date = last.get("d", "")
            close = _fnum(last.get("c"))
            base = _fnum(last.get("s")) or close
            pct = ((close - base) / base * 100.0) if (base and close is not None) else None
            result.append({
                "symbol": code,
                "name": friendly_name(code),
                "close": close,
                "change_pct": pct,
                "volume": int(_fnum(last.get("v")) or 0),
                "position": int(_fnum(last.get("p")) or 0),
                "date": date,
            })
        # 按交割月份（到期时间）从近到远排列
        result.sort(key=lambda c: _delivery_ym(c["symbol"]) or (9999, 99))
        return result

    return cached("contracts:%s" % variety, 600, build)


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默访问日志

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _query(self):
        from urllib.parse import urlparse, parse_qs
        return parse_qs(urlparse(self.path).query)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/":
                return self._serve_static("index.html", "text/html; charset=utf-8")
            if path == "/api/quote":
                q = self._query()
                symbol = (q.get("symbol", [DEFAULT_SYMBOL])[0]).upper()
                quote = get_quote(symbol)
                if quote is None:
                    return self._json({"error": "未获取到行情数据"}, 404)
                return self._json({"ok": True, "data": quote})
            if path == "/api/kline":
                q = self._query()
                symbol = (q.get("symbol", [DEFAULT_SYMBOL])[0]).upper()
                period = q.get("period", ["day"])[0]
                if period not in PERIODS:
                    return self._json({"error": "无效周期"}, 400)
                data = get_kline(symbol, period)
                return self._json({"ok": True,
                                   "symbol": symbol,
                                   "name": friendly_name(symbol),
                                   "period": period,
                                   "data": data})
            if path == "/api/line":
                q = self._query()
                symbol = (q.get("symbol", [DEFAULT_SYMBOL])[0]).upper()
                data = get_line(symbol)
                meta = line_meta(symbol, data)
                return self._json({"ok": True, "symbol": symbol,
                                   "data": data, **meta})
            if path == "/api/contracts":
                q = self._query()
                variety = (q.get("variety", [DEFAULT_VARIETY])[0]).upper()
                return self._json({"ok": True, "variety": variety,
                                   "contracts": get_contracts(variety)})
            if path == "/api/periods":
                return self._json({"ok": True, "periods": PERIODS})
            if path == "/api/varieties":
                return self._json({"ok": True, "groups": get_varieties()})
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/"):], None)
            return self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa
            return self._json({"error": str(e)}, 500)

    def _serve_static(self, filename, ctype):
        safe = os.path.basename(filename)
        fp = os.path.join(BASE_DIR, safe)
        if not os.path.isfile(fp):
            return self._json({"error": "file not found"}, 404)
        with open(fp, "rb") as f:
            body = f.read()
        if ctype is None:
            if safe.endswith(".html"):
                ctype = "text/html; charset=utf-8"
            elif safe.endswith(".js"):
                ctype = "application/javascript; charset=utf-8"
            elif safe.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            else:
                ctype = "application/octet-stream"
        self._send(200, body, ctype)


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("=" * 62)
    print("  纯碱行情面板 服务已启动")
    print("  请在浏览器打开:  http://%s:%d" % (HOST, PORT))
    print("  默认品种合约:  %s（纯碱2701）" % DEFAULT_SYMBOL)
    print("  停止服务:  关闭本窗口 / 按 Ctrl+C")
    print("=" * 62)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        httpd.server_close()


if __name__ == "__main__":
    main()
