#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from track_io import load_track, summary, TrackFormatError

CAT_COLORS = {
    "WEAK/UNKNOWN": "#bdbdbd", "TD": "#90EE90", "TS": "#32CD32",
    "STS": "#FFD700", "TY": "#FFA500", "STY": "#FF4500",
    "SUPERTY": "#8B008B", "EX": "#808080", "ET": "#808080",
    "ENTERING": "#4aa3df", "TC>=TS": "#FFD700", "DB": "#bdbdbd",
    "SS": "#32CD32", "ST": "#8B008B", "TC": "#8B008B",
}


def setup_fonts(plt):
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC",
        "WenQuanYi Micro Hei", "Arial Unicode MS", "DejaVu Sans"
    ]
    plt.rcParams["axes.unicode_minus"] = False


def resolve_shp(path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".shp":
        return p
    if p.is_dir():
        preferred = list(p.rglob("bou2_4l.shp"))
        if preferred:
            return preferred[0]
        shps = list(p.rglob("*.shp"))
        if shps:
            return shps[0]
    raise FileNotFoundError(f"未找到 shapefile: {path}")


def _track_extent(df):
    lons = df["lon"].to_numpy(float)
    lats = df["lat"].to_numpy(float)
    lon_span = np.nanmax(lons) - np.nanmin(lons)
    if lon_span > 180:  # dateline crossing: avoid bad clipping
        lon_min, lon_max = -180, 180
    else:
        pad_lon = max(3.0, min(10.0, lon_span * 0.15 + 2.0))
        lon_min, lon_max = max(-180, np.nanmin(lons)-pad_lon), min(180, np.nanmax(lons)+pad_lon)
    lat_span = np.nanmax(lats) - np.nanmin(lats)
    pad_lat = max(2.0, min(8.0, lat_span * 0.15 + 1.5))
    lat_min, lat_max = max(-90, np.nanmin(lats)-pad_lat), min(90, np.nanmax(lats)+pad_lat)
    return [lon_min, lon_max, lat_min, lat_max]


def _draw_plain_shp(ax, shp_path: Path):
    import shapefile  # pyshp
    sf = shapefile.Reader(str(shp_path))
    for shape in sf.shapes():
        pts = np.asarray(shape.points)
        if pts.size == 0:
            continue
        parts = list(shape.parts) + [len(pts)]
        for i in range(len(parts)-1):
            seg = pts[parts[i]:parts[i+1]]
            if len(seg) >= 2:
                ax.plot(seg[:,0], seg[:,1], color="black", linewidth=0.55, alpha=0.85, zorder=1)


def _plot_points(ax, df, transform=None, show_time=False):
    kwargs = {"transform": transform} if transform is not None else {}
    lons = df["lon"].to_numpy(float); lats = df["lat"].to_numpy(float)
    # break lines over dateline to avoid a line across the whole map
    seg_lon = lons.astype(float).copy(); seg_lat = lats.astype(float).copy()
    jumps = np.where(np.abs(np.diff(seg_lon)) > 180)[0]
    if len(jumps):
        # plot individual segments
        start = 0
        for j in list(jumps) + [len(seg_lon)-1]:
            end = j + 1
            ax.plot(seg_lon[start:end], seg_lat[start:end], "k-", linewidth=1.4, alpha=0.7, zorder=5, **kwargs)
            start = end
    else:
        ax.plot(seg_lon, seg_lat, "k-", linewidth=1.4, alpha=0.7, zorder=5, **kwargs)

    cats = df["native_category"].fillna("UNKNOWN").astype(str)
    for cat in cats.unique():
        mask = cats == cat
        color = CAT_COLORS.get(cat.upper(), "#5f9ea0")
        ax.scatter(df.loc[mask, "lon"], df.loc[mask, "lat"], s=34, c=color,
                   edgecolors="black", linewidths=0.45, zorder=8, label=cat, **kwargs)

    ax.scatter(lons[0], lats[0], marker="*", s=190, c="green", edgecolors="black",
               linewidths=0.6, zorder=12, label="Start", **kwargs)
    ax.scatter(lons[-1], lats[-1], marker="*", s=190, c="blue", edgecolors="black",
               linewidths=0.6, zorder=12, label="End", **kwargs)

    if show_time:
        step = 1 if len(df) <= 20 else max(1, len(df)//12)
        for i in range(0, len(df), step):
            t = pd.Timestamp(df.iloc[i]["time_utc"]).strftime("%m-%d %HZ")
            ann_kw = dict(xytext=(5,5), textcoords="offset points", fontsize=7, zorder=15)
            if transform is not None:
                ann_kw["transform"] = transform
            ax.annotate(t, (df.iloc[i]["lon"], df.iloc[i]["lat"]), **ann_kw)


def _title(df, title_cn=None):
    name = str(df["storm_name"].iloc[0]); sid = str(df["storm_id"].iloc[0])
    src = str(df["source"].iloc[0])
    avg = sorted({float(v) for v in df["wind_avg_min"].dropna().unique()})
    avg_txt = "/".join(f"{x:g}-min" for x in avg) if avg else "agency-dependent"
    disp = f"{title_cn} / {name}" if title_cn and title_cn.upper() != name.upper() else (title_cn or name)
    return f"{disp} ({sid}) Best Track\n{src} | Vmax averaging: {avg_txt}"


def plot_cartopy(df, output, title_cn=None, show_time=False, admin1=False, shp=None, dpi=300):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    from cartopy.io.shapereader import Reader
    from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter

    setup_fonts(plt)
    lons = df["lon"].to_numpy(float)
    central = 180 if np.nanmax(lons)-np.nanmin(lons) > 180 else 0
    data_crs = ccrs.PlateCarree(); proj = ccrs.PlateCarree(central_longitude=central)
    fig = plt.figure(figsize=(13,10)); ax = fig.add_subplot(1,1,1, projection=proj)
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="0.95", zorder=0)
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="0.99", zorder=0)
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), linewidth=0.8, zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale("10m"), linewidth=0.65, zorder=2)
    if admin1:
        feat = cfeature.NaturalEarthFeature("cultural", "admin_1_states_provinces_lines", "10m", facecolor="none")
        ax.add_feature(feat, edgecolor="0.45", linewidth=0.4, zorder=2)
    if shp:
        ax.add_geometries(Reader(str(shp)).geometries(), crs=data_crs,
                          facecolor="none", edgecolor="black", linewidth=0.7, zorder=3)
    try:
        ax.set_extent(_track_extent(df), crs=data_crs)
    except Exception:
        ax.set_global()
    gl = ax.gridlines(draw_labels=True, linewidth=0.55, linestyle="--", alpha=0.45)
    gl.top_labels = False; gl.right_labels = False
    gl.xformatter = LongitudeFormatter(); gl.yformatter = LatitudeFormatter()
    _plot_points(ax, df, transform=data_crs, show_time=show_time)
    ax.set_title(_title(df, title_cn), fontsize=14, pad=14)
    ax.legend(loc="best", fontsize=8, title="Native category", framealpha=0.92)
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight"); plt.close(fig)


def plot_plain(df, output, title_cn=None, show_time=False, shp=None, dpi=300):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    setup_fonts(plt)
    fig, ax = plt.subplots(figsize=(13,10))
    if shp:
        _draw_plain_shp(ax, shp)
    _plot_points(ax, df, transform=None, show_time=show_time)
    ext = _track_extent(df)
    if ext[0] == -180 and ext[1] == 180:
        ax.set_xlim(-180,180)
    else:
        ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_xlabel("Longitude (°)"); ax.set_ylabel("Latitude (°)")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.set_title(_title(df, title_cn), fontsize=14)
    ax.legend(loc="best", fontsize=8, title="Native category")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight"); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Robust multi-source typhoon best-track plotter")
    ap.add_argument("input", help="CMA/JMA/JTWC/IBTrACS file")
    ap.add_argument("--source", default="auto", choices=["auto","cma","jma","jtwc","ibtracs"])
    ap.add_argument("--storm", help="storm name, e.g. LEKIMA")
    ap.add_argument("--year", type=int)
    ap.add_argument("--id", dest="storm_id", help="international ID / SID / ATCF ID")
    ap.add_argument("--agency", default="auto", choices=["auto","wmo","usa","tokyo","cma","hko"],
                    help="IBTrACS agency group")
    ap.add_argument("--title-cn")
    ap.add_argument("--output", default="outputs/typhoon_track.png")
    ap.add_argument("--export-csv")
    ap.add_argument("--show-time", action="store_true")
    ap.add_argument("--admin1", action="store_true", help="Natural Earth Admin-1 boundaries")
    ap.add_argument("--china-shp", "--boundary-shp", dest="shp",
                    help="optional .shp file or directory; bou2_4l.shp is auto-preferred")
    ap.add_argument("--map-mode", choices=["auto","cartopy","plain"], default="auto",
                    help="auto falls back to plain lon/lat when Cartopy/basemap fails")
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    try:
        df = load_track(args.input, args.source, args.storm, args.year, args.storm_id, args.agency)
        shp = resolve_shp(args.shp)
    except (TrackFormatError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr); return 2

    print("Track summary:")
    for k,v in summary(df).items(): print(f"  {k}: {v}")
    if args.export_csv:
        p = Path(args.export_csv); p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False, encoding="utf-8-sig")
        print(f"Normalized CSV saved: {p}")

    try:
        if args.map_mode == "plain":
            plot_plain(df, args.output, args.title_cn, args.show_time, shp, args.dpi)
        else:
            try:
                plot_cartopy(df, args.output, args.title_cn, args.show_time, args.admin1, shp, args.dpi)
            except Exception as e:
                if args.map_mode == "cartopy":
                    raise
                warnings.warn(f"Cartopy mode failed ({e}); falling back to plain lon/lat map.")
                plot_plain(df, args.output, args.title_cn, args.show_time, shp, args.dpi)
    except Exception as e:
        print(f"ERROR while plotting: {e}", file=sys.stderr); return 3
    print(f"Track figure saved: {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
