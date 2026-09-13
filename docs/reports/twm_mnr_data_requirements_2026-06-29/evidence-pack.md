# TWM 自然资源数据需求证据包

## 输入证据

| 证据 | 路径 | 用途 |
|---|---|---|
| 生产输入要求 | `docs/twm-production-input-data-requirements.md` | 字段组、通过门槛、scale profile、生产接入命令 |
| validation bundle | `docs/reports/twm_validation_bundle.md` / `.json` | 当前生产 observed-history、scale readiness、production readiness gate 状态 |
| scale profile 模板 | `docs/reports/twm_production_scale_profile_template.json` | 规模画像 JSON 契约 |
| 生产接入脚本 | `scripts/run_twm_production_onboarding.py` | 生产 onboarding 输入参数和输出目录 |
| validation runner | `scripts/run_twm_validation_bundle.py` | production readiness gate、scale readiness、observed history preflight |
| 数据基础校验脚本 | `scripts/validate_twm_data_foundation.py` | observed history schema audit 和模板输出 |
| handoff | `docs/twm-current-handoff.md` | 当前 roadmap、claim boundary、future_latent_state v2、TxPoint10M scale evidence |

## 关键事实

1. 当前 TWM 的生产 observed-history preflight 需要真实非合成记录、treated/control、outcome、空间支撑、协变量、policy history、temporal holdout。
2. 当前 production scale readiness 需要 production_scale_profile，并按百万/千万/亿级检查 lakehouse、partition、spatial index、distributed compute、sampling/tiling。
3. 当前 validation bundle 默认仍为 review，不是生产准确性证书。
4. TxPoint10M 证明 lakehouse 大数据路径，但不是自然资源业务 observed history。

## 不确定项

- 自然资源部具体源系统、字段名、权限边界、保密等级需要数据主管确认。
- 文档中的 action_type 枚举为 TWM 接入建议，不替代正式业务分类。
- 原始几何是否跨环境交付需由数据安全主管确认；建议默认不跨环境导出。
