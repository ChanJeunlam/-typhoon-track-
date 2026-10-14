---
name: typhoon-track
description: >
  多源台风/热带气旋最佳路径检索、解析、质量检查、统一格式导出和路径绘图 Skill。
  支持 CMA 年度最佳路径、JMA/RSMC Tokyo Best Track、JTWC/ATCF b-deck、NOAA IBTrACS CSV/NetCDF。
  支持加载中国/自定义 Shapefile，也支持完全不加载 SHP；默认优先 Cartopy + Natural Earth，失败时可回退为普通经纬度图。
  适用于台风路径制图、跨机构路径/强度比较、WW3/SWAN/ADCIRC 驱动前处理，以及 Holland/Rankine 参数化台风风场的路径强度准备。
---

# Typhoon Track — Robust Multi-source Best-track Skill

## 1. Skill 的目标

当用户说：

- “画 2019 年利奇马路径图”
- “从 CMA 最佳路径中提取 1909 利奇马”
- “比较 CMA/JMA/JTWC 对同一台风的路径和强度”
- “把台风路径整理成 WW3/Holland 风场可以继续处理的 CSV”
- “加载中国省界 shp 画路径图”

本 Skill 应：

1. 判断数据源和文件格式；
2. 精确定位目标台风；
3. 解析时间、中心经纬度、中心气压、最大持续风速、机构原生等级；
4. 保留风速单位和**风速平均时段**；
5. 对 JTWC 风圈/RMW/ROCI 等扩展字段尽量保留；
6. 做基本质量检查；
7. 输出统一 CSV 和路径图；
8. 不擅自把不同机构风速转换成“同一种风速定义”。

---

# 2. 项目结构

```text
typhoon-track-robust/
├── SKILL.md
├── README.md
├── requirements.txt
├── scripts/
│   ├── track_io.py              # 核心：CMA/JMA/JTWC/IBTrACS 多源解析
│   ├── plot_track.py            # 核心：绘图、可选 SHP、无 SHP 回退
│   ├── inspect_track.py         # 列出台风/检查解析结果
│   └── download_besttrack.py    # 数据与 Natural Earth 边界下载助手
├── references/
│   ├── DATA_SOURCES.md          # 官方下载地址、用途、限制
│   ├── DATA_FORMATS.md          # 字段级深度解析
│   └── sample/                  # 人工构造的最小测试样例
├── data/
│   └── china_boundary/
│       └── README.md            # 中国 shp / Natural Earth 使用说明
├── tests/
│   └── test_parsers.py
└── outputs/
```

---

# 3. 支持的数据源

## 3.1 CMA 中国气象局热带气旋最佳路径

官方说明和下载：

```text
https://tcdata.typhoon.org.cn/zjljsjj.html
```

英文说明：

```text
https://tcdata.typhoon.org.cn/en/zjljsjj.html
```

年度文件名：

```text
CHYYYYBST.txt
```

例如：

```text
CH2019BST.txt
```

### CMA 关键定义

单条记录常见格式：

```text
YYYYMMDDHH I LAT LON PRES WND [OWD]
```

其中：

- `YYYYMMDDHH`：UTC；
- `I`：强度等级；
- `LAT`：0.1°N；
- `LON`：0.1°E；
- `PRES`：中心最低气压 hPa；
- `WND`：近中心最大持续风速，**2 分钟平均，m/s**；
- `OWD`：可选扩展风速字段。

等级：

```text
0  弱于热带低压或未知
1  TD
2  TS
3  STS
4  TY
5  STY
6  SuperTY
9  ET
```

必须处理的特殊值：

```text
WND = 9  -> 表示 MSW < 10 m/s，不等同于正常的“9 m/s观测”
WND = 0  -> 强度未知
```

本 Skill 会在 `note` 字段中保留这一语义。

---

## 3.2 JMA / RSMC Tokyo Best Track

官方入口：

```text
https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/besttrack.html
```

全部年份：

```text
https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip
```

年度文件：

```text
https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bstYYYY.txt
```

格式说明：

```text
https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/e_format_bst.html
```

### JMA 数据行

```text
YYMMDDHH 002 GRADE LAT LON PRES VMAX [50kt radius fields] [30kt radius fields]
```

关键点：

- 时间 UTC；
- 纬经度单位 0.1°；
- 中心气压 hPa；
- `VMAX` 单位 kt；
- JMA/RSMC Tokyo 最大持续风速采用**10 分钟平均**；
- 数据行还可含 50 kt、30 kt 风圈长短半径及方向。

本 Skill 除核心路径外，还保留：

```text
jma_r50_long_dir
jma_r50_long_nm
jma_r50_short_nm
jma_r30_long_dir
jma_r30_long_nm
jma_r30_short_nm
```

---

## 3.3 JTWC / ATCF b-deck

JTWC 官方入口：

```text
https://www.metoc.navy.mil/jtwc/jtwc.html
```

历史 Best Track 说明资料：

```text
https://www.metoc.navy.mil/jtwc/products/best-tracks/tc-bt-report.html
```

便于脚本下载的公开 ATCF b-deck 镜像：

```text
https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/
```

年度目录：

```text
https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/YYYY/
```

西北太平洋常见文件：

```text
bwpNNYYYY.dat
```

例如：

```text
bwp102019.dat
```

### JTWC 关键点

JTWC 最大持续风速为：

```text
1-minute mean sustained 10-m wind
```

单位通常为 kt。

ATCF b-deck 一行通常包含：

```text
BASIN, CY, YYYYMMDDHH, TECHNUM, TECH, TAU,
LAT, LON, VMAX, MSLP, TY,
RAD, WINDCODE, RAD1, RAD2, RAD3, RAD4,
POUTER, ROUTER, RMW, ... STORMNAME ...
```

**鲁棒性重点：**

同一 UTC 时刻可能出现多行：

```text
RAD=34
RAD=50
RAD=64
```

它们不是三个轨迹点，而是同一个中心点对应不同风速阈值的风圈。

本 Skill 会按时间聚合并输出：

```text
r34_ne_nm r34_se_nm r34_sw_nm r34_nw_nm
r50_ne_nm r50_se_nm r50_sw_nm r50_nw_nm
r64_ne_nm r64_se_nm r64_sw_nm r64_nw_nm
rmw_nm
roci_nm
p_outer_hpa
```

对于 `NEQ` 风圈编码按：

```text
NE -> SE -> SW -> NW
```

解释。

若遇到未知 `WINDCODE`，不强行旋转，而在 `note` 中报警。

---

## 3.4 NOAA IBTrACS v04r01

官方产品页：

```text
https://www.ncei.noaa.gov/products/international-best-track-archive
```

CSV：

```text
https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/
```

NetCDF：

```text
https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/netcdf/
```

西北太平洋推荐：

```text
ibtracs.WP.list.v04r01.csv
IBTrACS.WP.v04r01.nc
```

### IBTrACS 的本质

IBTrACS 不是“另一套单独的台风分析”，而是把多个机构整合到统一结构中。

同一个台风可能同时有：

```text
WMO_*
USA_*
TOKYO_*
CMA_*
HKO_*
```

因此不能简单地：

```text
取一个 WIND 列 -> 当成统一风速
```

本 Skill 提供：

```text
--agency wmo
--agency usa
--agency tokyo
--agency cma
--agency hko
--agency auto
```

说明：

- `usa`：按 1-min 体系处理；
- `tokyo`：按 10-min；
- `cma`：按 2-min；
- `hko`：按 10-min；
- `wmo`：报告机构可能随时间变化，所以默认把 `wind_avg_min` 留空，并在 `source_detail/note` 中保存 `WMO_AGENCY`。

**禁止在没有说明转换方法的情况下将这些风速直接做等价比较。**

---

# 4. 中国边界 / SHP

## 4.1 推荐方案：不依赖 bou2_4l.shp

默认：

```text
Cartopy + Natural Earth
```

Natural Earth 主页：

```text
https://www.naturalearthdata.com/downloads/
```

1:10m Admin-1：

```text
https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/
```

直接 ZIP 常用地址：

```text
https://www.naturalearthdata.com/download/10m/cultural/ne_10m_admin_1_states_provinces.zip
```

本 Skill 可直接：

```bash
python scripts/download_besttrack.py naturalearth --layer admin1 --out data
```

绘图时：

```bash
python scripts/plot_track.py ... --admin1
```

无需任何手工 SHP。

## 4.2 使用自己的中国 SHP

如果已有：

```text
bou2_4l.shp
bou2_4l.shx
bou2_4l.dbf
```

最好还有：

```text
bou2_4l.prj
```

放到：

```text
data/china_boundary/
```

然后：

```bash
python scripts/plot_track.py ... \
  --china-shp data/china_boundary/bou2_4l.shp
```

也可直接传目录：

```bash
--china-shp data/china_boundary/
```

程序会优先寻找：

```text
bou2_4l.shp
```

否则使用目录中的第一个 `.shp`。

### 关于网上的 bou2_4l.shp

`bou2_4m/bou2_4l.shp` 在很多旧 GIS 教程、MATLAB/Python 项目中被反复转载，但经常缺少清晰的原始发布方、版本号和许可信息。

因此：

- 科研内部复现：可以用你已有的文件；
- 新项目：优先 Natural Earth 或你所在单位认可的数据；
- 正式公开地图/工程交付：中国地图边界需按项目适用的地图合规与审图要求处理。

本 Skill **不捆绑来源不明的 bou2_4l.shp**。

---

# 5. 安装

Python 3.10+ 推荐。

```bash
python -m venv .venv
```

Windows：

```cmd
.venv\Scripts\activate
```

Linux/macOS：

```bash
source .venv/bin/activate
```

安装：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

# 6. 下载示例

## CMA 2019

```bash
python scripts/download_besttrack.py cma --year 2019 --out references
```

CMA 页面如果阻止程序下载，脚本会打印官方页面，改为浏览器下载：

```text
CH2019BST.txt
```

## JMA 全量

```bash
python scripts/download_besttrack.py jma --all --out references
```

## JMA 指定年份

```bash
python scripts/download_besttrack.py jma --year 2019 --out references
```

## JTWC 2019 西北太平洋第 10 号系统

```bash
python scripts/download_besttrack.py jtwc \
  --year 2019 --basin WP --storm-number 10 --out references
```

## IBTrACS 西北太平洋 CSV

```bash
python scripts/download_besttrack.py ibtracs \
  --subset WP --format csv --out references
```

## IBTrACS NetCDF

```bash
python scripts/download_besttrack.py ibtracs \
  --subset WP --format netcdf --out references
```

---

# 7. 先查看数据中有哪些台风

CMA/JMA：

```bash
python scripts/inspect_track.py references/CH2019BST.txt \
  --source cma --list
```

IBTrACS：

```bash
python scripts/inspect_track.py references/ibtracs.WP.list.v04r01.csv \
  --source ibtracs --list
```

若同名台风或 nameless 系统存在歧义，必须结合：

```text
--year
--id
```

不要静默选择第一条。

---

# 8. 绘图

## CMA 利奇马

```bash
python scripts/plot_track.py references/CH2019BST.txt \
  --source cma \
  --storm LEKIMA \
  --year 2019 \
  --title-cn 利奇马 \
  --output outputs/LEKIMA_CMA.png \
  --export-csv outputs/LEKIMA_CMA.csv \
  --show-time
```

## 使用中国 SHP

```bash
python scripts/plot_track.py references/CH2019BST.txt \
  --source cma --storm LEKIMA --year 2019 \
  --china-shp data/china_boundary/bou2_4l.shp \
  --output outputs/LEKIMA_CMA_SHP.png
```

## 不使用 SHP

```bash
python scripts/plot_track.py references/CH2019BST.txt \
  --source cma --storm LEKIMA --year 2019 \
  --admin1 \
  --output outputs/LEKIMA_CMA_NE.png
```

## 完全不用 Cartopy / 离线兜底

```bash
python scripts/plot_track.py references/CH2019BST.txt \
  --source cma --storm LEKIMA --year 2019 \
  --map-mode plain \
  --output outputs/LEKIMA_plain.png
```

---

# 9. IBTrACS 多机构比较

同一数据文件分别提取：

```bash
python scripts/plot_track.py ibtracs.WP.list.v04r01.csv \
  --source ibtracs --storm LEKIMA --year 2019 --agency cma \
  --output outputs/LEKIMA_IB_CMA.png
```

```bash
python scripts/plot_track.py ibtracs.WP.list.v04r01.csv \
  --source ibtracs --storm LEKIMA --year 2019 --agency tokyo \
  --output outputs/LEKIMA_IB_JMA.png
```

```bash
python scripts/plot_track.py ibtracs.WP.list.v04r01.csv \
  --source ibtracs --storm LEKIMA --year 2019 --agency usa \
  --output outputs/LEKIMA_IB_USA.png
```

对比时必须在图注或结果中说明：

```text
CMA: 2-min
JMA/Tokyo: 10-min
JTWC/USA: 1-min
```

---

# 10. 统一输出字段

导出 CSV 至少包括：

```text
time_utc
lat
lon
pressure_hpa
vmax
vmax_unit
wind_avg_min
native_category
source
source_detail
storm_id
storm_name
basin
note
```

扩展字段包括：

```text
rmw_nm
roci_nm
p_outer_hpa
r34_ne_nm r34_se_nm r34_sw_nm r34_nw_nm
r50_ne_nm r50_se_nm r50_sw_nm r50_nw_nm
r64_ne_nm r64_se_nm r64_sw_nm r64_nw_nm
jma_r50_long_dir
jma_r50_long_nm
jma_r50_short_nm
jma_r30_long_dir
jma_r30_long_nm
jma_r30_short_nm
cma_owd_ms
```

---

# 11. 面向 WW3 / Holland 风场的规则

如果用户要把路径用于 WW3 台风风场：

1. 先保留原始 best track；
2. 不直接修改原始 Vmax；
3. 另建“model forcing”表；
4. 记录：
   - 原始机构；
   - 原始风速平均时段；
   - 单位转换；
   - 若做 1-min/2-min/10-min 换算，记录换算公式和系数；
   - RMW 是观测/机构字段还是参数化估计；
   - 中心气压缺失时使用的估算关系；
5. 台风参数风场与 ERA5/GFS 背景场叠加时，不默认简单全域线性相加；应设置随中心距离变化的 blending 权重，避免双计台风环流和边界突变。

Holland 模型通常至少需要：

```text
中心位置
中心气压 Pc
环境气压 Pn
Vmax 或约束信息
RMW
B 参数或可估算它的关系
```

JTWC/IBTrACS USA 字段往往比单纯 CMA 六列数据更容易得到 RMW/风圈信息，但不同年份完整度会变化。

---

# 12. 质量检查要求

每次运行至少检查：

- UTC 是否正确；
- 纬度是否落在 [-90, 90]；
- 经度规范到 [-180, 180)；
- 是否跨 180° 经线；
- 是否有重复 UTC；
- 气压/风速缺测；
- 风速单位；
- 风速平均时段；
- 同名台风是否多匹配；
- JTWC 多风圈行是否已聚合；
- IBTrACS 是否混用了不同 agency。

若源格式不确定：

```text
不要猜，要求显式 --source
```

若台风匹配多个：

```text
不要自动取第一个，要求增加 --year 或 --id
```

---

# 13. 重要科学注意事项

**最佳路径不是预报路径。**

- Best Track 是事后综合分析；
- 实时预报轨迹、a-deck、NMC/JMA/JTWC forecast track 与最终 best track 不应混用；
- 做历史复现/验证一般使用 best track；
- 做真正实时 WW3 预报，应使用实时分析/预报路径并记录版本时间。

不同机构 Vmax 由于平均时段、分析方法和业务规则不同，不应只通过单位换算就直接等价。
