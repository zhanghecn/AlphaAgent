# -*- coding: utf-8 -*-
"""高位接力 · 好差票验证月度文件表格 → 文字条目式（主人要求：不用表格，标题+换行）。

每票一个小节:
### 名称 代码｜买入日｜结果
- 首刻 / 次日开收 / 断板收益
- 接力链 + 今天开
- 地基 / 位置 / 均线 / 10日线
- 反包 / 前波 / 环境
- v1.3方案点(不符合在哪) / 链式方案

已转换的文件跳过(幂等)。宿主机: uv run python relay_md_reformat.py
"""
import os

BASE = "/root/project/ai/vnpy/量化因子研究/高位接力/好差票验证"


def parse_cells(ln):
    return [c.strip() for c in ln.split("|")]


def fmt_ticket(cells, kind):
    """cells: [空,代码,名称,买入日,月日序,方案点,链式,首刻,结果,次日开,次日收,断板,链,买入开,地基,位置,均线,MA10,反包,前波,环境,不符合]"""
    code, name, date = cells[1], cells[2], cells[3]
    plan, chain = cells[5].replace("*", ""), cells[6]
    first, result = cells[7], cells[8]
    n_open, n_close, hold = cells[9], cells[10], cells[11]
    lk, buyo = cells[12], cells[13]
    jidi, pos, ma, ma10 = cells[14], cells[15], cells[16], cells[17]
    fb, qb, env = cells[18], cells[19], cells[20]
    bad = cells[21] if len(cells) > 21 else ""
    out = [f"### {name} {code}｜{date}｜{kind}：{result}", "",
           f"- 首刻：{first}｜次日开 {n_open}｜次日收 {n_close}｜断板收益 {hold}",
           f"- 接力链：{lk}｜今天开 {buyo}",
           f"- 地基：{jidi}｜距新高 {pos}｜均线 {ma}｜距10日线 {ma10}",
           f"- 反包：{fb}｜前波 {qb}｜当日涨停家数 {env}",
           f"- v1.3方案点：{plan}" + (f"（不符合：{bad}）" if bad and bad != "—" else ""),
           f"- 链式方案：{chain}", ""]
    return out


def convert(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if not any(x.startswith("| 代码") for x in lines):
        return False                          # 已转换或无表格
    out = []
    kind = ""
    for ln in lines:
        s = ln.strip()
        if s.startswith("| 代码") or s.startswith("|---"):
            continue                          # 表头/分隔行丢弃
        if s.startswith("## 坏票"):
            kind = "坏票"
            out.append(ln)
            continue
        if s.startswith("## 好票"):
            kind = "好票"
            out.append(ln)
            continue
        if s.startswith("### 第"):            # 周分块标题丢弃(时间序已够)
            continue
        if s.startswith("|") and ".S" in s:
            cells = parse_cells(ln)
            if len(cells) >= 21:
                out.extend(fmt_ticket(cells, kind))
                continue
        out.append(ln)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return True


def main():
    n = 0
    for grp in ["二接三阳", "二接三阴", "三接四阳", "三接四阴"]:
        d = f"{BASE}/{grp}"
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".md") and convert(f"{d}/{fn}"):
                n += 1
    print(f"转换 {n} 个月度文件为文字条目式")


if __name__ == "__main__":
    main()
