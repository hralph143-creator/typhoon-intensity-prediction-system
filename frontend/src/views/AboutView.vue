<template>
  <section class="page-stack">
    <div class="page-heading"><h2>关于云浪智析</h2></div>
    <el-card shadow="never" class="data-card">
      <h3>系统定位</h3>
      <p class="body-copy"><strong>基于时空注意力的台风强度预测系统</strong>（品牌：云浪智析）用于历史台风资料管理、ERA5 风场分析、模型训练记录、未来 6 小时风速历史回测、模型评价及科研报告生成。当前版本已接入 NOAA IBTrACS、中国气象局 CMA 独立最佳路径和 ERA5 真实风场，并保存 Persistence、Ridge、LSTM、GRU 和 SAF-Net 的真实实验结果。</p>
      <h3>数据来源与接入范围</h3>
      <ul class="source-list">
        <li><strong><a href="https://www.ncei.noaa.gov/products/international-best-track-archive" target="_blank" rel="noopener">NOAA IBTrACS ↗</a></strong><span>国际热带气旋最佳路径档案 · v04r01 · 已提供接入能力</span></li>
        <li><strong>中国气象局 CMA</strong><span>2014—2025 独立最佳路径文件 · 已解析入库</span></li>
        <li><strong>ECMWF / Copernicus ERA5</strong><span>公共 ARCO 镜像 U10、V10 再分析风场 · 已接入真实四时次样本</span></li>
      </ul>
      <p class="body-copy">不同机构风速平均时段不同，系统保留原值与机构信息，不将其换算为同一种观测口径。历史最佳路径与再分析资料均不代表实时预报。</p>
      <el-alert title="使用边界" description="本系统仅供科研与教学使用，不构成气象主管部门发布的业务预报或预警。" type="warning" :closable="false" show-icon />
    </el-card>
  </section>
</template>
