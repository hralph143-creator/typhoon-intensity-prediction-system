<template>
  <section class="page-stack">
    <div class="page-heading"><h2>关于云浪智析</h2></div>
    <el-card shadow="never" class="data-card">
      <h3>系统定位</h3>
      <p class="body-copy">本系统服务于“云浪智析——数智融合下台风强度演变智能预判平台”项目。当前版本已接入 NOAA IBTrACS、中国气象局 CMA 独立最佳路径和 ERA5 真实风场，并完成 Persistence、Ridge、LSTM 和 GRU 的未来6小时 CMA 风速历史回测。实时业务预报不在当前范围。</p>
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
