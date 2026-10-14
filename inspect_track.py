#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, sys
from pathlib import Path
import pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from track_io import list_storms, load_track, summary, TrackFormatError

ap = argparse.ArgumentParser(description="List storms or inspect one normalized track")
ap.add_argument("input")
ap.add_argument("--source", default="auto", choices=["auto","cma","jma","jtwc","ibtracs"])
ap.add_argument("--list", action="store_true")
ap.add_argument("--storm")
ap.add_argument("--year", type=int)
ap.add_argument("--id", dest="storm_id")
ap.add_argument("--agency", default="auto", choices=["auto","wmo","usa","tokyo","cma","hko"])
ap.add_argument("--head", type=int, default=12)
args = ap.parse_args()
try:
    if args.list:
        print(list_storms(args.input, args.source).to_string(index=False))
    else:
        df = load_track(args.input, args.source, args.storm, args.year, args.storm_id, args.agency)
        print(summary(df))
        print(df.head(args.head).to_string(index=False))
except TrackFormatError as e:
    print("ERROR:", e, file=sys.stderr); raise SystemExit(2)
