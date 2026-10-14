#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Robust multi-source tropical-cyclone best-track reader.

Supported:
- CMA annual best-track text (CHYYYYBST.txt)
- JMA/RSMC Tokyo best-track text (bst_all.txt / bstYYYY.txt)
- JTWC/ATCF b-deck (*.dat)
- NOAA IBTrACS v04r01 CSV / NetCDF

The output is a normalized pandas.DataFrame. Wind averaging periods are retained
rather than silently homogenized.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import re
import warnings

import numpy as np
import pandas as pd


class TrackFormatError(RuntimeError):
    pass


BASE_COLS = [
    "time_utc", "lat", "lon", "pressure_hpa", "vmax", "vmax_unit",
    "wind_avg_min", "native_category", "source", "source_detail",
    "storm_id", "storm_name", "basin", "note",
]
EXTRA_COLS = [
    "rmw_nm", "roci_nm", "p_outer_hpa",
    "r34_ne_nm", "r34_se_nm", "r34_sw_nm", "r34_nw_nm",
    "r50_ne_nm", "r50_se_nm", "r50_sw_nm", "r50_nw_nm",
    "r64_ne_nm", "r64_se_nm", "r64_sw_nm", "r64_nw_nm",
    "jma_r50_long_dir", "jma_r50_long_nm", "jma_r50_short_nm",
    "jma_r30_long_dir", "jma_r30_long_nm", "jma_r30_short_nm",
    "cma_owd_ms",
]
ALL_COLS = BASE_COLS + EXTRA_COLS


def _float(v):
    try:
        if v is None:
            return np.nan
        s = str(v).strip()
        if not s or s.lower() in {"nan", "none", "--"}:
            return np.nan
        x = float(s)
        if x <= -9000:
            return np.nan
        return x
    except Exception:
        return np.nan


def normalize_lon(x: float) -> float:
    return ((float(x) + 180.0) % 360.0) - 180.0


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise TrackFormatError("没有解析到任何有效台风路径点。")
    for c in ALL_COLS:
        if c not in df.columns:
            df[c] = np.nan

    df["time_utc"] = pd.to_datetime(df["time_utc"], errors="coerce", utc=True)
    for c in ["lat", "lon", "pressure_hpa", "vmax", "wind_avg_min"] + EXTRA_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c not in {
            "jma_r50_long_dir", "jma_r30_long_dir"
        } else df[c]

    df = df.dropna(subset=["time_utc", "lat", "lon"]).copy()
    if df.empty:
        raise TrackFormatError("记录存在，但时间或经纬度全部无效。")
    bad_lat = (df["lat"] < -90) | (df["lat"] > 90)
    if bad_lat.any():
        raise TrackFormatError("发现纬度超出 [-90, 90]。")
    df["lon"] = df["lon"].map(normalize_lon)
    df = df.sort_values("time_utc").reset_index(drop=True)
    return df[ALL_COLS]


def _header_name(line: str) -> str:
    # CMA/JMA both reserve a 20-character name field around columns 31-50.
    name = line[30:50].strip() if len(line) >= 31 else ""
    if name:
        return name
    parts = line.split()
    if parts and re.fullmatch(r"\d{8}", parts[-1]) and len(parts) >= 2:
        return parts[-2]
    return parts[-1] if parts else "UNKNOWN"


def _year_from_intl_id(iid: str, lower_bound: int = 49) -> Optional[int]:
    if len(iid) < 2 or not iid[:2].isdigit():
        return None
    yy = int(iid[:2])
    return 1900 + yy if yy >= lower_bound else 2000 + yy


def detect_source(path: str | Path) -> str:
    p = Path(path)
    name = p.name.lower()
    if p.suffix.lower() in {".nc", ".nc4", ".cdf"}:
        return "ibtracs"
    if name.startswith("ibtracs") and p.suffix.lower() == ".csv":
        return "ibtracs"
    if re.fullmatch(r"b(?:wp|io|sh|al|ep|cp)\d{6}\.dat", name):
        return "jtwc"

    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        head = "".join([f.readline() for _ in range(15)])
    if re.search(r"^(WP|IO|SH|AL|EP|CP),\s*\d{1,2},\s*\d{10},", head, re.M):
        return "jtwc"
    if "66666" in head:
        if re.search(r"^\s*\d{10}\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+", head, re.M):
            return "cma"
        if re.search(r"^\s*\d{8}\s+002\s+\d+\s+\d+\s+\d+", head, re.M):
            return "jma"
    raise TrackFormatError("无法自动识别格式；请显式使用 --source cma|jma|jtwc|ibtracs。")


def _split_blocks(path: str | Path, source: str):
    blocks = []
    meta = None
    rows = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            if line.lstrip().startswith("66666"):
                if meta is not None:
                    blocks.append((meta, rows))
                parts = line.split()
                iid = parts[1] if len(parts) > 1 else ""
                name = _header_name(line)
                year = _year_from_intl_id(iid, 49 if source == "cma" else 51)
                meta = {
                    "id": iid,
                    "name": name,
                    "year": year,
                    "header": line,
                    "tc_id": parts[3] if len(parts) > 3 else "",
                    "china_id": parts[4] if len(parts) > 4 else "",
                }
                rows = []
            elif meta is not None:
                rows.append(line.strip())
    if meta is not None:
        blocks.append((meta, rows))
    return blocks


def _select_block(blocks, storm=None, year=None, storm_id=None):
    found = []
    qname = storm.upper() if storm else None
    qid = storm_id.upper() if storm_id else None
    for meta, rows in blocks:
        ok = True
        if qname:
            ok &= qname in str(meta.get("name", "")).upper()
        if year is not None and meta.get("year") is not None:
            ok &= int(meta["year"]) == int(year)
        if qid:
            ids = " ".join(str(meta.get(k, "")) for k in ("id", "tc_id", "china_id"))
            ok &= qid in ids.upper()
        if ok:
            found.append((meta, rows))
    if not found:
        sample = ", ".join(
            f"{m.get('year')}:{m.get('id')}:{m.get('name')}" for m, _ in blocks[:40]
        )
        raise TrackFormatError(f"未找到目标台风。候选示例：{sample}")
    if len(found) > 1:
        text = "\n".join(
            f"- year={m.get('year')} id={m.get('id')} name={m.get('name')}" for m, _ in found[:30]
        )
        raise TrackFormatError("匹配到多个台风，请增加 --year 或 --id：\n" + text)
    return found[0]


# ---------------- CMA ----------------
CMA_CATEGORY = {
    0: "WEAK/UNKNOWN", 1: "TD", 2: "TS", 3: "STS", 4: "TY",
    5: "STY", 6: "SuperTY", 9: "ET",
}


def read_cma(path, storm=None, year=None, storm_id=None):
    meta, rows = _select_block(_split_blocks(path, "cma"), storm, year, storm_id)
    recs = []
    for line in rows:
        p = line.split()
        if len(p) < 6 or not re.fullmatch(r"\d{10}", p[0]):
            continue
        try:
            cat = int(p[1]); lat = int(p[2]) / 10.0; lon = int(p[3]) / 10.0
            pres = _float(p[4]); wnd = _float(p[5]); owd = _float(p[6]) if len(p) > 6 else np.nan
        except Exception:
            continue
        note = ""
        if wnd == 0:
            wnd = np.nan; note = "CMA WND=0: unknown intensity"
        elif wnd == 9:
            note = "CMA WND=9 means MSW < 10 m/s; numeric 9 retained"
        recs.append({
            "time_utc": pd.to_datetime(p[0], format="%Y%m%d%H", utc=True),
            "lat": lat, "lon": lon,
            "pressure_hpa": pres if pres > 0 else np.nan,
            "vmax": wnd, "vmax_unit": "m/s", "wind_avg_min": 2,
            "native_category": CMA_CATEGORY.get(cat, str(cat)),
            "source": "CMA", "source_detail": "CMA Best Track",
            "storm_id": meta.get("china_id") or meta.get("id"),
            "storm_name": meta.get("name"), "basin": "WP/SCS",
            "note": note, "cma_owd_ms": owd,
        })
    return _finish(pd.DataFrame(recs))


# ---------------- JMA ----------------
JMA_CATEGORY = {2: "TD", 3: "TS", 4: "STS", 5: "TY", 6: "EX", 7: "ENTERING", 9: "TC>=TS"}


def _jma_time(s: str):
    yy = int(s[:2]); yyyy = 1900 + yy if yy >= 51 else 2000 + yy
    return pd.to_datetime(f"{yyyy}{s[2:]}", format="%Y%m%d%H", utc=True)


def _decode_jma_radius(token: str):
    """JMA radius token HIIII or KLLLL: first digit direction, next 4 radius nm."""
    token = str(token).strip()
    if not token or not token.isdigit():
        return np.nan, np.nan
    token = token.zfill(5)
    return int(token[0]), _float(token[1:])


def read_jma(path, storm=None, year=None, storm_id=None):
    meta, rows = _select_block(_split_blocks(path, "jma"), storm, year, storm_id)
    recs = []
    for line in rows:
        p = line.split()
        if len(p) < 7 or not re.fullmatch(r"\d{8}", p[0]) or p[1] != "002":
            continue
        try:
            grade = int(p[2]); lat = int(p[3]) / 10.0; lon = int(p[4]) / 10.0
        except Exception:
            continue
        pres = _float(p[5]); wind = _float(p[6])
        r50dir = r50long = r50short = r30dir = r30long = r30short = np.nan
        # With wind radii present, split fields typically become: HIIII JJJJ KLLLL MMMM [P]
        if len(p) >= 11:
            r50dir, r50long = _decode_jma_radius(p[7]); r50short = _float(p[8])
            r30dir, r30long = _decode_jma_radius(p[9]); r30short = _float(p[10])
        recs.append({
            "time_utc": _jma_time(p[0]), "lat": lat, "lon": lon,
            "pressure_hpa": pres if pres > 0 else np.nan,
            "vmax": wind if wind > 0 else np.nan, "vmax_unit": "kt", "wind_avg_min": 10,
            "native_category": JMA_CATEGORY.get(grade, str(grade)),
            "source": "JMA", "source_detail": "RSMC Tokyo Best Track",
            "storm_id": meta.get("id"), "storm_name": meta.get("name"), "basin": "WP/SCS",
            "note": "",
            "jma_r50_long_dir": r50dir, "jma_r50_long_nm": r50long, "jma_r50_short_nm": r50short,
            "jma_r30_long_dir": r30dir, "jma_r30_long_nm": r30long, "jma_r30_short_nm": r30short,
        })
    return _finish(pd.DataFrame(recs))


# ---------------- JTWC / ATCF b-deck ----------------
def _atcf_coord(s: str):
    s = str(s).strip().upper()
    m = re.fullmatch(r"(\d+)([NSEW])", s)
    if not m:
        return np.nan
    v = float(m.group(1)) / 10.0
    if m.group(2) in {"S", "W"}:
        v = -v
    return v


def _put_radii(rec: dict, rad, windcode, values):
    if not np.isfinite(rad) or int(rad) not in {34, 50, 64}:
        return
    vals = [_float(x) for x in values]
    if len(vals) < 4:
        vals += [np.nan] * (4 - len(vals))
    code = str(windcode).upper().strip()
    if code == "AAA":
        vals = [vals[0]] * 4
    elif code not in {"NEQ", ""}:
        # Most JTWC b-decks use NEQ. Preserve unknown codes in note rather than rotate incorrectly.
        rec["note"] = (str(rec.get("note", "")) + f" unsupported windcode={code};").strip()
        return
    for q, v in zip(("ne", "se", "sw", "nw"), vals):
        rec[f"r{int(rad)}_{q}_nm"] = v


def read_jtwc(path, storm=None, year=None, storm_id=None):
    """Read ATCF b-deck and aggregate repeated radii lines at the same timestamp."""
    by_time = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            if not raw.strip():
                continue
            p = [x.strip() for x in raw.split(",")]
            if len(p) < 11 or not re.fullmatch(r"\d{10}", p[2] if len(p) > 2 else ""):
                continue
            basin, cy, dtg = p[0].upper(), p[1].zfill(2), p[2]
            tech = p[4].upper() if len(p) > 4 else ""
            tau = p[5] if len(p) > 5 else ""
            if tech not in {"BEST", ""} or tau not in {"0", "00", "000", ""}:
                continue
            sid = f"{basin}{cy}{dtg[:4]}"
            name = p[27].upper() if len(p) > 27 and p[27] else sid
            if year is not None and int(dtg[:4]) != int(year):
                continue
            if storm_id and storm_id.upper() not in {sid.upper(), Path(path).stem.upper()}:
                continue
            if storm and storm.upper() not in name.upper():
                continue
            t = pd.to_datetime(dtg, format="%Y%m%d%H", utc=True)
            rec = by_time.setdefault(t, {
                "time_utc": t, "lat": _atcf_coord(p[6]), "lon": _atcf_coord(p[7]),
                "pressure_hpa": _float(p[9]), "vmax": _float(p[8]),
                "vmax_unit": "kt", "wind_avg_min": 1,
                "native_category": p[10].upper() if len(p) > 10 else "",
                "source": "JTWC", "source_detail": "ATCF b-deck",
                "storm_id": sid, "storm_name": name, "basin": basin, "note": "",
                "p_outer_hpa": _float(p[17]) if len(p) > 17 else np.nan,
                "roci_nm": _float(p[18]) if len(p) > 18 else np.nan,
                "rmw_nm": _float(p[19]) if len(p) > 19 else np.nan,
            })
            # Fill from subsequent same-time records when first line is sparse.
            for key, val in {
                "lat": _atcf_coord(p[6]), "lon": _atcf_coord(p[7]),
                "vmax": _float(p[8]), "pressure_hpa": _float(p[9]),
                "p_outer_hpa": _float(p[17]) if len(p) > 17 else np.nan,
                "roci_nm": _float(p[18]) if len(p) > 18 else np.nan,
                "rmw_nm": _float(p[19]) if len(p) > 19 else np.nan,
            }.items():
                if pd.isna(rec.get(key)) and not pd.isna(val):
                    rec[key] = val
            if len(p) > 11:
                rad = _float(p[11]); windcode = p[12] if len(p) > 12 else ""
                _put_radii(rec, rad, windcode, p[13:17])
    if not by_time:
        raise TrackFormatError("JTWC/ATCF b-deck 中没有符合条件的 BEST/tau=0 记录。")
    return _finish(pd.DataFrame(list(by_time.values())))


# ---------------- IBTrACS ----------------
IB_AGENCIES = {
    "wmo":  {"lat": "LAT",       "lon": "LON",       "wind": "WMO_WIND",   "pres": "WMO_PRES",   "cat": "NATURE",      "avg": np.nan},
    "usa":  {"lat": "USA_LAT",   "lon": "USA_LON",   "wind": "USA_WIND",   "pres": "USA_PRES",   "cat": "USA_STATUS",  "avg": 1},
    "tokyo":{"lat": "TOKYO_LAT", "lon": "TOKYO_LON", "wind": "TOKYO_WIND", "pres": "TOKYO_PRES", "cat": "TOKYO_GRADE", "avg": 10},
    "cma":  {"lat": "CMA_LAT",   "lon": "CMA_LON",   "wind": "CMA_WIND",   "pres": "CMA_PRES",   "cat": "CMA_CAT",     "avg": 2},
    "hko":  {"lat": "HKO_LAT",   "lon": "HKO_LON",   "wind": "HKO_WIND",   "pres": "HKO_PRES",   "cat": "HKO_CAT",     "avg": 10},
}


def _read_ib_csv(path):
    return pd.read_csv(path, low_memory=False)


def _decode_scalar(v):
    a = np.asarray(v)
    if a.dtype.kind == "S":
        if a.ndim == 0:
            return a.item().decode(errors="ignore").strip()
        return b"".join(a.flatten().tolist()).decode(errors="ignore").strip()
    if a.dtype.kind == "U":
        return "".join(a.flatten().tolist()).strip() if a.ndim else str(a.item()).strip()
    try:
        return a.item()
    except Exception:
        return v


def _read_ib_netcdf_selected(path, storm=None, year=None, storm_id=None):
    import xarray as xr
    ds = xr.open_dataset(path, decode_times=True)
    if "storm" not in ds.dims:
        frame = ds.to_dataframe().reset_index()
        ds.close()
        return frame

    n = ds.sizes["storm"]
    names = []
    sids = []
    seasons = []
    for i in range(n):
        names.append(str(_decode_scalar(ds["name"].isel(storm=i).values)) if "name" in ds else "")
        sids.append(str(_decode_scalar(ds["sid"].isel(storm=i).values)) if "sid" in ds else "")
        if "season" in ds:
            try: seasons.append(int(_decode_scalar(ds["season"].isel(storm=i).values)))
            except Exception: seasons.append(None)
        else: seasons.append(None)
    idx = []
    for i in range(n):
        ok = True
        if storm: ok &= storm.upper() in names[i].upper()
        if storm_id: ok &= storm_id.upper() in sids[i].upper()
        if year is not None and seasons[i] is not None: ok &= int(year) == int(seasons[i])
        if ok: idx.append(i)
    if not idx:
        ds.close(); raise TrackFormatError("IBTrACS NetCDF 未找到目标台风。")
    if len(idx) > 1:
        text = "\n".join(f"- {seasons[i]} {sids[i]} {names[i]}" for i in idx[:30])
        ds.close(); raise TrackFormatError("IBTrACS 匹配多个台风，请增加 --year/--id：\n" + text)

    sub = ds.isel(storm=idx[0])
    frame = sub.to_dataframe().reset_index()
    ds.close()
    # normalize variable names to CSV naming convention
    frame = frame.rename(columns={c: c.upper() for c in frame.columns})
    if "ISO_TIME" not in frame.columns and "TIME" in frame.columns:
        frame["ISO_TIME"] = frame["TIME"]
    if "SID" not in frame.columns: frame["SID"] = sids[idx[0]]
    if "NAME" not in frame.columns: frame["NAME"] = names[idx[0]]
    return frame


def _ib_filter(x, storm=None, year=None, storm_id=None):
    x = x.copy()
    # Normalize columns; CSV uses uppercase, xarray path is normalized above.
    x.columns = [str(c).upper() for c in x.columns]
    if "ISO_TIME" not in x.columns:
        raise TrackFormatError("IBTrACS 缺少 ISO_TIME。")
    x["_TIME"] = pd.to_datetime(x["ISO_TIME"], errors="coerce", utc=True)
    x = x[x["_TIME"].notna()].copy()  # also removes CSV units row
    if year is not None:
        x = x[x["_TIME"].dt.year == int(year)]
    if storm:
        q = re.escape(storm.upper())
        mask = pd.Series(False, index=x.index)
        for c in ["NAME", "SID", "USA_ATCF_ID"]:
            if c in x.columns:
                mask |= x[c].astype(str).str.upper().str.contains(q, regex=True, na=False)
        x = x[mask]
    if storm_id:
        q = re.escape(storm_id.upper())
        mask = pd.Series(False, index=x.index)
        for c in ["SID", "USA_ATCF_ID"]:
            if c in x.columns:
                mask |= x[c].astype(str).str.upper().str.contains(q, regex=True, na=False)
        x = x[mask]
    if x.empty:
        raise TrackFormatError("IBTrACS 未找到匹配记录。")
    key = "SID" if "SID" in x.columns else ("USA_ATCF_ID" if "USA_ATCF_ID" in x.columns else None)
    if key:
        ids = [z for z in x[key].dropna().astype(str).unique() if z and z.lower() != "nan"]
        if len(ids) > 1:
            info = []
            for sid in ids[:30]:
                z = x[x[key].astype(str) == sid]
                nm = str(z["NAME"].iloc[0]) if "NAME" in z.columns else ""
                info.append(f"- {z['_TIME'].dt.year.min()} {sid} {nm}")
            raise TrackFormatError("IBTrACS 匹配多个台风，请增加 --year/--id：\n" + "\n".join(info))
    return x


def _choose_agency(x, agency):
    agency = agency.lower()
    if agency != "auto":
        if agency not in IB_AGENCIES:
            raise TrackFormatError("--agency 支持 auto|wmo|usa|tokyo|cma|hko")
        return agency
    counts = {}
    for k, m in IB_AGENCIES.items():
        if m["lat"] in x.columns and m["lon"] in x.columns:
            la = pd.to_numeric(x[m["lat"]], errors="coerce")
            lo = pd.to_numeric(x[m["lon"]], errors="coerce")
            counts[k] = int((la.notna() & lo.notna()).sum())
        else:
            counts[k] = 0
    if counts.get("wmo", 0) >= 2:
        return "wmo"
    best = max(counts, key=counts.get)
    if counts[best] < 2:
        raise TrackFormatError("IBTrACS 各 agency 字段均没有足够位置点。")
    return best


def read_ibtracs(path, storm=None, year=None, storm_id=None, agency="auto"):
    p = Path(path)
    if p.suffix.lower() == ".csv":
        raw = _read_ib_csv(p)
        x = _ib_filter(raw, storm, year, storm_id)
    elif p.suffix.lower() in {".nc", ".nc4", ".cdf"}:
        raw = _read_ib_netcdf_selected(p, storm, year, storm_id)
        x = _ib_filter(raw, None, None, None)
    else:
        raise TrackFormatError("IBTrACS 仅支持 CSV/NetCDF。")

    ag = _choose_agency(x, agency)
    m = IB_AGENCIES[ag]
    for c in [m["lat"], m["lon"], m["wind"], m["pres"]]:
        if c not in x.columns: x[c] = np.nan
    lat = pd.to_numeric(x[m["lat"]], errors="coerce")
    lon = pd.to_numeric(x[m["lon"]], errors="coerce")
    wind = pd.to_numeric(x[m["wind"]], errors="coerce")
    pres = pd.to_numeric(x[m["pres"]], errors="coerce")
    lat = lat.mask(lat <= -9000); lon = lon.mask(lon <= -9000)
    wind = wind.mask(wind <= -9000); pres = pres.mask(pres <= -9000)
    cat = x[m["cat"]].astype(str) if m["cat"] in x.columns else pd.Series("", index=x.index)
    sid = x["SID"].astype(str) if "SID" in x.columns else pd.Series("", index=x.index)
    name = x["NAME"].astype(str) if "NAME" in x.columns else sid
    basin = x["BASIN"].astype(str) if "BASIN" in x.columns else pd.Series("", index=x.index)
    detail = pd.Series(f"IBTrACS agency={ag}", index=x.index)
    note = pd.Series("", index=x.index)
    avg = pd.Series(m["avg"], index=x.index)
    if ag == "wmo":
        # WMO_AGENCY can change along a storm, so do not pretend one wind averaging period applies.
        if "WMO_AGENCY" in x.columns:
            detail = "IBTrACS WMO agency=" + x["WMO_AGENCY"].astype(str)
            note = "WMO_WIND averaging period depends on reporting agency; inspect WMO_AGENCY"
        avg = pd.Series(np.nan, index=x.index)
    out = pd.DataFrame({
        "time_utc": x["_TIME"], "lat": lat, "lon": lon,
        "pressure_hpa": pres.where(pres > 0), "vmax": wind.where(wind > 0),
        "vmax_unit": "kt", "wind_avg_min": avg,
        "native_category": cat, "source": "IBTrACS", "source_detail": detail,
        "storm_id": sid, "storm_name": name, "basin": basin, "note": note,
    })
    return _finish(out)


def load_track(path, source="auto", storm=None, year=None, storm_id=None, agency="auto"):
    source = source.lower()
    if source == "auto": source = detect_source(path)
    if source == "cma": return read_cma(path, storm, year, storm_id)
    if source == "jma": return read_jma(path, storm, year, storm_id)
    if source == "jtwc": return read_jtwc(path, storm, year, storm_id)
    if source == "ibtracs": return read_ibtracs(path, storm, year, storm_id, agency)
    raise TrackFormatError(f"不支持 source={source}")


def list_storms(path, source="auto") -> pd.DataFrame:
    if source == "auto": source = detect_source(path)
    if source in {"cma", "jma"}:
        blocks = _split_blocks(path, source)
        return pd.DataFrame([{"year": m["year"], "id": m["id"], "name": m["name"]} for m, _ in blocks])
    if source == "jtwc":
        rows = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                p = [x.strip() for x in raw.split(",")]
                if len(p) >= 3 and re.fullmatch(r"\d{10}", p[2]):
                    name = p[27].upper() if len(p) > 27 and p[27] else ""
                    rows.append({"year": int(p[2][:4]), "id": f"{p[0].upper()}{p[1].zfill(2)}{p[2][:4]}", "name": name})
        return pd.DataFrame(rows).drop_duplicates()
    if source == "ibtracs":
        p = Path(path)
        if p.suffix.lower() != ".csv":
            raise TrackFormatError("IBTrACS list-storms 当前建议对 CSV 使用；NetCDF 请配合 --storm/--id。")
        x = pd.read_csv(p, low_memory=False)
        x.columns = [str(c).upper() for c in x.columns]
        if "ISO_TIME" in x.columns:
            t = pd.to_datetime(x["ISO_TIME"], errors="coerce", utc=True)
            x = x[t.notna()].copy(); x["YEAR"] = t[t.notna()].dt.year
        cols = [c for c in ["YEAR", "SID", "NAME", "BASIN", "USA_ATCF_ID"] if c in x.columns]
        return x[cols].drop_duplicates()
    raise TrackFormatError(source)


def summary(df: pd.DataFrame) -> dict:
    wavg = sorted({float(v) for v in df["wind_avg_min"].dropna().unique()})
    return {
        "points": int(len(df)),
        "start_utc": str(df["time_utc"].min()),
        "end_utc": str(df["time_utc"].max()),
        "storm_id": str(df["storm_id"].iloc[0]),
        "storm_name": str(df["storm_name"].iloc[0]),
        "source": str(df["source"].iloc[0]),
        "source_detail": sorted(set(df["source_detail"].dropna().astype(str)))[:8],
        "wind_avg_min": wavg if wavg else "agency-dependent/unknown",
        "min_pressure_hpa": None if df["pressure_hpa"].dropna().empty else float(df["pressure_hpa"].min()),
        "max_vmax": None if df["vmax"].dropna().empty else float(df["vmax"].max()),
        "vmax_unit": sorted(set(df["vmax_unit"].dropna().astype(str))),
    }
