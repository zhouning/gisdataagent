# 重庆数字资产与智慧片区证据就绪度验证报告（需求17）

- 日期：2026-07-12
- Schema：`uwm.digital_asset_smart_district_readiness.v1`
- Bundle：`digital-readiness-50be418b90412fe4ade9`
- Digest：`sha256:094b5c807f8bb30d25043a832cba6bb85e6def69877f35961ef2ad4f501131bf`

## 真实结果

- 有证据的平台数字能力：17项。
- 智慧设施证据通道：12类。
- 当前具备权威资产数据的设施通道：0。
- 数字基础设施UWM开放机制：0。
- 伪造值：0。

平台能力仅登记实施台账中具有实际证据产物的传统GIS、UWM和证据编排产品。单纯存在API路由或代码合同不会被计为已验证能力。

智慧设施通道覆盖IoT、摄像头、智慧照明、公共Wi-Fi、移动基站、边缘/数据中心、智慧停车、环境终端、城市运行中心、故障维护、服务可用性和服务使用时间序列。所有通道当前均为 `unavailable`，值为 `null`。

## 边界

产品不输出智慧城市分、数字成熟度分、IoT/摄像头/Wi-Fi/5G覆盖率、设备在线率、数字服务使用率、智慧片区排名、数字投资回报或政策效果。

平台产品能力不等于区县智慧基础设施覆盖。资产存在不等于在线、可用或被实际使用。数字基础设施状态转移、故障传播、维护响应、服务恢复和维护反事实机制全部关闭。

## 验证

- 聚焦后端测试：14 passed。
- 能力证据、空值通道和关闭UWM机制独立校验：通过。
- 前端TypeScript/Vite生产构建：通过。
- 最大声明：`platform_digital_capability_and_district_smart_infrastructure_evidence_readiness`。
