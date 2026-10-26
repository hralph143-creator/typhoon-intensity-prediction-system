# 云浪智析——基于时空注意力的台风强度预测系统

这是面向台风强度演变研究的前后端分离科研软件。当前版本为 **0.3.0，第三阶段：历史强度时序预测与模型评估**。

已接入 NOAA 官方 IBTrACS 西北太平洋历史数据，并使用严格 CMA IFLAG 质量筛选构建未来 6 小时预测样本。系统已实际训练 Persistence、Ridge、LSTM 和 GRU，支持历史回测推理、真实指标比较、实验管理和导出。ERA5 和 SAF-Net 仍未接入。

## 技术架构

- 后端：Python 3.12、FastAPI、SQLAlchemy、Pydantic、SQLite、PyTorch、scikit-learn
- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Axios、ECharts、Leaflet
- 测试：pytest、Vitest、Playwright、本机 Edge 浏览器、TypeScript 类型检查、Vite 生产构建

## 首次安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm ci
cd ..
```

需使用 Python 3.12、Node.js 22+。若 `python` 不是 3.12，请改用本机解释器的完整路径。可将 `.env.example` 复制为 `.env` 修改配置；默认配置可直接运行。后端首次启动自动执行数据库版本迁移，保留第一阶段系统表。

本机实际验证环境：Python 3.12.10、Node.js 24.13.0、npm 11.6.2。若临时目录权限限制导致虚拟环境 `ensurepip` 失败，可将当前终端的 TEMP、TMP 指向项目内可写临时目录后重试，避免改动全局环境。

## 启动与检查

双击 `run.bat`，或运行 `run.bat`。访问：

- 前端：http://127.0.0.1:5173
- API 文档：http://127.0.0.1:8000/docs

环境检查：`run.bat --check`。启动器检查实际服务就绪状态，复用已运行的本项目服务；其他程序占用端口时会明确提示。后台日志位于 `logs/`。

## 真实数据获取与使用

在“历史台风数据 → 数据接入与任务”中点击“下载官方数据并导入”。默认复用 SHA-256 校验通过的官方缓存；勾选“强制刷新官方文件”可重新获取 NOAA 当前文件。任务支持进度、速度、取消、失败原因和刷新后恢复查询。

本地文件可通过页面“上传本地 CSV”导入，或使用命令行：

```powershell
.\.venv\Scripts\python.exe -m backend.cli download
.\.venv\Scripts\python.exe -m backend.cli download --force
.\.venv\Scripts\python.exe -m backend.cli import "D:\数据\ibtracs.WP.list.v04r01.csv"
```

API 与 CLI 共用处理逻辑和跨进程任务锁。CSV 分块接收、逐行解析、批量入库；导入失败或取消会回滚未提交业务记录。相同 SHA-256 和处理策略重复导入不增加事件或观测。

数据选择规则为 **SEASON 与实际 UTC 年份均为 2014—2025，逐条 BASIN=WP**。保留其他轨迹类型，默认展示 MAIN；勾选“包含临时轨迹和支轨事件”可查询全部事件。2025 年仍有不少 US-PROVISIONAL 记录，MAIN 数量不能代表当年全部气旋数量。

默认统计 CMA 2 分钟平均风速；USA、TOKYO 和 WMO 独立显示。节只换算成 m/s，不转换平均时段。CMA 17 kn 特殊代码保留原值，精确风速为空。缺测不填补，质量标记和原始字段可追溯。

2026-10-26 首次真实导入结果：249,153 行原始数据，23,188 条有效观测，366 个保留事件，其中 331 个含 MAIN。详见 [第二阶段验收记录](docs/phase-2-acceptance.md)。这些是当前归档快照统计，不是对全部官方台风数量的业务认定。

## 历史强度回测

主实验仅使用 MAIN 轨迹且 CMA IFLAG 第三位为 O/V 的风速。输入为同一 SID 的 `t-18h、t-12h、t-6h、t`，标签为 `t+6h`；空值、17 kn 特殊编码和不连续窗口不会填零或插值。按台风事件和时间分为 2014—2021 训练、2022—2023 验证、2024 主测试；2025 无符合主轨迹严格窗口的样本，不强行混入。

实际主实验均在同一组 722 个 2024 年样本上评价：

| 模型 | MAE (m/s) | RMSE (m/s) | Bias (m/s) | 相对 Persistence MAE 改善 |
|---|---:|---:|---:|---:|
| Persistence | 1.9288 | 3.1267 | 0.2373 | 0.00% |
| Ridge | 1.6956 | 2.4460 | 0.0706 | 12.09% |
| LSTM | 1.6075 | 2.3590 | -0.0414 | 16.66% |
| GRU | 1.6429 | 2.3980 | 0.1093 | 14.83% |

指标与模型文件相互关联，不是页面硬编码。在“模型训练”创建后台任务，在“强度预测”选择历史台风和起报时刻，在“预测性能评估”查看真实测试结果。详见 [第三阶段验收报告](docs/phase-3-acceptance.md)。

## 自动化测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v
cd frontend
npm run type-check
npm run test
npm run build
cd ..
node scripts\browser_smoke.cjs
```

浏览器验收要求前后端已启动且存在真实入库数据，使用本机 Edge 无界面执行。截图和报告位于 `logs/browser-qa/`；可设 `TEST_REAL_UPLOAD=1` 附加真实原始文件重复上传验证。自动化后端样例仅进入隔离测试数据库，不污染正式数据。

## 目录说明

```text
backend/       FastAPI 应用、数据访问与后端测试
frontend/      Vue 3 用户界面
data/          原始数据、处理数据、缓存与 SQLite 数据库
checkpoints/   后续模型权重
experiments/   后续实验结果
logs/          运行日志
scripts/       工程检查脚本
docs/          项目文档
```

## 当前 API

- `GET /api/health`：服务与数据库健康状态
- `GET /api/system/info`：真实运行环境与路径信息
- `GET /api/data-sources/status`：本地文件与实际入库状态
- `GET /api/ibtracs/status`、`GET /api/ibtracs/jobs`：文件元信息和任务记录
- `POST /api/ibtracs/download`、`POST /api/ibtracs/import`、`POST /api/ibtracs/reimport`：后台下载/导入
- `POST /api/ibtracs/jobs/{id}/cancel`：请求取消
- `GET /api/typhoons`：过滤、排序与分页
- `GET /api/typhoons/statistics`：按明确口径统计
- `GET /api/typhoons/{id}`、`/track`、`/intensity`、`/observations`：档案、路径、曲线与原始观测
- `GET /api/ml/audit`、`/samples/statistics`：训练前真实审计与分组
- `POST/GET /api/ml/experiments`：训练任务与实验查询、取消和删除
- `GET /api/ml/models`、`/comparison`：已保存模型与公平指标比较
- `POST /api/ml/predict`：调用真实模型执行历史回测
- `GET /api/ml/export/experiments`：导出 CSV 或 Excel 实验记录

接口返回统一 `success/message/data` 格式；错误返回 `success=false/message/error`。日期统一 UTC，风速 m/s、气压 hPa，原始风速 knots 和机构保留。SQLite WAL 模式允许导入事务期间继续查询旧的已提交数据。

## 文档和使用边界

- [数据来源与署名](docs/data-sources.md)
- [字段与清洗规则](docs/data-fields.md)
- [下载和导入说明](docs/data-import.md)
- [第二阶段验收记录](docs/phase-2-acceptance.md)
- [训练数据构建](docs/training-data.md)
- [第三阶段数据审计](docs/phase-3-data-audit.md)
- [模型设计](docs/model-design.md)
- [模型训练](docs/model-training.md)
- [模型评价](docs/model-evaluation.md)
- [第三阶段操作说明](docs/phase-3-operations.md)
- [第三阶段验收报告](docs/phase-3-acceptance.md)

当前使用的是 NOAA IBTrACS 中的 CMA 字段，并未接入独立 CMA TXT 数据源或 ERA5。地图底图来自 OpenStreetMap；网络不可用时显示经纬网与真实路径。Leaflet 和 ECharts 均动态渲染，未使用截图伪装交互图表。

原始文件、数据库、任务锁、模型权重、虚拟环境、前端依赖和运行日志均不纳入 Git；请单独备份科研数据。系统仅供科研教学，不构成业务气象预报或预警。后续阶段需在当前清洗结果上进行严格事件/年份隔离和真实基线实验；本次完成后不自动开展训练。
