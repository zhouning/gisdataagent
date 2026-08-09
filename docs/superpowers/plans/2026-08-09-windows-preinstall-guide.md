# Windows native-lite Pre-Extraction Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a Chinese plain-text native-lite deployment guide beside the ZIP so an operator can verify and prepare the deployment before extracting anything.

**Architecture:** Keep one version-controlled UTF-8 source template under `deploy/windows-standalone`. After a successful `native-lite` build, the Python bundle builder renders the manifest version, actual ZIP/sidecar/TXT names, and extracted directory into that template, writes ZIP and TXT staging files under the output directory, and publishes both only after each is complete. The generated TXT uses UTF-8 with BOM and its path is returned in the result. The ZIP payload remains unchanged except for the already-versioned root README update describing the three-file handoff.

**Tech Stack:** Python 3.11 `pathlib`, pytest, UTF-8 with BOM, Windows PowerShell 5.1, existing offline bundle builder and artifact verifier.

---

### Task 1: Lock the external guide contract with a failing test

**Files:**
- Modify: `data_agent/test_windows_offline_bundle.py`
- Test: `data_agent/test_windows_offline_bundle.py`

- [ ] **Step 1: Add a real minimal-build regression test**

Add a test that replaces the manifest with a valid artifact-free `native-lite`
manifest, invokes the real `build()` function, and verifies the external guide
name, result field, UTF-8 BOM, required instructions, and README handoff text:

```python
def test_native_lite_build_emits_external_preinstall_guide(tmp_path, monkeypatch):
    manifest = {
        "bundle_version": "test",
        "profiles": {"native-lite": {"required_artifacts": []}},
        "artifacts": [],
    }
    manifest_path = tmp_path / "bundle-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(_BUILDER, "MANIFEST_TEMPLATE", manifest_path)

    vendor_root = tmp_path / "vendor"
    vendor_root.mkdir()
    output = tmp_path / "GIS-Data-Agent-Windows-native-lite.zip"
    result = _BUILDER.build("native-lite", vendor_root, output)

    guide = tmp_path / "GIS-Data-Agent-Windows-native-lite-PRE-INSTALL.txt"
    assert Path(result["pre_install_guide"]) == guide.resolve()
    assert guide.read_bytes().startswith(b"\xef\xbb\xbf")
    text = guide.read_text(encoding="utf-8-sig")
    for required in (
        "解压前部署操作说明",
        "GIS-Data-Agent-Windows-native-lite.zip.sha256",
        "LM_STUDIO_BASE_URL",
        "768",
        "Get-FileHash",
        "Expand-Archive",
        "install_offline_bundle.ps1",
        "postgres-superpassword.txt",
        "natural_resource_standard_contracts.json",
    ):
        assert required in text

    readme = (DEPLOY_DIR / "README.md").read_text(encoding="utf-8")
    assert "PRE-INSTALL.txt" in readme
    assert "三个文件" in readme
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest `
  data_agent\test_windows_offline_bundle.py::test_native_lite_build_emits_external_preinstall_guide -q
```

Expected: FAIL because the builder does not generate `pre_install_guide` and
the external source document does not exist.

### Task 2: Implement the source guide and successful-build output

**Files:**
- Create: `deploy/windows-standalone/PRE_INSTALL_GUIDE.txt`
- Modify: `deploy/windows-standalone/build_offline_bundle.py`
- Modify: `deploy/windows-standalone/README.md`
- Test: `data_agent/test_windows_offline_bundle.py`

- [ ] **Step 1: Add the source guide**

Create `PRE_INSTALL_GUIDE.txt` in Chinese with this complete operational
structure. Keep these builder placeholders in the source template so future
bundle versions and custom output names render correctly:

```text
__BUNDLE_VERSION__  __ZIP_NAME__  __SHA256_NAME__  __GUIDE_NAME__  __BUNDLE_DIRECTORY__
```

The generated native-lite document replaces them with the manifest version,
the actual ZIP filename, the sidecar filename, the generated guide filename,
and the actual extracted directory name:

```text
GIS Data Agent Windows native-lite 解压前部署操作说明
版本：23.0.0-windows-standalone.2

一、移动硬盘必须包含三个文件
1. GIS-Data-Agent-Windows-native-lite.zip
2. GIS-Data-Agent-Windows-native-lite.zip.sha256
3. GIS-Data-Agent-Windows-native-lite-PRE-INSTALL.txt

二、解压前停止条件
- ZIP 或 sha256 文件缺失、哈希不一致：停止。
- 无本机管理员权限：停止。
- 部署机不能访问内网 LM Studio：停止。
- embedding 模型不是 768 维：停止。
- Windows 不是 x64，或低于项目已验证范围：停止并先做兼容性确认。

三、提前向 LM Studio 管理员取得
- LM_STUDIO_BASE_URL，例如 http://10.0.0.8:1234/v1，必须以 /v1 结束。
- Qwen 的精确 model ID。
- embedding 的精确 model ID，输出必须是 768 维。
- LM Studio 启用认证时所需的 API key；不要把真实 key 写入本文档或移动硬盘。

四、复制到部署机后先校验 ZIP，不要先解压
在移动硬盘文件所在目录打开 PowerShell：

$zip = Resolve-Path .\GIS-Data-Agent-Windows-native-lite.zip
$expected = ((Get-Content -Raw .\GIS-Data-Agent-Windows-native-lite.zip.sha256) -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "ZIP SHA-256 校验失败，停止解压。expected=$expected actual=$actual" }
Write-Host "ZIP SHA-256 校验通过：$actual"

五、准备目录和 LM Studio 参数
$env:LM_STUDIO_BASE_URL = 'http://LM-STUDIO-SERVER:1234/v1'
$env:LM_STUDIO_MODEL = '<QWEN_MODEL_ID>'
$env:LM_STUDIO_EMBEDDING_MODEL = '<EMBEDDING_MODEL_ID>'
# 仅当 LM Studio 启用认证时，在当前 PowerShell 会话中设置：
# $env:LM_STUDIO_API_KEY = '<API_KEY>'
Test-NetConnection LM-STUDIO-SERVER -Port 1234

六、校验通过后解压
Expand-Archive .\GIS-Data-Agent-Windows-native-lite.zip -DestinationPath D:\GDA_STAGING
Set-Location D:\GDA_STAGING\GIS-Data-Agent-23.0.0-windows-standalone.2-native-lite
Get-Content .\README.md -TotalCount 80

七、以管理员 PowerShell 安装
.\install_offline_bundle.ps1 `
  -Profile native-lite `
  -InstallRoot D:\GDA `
  -DataRoot D:\GDA_DATA `
  -Inbox D:\NX_INCOMING `
  -LogRoot D:\GDA_LOGS `
  -LmStudioBaseUrl $env:LM_STUDIO_BASE_URL `
  -LmStudioChatModel $env:LM_STUDIO_MODEL `
  -LmStudioEmbeddingModel $env:LM_STUDIO_EMBEDDING_MODEL `
  -LmStudioApiKey $env:LM_STUDIO_API_KEY

.\register_tasks.ps1 -InstallRoot D:\GDA -RunAs SYSTEM
.\start_gda.ps1 -InstallRoot D:\GDA

八、安装后的入口和凭据
- Web：http://127.0.0.1:8000
- PostgreSQL 超级用户密码：D:\GDA\runtime\postgres-superpassword.txt
- 应用数据库和 MinIO 配置：D:\GDA\config\gda.env
- 安装验收：D:\GDA_DATA\file_lake\diagnostics\bundle-verify.json
- 预检报告：D:\GDA_DATA\file_lake\diagnostics\windows-ingest-preflight.json

九、不需要另外准备
- 不需要 natural_resource_standard_contracts.json；安装器从包内基线生成运行时文件。
- 不需要 Ollama、Gemma4 或文本 embedding 权重；Qwen 和 embedding 由内网 LM Studio 提供。
- 不需要 Docker Desktop。
```

- [ ] **Step 2: Add the builder output helper**

Add the source constant, a focused renderer, and a paired publisher:

```python
PRE_INSTALL_GUIDE = SCRIPT_DIR / "PRE_INSTALL_GUIDE.txt"


def _write_pre_install_guide(
    destination: Path, output: Path, bundle_version: str, bundle_directory: str
) -> Path:
    guide_path = output.with_name(f"{output.stem}-PRE-INSTALL.txt")
    text = PRE_INSTALL_GUIDE.read_text(encoding="utf-8-sig")
    for placeholder, value in {
        "__BUNDLE_VERSION__": bundle_version,
        "__BUNDLE_DIRECTORY__": bundle_directory,
        "__ZIP_NAME__": output.name,
        "__SHA256_NAME__": f"{output.name}.sha256",
        "__GUIDE_NAME__": guide_path.name,
    }.items():
        text = text.replace(placeholder, value)
    if re.search(r"__[A-Z0-9_]+__", text):
        raise ValueError("unresolved pre-install guide placeholders")
    destination.write_text(text, encoding="utf-8-sig")
    return destination


def _publish_native_lite_bundle(staged_zip, staged_guide, output, backup_dir):
    # Stage both files under output.parent so Windows ACL inheritance remains
    # valid after replace; restore backups if either final move fails.
    guide_path = output.with_name(f"{output.stem}-PRE-INSTALL.txt")
    backup_dir.mkdir()
    backups = {}
    published = []
    try:
        for final_path in (output, guide_path):
            if final_path.exists():
                backup_path = backup_dir / final_path.name
                final_path.replace(backup_path)
                backups[final_path] = backup_path
        staged_zip.replace(output)
        published.append(output)
        staged_guide.replace(guide_path)
        published.append(guide_path)
    except Exception:
        for final_path in reversed(published):
            if final_path.exists():
                final_path.unlink()
        for final_path, backup_path in backups.items():
            if backup_path.exists():
                backup_path.replace(final_path)
        raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)
    return guide_path
```

Before artifact collection, fail if `PRE_INSTALL_GUIDE` is missing for
`native-lite`. Stage the ZIP and rendered guide first, then publish the pair
only for a successful `profile == "native-lite"` build and add its absolute
path to the result:

```python
if not PRE_INSTALL_GUIDE.is_file():
    raise FileNotFoundError(f"missing pre-install guide: {PRE_INSTALL_GUIDE}")

staged_zip = _reserve_staged_file(output, ".zip")
_zip_directory(stage, staged_zip)
if profile == "native-lite":
    staged_guide = _reserve_staged_file(output, ".txt")
    _write_pre_install_guide(staged_guide, output, template["bundle_version"], stage.name)
    guide_path = _publish_native_lite_bundle(
        staged_zip, staged_guide, output, temporary / "publish-backup"
    )
else:
    staged_zip.replace(output)
    guide_path = None
result = {
    "status": "ready",
    "profile": profile,
    "bundle": str(zip_path.resolve()),
    "manifest_member": f"{stage.name}/manifest.json",
    "artifacts": len(records),
    "optional_missing": missing_optional,
}
if guide_path is not None:
    result["pre_install_guide"] = str(guide_path.resolve())
return result
```

- [ ] **Step 3: Update the main README handoff contract**

Replace the two-file instruction with this exact meaning:

```markdown
移动硬盘必须复制三个文件：最终 ZIP、同名 `.sha256` 和构建器生成的
`GIS-Data-Agent-Windows-native-lite-PRE-INSTALL.txt`。现场人员先阅读外置 TXT，完成哈希和
LM Studio 前置检查后再解压；ZIP 内的 `README.md` 继续作为解压后的详细安装与运维文档。
```

- [ ] **Step 4: Run the new test and verify GREEN**

Run the single test from Task 1. Expected: `1 passed`.

- [ ] **Step 5: Run the complete focused regression file**

Run:

```powershell
D:\adk\.venv\Scripts\python.exe -m pytest data_agent\test_windows_offline_bundle.py -q
```

Expected: all tests pass.

### Task 3: Build and validate the three-file handoff

**Files:**
- Generated: `deploy/windows-standalone/out/GIS-Data-Agent-Windows-native-lite.zip`
- Generated: `deploy/windows-standalone/out/GIS-Data-Agent-Windows-native-lite.zip.sha256`
- Generated: `deploy/windows-standalone/out/GIS-Data-Agent-Windows-native-lite-PRE-INSTALL.txt`

- [ ] **Step 1: Parse code and deployment scripts**

Run Python AST parsing for the builder/tests, parse all six `.ps1` files with
Windows PowerShell 5.1, parse both JSON templates, and run `git diff --check`.
Expected: zero errors.

- [ ] **Step 2: Rebuild the full native-lite ZIP**

```powershell
D:\adk\.venv\Scripts\python.exe deploy\windows-standalone\build_offline_bundle.py `
  --profile native-lite `
  --vendor-root deploy\windows-standalone\vendor `
  --output deploy\windows-standalone\out\GIS-Data-Agent-Windows-native-lite.zip `
  --force
```

Expected: JSON status `ready`, `artifacts` equals 21, and
`pre_install_guide` names the external TXT. Prometheus/Grafana may remain in
`optional_missing`.

- [ ] **Step 3: Regenerate and verify the external ZIP checksum**

```powershell
$zip = Resolve-Path .\deploy\windows-standalone\out\GIS-Data-Agent-Windows-native-lite.zip
$sha256 = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$sha256  $([IO.Path]::GetFileName($zip))" | Set-Content -LiteralPath "$zip.sha256" -Encoding ASCII
```

Recompute once more and assert the sidecar matches. Expected: `Match=True`.

- [ ] **Step 4: Validate the external TXT**

Verify that the generated file exists, begins with bytes `EF BB BF`, opens as
UTF-8 Chinese text, names all three handoff files, contains the fail-closed
hash command, and contains no real API key or password.

- [ ] **Step 5: Extract and rerun artifact verification**

Extract to a new explicit directory under `D:\tmp`, then run:

```powershell
D:\adk\.venv\Scripts\python.exe scripts\verify_windows_offline_bundle.py `
  --bundle-root <EXTRACTED_BUNDLE_ROOT> `
  --profile native-lite `
  --phase artifact `
  --output <EXTRACTED_VERIFICATION_JSON>
```

Expected: `critical_failures=0`; internal `SHA256SUMS` has zero failures. The
only allowed warning is missing optional Prometheus/Grafana media.

### Task 4: Commit and publish

**Files:**
- Modify: `data_agent/test_windows_offline_bundle.py`
- Create: `deploy/windows-standalone/PRE_INSTALL_GUIDE.txt`
- Modify: `deploy/windows-standalone/build_offline_bundle.py`
- Modify: `deploy/windows-standalone/README.md`
- Add: `docs/superpowers/plans/2026-08-09-windows-preinstall-guide.md`

- [ ] **Step 1: Review the final diff and status**

Confirm no cache, ZIP, `.sha256`, extracted directory, or generated `out` TXT
is staged. Run `git diff --cached --check`.

- [ ] **Step 2: Commit the implementation**

```powershell
git add data_agent/test_windows_offline_bundle.py `
  deploy/windows-standalone/PRE_INSTALL_GUIDE.txt `
  deploy/windows-standalone/build_offline_bundle.py `
  deploy/windows-standalone/README.md `
  docs/superpowers/plans/2026-08-09-windows-preinstall-guide.md
git commit -m "Add pre-extraction Windows deployment guide"
```

- [ ] **Step 3: Push the existing feature branch**

```powershell
git push origin feat/windows-standalone-offline-bundle
```

Expected: remote branch points to the new implementation commit. Report the
three exact mobile-disk paths, ZIP byte size, SHA-256, test counts, artifact
verification result, and the optional monitoring warning.
