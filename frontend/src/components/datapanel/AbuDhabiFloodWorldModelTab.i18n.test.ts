import { describe, expect, it } from 'vitest';
import { buildCustomerHotspotMapLayer, translateAbuEnglishText } from './AbuDhabiFloodWorldModelTab';

describe('Abu Dhabi flood world-model English presentation', () => {
  it('builds the validated 506-point customer hotspot map layer contract', () => {
    const geojson = {
      type: 'FeatureCollection' as const,
      features: Array.from({ length: 506 }, (_, index) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [54.4, 24.4] },
        properties: { hotspot_id: index + 1, priority: index < 151 ? 'Very Important' : 'Important' },
      })),
    };
    const layer = buildCustomerHotspotMapLayer({ metadata: { feature_count: 506 }, geojson });
    expect(layer.layer_id).toBe('abu-dhabi-customer-hotspots-506');
    expect(layer.geojsonData.features).toHaveLength(506);
    expect(layer.category_column).toBe('priority');
    expect(layer.category_colors['Very Important']).toBe('#ef4444');
    expect(layer.tooltip_fields).toEqual(expect.arrayContaining(['hotspot_id', 'priority', 'center', 'description']));
  });

  it('translates the core workflow and scenario controls without Han characters', () => {
    const text = translateAbuEnglishText(
      '模型输入降雨数据 · 全市连续网络（单个 SWMM 作业） · 在线公开来源降雨数据（Open-Meteo）',
    );
    expect(text).toContain('Model rainfall input');
    expect(text).toContain('Citywide continuous network');
    expect(text).toContain('Online public rainfall data');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates dynamic SWMM receipt text and preserves values', () => {
    const text = translateAbuEnglishText(
      'EPA SWMM 原生 OUT 共包含 146,823 个结果节点；当前地图可定位 138,831 个（94.6%），7,992 个因几何缺失暂不可视化。已映射节点包含零值节点，且未按数值阈值或数量截断。该作业严格数值质量门未通过，仅用于诊断。',
    );
    expect(text).toContain('native EPA SWMM OUT');
    expect(text).toContain('146,823');
    expect(text).toContain('138,831');
    expect(text).toContain('7,992');
    expect(text).not.toContain('all nodes');
    expect(text).not.toContain('model metadata');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('states the 2D resolution and deployed GWM boundary in English', () => {
    const text = translateAbuEnglishText(
      '客户 5 m DTM 作为地形输入，ANUGA 2D 实际采用 250 m 计算网格并接受 SWMM 单向源项；2/5/10/25/50/100 年一遇结果可切换，但尚未完成观测校准和工程准入。 当前可调用版本为 GWM-R1-20260914：17 场训练事件，学习 250 m SWMM–ANUGA 物理标签；它不是直接由历史积水观测训练的工程预测模型。',
    );
    expect(text).toContain('5 m DTM');
    expect(text).toContain('250 m computational grid');
    expect(text).toContain('one-way SWMM source terms');
    expect(text).toContain('GWM-R1-20260914');
    expect(text).toContain('17 training events');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('distinguishes complete topology nodes from source facility points', () => {
    const topology = translateAbuEnglishText('模型输入 · 管线端点拓扑节点（0.1 m 吸附派生，238,350 个）');
    const facilities = translateAbuEnglishText('原始参考 · Makani SW_NODE 设施点（8,614 个，不代表全部管线端点）');
    expect(topology).toBe('Model input · pipe-endpoint topology nodes (0.1 m snap-derived, 238,350 features)');
    expect(facilities).toBe('Source reference · Makani SW_NODE facilities (8,614 features, not all pipe endpoints)');
  });

  it('labels SWMM execution as a simulation rather than a real-world result', () => {
    expect(translateAbuEnglishText('运行真实 SWMM 情景')).toBe('Run SWMM Simulation');
    expect(translateAbuEnglishText('正在执行真实 SWMM…')).toBe('Running SWMM Simulation...');
  });

  it('labels the phase-4 execution action as historical inundation inference', () => {
    expect(translateAbuEnglishText('推理历史积水过程')).toBe('Run historical inundation inference');
    expect(translateAbuEnglishText('规则型情景筛选')).toBe('Rule-based scenario screening');
    expect(translateAbuEnglishText('运行规则型情景筛选')).toBe('Run rule-based scenario screening');
    expect(translateAbuEnglishText('GWM 推演模式')).toBe('GWM inference mode');
    expect(translateAbuEnglishText('历史降雨场次')).toBe('Historical rainfall event');
    expect(translateAbuEnglishText('出水边界水位调整（m）')).toBe('Outfall boundary level adjustment (m)');
    expect(translateAbuEnglishText('二维历史事件')).toBe('2D historical event');
  });

  it('does not expose the legacy placeholder or Han characters for unmapped receipt fragments', () => {
    const text = translateAbuEnglishText('遗留诊断字段：未知状态');
    expect(text).toBe('untranslated field: UnknownStatus');
    expect(text).not.toContain('model metadata');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates dynamic map labels without generic fallback words', () => {
    const text = translateAbuEnglishText('全市二维最大积水深度（m）· 公共 DEM 原型');
    expect(text).toBe('Citywide 2D maximum flood depth (m) · public DEM prototype');
    expect(text).not.toContain('source label');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates the complete phase-3 invocation and registered-result vocabulary', () => {
    const text = translateAbuEnglishText(
      '二维模型调用 · 求解器与一维输入 · 二维求解器 · ANUGA 2D（当前可新建作业） · '
      + '地形、网格与糙率 · 客户 AUH_DTM 5 m（主输入） · 交换与重复计量控制 · '
      + '动态水头反向反馈 · 本次新算关闭（双向已算成果可在右侧页面加载） · '
      + '已登记的二维成果 · SWMM–ANUGA 同步双向验证（100 年一遇） · 登记成果运行回执 · 能力边界',
    );
    expect(text).toContain('2D model invocation');
    expect(text).toContain('Solver and 1D input');
    expect(text).toContain('ANUGA 2D (new jobs available)');
    expect(text).toContain('Terrain, grid and roughness');
    expect(text).toContain('Customer AUH_DTM 5 m (primary input)');
    expect(text).toContain('Exchange and double-counting controls');
    expect(text).toContain('Dynamic head feedback');
    expect(text).toContain('Registered 2D results');
    expect(text).toContain('Synchronous two-way SWMM–ANUGA validation');
    expect(text).toContain('Registered-result run receipt');
    expect(text).toContain('Capability boundary');
    expect(text).not.toContain('model metadata');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates phase-3 timeline tooltip fields instead of using a placeholder', () => {
    const text = translateAbuEnglishText('二维单元 ID · 模拟时间（分钟） · 积水深度（m） · 最大深度时刻（分钟）');
    expect(text).toBe('2D cell ID · Simulation time (minutes) · Flood depth (m) · Time of maximum depth (minutes)');
    expect(text).not.toContain('model metadata');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates GWM spatialized-result labels and summary metrics', () => {
    const text = translateAbuEnglishText(
      '阿布扎比暴雨内涝世界模型 · GWM 快速推演 | GWM 基线最大积水深度（m） | 空间响应倍率 | 水域主导单元 | 基线受影响网格',
    );
    expect(text).toContain('Abu Dhabi Stormwater Flood World Model · GWM rapid rollout');
    expect(text).toContain('GWM baseline maximum flood depth (m)');
    expect(text).toContain('Spatial response factor');
    expect(text).toContain('Water-dominated cell');
    expect(text).toContain('baseline affected cells');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });

  it('translates customer pipe and topology-node tooltip labels exactly', () => {
    const pipeLabels = translateAbuEnglishText(
      '客户管段 FID | 起点拓扑 ID | 终点拓扑 ID | 重算长度（m） | 管径候选值 | 管材 | 管线状态',
    );
    expect(pipeLabels).toBe(
      'Customer pipe FID | Source topology node ID | Target topology node ID | Recomputed length (m) | Candidate diameter | Pipe material | Pipe status',
    );
    const nodeLabels = translateAbuEnglishText(
      '拓扑节点 ID | 连接度 | 吸附端点数 | 连通分量 | 候选设施数 | 候选设施角色',
    );
    expect(nodeLabels).toBe(
      'Topology node ID | Node degree | Snapped endpoint count | Connected component | Candidate facility count | Candidate facility roles',
    );
  });

  it('preserves GWM spatial summary counts in English', () => {
    const text = translateAbuEnglishText(
      'GWM 基于阶段 3 二维地表结果进行 100 年一遇快速 rollout；15,300 个二维单元（15,300 个陆域有效单元，排除 0 个水域单元）、11 个时间片。',
    );
    expect(text).toContain('100-year event');
    expect(text).toContain('15,300 2D cells');
    expect(text).toContain('15,300 active land cells');
    expect(text).toContain('0 water cells excluded');
    expect(text).toContain('11 time slices');
    expect(text).not.toMatch(/[\u3400-\u9fff]/u);
  });
});
