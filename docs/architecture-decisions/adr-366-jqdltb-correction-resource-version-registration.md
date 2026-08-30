# ADR-366：JQDLTB 更正文件的 ResourceVersion 登记边界

**状态**：Accepted  交付日期：2026-08-30

## 决策

业务更正文件使用独立登记入口 `scripts/register_chongqing_jqdltb_correction_resource.py`。
入口先复用冻结源键集合和正数校验，再通过唯一的 PlatformGateway 登记
`gda://local-dev/dataset/chongqing-bizhu-jqdltb-business-correction` 及其内容寻址
`ResourceVersion`。版本身份由资源 URN 与 artifact SHA-256 的 UUID5 确定，登记结果记录
源版本、archive/bundle/diagnostic 指纹和校验记录数。

登记只证明“这份业务文件的字节可寻址”，不代表业务批准、Transformation Strategy、
ApprovalCase 或 DataProductVersion。空模板、缺行、额外键、非正数、源键漂移和未授权
owner 在调用 Gateway 之前失败，因此不会留下半个资源版本。

当前更正文件尚未补交，本轮没有调用登记命令，也没有在真实控制账本创建更正
ResourceVersion。
