# 第二阶段验收记录

验收日期：2026-10-26（Asia/Shanghai）。本记录对应版本 0.2.0，范围仅限真实历史台风数据接入、管理、查询与可视化；未开展 ERA5、模型训练、预测或评估。

## 真实数据快照

- 来源：NOAA NCEI IBTrACS v04r01 西北太平洋 CSV。
- 原始文件：`ibtracs.WP.list.v04r01.csv`，114,661,893 字节。
- SHA-256：`ff4b6937d54f2f34fe4f87fb1361930ed67856ae870a9c20af46c66b70bc3d9c`。
- 选择口径：`SEASON` 和观测 UTC 年份均在 2014—2025，逐行 `BASIN=WP`；保留全部轨迹类型，默认统计 MAIN。
- 原始数据行 249,153；有效观测 23,188；跳过 225,965；失败 0。
- 保留事件 366 个，其中含 MAIN 的默认统计事件 331 个；MAIN 观测 21,246 条。
- 缺失 CMA 风速 3,636 条；非 MAIN 1,942 条；其中临时轨迹 1,924 条。缺测不填补，机构风速平均时段不混合。
- 2025 年 MAIN 事件仅 2 个，包含其他轨迹类型时为 36 个。这是当前官方归档状态，不应将 MAIN 数直接解读为当年全部气旋数。

## 导入与幂等性

1. 首次官方下载及导入任务 `7d6c277a-db08-4387-8baf-76aa7f34ba14` 成功，插入 23,188 条观测，导入阶段用时 16.718 秒。
2. 清洗策略升级为 `wp-observations-2014-2025-cma17-censored-latest-main-v2` 后，任务 `339ec17a-db39-4768-a72f-021def433326` 完成全量重扫：新增 0，重复 23,188，冲突 0。
3. 最终使用真实 Edge 页面上传同一个 114.66 MB CSV，任务 `c9749f61-b80c-432e-a3f2-c14f97904271` 成功：`idempotent=true`，新增 0，事件和观测数未增长，耗时 0.109 秒。

原始文件、数据库和任务记录保留在本地且已排除出 Git。文件哈希用于本地一致性和幂等识别，不代表 NOAA 数字签名。

## 自动化和真实浏览器结果

- 后端：`58 passed`，覆盖数据库隔离、CSV 解析、单位与缺测、导入幂等、下载断点/重试/校验、任务锁/取消/恢复、历史查询 API 和启动器。
- 前端：`15 passed`，4 个测试文件；TypeScript 检查和 Vite 生产构建通过。
- 真实浏览器：本机 Microsoft Edge 无界面运行，`17 passed`，无页面异常。已实测首页统计图、MERANTI 名称查询、Leaflet 真实轨迹、风速/气压曲线、时次/地图/表格联动、空结果、MAIN/全部轨迹切换、任务恢复、115 MB 真实上传与幂等、后续模块空状态和 1280 px 视口。
- 环境检查：Python 3.12.10、Node.js 24.13.0、npm 11.6.2，`run.bat --check` 全部通过。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm run type-check
npm test -- --run
npm run build
cd ..
$env:TEST_REAL_UPLOAD='1'
node scripts\browser_smoke.cjs
```

## 已知边界

- 地图底图依赖在线瓦片；无网络时会保留经纬网、坐标标注和本地真实轨迹。
- 生产构建有较大图表/UI 依赖分块的性能提示，不影响本阶段功能验收；可在后续性能优化中进一步拆分。
- 后端测试仅有 Starlette 依赖内部 `BlockingPortal` 别名弃用警告，无失败用例。
