#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download helper for best-track datasets and Natural Earth boundaries.

CMA may require browser interaction; if automatic discovery fails this script
prints the official download page instead of guessing a hidden URL.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import zipfile
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 typhoon-track-skill/1.0"


def fetch(url: str, dest: Path, timeout=120):
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("GET", url)
    with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"Saved: {dest} ({dest.stat().st_size} bytes)")
    return dest


def jma(args):
    out = Path(args.out)
    if args.all:
        url = "https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip"
        z = fetch(url, out / "bst_all.zip")
        with zipfile.ZipFile(z) as zz:
            zz.extractall(out)
        print("Extracted to", out)
    else:
        y = args.year
        if not y:
            raise SystemExit("JMA: use --all or --year YYYY")
        url = f"https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst{y}.txt"
        fetch(url, out / f"bst{y}.txt")


def ibtracs(args):
    subset = args.subset.upper()
    allowed = {"ALL", "WP", "NI", "SI", "SP", "EP", "NA", "SA"}
    if subset not in allowed:
        raise SystemExit(f"IBTrACS subset must be one of: {sorted(allowed)}")
    out = Path(args.out)
    if args.format == "csv":
        fn = f"ibtracs.{subset}.list.v04r01.csv"
        url = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/" + fn
    else:
        fn = f"IBTrACS.{subset}.v04r01.nc"
        url = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/netcdf/" + fn
    fetch(url, out / fn, timeout=300)


def jtwc(args):
    basin = args.basin.upper()
    if basin not in {"WP", "IO", "SH", "AL", "EP", "CP"}:
        raise SystemExit("JTWC basin: WP|IO|SH|AL|EP|CP")
    fn = f"b{basin.lower()}{args.storm_number:02d}{args.year}.dat"
    # Public open ATCF repository mirror. See DATA_SOURCES.md for official JTWC landing page.
    url = f"https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/{args.year}/{fn}"
    fetch(url, Path(args.out) / fn)


def cma(args):
    page = "https://tcdata.typhoon.org.cn/zjljsjj.html"
    fn = f"CH{args.year}BST.txt"
    print(f"Trying to discover {fn} from CMA official page...")
    try:
        r = requests.get(page, headers={"User-Agent": UA}, timeout=45)
        r.raise_for_status()
        # CMA may expose annual links directly or behind a relative path.
        patterns = [
            re.compile(r'''href=["']([^"']*''' + re.escape(fn) + r'''[^"']*)["']''', re.I),
            re.compile(r'''["']([^"']*''' + re.escape(fn) + r'''[^"']*)["']''', re.I),
        ]
        m = next((p.search(r.text) for p in patterns if p.search(r.text)), None)
        if not m:
            raise RuntimeError("annual file URL not found in HTML")
        url = urljoin(page, m.group(1))
        fetch(url, Path(args.out) / fn)
    except Exception as e:
        print("Automatic CMA download failed:", e)
        print("Please download manually from:")
        print(page)
        print("Target annual filename:", fn)
        print("CMA's page also provides the dataset notes, citation rules and updates.")
        return 4


def naturalearth(args):
    out = Path(args.out)
    if args.layer == "admin1":
        fn = "ne_10m_admin_1_states_provinces.zip"
        url = "https://www.naturalearthdata.com/download/10m/cultural/" + fn
    elif args.layer == "admin1-lines":
        fn = "ne_10m_admin_1_states_provinces_lines.zip"
        url = "https://www.naturalearthdata.com/download/10m/cultural/" + fn
    else:
        fn = "ne_10m_admin_0_countries.zip"
        url = "https://www.naturalearthdata.com/download/10m/cultural/" + fn
    z = fetch(url, out / fn)
    target = out / z.stem
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zz:
        zz.extractall(target)
    print("Extracted to", target)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="dataset", required=True)

    p = sp.add_parser("cma"); p.add_argument("--year", type=int, required=True); p.add_argument("--out", default="references")
    p = sp.add_parser("jma"); p.add_argument("--year", type=int); p.add_argument("--all", action="store_true"); p.add_argument("--out", default="references")
    p = sp.add_parser("jtwc"); p.add_argument("--year", type=int, required=True); p.add_argument("--basin", default="WP"); p.add_argument("--storm-number", type=int, required=True); p.add_argument("--out", default="references")
    p = sp.add_parser("ibtracs"); p.add_argument("--subset", default="WP"); p.add_argument("--format", choices=["csv","netcdf"], default="csv"); p.add_argument("--out", default="references")
    p = sp.add_parser("naturalearth"); p.add_argument("--layer", choices=["admin0","admin1","admin1-lines"], default="admin1"); p.add_argument("--out", default="data")
    args = ap.parse_args()

    return globals()[args.dataset](args) or 0

if __name__ == "__main__":
    raise SystemExit(main())
