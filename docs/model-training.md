# 模型训练

训练任务在单独后台工作线程运行，FastAPI 请求只创建任务。同时只允许一个训练任务，状态包含 queued、preparing、training、evaluating、succeeded、failed、cancelled 和 interrupted。重启时会将遗留运行态标记为 interrupted。

“模型训练”页面允许选择模型、严格/扩展质量配置、Epoch、Batch Size、学习率、隐藏维度和随机种子。页面实时读取进度、Epoch 和训练/验证损失，不生成模拟曲线。

成功实验将最佳权重、预处理参数、数据版本、特征列表、训练配置和评估结果保存到 `checkpoints/<experiment-id>/`；实验元数据在 SQLite。这些大文件已排除出 Git。
