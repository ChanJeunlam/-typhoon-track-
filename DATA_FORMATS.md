# 台风路径数据深度解析

## 1. 为什么同一个台风会有“很多条路径”

同一热带气旋可以同时存在：

1. **实时分析路径**：业务中心当前认为的位置；
2. **预报路径**：未来 24/48/72/120 h 的预测位置；
3. **Best Track**：台风结束后综合更多观测重新分析得到的事后最佳路径；
4. **不同机构的 Best Track**：CMA、JMA、JTWC、HKO 等会有中心位置和强度差异；
5. **集合/数值模式轨迹**：ECMWF/GFS/集合成员的涡旋追踪结果，不是官方 Best Track。

做历史 WW3 复现/验证通常优先 Best Track；做实时预报则应使用实时分析 + forecast track。

## 2. 风速平均时段是核心差异

- CMA：2-min MSW，m/s；
- JMA/RSMC Tokyo：10-min MSW，kt；
- JTWC：1-min MSW，kt；
- IBTrACS：保留多机构字段，取决于选择的 agency。

`kt -> m/s` 是单位换算；`1-min -> 10-min` 是统计定义转换，二者不是一回事。

不要在没有注明转换方案时把不同平均时段的 Vmax 混合用于 Holland B、风压关系或强度误差统计。

## 3. CMA

头记录 `66666` 后给出国际编号、记录数、名称、修订时间等。

数据行：

```text
YYYYMMDDHH I LAT LONG PRES WND [OWD]
```

纬经度均为 0.1°整数编码。

特殊值：
- `WND=0`：未知；
- `WND=9`：`MSW < 10 m/s`。

2017/2018 以后部分登陆中国台风在登陆前/陆地阶段有 3 h 加密记录，因此不能硬编码“永远 6 小时”。

## 4. JMA

头记录与 CMA 外形相似，但数据时间为 `YYMMDDHH`。

数据行：

```text
YYMMDDHH 002 C DDD EEEE FFFF GGG HIIII JJJJ KLLLL MMMM [P]
```

- `C`：等级；
- `DDD`：纬度 0.1°；
- `EEEE`：经度 0.1°；
- `FFFF`：中心气压 hPa；
- `GGG`：最大持续风 kt；
- `HIIII/JJJJ`：50 kt 风圈最长方向/最长半径/最短半径；
- `KLLLL/MMMM`：30 kt 风圈最长方向/最长半径/最短半径。

## 5. JTWC / ATCF b-deck

核心字段顺序：

```text
BASIN,CY,YYYYMMDDHH,TECHNUM,TECH,TAU,LAT,LON,VMAX,MSLP,TY,
RAD,WINDCODE,RAD1,RAD2,RAD3,RAD4,POUTER,ROUTER,RMW,...
```

### 多行同一时刻

例如：

```text
2019080712 ... RAD=34 ...
2019080712 ... RAD=50 ...
2019080712 ... RAD=64 ...
```

应聚合为一个时间点，并把风圈写入不同字段；不能简单 `drop_duplicates(time)`，否则可能丢掉 50/64 kt 风圈。

### 经纬度

ATCF 常见：

```text
245N
1234E
```

即：

```text
24.5°N
123.4°E
```

S/W 需要取负。

### 风圈

`NEQ` 通常表示四象限顺序：

```text
NE, SE, SW, NW
```

## 6. IBTrACS

IBTrACS 的优势是统一结构，不是统一“物理定义”。

常见字段组：

```text
LAT/LON/WMO_WIND/WMO_PRES/WMO_AGENCY
USA_LAT/USA_LON/USA_WIND/USA_PRES/USA_STATUS
TOKYO_LAT/TOKYO_LON/TOKYO_WIND/TOKYO_PRES/TOKYO_GRADE
CMA_LAT/CMA_LON/CMA_WIND/CMA_PRES/CMA_CAT
HKO_LAT/HKO_LON/HKO_WIND/HKO_PRES/HKO_CAT
```

对科研最安全的做法是显式指定 `--agency`，并把 agency 写进结果元数据。

## 7. Holland / WW3 前处理建议

Best Track 只是路径/强度约束，不等于完整二维风场。

生成参数化台风风场时还可能需要：
- 环境气压 Pn；
- RMW；
- Holland B；
- 平移速度；
- 非对称修正；
- 34/50/64 kt 风圈约束。

若 RMW 缺失，需要使用经验关系估计时，必须另存 `rmw_method`/`rmw_source`，不要覆盖原始 best-track 字段。

与 ERA5/GFS 混合时建议构造距离相关的 blending 权重，而不是无条件把两个风矢量全域直接相加。
