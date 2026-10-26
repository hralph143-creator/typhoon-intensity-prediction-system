# 云浪智析——基于时空注意力的台风强度预测系统

这是面向台风强度演变研究的前后端分离科研软件。当前完成**第一阶段：工程初始化与基础架构搭建**。

当前版本不包含真实台风数据、训练模型、预测结果或性能指标；未开发模块会明确显示“尚未接入”。

## 技术架构

- 后端：Python 3.12、FastAPI、SQLAlchemy、Pydantic、SQLite
- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Axios、ECharts
- 测试：pytest、Vitest、TypeScript 类型检查、Vite 生产构建

## 首次安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm install
cd ..
```

需使用 Python 3.12。若 `python` 不是 3.12，请改用本机 Python 3.12 解释器的完整路径。可将 `.env.example` 复制为 `.env` 修改配置；默认配置可直接运行。

## 启动与检查

双击 `run.bat`，或运行 `run.bat`。访问：

- 前端：http://127.0.0.1:5173
- API 文档：http://127.0.0.1:8000/docs

环境检查：`run.bat --check`

## 自动化测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v
cd frontend
npm run type-check
npm run test
npm run build
```

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
- `GET /api/data-sources/status`：根据本地目录检测 IBTrACS、CMA、ERA5 接入状态

规划数据来源为 NOAA IBTrACS、中国气象局 CMA 最佳路径数据和 Copernicus ERA5。当前阶段未下载这些数据。系统仅供科研与教学使用，不构成业务气象预报或预警。

下一阶段将优先实现 IBTrACS 数据下载、校验、解析、清洗与入库；本阶段不会自动进入该工作。
