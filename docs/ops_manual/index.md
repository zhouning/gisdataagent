# Data Agent 运维手册

## 1. 系统要求
*   **OS**: Windows 10/11, Linux (Ubuntu 20.04+), macOS.
*   **Runtime**: Python 3.10 - 3.12.
*   **Dependencies**: GDAL (地理空间库核心依赖), Java 11+ (ADK 依赖).

## 2. 部署步骤

### 2.1 获取代码
```bash
git clone <repository_url>
cd data_agent
```

### 2.2 创建虚拟环境
```powershell
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate # Linux/Mac
```

### 2.3 安装依赖
```bash
pip install -r requirements.txt
# 注意：GDAL/Fiona 在 Windows 下可能需要下载 whl 文件手动安装
```

### 2.4 模型文件检查
确保 `data_agent/` 目录下存在以下核心模型文件：
*   `scorer_weights_v7.pt`: **[必需]** v7 模型的权重文件，用于推理。
*   `parcel_scoring_policy.py`: **[必需]** 定义模型网络结构的 Python 模块。
*   `land_use_model_v7.zip`: (可选) 完整训练模型备份。

### 2.5 环境变量配置
在项目根目录创建 `.env` 文件，填入以下关键配置：
```ini
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=path/to/key.json
DATASTORE_ID=your-vertex-search-datastore-id
```

---

## 3. 服务管理

### 3.1 启动服务
使用 Chainlit 启动 Web 服务：
```bash
chainlit run data_agent/app.py -w --port 8000
```
*   `-w`: 开发模式（文件变动自动重启）。生产环境建议去掉。
*   `--headless`: 无头模式（不自动打开浏览器）。

### 3.2 生产环境建议
*   建议使用 `Process Manager` (如 Supervisor 或 PM2) 守护进程。
*   如果部署在 Docker 中，请确保基础镜像包含 GDAL 库 (推荐 `osgeo/gdal` 镜像)。

---

## 4. 故障排查

| 错误现象 | 可能原因 | 解决方案 |
| :--- | :--- | :--- |
| **启动报错 `ImportError: DLL load failed`** | GDAL/Fiona 库版本不兼容 | 重新安装对应 Python 版本的 `.whl` 包。 |
| **Agent 无响应 / 思考超时** | API Key 缺失或网络不通 | 检查 `.env` 配置；检查服务器是否能访问 Google Vertex AI。 |
| **图表中文乱码** | 系统缺失中文字体 | 安装 `SimHei` 或 `Microsoft YaHei` 字体到服务器，或修改 `_configure_fonts` 逻辑。 |
| **报告导出失败** | 临时目录权限问题 | 检查 `data_agent/` 目录的写入权限。 |
