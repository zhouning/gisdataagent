# BIRD 智能问数提交交接

## 分支与范围

提交分支为 `feat/bird-nl2sql-strict-ir`，基于当前产品分支 `feat/agent-lifecycle-management` 的 `0d84a5dc` 建立。当前产品分支与 `origin/main` 已分叉，因此本次沿用已经验证的产品基线，在独立工作树整理 BIRD 改动，未合并或更新 main。

此前 BIRD 问数的部分运行依赖尚未提交，本次同时纳入数据源适配器、语义检索与指标模块、模型调用预算、迁移 257–259 和相关回归。共享 `app.py`、`frontend_api.py` 仅纳入 BIRD 的接入行；原工作区其他任务保持原状。

## 产品行为

- 默认 `GDA_NL2SQL_QUERY_PROFILE=configured` 保留原配置行为。
- 候选配置 `registered_ir_strict` 强制授权登记目录、结构契约和显式操作；不支持的计划返回 unsupported，禁止自由 SQL 回退。
- 登记基础聚合参与编译；增加关联放大和显式 Top-N 检查。
- 产品响应及评测保存实际路线、编译计划、执行 SQL、独立参数和模型调用证据。路线或执行证据不一致时停止继续评测。
- 在线评测和验收要求显式 `--query-profile`；冻结配置必须匹配。`--preflight-only` 不加载凭据、不调用模型。
- BIRD 数据源授权测试增加独立身份上下文，避免同进程测试之间的身份状态影响断言。

严格路线尚有复杂公式、人群合同和概念绑定缺口，未切换现场配置。本次没有运行迁移、重启服务或调用在线模型。

## 成绩与证据

最近完整真实测试仍为 **90/150，60%**。150 题已用于开发，不能作为独立验收集。本次保留历史 records、manifest、completion 和 report 原文，并核对记录及清单的 SHA-256。离线诊断的全部输入与绑定器哈希亦已核对。

- [改进说明](../../benchmarks/BIRD智能问数_离线改进说明_20261016.md)
- [60 道错题清单](../../benchmarks/bird_full150_v9_离线改进清单_20261016.md)

## 提交前验证

BIRD 相关 14 个模块的 **358 项测试通过**，有两条依赖弃用警告。验证在独立工作树运行，未复制环境凭据，也未连接真实模型或数据源。执行命令：

```sh
python -m pytest -q \
  data_agent/test_nl2sql_registered_ir.py \
  data_agent/test_nl2sql_route_policy.py \
  data_agent/test_bird_acceptance_gate.py \
  data_agent/test_bird_runtime_freeze.py \
  data_agent/test_bird_chat.py \
  data_agent/test_bird_product_manifest.py \
  data_agent/test_nl2sql_observability.py \
  data_agent/test_nl2sql_executor.py \
  data_agent/test_nl2sql_candidates.py \
  data_agent/test_nl2sql_metric_integration.py \
  data_agent/test_bird_product_route_evidence.py \
  data_agent/test_llm_call_budget.py \
  data_agent/test_bird_source.py \
  data_agent/test_bird_semantic_contracts.py
```

共享 IR 的历史模块 `test_semantic_query_ir.py` 还依赖本机 `docs/customer/abu_dhabi_liveability_site_validation` 下被 Git 忽略的客户语义及本体夹具。复用本机的 20 个夹具文件后，该模块 **118 项测试通过**。这些夹具没有纳入本次公开提交，全新检出无法独立运行整个历史模块；该结果与上述可复现的 BIRD 回归分开报告。

提交范围的代码编译检查、`git diff --cached --check`、诊断输入哈希及历史记录校验通过。CSV 保留原始 CRLF 字节，文件属性仅声明其合法行尾，不更改历史产物。

本次未验证 PostgreSQL 集成、在线端到端准确率或现场延迟。
