#!/usr/bin/env node
/** Capture bounded official Chicago data through an existing headed Chrome CDP session. */

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

const ALLOWED_HOSTS = new Set([
  "data.cityofchicago.org",
  "www.chicago.gov",
]);

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`invalid_argument_at:${index}`);
    }
    args[key.slice(2)] = value;
  }
  return args;
}

function csvValues(value) {
  return value ? value.split(",").map((item) => item.trim()).filter(Boolean) : [];
}

function validateJson(payload, args) {
  if (payload === null || (typeof payload !== "object" && !Array.isArray(payload))) {
    throw new Error("json_object_or_list_required");
  }
  const rows = Array.isArray(payload) ? payload : [payload];
  if (args["expected-count"] !== undefined) {
    const expectedCount = Number.parseInt(args["expected-count"], 10);
    if (!Array.isArray(payload) || rows.length !== expectedCount) {
      throw new Error(`unexpected_row_count:${rows.length}:${expectedCount}`);
    }
  }
  const requiredFields = csvValues(args["required-fields"]);
  for (const [rowIndex, row] of rows.entries()) {
    if (row === null || typeof row !== "object" || Array.isArray(row)) {
      throw new Error(`json_row_not_object:${rowIndex}`);
    }
    const missing = requiredFields.filter((field) => !(field in row));
    if (missing.length) {
      throw new Error(`required_fields_missing:${rowIndex}:${missing.join(",")}`);
    }
  }
  const uniqueFields = csvValues(args["unique-fields"]);
  for (const field of uniqueFields) {
    const values = rows.map((row) => String(row[field] ?? ""));
    if (values.some((value) => !value)) {
      throw new Error(`unique_field_blank:${field}`);
    }
    if (new Set(values).size !== values.length) {
      throw new Error(`unique_field_duplicate:${field}`);
    }
  }
  return {
    json_kind: Array.isArray(payload) ? "list" : "object",
    row_count: Array.isArray(payload) ? rows.length : null,
    required_fields: requiredFields,
    unique_fields: uniqueFields,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const sourceUrl = new URL(args.url);
  if (sourceUrl.protocol !== "https:" || !ALLOWED_HOSTS.has(sourceUrl.hostname)) {
    throw new Error("url_not_allowlisted_official_https_source");
  }
  if (!args.output) {
    throw new Error("output_required");
  }
  const mode = args.mode ?? "json";
  if (!new Set(["json", "text"]).has(mode)) {
    throw new Error(`invalid_mode:${mode}`);
  }
  const maxBytes = Number.parseInt(args["max-bytes"] ?? "25000000", 10);
  if (!Number.isFinite(maxBytes) || maxBytes <= 0) {
    throw new Error("positive_max_bytes_required");
  }
  const cdpUrl = args["cdp-url"] ?? "http://127.0.0.1:9229";
  const browser = await chromium.connectOverCDP(cdpUrl);
  const context = browser.contexts()[0];
  if (!context) {
    throw new Error("cdp_browser_context_missing");
  }
  const page = context.pages().find((candidate) => candidate.url() === args.url)
    ?? context.pages().find((candidate) => candidate.url().startsWith("https://data.cityofchicago.org/"))
    ?? await context.newPage();
  const response = await page.goto(args.url, { waitUntil: "domcontentloaded" });
  if (!response) {
    throw new Error("navigation_response_missing");
  }
  const status = response.status();
  if (status !== 200) {
    throw new Error(`unexpected_http_status:${status}`);
  }
  const body = await response.body();
  if (!body.length || body.length > maxBytes) {
    throw new Error(`response_size_invalid:${body.length}:${maxBytes}`);
  }
  const bodyText = body.toString("utf8");
  let validation;
  if (mode === "json") {
    validation = validateJson(JSON.parse(bodyText), args);
  } else {
    const requiredText = csvValues(args["required-text"]);
    const missing = requiredText.filter((value) => !bodyText.includes(value));
    if (missing.length) {
      throw new Error(`required_text_missing:${missing.join(",")}`);
    }
    validation = { required_text: requiredText };
  }

  const outputPath = path.resolve(args.output);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, body);
  const digest = crypto.createHash("sha256").update(body).digest("hex");
  const manifest = {
    schema: "gwm.chicago_browser_cdp_capture.v1",
    captured_at: new Date().toISOString(),
    source_url: response.url(),
    browser_url: page.url(),
    http_status: status,
    content_type: response.headers()["content-type"] ?? null,
    output_path: outputPath,
    bytes: body.length,
    sha256: digest,
    mode,
    validation,
    access_boundary: "browser_or_waf",
    cookies_or_credentials_persisted: false,
  };
  await fs.writeFile(
    `${outputPath}.capture.json`,
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(`${JSON.stringify(manifest)}\n`);
  process.exit(0);
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exit(1);
});
