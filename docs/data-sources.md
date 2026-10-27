# 数据来源与使用边界

## NOAA IBTrACS

本阶段接入 NOAA National Centers for Environmental Information（NCEI）发布的 International Best Track Archive for Climate Stewardship（IBTrACS），优先使用西北太平洋子集 `ibtracs.WP.list.v04r01.csv`。

- [官方介绍与资料入口](https://www.ncei.noaa.gov/products/international-best-track-archive)
- [v04r01 CSV 目录](https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/)
- [WP 官方 CSV](https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.WP.list.v04r01.csv)
- [技术说明（2025-04）](https://www.ncei.noaa.gov/sites/default/files/2025-04/IBTrACS_version4r01_Technical_Details.pdf)
- [字段说明（2025-09-23）](https://www.ncei.noaa.gov/sites/default/files/2025-09/IBTrACS_v04r01_column_documentation.pdf)

IBTrACS 汇集多个气象机构提供的最佳路径。不同机构观测方法和风速平均时段存在差异，不能简单合并或按固定比例换算成同一机构口径。最佳路径属于事后分析资料；其中暂定轨迹及最新年份的记录还可能修订。

### 研究范围

程序按观测行筛选 `BASIN=WP`，同时限制 `SEASON` 为 2014—2025 年且观测 UTC 时间在 `[2014-01-01 00:00:00, 2026-01-01 00:00:00)`。WP 文件包含曾进入该海域的系统在其他海域的记录，因此文件名不能代替 BASIN 筛选。本系统保留 WP 内符合条件的轨迹段，页面显示的起止时间是研究范围内首末记录，并不保证覆盖系统在其他海域的完整生命周期。南海属于此处的西北太平洋范围。

默认统计和路径展示以 `MAIN` 为主轨迹口径；导入时保留其他轨迹类型及质量标记，详情可选择轨迹类型。`US-PROVISIONAL` 表示美国机构变量和合成轨迹仍属暂定资料，而其他机构变量可能已经是最佳路径；不把它等同于全部机构最终定稿。

### 原始文件与可追溯性

原始 CSV 保存在 `data/raw/ibtracs/`，不在清洗时覆盖。文件登记记录原始文件名、官方版本、字节数、SHA-256、来源 URL、获取时间与导入时间。每条观测关联源文件，并保留原始字段字典。导入任务记录筛选、缺测、重复、冲突和错误计数。SHA-256 用于本地内容一致性和幂等识别；若官方未提供独立校验值，不应宣称它代表官方签名认证。

### 引用与许可说明

使用数据发表报告、论文或其他成果时，应遵守 NOAA 官方页面和原始贡献机构的使用说明，注明 IBTrACS 版本、下载日期及本系统筛选规则。NOAA 要求在有参考文献的作品中同时引用数据集与基础论文：

- 数据集 DOI：[10.25921/82ty-9e16](https://doi.org/10.25921/82ty-9e16)
- Knapp, K. R., M. C. Kruk, D. H. Levinson, H. J. Diamond, and C. J. Neumann, 2010: *The International Best Track Archive for Climate Stewardship (IBTrACS): Unifying tropical cyclone best track data*. BAMS, 91, 363–376. [10.1175/2009BAMS2755.1](https://doi.org/10.1175/2009BAMS2755.1)

官方页面的用户登记用于帮助团队了解资料使用情况。软件不会代替用户提交登记或接受额外条款。

## 后续数据来源

- [中国气象局 CMA 最佳路径数据](https://tcdata.typhoon.org.cn/zjljsjj.html)：已独立解析并入库 2014—2025 年年度 TXT；与 IBTrACS 事件分开保存，可按 `source=cma` 查询，不拿 IBTrACS 内嵌字段冒充独立来源。
- [Copernicus ERA5 单层再分析数据](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)：已通过 Google Cloud 公共 ARCO-ERA5 镜像接入真实 U10/V10，并保留上游生产方、公共存储地址、时间范围、空间范围和 SHA-256。ERA5 是历史再分析资料，不是实时预报资料。

## 第三方组件

后端使用 FastAPI（MIT）、SQLAlchemy（MIT）、Pydantic（MIT）、Uvicorn（BSD-3-Clause）、HTTPX（BSD-3-Clause）及 python-multipart（Apache-2.0）；前端使用 Vue（MIT）、Vite（MIT）、TypeScript（Apache-2.0）、Element Plus（MIT）、Pinia（MIT）、Vue Router（MIT）、Axios（MIT）、ECharts（Apache-2.0）和 Leaflet（BSD-2-Clause）。具体安装版本由依赖文件和锁文件记录；分发时应保留各组件许可证。

地图底图使用在线地图服务时，应保留底图署名并遵守服务使用政策。网络中断可能影响底图显示，不改变数据库中的经纬度和轨迹数据。

本系统用于科研与教学，提供历史数据分析，不构成气象主管部门的业务预报或预警。
