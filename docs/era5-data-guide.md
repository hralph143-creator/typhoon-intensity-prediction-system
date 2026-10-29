# ERA5 数据接入指南

## 官方来源与授权

本系统使用 ECMWF/Copernicus ERA5 单层再分析数据，仅请求 10 m U、V 风分量。默认公共通道为 Google Cloud 公共数据集中的 ARCO-ERA5，可匿名读取；扩展通道仍支持 Copernicus Climate Data Store 的 `cdsapi`。Windows 用户登录 CDS 后，可将个人配置保存为 `%USERPROFILE%\.cdsapirc`：

```yaml
url: https://cds.climate.copernicus.eu/api
key: <PERSONAL-ACCESS-TOKEN>
```

令牌不得写入 `.env`、数据库、日志或 Git。还必须登录 ERA5 数据集页面手动接受 CC-BY 许可。配置页：<https://cds.climate.copernicus.eu/how-to-api>；数据集页：<https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels>。

页面“检查 CDS 连接”只返回是否已配置和客户端是否能初始化，不返回 URL 或令牌。未授权时系统不会创建 CDS 伪下载任务，但可使用公共 ARCO-ERA5 通道取得真实数据。

## 小范围下载策略

- 数据集：`reanalysis-era5-single-levels`。
- 变量：`10m_u_component_of_wind`、`10m_v_component_of_wind`。
- 格式：NetCDF，单文件不压缩。
- 时次：每个任务恰好一个 UTC 小时；一个第三阶段样本对应 `t-18h、t-12h、t-6h、t`。
- 范围：历史台风中心四周各 4°，单请求最大 10°×10°；跨 ±180° 自动拆成两块。
- 并发：默认 1；磁盘预算默认 20 GB。CDS 服务端排队时无法得到可信字节进度，界面显示阶段而不伪造百分比。

请求内容经规范化 JSON 计算 SHA-256。已有相同请求且文件有效时命中缓存。任务持久化状态、阶段、请求、错误和文件关联；应用重启会将未完成任务记为 `interrupted`，允许手动重试。取消是合作式的：本地提交前可立即停止；CDS 服务端已经处理时，要等 API 返回后才清理本地结果。

## 本地导入与质量门槛

可导入 `.nc` 或 `.nc4`。文件进入业务归档前必须通过：

1. 同时存在 U10、V10，支持短名 `u10/v10` 和官方长名。
2. 纬度、经度、时间坐标存在；时间范围与维度可解析。
3. 单位为空时记录，非空时必须是常见 m/s 表达。
4. U/V 联合有效率可计算且非零；裁剪后必须至少 99.9% 有效。
5. 合成风速最大值不超过 150 m/s。
6. 文件 SHA-256 唯一，原始文件只归档一次。

NetCDF3/NetCDF4 均通过内存读取，以规避 Windows 中文路径的底层库编码问题。业务原始文件位于 `data/raw/era5/`，已被 Git 忽略。

## 当前机器状态

2026-10-27 检查结果：没有 `.cdsapirc` 或 `CDSAPI_URL/CDSAPI_KEY`；公共 ARCO-ERA5 已成功读取并归档 1 个 NetCDF，覆盖 4 个 UTC 时次，质量有效率 100%，已构建 4 个单时次风场和 1 个 `4×2×31×31` 时空样本。CDS 个人令牌仍可在需要批量扩展时配置。

## 第八阶段批处理约束

批次先冻结 SID、起报时间、目标时间和四个输入时次，再开始访问远端。选样规则固定为“新独立事件优先，其次按时间排序”，不读取模型误差。ARCO 分析就绪数组的一个小时/变量块覆盖全球 0.25° 网格，系统按每块约 154 MiB 对远程量作保守估算；U10/V10 四时次单样本按 8 块计。默认单批远程预算 4 GiB、本地 ERA5 预算 20 GiB、并发 1、超时 1800 秒。

每条完成项立即写入批次游标。暂停、失败或部分完成后可从游标恢复；已归档请求、单时次风场和四时次样本分别通过请求指纹及版本唯一键复用。`spatiotemporal-v2` 与 `era5-crop-v2` 不覆盖第七阶段 v1 文件。质量审计通过后可生成带文件 SHA-256 的不可变数据集清单。
