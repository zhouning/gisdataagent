# ADR-362: Runtime Dependency Profiles for Scientific and Document Adapters

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-30

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

平台的 Lite 安装不应被 GWM/GeoTransport 的 HDF5 读取器或标准 PDF 抽取器拖重，但
`data_agent/` 的测试 collection 又必须在选择相应运行 profile 时得到可重复的导入环境。
此前 `h5py` 只存在于某个 GeoTransport 镜像的额外安装步骤，PDF 读取器只在
`requirements.txt` 中出现，导致 `pyproject.toml`、CI 和本地 profile 的边界不一致。

## 决策

- `scientific` profile 固定 `h5py==3.16.0`，供 GWM/GeoTransport 和其他 HDF5 科学数据适配器使用。
- `documents` profile 固定 `PyMuPDF==1.27.2.2`，供标准 PDF 抽取使用。
- `full` 同时包含两个依赖；锁定的 `requirements.txt` 也必须包含两者，作为 CI 和完整部署输入。
- Windows standalone 的 `production` offline profile 同样固定 `litellm>=1.84,<2.0`、
  `h5py==3.16.0` 和 `PyMuPDF==1.27.2.2`；`core` profile 保持不含两个可选读取器。
  staging wheelhouse 缺少这些直接依赖，或 wheel 元数据版本不满足 specifier 时，离线
  bundle 构建必须阻断。
- Lite 基础依赖不引入这两个包。需要对应适配器的开发者或部署 profile 必须显式选择
  `.[scientific]`、`.[documents]` 或 `.[full]`。
- CI 在测试 collection 前执行两者的 import smoke check，并由无第三方导入的 profile contract
  test 防止声明漂移。

## 取舍与边界

这样保留 Lite 的启动体积和安装速度，同时把“能导入测试模块”变成安装合同，而不是依赖某个
开发者机器上的隐式包。`ezdxf`、Playwright 和 `anuga` 仍属于各自子系统或隔离环境，不因本 ADR
进入核心 profile。依赖声明完成不代表 GWM、MMFE、标准抽取或 AR-0 产品发布已经完成。

## 证据

- [pyproject.toml](../../pyproject.toml)
- [requirements.txt](../../requirements.txt)
- [CI workflow](../../.github/workflows/ci.yml)
- [GeoTransport image](../../deploy/geotransport-troute-mc/Dockerfile)
- [profile contract test](../../data_agent/test_dependency_profiles.py)
- [Windows production requirements](../../deploy/windows-standalone/requirements-windows-production.txt)
- [Windows/core dependency contract test](../../tests/test_runtime_dependency_constraints.py)
- [Windows bundle builder](../../deploy/windows-standalone/build_offline_bundle.py)
- [Windows bundle version contract test](../../tests/test_windows_offline_bundle_contract.py)

验证：profile contract test `2 passed`，Windows/runtime dependency contract test `4 passed`，
bundle builder contract test `2 passed`；CI
安装合同包含 import smoke check。本轮已在开发环境安装两个锁定依赖，`data_agent` 全量
collection 成功收集 `13,953` 个测试。Windows vendor wheelhouse 尚未在本机生成，不能把依赖
声明或本机安装误写成现场 bundle 已构建，也不改变 AR-0 当前状态。
