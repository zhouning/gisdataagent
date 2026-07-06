# UWM Shanghai Data Requirements Inventory

- Generated: `2026-07-05`
- Working directory: `/Users/zhouning/gisdataagent`
- Output directory: `docs/reports/uwm_shanghai_data_requirements_2026-07-05`

## Code Roots

### `/Users/zhouning/gisdataagent`

- Exists: `True`
- Project: GIS Data Agent
- Relevant modules:
  - `data_agent/uwm/`
  - `data_agent/test_uwm_*.py`
  - `scripts/build_uwm_*.py`
  - `scripts/download_uwm_*.py`
- Relevant docs:
  - `docs/uwm-urban-livability-strategic-technical-proposal.md`
  - `docs/uwm-livability-track2-design-2026-07-04.md`
  - `docs/uwm-renderer-simulator-planner-theory-2026-07-04.md`
  - `docs/uwm-livability-implementation-roadmap-2026-07-04.md`
  - `docs/reports/uwm_data_foundation_summary_2026-07-05.md`
  - `docs/reports/uwm_data_foundation_manifest.md`
  - `docs/reports/uwm_livability_business_theory_2026-07-05.md`
  - `docs/reports/uwm_model_based_rl_inspiration_implementation_2026-07-05.md`

## Generated Artifacts

- `UWM上海市权威数据需求说明书.md`
- `UWM上海市权威数据需求说明书.docx`
- `evidence-pack.md`
- `traceability-matrix.md`
- `templates/README_模板说明.md`
- `templates/*.csv`
- `templates/production_scale_profile_template.json`

## Recommended Next Steps

1. 与上海市数据主管确认可申请的源系统、数据目录、字段边界和授权方式。
2. 先提交模板和脱敏字段映射，不直接索取敏感明细。
3. 优先选择一个试点主题，例如城市体检、城市更新、气候健康风险或公共服务补短板。
4. 在上海市授权环境中运行 renderer/state construction，再逐步进入 simulator/planner 真实验证。
