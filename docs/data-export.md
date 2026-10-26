# 数据与结果导出

- `/api/exports/workbook`：包含历史台风、历史观测、模型实验、评价指标、预测结果和综合统计的 XLSX。
- `/api/exports/typhoons.csv` 与 `/api/exports/predictions.csv`：UTF-8 BOM CSV，保留单位和 UTC 时间。
- `/api/exports/model-comparison.png`：服务端按正式指标重绘的 PNG，不依赖浏览器截图。

所有文本单元格都防护以 `= + - @` 开头的公式注入。导出只读数据库，不触发训练或数据下载。
