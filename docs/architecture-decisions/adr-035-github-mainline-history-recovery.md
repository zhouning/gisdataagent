# ADR-035：GitHub Mainline 历史恢复与受保护主线切换

**Status**: Proposed

**Date**: 2026-07-26

**Decision owners**: Repository Owner, Platform Architecture, SRE, Security

**Related decisions**: ADR-028、ADR-032、ADR-033、ADR-034

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

首次发布前只读审计确认 GitHub 默认分支是 `main@f339e13`，但当前 AR-1 分支 `feat/ar1-dolphinscheduler-adapter@499dd2e` 与它没有共同祖先：远端旧历史从 `217e70c` 起根，当前活跃历史从 `ed97623` 起根。当前分支与远端 `feat/v12-extensible-platform@ebd99f8` 有共同祖先，并在其上领先 25 个提交。

这不是普通的 ahead/behind。把当前树直接与旧 `main` 比较会产生约 4,859 个文件、5,130,385 行新增和 197,618 行删除；普通 PR 无法表达可信的增量评审。审计同时确认：

- `main` 没有 classic branch protection；
- 仓库没有 repository ruleset；
- 仓库没有任何 GitHub environment，`staging-provenance` 也不存在；
- Actions 已启用，远端只有旧 `main` 上的三个 active workflow；
- 当前 25 个 AR-0/AR-1 提交尚未 push。

在主线 lineage 未恢复前，`push -> main`、protected verifier、GHCR provenance 和 staging promotion 都不具备可信触发基础。

## Decision Drivers

- 不得 force push 或删除任一现有历史；
- 旧 `main` 必须保留可定位的 branch/tag，供审计和回退；
- 当前活跃历史中的提交、作者、顺序和现有远端 feature lineage 应保留；
- 不得用一个只保留当前 tree 的 synthetic merge 冒充已经评审过 500 万行差异；
- 新 canonical `main` 在首次 publisher run 前必须具备 ruleset、environment 和 reviewers；
- 分支切换、远端配置和首次 workflow run 必须分阶段批准、每步可复核。

## Considered Options

| 方案 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| force push 当前 HEAD 到 `main` | 最快 | 覆盖默认分支、破坏可恢复性与审计边界 | 拒绝 |
| `--allow-unrelated-histories` 合并并保留当前 tree | 两条历史在图上相连 | PR 表现为 4,859 文件/500 万行替换，merge resolution 不可可信评审 | 拒绝 |
| 重写 645 个活跃提交，把新 root graft 到旧 `main` | 得到单一线性祖先 | 所有 commit SHA 变化，现有 branches/artifacts/文档引用失效 | 拒绝 |
| 归档旧 `main`，保护两条分支后把活跃 `feat/v12` lineage 改名为 canonical `main` | 不重写、不丢历史；当前 25 提交可在真实共同祖先上评审 | 主线存在一次显式 lineage discontinuity，需要仓库管理员分阶段切换 | 推荐，待批准 |

## Proposed Decision

采用“归档旧主线 + 提升活跃 lineage”，禁止 force push、synthetic unrelated merge 和全历史重写。

1. 先建立同时覆盖现有 `main`、`feat/v12-extensible-platform` 和未来 `main` 的 repository ruleset：禁止 force push/delete，要求 PR，限制 bypass；required checks 在确认新主线 CI check name 后收紧。
2. 创建 `staging-provenance` environment，配置 required reviewers、禁止未经审核 bypass，并仅设置 environment-level `GDA_STAGING_PROVENANCE_PROTECTED=true`。在主线切换完成前不运行 publisher。
3. 在远端创建不可变审计锚点：`archive/main-2026-04-10` 和 annotated tag 指向 `f339e13`；另为切换前的 active lineage 创建 archive ref。不得删除旧对象。
4. 将当前 25 个提交 push 到独立 review branch，并以 `feat/v12-extensible-platform` 为 base 评审；因为两者共享 `ebd99f8`，该 PR 是真实增量，不涉及 unrelated history。
5. 合入并验证后，把旧 `main` 改名为 `legacy/main-2026-04-10`，再把已验证的 `feat/v12-extensible-platform` 改名为 `main`，确认 GitHub default branch、ruleset target、workflow source ref 和本地 remote-tracking ref 全部指向新 canonical branch。
6. 先运行只读 CI/合同验证，再按 ADR-032 至 ADR-034 的顺序进行首次 candidate publish、protected provenance verify 和 release materialization。未取得真实 artifact 前不得部署 staging。
7. 将 lineage discontinuity、旧/新 root、切换人、时间、GitHub audit log 和最终 SHA 追加到本 ADR；完成复核后才能把状态改为 Accepted。

## Consequences

正面影响：

- 两套 Git 对象都保留，旧主线可查、可恢复；
- AR-0/AR-1 的 25 个提交能在共同祖先上正常评审；
- workflow 中固定的 `refs/heads/main` 最终对应真实活跃代码；
- ruleset 和 environment 先于首次发布建立，不再依赖当前无保护状态。

限制与代价：

- GitHub 主线会留下明确的历史断点，`main` 改名前后的 commit 无祖先关系；
- 外部链接、clone、open PR、默认分支缓存和本地 automation 需要逐项复核；
- 分支改名属于仓库级外部变更，必须由 owner 明确批准，不能由“继续开发”隐含授权；
- 旧 `main` 的后续修复若仍有价值，需要通过内容级评估单独 port，不能假设已包含在新主线。

## Verification Plan

- 切换前记录 `default_branch`、两个 root SHA、old/new head SHA、ruleset、environment 和 workflow 清单；
- 证明 review branch 与 `feat/v12-extensible-platform` 的 merge base 是 `ebd99f8`，且只包含预期 25 个提交；
- 证明 archive branch/tag 精确指向 `f339e13`，且禁止删除/force update；
- 切换后确认 `main` 是活跃 lineage 的 descendant，旧历史仍可通过 archive ref 获取；
- 确认 `main` ruleset、`staging-provenance` reviewers/variable、Actions permissions 和 workflow source 均符合 ADR-033/034；
- 首次远端运行只允许产生 candidate/registry/provenance/release evidence，不直接触发 production。

## Approval Gate

本 ADR 保持 Proposed，直到 repository owner 明确批准以下外部动作：创建 ruleset/environment/archive refs、push review branch、合并到 active lineage、重命名两条远端分支和切换 default branch。批准前继续保持本地提交，不 push。
