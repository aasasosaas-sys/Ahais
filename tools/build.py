#!/usr/bin/env python3
"""PDF（地理 合格ライン問題集）→ サイト用データを生成する。

使い方: python3 tools/build.py <PDFが入ったフォルダ>
  - PDFのタイトル（例: 第1章_気候_本冊_iPad横.html）から 章・本冊/解答・版 を判定
  - iPad横版を優先し、無ければA4版を使う
  - img/ にページ画像(webp)、data.js に問題データを書き出す
"""
import html, json, os, re, subprocess, sys, glob, shutil, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIRC = "①②③④⑤⑥⑦⑧⑨"
DPI = 144

def title_of(pdf):
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
    m = re.search(r"^Title:\s*(.*)$", out, re.M)
    return m.group(1).strip() if m else ""

def parse_bbox(pdf):
    xml = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, text=True).stdout
    pages = []
    for pm in re.finditer(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', xml, re.S):
        W, H, body = float(pm.group(1)), float(pm.group(2)), pm.group(3)
        lines = []
        for lm in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', body, re.S):
            words = [dict(x0=float(a), y0=float(b), x1=float(c), y1=float(d), t=html.unescape(t))
                     for a, b, c, d, t in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', lm.group(5))]
            lines.append(dict(x0=float(lm.group(1)), y0=float(lm.group(2)), x1=float(lm.group(3)), y1=float(lm.group(4)), words=words,
                              t="".join(w["t"] for w in words)))
        pages.append(dict(W=W, H=H, lines=lines, text="\n".join(l["t"] for l in lines)))
    return pages

def page_qid(p, word=False):
    for l in p["lines"]:
        for w in l["words"]:
            m = re.match(r"(\d+-\d{2})(?!\d{1,2}\b)", w["t"])
            if m and (w["y1"] - w["y0"]) > 30:
                return (m.group(1), w) if word else m.group(1)
    return None

JOBS = []

def render(pdf, outdir, pages_idx):
    os.makedirs(outdir, exist_ok=True)
    for i, name in pages_idx.items():
        JOBS.append((pdf, i + 1, os.path.join(outdir, name + ".webp")))

def _render_one(job):
    pdf, pg, out = job
    if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(pdf):
        return
    base = out[:-5] + ".tmp"
    subprocess.run(["pdftoppm", "-f", str(pg), "-l", str(pg), "-singlefile", "-r", str(DPI), "-png", pdf, base], check=True)
    from PIL import Image
    Image.open(base + ".png").convert("RGB").save(out, quality=74, method=4)
    os.remove(base + ".png")

def hotspots(p, n):
    """問題ページ上の①〜(n)の位置（ページに対する%）"""
    W, H = p["W"], p["H"]
    found = {}
    for li, l in enumerate(p["lines"]):
        for wi, w in enumerate(l["words"]):
            t = w["t"]
            if not t or t[0] not in CIRC or "〜" in t or "～" in t:
                continue
            k = CIRC.index(t[0]) + 1
            if k > n:
                continue
            nxt = l["words"][wi + 1]["t"] if wi + 1 < len(l["words"]) else ""
            listy = wi == 0 and (len(t) > 1 or (nxt and nxt[0] not in CIRC))
            found[k] = dict(li=li, w=w, listy=listy, line=l)  # 後に出たものを優先
    spots = []
    for k in sorted(found):
        f = found[k]; w = f["w"]; L = f["line"]
        if f["listy"]:
            x0, y0 = L["x0"], L["y0"]
            # 同じ列で次に出てくる選択肢の行まで
            below = [g["line"]["y0"] for g in found.values() if g["listy"] and abs(g["line"]["x0"] - x0) < 3 and g["line"]["y0"] > y0 + 2]
            y1 = min(below) if below else None
            if y1 is None:
                cont = [l for l in p["lines"] if l["y0"] >= L["y1"] - 4 and l["y0"] < L["y1"] + 30 * 3 and x0 - 2 <= l["x0"] <= x0 + 30]
                y1 = L["y1"]
                for l in sorted(cont, key=lambda l: l["y0"]):
                    if l["y0"] - y1 > 12 or any(c[0] in CIRC for c in [l["words"][0]["t"]] if l["words"]):
                        break
                    y1 = l["y1"]
            x1 = max([l["x1"] for l in p["lines"] if y0 - 1 <= l["y0"] < y1 - 2 and x0 - 2 <= l["x0"] <= x0 + 30] + [L["x1"]])
            x0 -= 4; y0 -= 3; x1 += 4
        else:
            pad = 9
            x0, y0, x1, y1 = w["x0"] - pad, w["y0"] - 2, w["x1"] + pad, w["y1"] + 2
        spots.append(dict(k=k, x=round(x0 / W * 100, 2), y=round(y0 / H * 100, 2),
                          w=round((x1 - x0) / W * 100, 2), h=round((y1 - y0) / H * 100, 2)))
    return spots

def main(src):
    docs = {}
    for pdf in glob.glob(os.path.join(src, "*.pdf")):
        t = title_of(pdf)
        m = re.match(r"第(\d+)章_(.+?)_(本冊|解答解説)_(iPad横|A4)", t)
        if not m:
            print("skip", pdf, t); continue
        ch, name, kind, ver = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if kind == "解答解説":
            key = (ch, kind, "")
            if key not in docs or (ver == "iPad横" and docs[key][1] != "iPad横"):
                docs[key] = (pdf, ver, name)
        else:
            docs[(ch, kind, ver)] = (pdf, ver, name)  # 本冊は横(iPad)・縦(A4)両方使う
    chapters = {}
    for (ch, kind, _v), (pdf, ver, name) in sorted(docs.items(), key=lambda kv: (kv[0][0], kv[0][1] != "本冊", kv[0][2] != "iPad横")):
        print(f"第{ch}章 {kind} ({ver}) {pdf}")
        C = chapters.setdefault(ch, dict(ch=ch, name=name, questions={}, summary=[], summaryP=[], hasBook=False, hasAns=False))
        pages = parse_bbox(pdf)
        pages_idx = {}
        d = f"img/ch{ch}"
        if kind == "本冊":
            C["hasBook"] = True
            land = ver == "iPad横"
            sfx, pre = ("", "") if land else ("P", "p")
            for i, p in enumerate(pages):
                qid = page_qid(p)
                if qid and "割ライン" in p["text"]:
                    q = C["questions"].setdefault(qid, dict(id=qid))
                    txt = p["text"]
                    q[pre + "q"] = f"{d}/{pre}q{qid.split('-')[1]}"
                    m2 = re.search(r"([①-⑨])\s*[〜～]\s*([①-⑨])\s*の\s*うち", txt.replace("\n", ""))
                    n = CIRC.index(m2.group(2)) + 1 if m2 else max([CIRC.index(c) + 1 for c in txt if c in CIRC] or [4])
                    q["spots" + sfx] = hotspots(p, n)
                    pages_idx[i] = f"{pre}q{qid.split('-')[1]}"
                    if "n" in q:
                        continue
                    lm = re.search(r"([6789])割ライン", txt); q["line"] = int(lm.group(1)) if lm else 0
                    cm = re.search(r"過去問に\s*(\d+)回", txt); q["count"] = int(cm.group(1)) if cm else None
                    m2 = re.search(r"([①-⑨])\s*[〜～]\s*([①-⑨])\s*の\s*うち", txt.replace("\n", ""))
                    n = CIRC.index(m2.group(2)) + 1 if m2 else max([CIRC.index(c) + 1 for c in txt if c in CIRC] or [4])
                    q["n"] = n
                    # 出典: 見出しブロックの語
                    src_words = []
                    hw = page_qid(p, True)[1]
                    for l in p["lines"]:
                        if hw["y0"] - 12 <= l["y0"] <= hw["y1"] + 2:
                            for w in l["words"]:
                                if not (hw["x0"] - 5 <= w["x0"] <= hw["x0"] + 330): continue
                                t_ = w["t"][len(qid):] if w["t"].startswith(qid) else w["t"]
                                if t_ and "割ライン" not in t_ and "過去問に" not in t_ and "回出た" not in t_ and not re.fullmatch(r"図\d*", t_):
                                    src_words.append((w["y0"] // 8, w["x0"], t_))
                    q["src"] = " ".join(t for _, _, t in sorted(src_words))
                else:
                    name_ = f"{pre}s{i+1:02d}"
                    C["summary" + sfx].append(f"{d}/{name_}")
                    pages_idx[i] = name_
        else:
            C["hasAns"] = True
            table = {}
            for i, p in enumerate(pages):
                qid = page_qid(p)
                if not qid:
                    if i == 0:
                        pages_idx[i] = "a00"; C["ansTable"] = f"{d}/a00"
                        table = {f"{ch}-{a}": CIRC.index(c) + 1 for a, c in re.findall(r"^(\d{2})\n([①-⑨])$", p["text"], re.M)}
                    continue
                q = C["questions"].setdefault(qid, dict(id=qid))
                txt = p["text"]
                am = re.search(r"正解\s*([①-⑨])", txt)
                if am: q["ans"] = CIRC.index(am.group(1)) + 1
                tm = re.search(r"この問題で身につく知識\s*\n?●\s*(.+?)(?:\s*過去問\d|\n)", txt)
                if tm: q["title"] = tm.group(1).strip()
                q["a"] = f"{d}/a{qid.split('-')[1]}"
                if "line" not in q:
                    lm = re.search(r"([6789])割ライン", txt); q["line"] = int(lm.group(1)) if lm else 0
                pages_idx[i] = f"a{qid.split('-')[1]}"
            for qid, a in table.items():
                q = C["questions"].setdefault(qid, dict(id=qid))
                if q.get("ans") and q["ans"] != a:
                    print("  !! 正解不一致", qid, q["ans"], a)
                q["ans"] = a
        render(pdf, os.path.join(ROOT, d), pages_idx)
    out = []
    for ch in sorted(chapters):
        C = chapters[ch]
        C["questions"] = [C["questions"][k] for k in sorted(C["questions"], key=lambda s: int(s.split("-")[1]))]
        out.append(C)
        print(f"第{ch}章 {C['name']}: {len(C['questions'])}問, まとめ{len(C['summary'])}p, 本冊={C['hasBook']} 解答={C['hasAns']}")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(os.cpu_count() or 4) as ex:
        list(ex.map(_render_one, JOBS))
    keep = {os.path.abspath(j[2]) for j in JOBS}
    for f in glob.glob(os.path.join(ROOT, "img", "*", "*")):
        if os.path.abspath(f) not in keep:
            os.remove(f)
    with open(os.path.join(ROOT, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.BOOK = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n")

if __name__ == "__main__":
    main(sys.argv[1])
