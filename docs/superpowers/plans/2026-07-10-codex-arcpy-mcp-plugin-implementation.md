# Codex ArcPy MCP Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build and privately publish a Codex marketplace repository that installs the remote ArcPy MCP connection on macOS and provides a secure, repeatable upload-job-download workflow.

**Architecture:** The repository contains one Codex marketplace entry and one arcpy-mcp plugin. The plugin uses a fixed HTTPS IP endpoint, reads the Bearer Token from ARCPY_MCP_TOKEN, distributes only the public local-CA certificate, and includes a Skill plus macOS scripts for Keychain-backed authentication and end-to-end verification.

**Tech Stack:** Codex CLI 0.144.1 or newer, Codex plugin manifest and marketplace JSON, MCP HTTP configuration, Markdown Skill instructions, Bash, macOS security and launchctl commands, curl, shasum, pytest, OpenAI plugin-creator validation scripts.

---

This is plan 2 of 2. Start it only after the Windows server plan has produced a healthy HTTPS endpoint and the CA public certificate.

## File Map

Repository root during execution: D:\adk\standalone\codex-arcpy-mcp-plugin

- .agents/plugins/marketplace.json: private marketplace metadata and local plugin source.
- plugins/arcpy-mcp/.codex-plugin/plugin.json: plugin identity and interface metadata.
- plugins/arcpy-mcp/.mcp.json: fixed ArcPy Streamable HTTP MCP endpoint and Bearer Token environment variable.
- plugins/arcpy-mcp/skills/arcpy-mcp/SKILL.md: Codex operating policy and artifact/job workflow.
- plugins/arcpy-mcp/scripts/configure-macos.sh: marketplace installation, CA trust, Keychain token, LaunchAgent, and plugin installation.
- plugins/arcpy-mcp/scripts/verify-connection.sh: TLS, environment, marketplace, plugin, and MCP health diagnostics.
- plugins/arcpy-mcp/assets/arcpy-mcp-ca.crt: public local-CA certificate copied from the server deployment.
- tests/test_manifests.py: exact marketplace, plugin, MCP, and Skill contract tests.
- tests/test_scripts.py: Bash syntax, secret-redaction, and fixed-endpoint tests.
- pyproject.toml: test-only Python project.
- README.md: private GitHub and macOS installation, update, rotation, and removal instructions.

### Task 1: Scaffold the Independent Marketplace Repository

**Files:**
- Create: D:\adk\standalone\codex-arcpy-mcp-plugin\pyproject.toml
- Create: D:\adk\standalone\codex-arcpy-mcp-plugin\.gitignore
- Create: D:\adk\standalone\codex-arcpy-mcp-plugin\tests\test_repository.py
- Create through scaffold: .agents/plugins/marketplace.json
- Create through scaffold: plugins/arcpy-mcp/.codex-plugin/plugin.json
- Create through scaffold: plugins/arcpy-mcp/.mcp.json

- [ ] **Step 1: Initialize the repository**

Run:

~~~powershell
New-Item -ItemType Directory -Force D:\adk\standalone\codex-arcpy-mcp-plugin
Set-Location D:\adk\standalone\codex-arcpy-mcp-plugin
git init -b main
~~~

Expected: an empty Git repository on main.

- [ ] **Step 2: Run the official plugin scaffold**

Run:

~~~powershell
python C:\Users\zn198\.codex\skills\.system\plugin-creator\scripts\create_basic_plugin.py arcpy-mcp --path D:\adk\standalone\codex-arcpy-mcp-plugin\plugins --marketplace-path D:\adk\standalone\codex-arcpy-mcp-plugin\.agents\plugins\marketplace.json --marketplace-name zhouning-arcpy --with-skills --with-scripts --with-assets --with-mcp --with-marketplace
~~~

Expected: marketplace and plugin directories are created with no manifest placeholders.

- [ ] **Step 3: Write the failing repository contract test**

~~~python
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_marketplace_points_to_arcpy_plugin():
    marketplace = json.loads(
        (ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
    )

    assert marketplace["name"] == "zhouning-arcpy"
    assert marketplace["plugins"][0]["name"] == "arcpy-mcp"
    assert marketplace["plugins"][0]["source"]["path"] == "./plugins/arcpy-mcp"
~~~

- [ ] **Step 4: Create the test project**

Create pyproject.toml:

~~~toml
[project]
name = "codex-arcpy-mcp-plugin-tests"
version = "0.1.0"
requires-python = ">=3.11"

[dependency-groups]
dev = ["pytest>=8.4,<9"]

[tool.pytest.ini_options]
testpaths = ["tests"]
~~~

Create .gitignore:

~~~gitignore
.venv/
__pycache__/
.pytest_cache/
*.pyc
~~~

- [ ] **Step 5: Install and run the repository test**

Run:

~~~powershell
uv sync --dev
uv run pytest tests/test_repository.py -v
~~~

Expected: PASS.

- [ ] **Step 6: Commit and create the private GitHub repository**

Run:

~~~powershell
git add .
git commit -m "chore: scaffold ArcPy Codex marketplace"
gh repo create zhouning/codex-arcpy-mcp-plugin --private --source . --remote origin --push
~~~

Expected: private repository zhouning/codex-arcpy-mcp-plugin exists and main is pushed.

### Task 2: Define the Plugin and Remote MCP Contract

**Files:**
- Modify: plugins/arcpy-mcp/.codex-plugin/plugin.json
- Modify: plugins/arcpy-mcp/.mcp.json
- Create: tests/test_manifests.py

- [ ] **Step 1: Write failing manifest tests**

~~~python
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "plugins/arcpy-mcp"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_manifest_has_remote_mcp_and_skill():
    manifest = load(PLUGIN / ".codex-plugin/plugin.json")

    assert manifest["name"] == "arcpy-mcp"
    assert manifest["version"] == "0.1.0"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert manifest["skills"] == "./skills/"
    assert manifest["interface"]["displayName"] == "ArcPy MCP"


def test_mcp_uses_fixed_ip_and_environment_token():
    config = load(PLUGIN / ".mcp.json")
    server = config["mcpServers"]["arcpy"]

    assert server == {
        "type": "http",
        "url": "https://192.168.25.228:8765/mcp",
        "bearer_token_env_var": "ARCPY_MCP_TOKEN",
    }
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_manifests.py -v

Expected: FAIL because scaffold defaults do not match the approved contract.

- [ ] **Step 3: Replace plugin.json with the exact manifest**

~~~json
{
  "name": "arcpy-mcp",
  "version": "0.1.0",
  "description": "Use a private Windows ArcGIS Pro installation from Codex on macOS.",
  "author": {
    "name": "zhouning"
  },
  "repository": "https://github.com/zhouning/codex-arcpy-mcp-plugin",
  "license": "Proprietary",
  "keywords": [
    "arcpy",
    "arcgis-pro",
    "gis",
    "mcp"
  ],
  "skills": "./skills/",
  "mcpServers": "./.mcp.json",
  "interface": {
    "displayName": "ArcPy MCP",
    "shortDescription": "Run private ArcPy workflows from Codex.",
    "longDescription": "Securely upload GIS data, run allowlisted ArcPy jobs on a Windows ArcGIS Pro host, and download verified results.",
    "developerName": "zhouning",
    "category": "Productivity",
    "capabilities": [
      "Remote GIS processing",
      "Artifact transfer",
      "Asynchronous ArcPy jobs"
    ],
    "defaultPrompt": [
      "Inspect this GIS dataset with ArcPy.",
      "Run an ArcPy buffer and download the result.",
      "Check the Windows ArcPy service status."
    ]
  }
}
~~~

- [ ] **Step 4: Replace .mcp.json with the exact remote definition**

~~~json
{
  "mcpServers": {
    "arcpy": {
      "type": "http",
      "url": "https://192.168.25.228:8765/mcp",
      "bearer_token_env_var": "ARCPY_MCP_TOKEN"
    }
  }
}
~~~

- [ ] **Step 5: Validate manifests**

Run:

~~~powershell
uv run pytest tests/test_manifests.py -v
python C:\Users\zn198\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins\arcpy-mcp
~~~

Expected: tests PASS and validator prints a successful result.

- [ ] **Step 6: Commit**

Run:

~~~powershell
git add plugins/arcpy-mcp/.codex-plugin/plugin.json plugins/arcpy-mcp/.mcp.json tests/test_manifests.py
git commit -m "feat: configure remote ArcPy MCP plugin"
~~~

### Task 3: Write the ArcPy Codex Skill

**Files:**
- Create: plugins/arcpy-mcp/skills/arcpy-mcp/SKILL.md
- Modify: tests/test_manifests.py

- [ ] **Step 1: Add failing Skill policy tests**

~~~python
def test_skill_contains_required_safety_and_workflow_rules():
    skill = (PLUGIN / "skills/arcpy-mcp/SKILL.md").read_text(encoding="utf-8")

    required = [
        "health_check",
        "create_upload",
        "get_upload_status",
        "complete_upload",
        "inspect_dataset",
        "search_tools",
        "describe_tool",
        "submit_job",
        "get_job",
        "create_download",
        "ARCPY_MCP_TOKEN",
        "Never send a Windows absolute path",
        "Never request arbitrary Python execution",
        "CPU deep-learning",
    ]
    for phrase in required:
        assert phrase in skill
~~~

- [ ] **Step 2: Run the test and verify failure**

Run: uv run pytest tests/test_manifests.py::test_skill_contains_required_safety_and_workflow_rules -v

Expected: FAIL because SKILL.md does not exist.

- [ ] **Step 3: Create the complete Skill**

~~~markdown
---
name: arcpy-mcp
description: Use the private Windows ArcPy MCP server for GIS inspection, vector and raster processing, map export, and CPU deep-learning inference from macOS Codex.
---

# ArcPy MCP Workflow

Use this skill whenever a task requires ArcPy, ArcGIS Pro geoprocessing, ArcGIS map export, or an allowlisted ArcGIS deep-learning inference tool.

## Required Safety Rules

- Never send a Windows absolute path, drive path, UNC path, parent traversal, or symlink target.
- Never request arbitrary Python execution, arbitrary ArcPy callables, shell commands, or a tool ID not returned by search_tools.
- Never print, store, commit, or summarize ARCPY_MCP_TOKEN.
- Never print or persist signed upload or download URLs beyond the active transfer command.
- Keep all server inputs and outputs represented by artifact IDs and artifact-relative paths.
- Treat CPU deep-learning inference as a long-running job and warn the user before submission.

## Connection Check

1. Call health_check before the first ArcPy operation in a thread.
2. Stop if the service is unavailable, ArcGIS product is not ArcInfo, or a required extension is unavailable.
3. Use get_capabilities when deciding whether a raster or deep-learning operation is executable.

## Upload

1. Package a multi-file GIS dataset as ZIP. Keep a single raster, model, PDF, or GeoPackage as one file.
2. Compute SHA-256 and byte size locally with shasum -a 256 and stat -f%z.
3. Call create_upload with logical name, size, SHA-256, and media type.
4. Stream the file to the returned HTTPS URL with curl. Do not place the URL in a script or project file.
5. On interruption, call get_upload_status, resume from committed_size, and call renew_upload if the URL expired.
6. Call complete_upload and require state ready before using the artifact.

## Tool Selection

1. Run inspect_dataset for every new dataset before processing.
2. Call search_tools using the user's intended operation.
3. Call describe_tool for the selected tool ID and construct only schema-approved parameters.
4. Prefer a dedicated MCP tool when it exactly matches the requested operation.

## Job Execution

1. Call submit_job or the dedicated tool and record the returned job ID in thread context only.
2. Poll get_job with increasing intervals of 2, 5, 10, then 20 seconds, never exceeding 20 seconds.
3. If the user asks to stop, call cancel_job once and poll until cancelled or failed.
4. On failure, call get_job_log and report the stable error code plus the final ArcPy error messages.

## Download

1. Call create_download for each result artifact.
2. Download with curl --fail --location --continue-at -.
3. Verify the returned SHA-256 before extracting or opening the result.
4. Keep ZIP extraction inside the current macOS workspace.

## Deep Learning

- Current execution mode is CPU because the Windows host exposes no usable NVIDIA device.
- Do not submit TrainDeepLearningModel.
- A compatible ArcGIS Pro 3.7.1 DLPK or EMD model artifact is required for inference.
- Use the longer timeout reported by describe_tool and avoid cancelling during final output writing unless requested.
~~~

- [ ] **Step 4: Validate the Skill**

Run:

~~~powershell
uv run pytest tests/test_manifests.py -v
python C:\Users\zn198\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins\arcpy-mcp
~~~

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

~~~powershell
git add plugins/arcpy-mcp/skills/arcpy-mcp/SKILL.md tests/test_manifests.py
git commit -m "feat: add secure ArcPy Codex workflow"
~~~

### Task 4: Add macOS CA, Keychain, and Plugin Configuration

**Files:**
- Create: plugins/arcpy-mcp/assets/arcpy-mcp-ca.crt
- Create: plugins/arcpy-mcp/scripts/configure-macos.sh
- Create: tests/test_scripts.py

- [ ] **Step 1: Copy the public CA certificate**

After the Windows server bootstrap, copy:

~~~text
%LOCALAPPDATA%\ArcPyMCP\certs\arcpy-mcp-ca.crt
~~~

to:

~~~text
plugins/arcpy-mcp/assets/arcpy-mcp-ca.crt
~~~

Verify it contains CERTIFICATE and no PRIVATE KEY block.

- [ ] **Step 2: Write failing script tests**

~~~python
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "plugins/arcpy-mcp/scripts/configure-macos.sh"


def test_configure_script_uses_keychain_and_never_echoes_token():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "security add-generic-password" in text
    assert "security find-generic-password" in text
    assert "launchctl setenv ARCPY_MCP_TOKEN" in text
    assert "codex plugin marketplace add" in text
    assert "codex plugin add arcpy-mcp@zhouning-arcpy" in text
    assert 'echo "$TOKEN"' not in text
    assert "set -x" not in text
~~~

- [ ] **Step 3: Run tests and verify failure**

Run: uv run pytest tests/test_scripts.py -v

Expected: FAIL because configure-macos.sh does not exist.

- [ ] **Step 4: Create configure-macos.sh**

~~~bash
#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This script must run on macOS.\n' >&2
  exit 1
fi

for command in codex git security launchctl curl shasum; do
  command -v "$command" >/dev/null || {
    printf 'Missing command: %s\n' "$command" >&2
    exit 1
  }
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CA_CERT="$PLUGIN_DIR/assets/arcpy-mcp-ca.crt"
SERVICE_NAME="codex-arcpy-mcp"
LAUNCH_DIR="$HOME/Library/Application Support/ArcPyMCP"
LOADER="$LAUNCH_DIR/load-token.sh"
PLIST="$HOME/Library/LaunchAgents/com.zhouning.arcpy-mcp-token.plist"

grep -q "BEGIN CERTIFICATE" "$CA_CERT"
if grep -q "PRIVATE KEY" "$CA_CERT"; then
  printf 'CA asset unexpectedly contains a private key.\n' >&2
  exit 1
fi

printf 'ArcPy MCP Bearer Token: '
IFS= read -r -s TOKEN
printf '\n'
if [[ ${#TOKEN} -lt 32 ]]; then
  printf 'Token must contain at least 32 characters.\n' >&2
  exit 1
fi

security add-generic-password \
  -U \
  -a "$USER" \
  -s "$SERVICE_NAME" \
  -w "$TOKEN" >/dev/null

mkdir -p "$LAUNCH_DIR" "$HOME/Library/LaunchAgents"
cat >"$LOADER" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
TOKEN="$(security find-generic-password -a "$USER" -s codex-arcpy-mcp -w)"
launchctl setenv ARCPY_MCP_TOKEN "$TOKEN"
SH
chmod 700 "$LOADER"

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.zhouning.arcpy-mcp-token</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LOADER</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
PLIST

"$LOADER"
launchctl bootout "gui/$UID/com.zhouning.arcpy-mcp-token" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

security add-trusted-cert \
  -r trustRoot \
  -k "$HOME/Library/Keychains/login.keychain-db" \
  "$CA_CERT"

if codex plugin marketplace list | grep -Fq "zhouning-arcpy"; then
  codex plugin marketplace upgrade zhouning-arcpy
else
  codex plugin marketplace add zhouning/codex-arcpy-mcp-plugin
fi
codex plugin add arcpy-mcp@zhouning-arcpy

curl \
  --fail \
  --silent \
  --show-error \
  --cacert "$CA_CERT" \
  "https://192.168.25.228:8765/healthz"

unset TOKEN
printf '\nArcPy MCP configured. Restart Codex and open a new thread.\n'
~~~

- [ ] **Step 5: Validate the script**

Run on Windows for static checks:

~~~powershell
uv run pytest tests/test_scripts.py -v
bash -n plugins/arcpy-mcp/scripts/configure-macos.sh
~~~

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

~~~powershell
git add plugins/arcpy-mcp/assets/arcpy-mcp-ca.crt plugins/arcpy-mcp/scripts/configure-macos.sh tests/test_scripts.py
git commit -m "feat: configure secure macOS ArcPy access"
~~~

### Task 5: Add Connection Diagnostics and Secret Rotation

**Files:**
- Create: plugins/arcpy-mcp/scripts/verify-connection.sh
- Modify: plugins/arcpy-mcp/scripts/configure-macos.sh
- Modify: tests/test_scripts.py

- [ ] **Step 1: Write failing diagnostic tests**

Assert verify-connection.sh checks:

- ARCPY_MCP_TOKEN is set without printing it;
- CA certificate parses;
- curl reaches /healthz;
- codex plugin list contains arcpy-mcp and zhouning-arcpy;
- codex mcp list contains arcpy;
- no command uses set -x or env output.

~~~python
def test_verify_script_checks_each_connection_layer_without_dumping_environment():
    path = ROOT / "plugins/arcpy-mcp/scripts/verify-connection.sh"
    text = path.read_text(encoding="utf-8")

    required = [
        "security find-generic-password",
        "launchctl setenv ARCPY_MCP_TOKEN",
        "security verify-cert",
        "https://192.168.25.228:8765/healthz",
        "codex plugin list",
        "codex mcp list",
    ]
    for phrase in required:
        assert phrase in text
    assert "set -x" not in text
    assert "\nenv\n" not in text
    assert 'echo "$TOKEN"' not in text
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_scripts.py -v

Expected: FAIL because verify-connection.sh does not exist.

- [ ] **Step 3: Create verify-connection.sh**

~~~bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CA_CERT="$PLUGIN_DIR/assets/arcpy-mcp-ca.crt"

TOKEN="$(security find-generic-password -a "$USER" -s codex-arcpy-mcp -w)"
[[ ${#TOKEN} -ge 32 ]]
launchctl setenv ARCPY_MCP_TOKEN "$TOKEN"
unset TOKEN

security verify-cert -c "$CA_CERT" >/dev/null
curl --fail --silent --show-error --cacert "$CA_CERT" \
  "https://192.168.25.228:8765/healthz"
codex plugin list | grep -F "arcpy-mcp"
codex plugin list | grep -F "zhouning-arcpy"
codex mcp list | grep -F "arcpy"

printf '\nArcPy MCP connection checks passed.\n'
~~~

- [ ] **Step 4: Add token rotation mode**

Replace the direct token prompt and Keychain write with:

~~~bash
MODE="${1:-install}"
if [[ "$MODE" != "install" && "$MODE" != "--rotate-token" ]]; then
  printf 'Usage: %s [--rotate-token]\n' "$0" >&2
  exit 2
fi

store_token() {
  local token
  printf 'ArcPy MCP Bearer Token: '
  IFS= read -r -s token
  printf '\n'
  if [[ ${#token} -lt 32 ]]; then
    printf 'Token must contain at least 32 characters.\n' >&2
    exit 1
  fi
  security add-generic-password \
    -U \
    -a "$USER" \
    -s "$SERVICE_NAME" \
    -w "$token" >/dev/null
  unset token
}

store_token
~~~

Wrap CA trust and marketplace installation in:

~~~bash
if [[ "$MODE" == "install" ]]; then
  security add-trusted-cert \
    -r trustRoot \
    -k "$HOME/Library/Keychains/login.keychain-db" \
    "$CA_CERT"

  if codex plugin marketplace list | grep -Fq "zhouning-arcpy"; then
    codex plugin marketplace upgrade zhouning-arcpy
  else
    codex plugin marketplace add zhouning/codex-arcpy-mcp-plugin
  fi
  codex plugin add arcpy-mcp@zhouning-arcpy
fi
~~~

Keep the loader execution and health request outside this branch so both install and rotation reload ARCPY_MCP_TOKEN and verify the endpoint. Neither branch prints the token.

- [ ] **Step 5: Run script tests**

Run:

~~~powershell
uv run pytest tests/test_scripts.py -v
bash -n plugins/arcpy-mcp/scripts/configure-macos.sh
bash -n plugins/arcpy-mcp/scripts/verify-connection.sh
~~~

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

~~~powershell
git add plugins/arcpy-mcp/scripts tests/test_scripts.py
git commit -m "feat: diagnose and rotate ArcPy credentials"
~~~

### Task 6: Validate Plugin Installation and Update Behavior

**Files:**
- Modify: README.md
- Modify: tests/test_manifests.py

- [ ] **Step 1: Write installation documentation tests**

Assert README.md contains these exact commands:

~~~text
git clone git@github.com:zhouning/codex-arcpy-mcp-plugin.git
./codex-arcpy-mcp-plugin/plugins/arcpy-mcp/scripts/configure-macos.sh
codex plugin add arcpy-mcp@zhouning-arcpy
codex plugin marketplace upgrade zhouning-arcpy
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests -v

Expected: FAIL because README.md lacks the commands.

- [ ] **Step 3: Write README.md**

~~~~markdown
# Codex ArcPy MCP Plugin

Private Codex plugin for the ArcPy MCP service at
https://192.168.25.228:8765/mcp.

## Prerequisites

- macOS can route to 192.168.25.228 through the LAN or VPN.
- GitHub SSH access can clone zhouning/codex-arcpy-mcp-plugin.
- Codex CLI 0.144.1 or newer is installed.
- The Windows ArcPy MCP service is healthy.
- You have the server-generated Bearer Token.

## Install

~~~bash
git clone git@github.com:zhouning/codex-arcpy-mcp-plugin.git
./codex-arcpy-mcp-plugin/plugins/arcpy-mcp/scripts/configure-macos.sh
~~~

The script imports the private CA into the login Keychain, stores the token
under Keychain service codex-arcpy-mcp, registers the private GitHub
marketplace, and installs arcpy-mcp@zhouning-arcpy.

Restart Codex and start a new thread after installation.

## Verify

~~~bash
./codex-arcpy-mcp-plugin/plugins/arcpy-mcp/scripts/verify-connection.sh
~~~

## Update

~~~bash
codex plugin marketplace upgrade zhouning-arcpy
codex plugin add arcpy-mcp@zhouning-arcpy
~~~

Restart Codex and use a new thread after an update.

## Rotate the Bearer Token

Rotate the Windows server token first, then run:

~~~bash
./codex-arcpy-mcp-plugin/plugins/arcpy-mcp/scripts/configure-macos.sh --rotate-token
~~~

## Remove

~~~bash
codex plugin remove arcpy-mcp
codex plugin marketplace remove zhouning-arcpy
launchctl bootout "gui/$UID/com.zhouning.arcpy-mcp-token" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.zhouning.arcpy-mcp-token.plist"
rm -rf "$HOME/Library/Application Support/ArcPyMCP"
security delete-generic-password -a "$USER" -s codex-arcpy-mcp
~~~

Remove the ArcPy MCP CA certificate from Keychain Access by matching the
certificate subject shown during installation.

## Deep Learning

The Windows host currently runs ArcGIS deep-learning inference on CPU.
Inference can take substantially longer than vector or raster processing.
Model training is not exposed.

## Troubleshooting Order

1. Confirm ping or TCP routing to 192.168.25.228:8765.
2. Run verify-connection.sh and resolve certificate errors.
3. Confirm the Keychain token and ARCPY_MCP_TOKEN session environment.
4. Confirm arcpy-mcp appears in codex plugin list and arcpy appears in codex mcp list.
5. Call MCP health_check and inspect ArcGIS license and extension status.
~~~~

- [ ] **Step 4: Run official plugin validation**

Run:

~~~powershell
python C:\Users\zn198\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins\arcpy-mcp
uv run pytest tests -v
git diff --check
~~~

Expected: validator PASS, tests PASS, and no whitespace errors.

- [ ] **Step 5: Test a local marketplace install on Windows Codex**

Run:

~~~powershell
codex plugin marketplace add D:\adk\standalone\codex-arcpy-mcp-plugin
codex plugin add arcpy-mcp@zhouning-arcpy --json
codex plugin list
codex mcp list
~~~

Expected: the plugin appears under zhouning-arcpy and the arcpy HTTP MCP entry is discovered. The connection may remain unavailable until the Windows service is running and ARCPY_MCP_TOKEN is present.

- [ ] **Step 6: Commit and push**

Run:

~~~powershell
git add README.md tests
git commit -m "docs: add ArcPy plugin installation and updates"
git push origin main
git status --short
~~~

Expected: push succeeds and status is clean.

### Task 7: Run the macOS End-to-End Acceptance Workflow

**Files:**
- Create on macOS test workspace: arcpy-mcp-acceptance/
- Record results in: acceptance-2026-07-10.md

- [ ] **Step 1: Install from the private GitHub repository**

Run on macOS:

~~~bash
git clone git@github.com:zhouning/codex-arcpy-mcp-plugin.git
./codex-arcpy-mcp-plugin/plugins/arcpy-mcp/scripts/configure-macos.sh
./codex-arcpy-mcp-plugin/plugins/arcpy-mcp/scripts/verify-connection.sh
~~~

Expected: CA, Keychain token, marketplace, plugin, and MCP checks pass.

- [ ] **Step 2: Start a new Codex thread and verify health**

Prompt:

~~~text
Use the ArcPy MCP plugin. Check the Windows ArcPy service health and report the ArcGIS version, license level, Spatial Analyst status, Image Analyst status, and processor type.
~~~

Expected: ArcGIS Pro 3.7.1, ArcInfo, Spatial and ImageAnalyst available, processor CPU.

- [ ] **Step 3: Test vector upload, processing, and download**

Use a small zipped shapefile. Ask Codex to upload it, inspect it, run a 50-meter buffer, wait for completion, download the result, and verify SHA-256.

Expected: ready upload artifact, succeeded job, downloadable result artifact, matching hash, and valid extracted output.

- [ ] **Step 4: Test raster processing**

Use a small DEM raster. Ask Codex to inspect it, run slope in degrees, download, and verify the output.

Expected: succeeded raster.slope job and an ArcPy-readable output raster.

- [ ] **Step 5: Test cancellation and recovery**

Submit a deliberately long CPU operation, request cancellation after it reaches running, then submit dataset inspection.

Expected: first job cancelled, worker PID changed on Windows, following inspection succeeds.

- [ ] **Step 6: Test CPU deep-learning inference when a model is available**

Upload a compatible ArcGIS Pro 3.7.1 DLPK or EMD and matching raster, run dl.detect_objects, download the result, and record duration.

Expected with a compatible model: succeeded inference. Without a model: record SKIPPED with reason "No compatible ArcGIS Pro 3.7.1 test model supplied"; do not report DL end-to-end success.

- [ ] **Step 7: Write the acceptance record**

acceptance-2026-07-10.md must contain:

- macOS and Codex versions;
- plugin commit;
- server commit;
- endpoint IP and port;
- health result;
- vector and raster job IDs and durations;
- cancellation result;
- DL result or explicit skip;
- no copied tokens or signed URLs.

- [ ] **Step 8: Tag both repositories after acceptance**

Run in each repository:

~~~bash
git tag -a v0.1.0 -m "ArcPy MCP v0.1.0"
git push origin v0.1.0
~~~

Expected: both private repositories have tag v0.1.0.
