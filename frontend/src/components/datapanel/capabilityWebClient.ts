import Ajv2020, { type ErrorObject, type ValidateFunction } from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import i18n, { getLocaleHeaders } from '../../i18n';

export type JsonObject = Record<string, unknown>;
export type FetchLike = typeof fetch;

export interface CapabilitySummary {
  capability_id: string;
  version: string;
  title: string;
  tier: string;
  lifecycle: string;
  operation: string;
  fingerprint: string;
  available_surfaces: string[];
}

export interface CapabilityManifest {
  schema: string;
  fingerprint: string;
  llm_mode: string;
  surface: string | null;
  count: number;
  capabilities: CapabilitySummary[];
}

export interface JsonSchemaContract {
  semantic_type: string;
  json_schema: JsonObject;
}

export interface CapabilityHttpProjection {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: string;
  operation_id: string;
  input_location: 'query' | 'body';
  success_status: number;
  additional_success_statuses: number[];
  parameter_aliases: Record<string, string>;
  path_parameters: string[];
  response_envelope: 'direct' | 'platform_v1';
  include_created: boolean;
}

export interface CapabilitySpec {
  capability_id: string;
  version: string;
  title: string;
  description: string;
  owner: string;
  tier: string;
  lifecycle: string;
  operation: string;
  risk: string;
  side_effect: string;
  input: JsonSchemaContract;
  output: JsonSchemaContract;
  policy: {
    action: string;
    allowed_roles: string[];
    tenant_scoped: boolean;
    resource_kinds: string[];
  };
  execution: {
    idempotency: string;
    preview: string;
    result: string;
    cancellable: boolean;
    compensatable: boolean;
    reconcilable: boolean;
  };
  http: CapabilityHttpProjection | null;
}

export interface CapabilityDetail {
  spec: CapabilitySpec;
  fingerprint: string;
  projections: JsonObject;
}

export interface CapabilityPreview {
  capability_id: string;
  version: string;
  fingerprint: string;
  operation: string;
  risk: string;
  side_effect: string;
  input: JsonObject;
  confirmation_code: string | null;
  expires_at: number;
}

export interface CapabilityReceipt {
  capability_id: string;
  version: string;
  fingerprint: string;
  status_code: number;
  data: JsonObject;
  request_id: string | null;
  created: boolean | null;
}

export class CapabilityWebError extends Error {
  readonly code: string;
  readonly statusCode: number | null;

  constructor(message: string, code: string, statusCode: number | null = null) {
    super(message);
    this.name = 'CapabilityWebError';
    this.code = code;
    this.statusCode = statusCode;
  }
}

export class CapabilityValidationError extends CapabilityWebError {
  readonly issues: string[];

  constructor(message: string, issues: string[]) {
    super(message, 'validation_error');
    this.name = 'CapabilityValidationError';
    this.issues = issues;
  }
}

export class CapabilityDriftError extends CapabilityWebError {
  constructor(message: string) {
    super(message, 'capability_contract_mismatch', 409);
    this.name = 'CapabilityDriftError';
  }
}

export class CapabilityConfirmationError extends CapabilityWebError {
  constructor(message: string, code = 'confirmation_invalid') {
    super(message, code);
    this.name = 'CapabilityConfirmationError';
  }
}

const REGISTRY_SCHEMA = 'gda.capability-registry.v1';
const FINGERPRINT_HEADER = 'X-GDA-Capability-Fingerprint';
const CONFIRMATION_TTL_MS = 5 * 60 * 1000;

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validators = new Map<string, ValidateFunction>();

function protocolMessage(key: string, values: Record<string, unknown> = {}): string {
  return i18n.t(`capabilities.platform.protocol.${key}`, values);
}

function asObject(value: unknown, message: string): JsonObject {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new CapabilityWebError(message, 'protocol_error');
  }
  return value as JsonObject;
}

async function responseJson(response: Response): Promise<JsonObject> {
  try {
    return asObject(await response.json(), protocolMessage('nonObjectJson', { status: response.status }));
  } catch (error) {
    if (error instanceof CapabilityWebError) throw error;
    throw new CapabilityWebError(
      protocolMessage('unparseableResponse', { status: response.status }),
      'protocol_error',
      response.status,
    );
  }
}

function remoteMessage(payload: JsonObject, status: number): string {
  const error = payload.error;
  if (typeof error === 'string' && error) return error;
  if (typeof error === 'object' && error !== null && !Array.isArray(error)) {
    const detail = (error as JsonObject).message ?? (error as JsonObject).code;
    if (typeof detail === 'string' && detail) return detail;
  }
  if (typeof payload.message === 'string' && payload.message) return payload.message;
  return protocolMessage('rejected', { status });
}

function isContractMismatch(payload: JsonObject): boolean {
  if (payload.code === 'capability_contract_mismatch') return true;
  const error = payload.error;
  return typeof error === 'object'
    && error !== null
    && !Array.isArray(error)
    && (error as JsonObject).code === 'capability_contract_mismatch';
}

export async function listWebCapabilities(fetchImpl: FetchLike = fetch): Promise<CapabilityManifest> {
  const response = await fetchImpl('/api/capability-specs?surface=web&llm_mode=disabled', {
    credentials: 'include',
    headers: { Accept: 'application/json', ...getLocaleHeaders() },
  });
  const payload = await responseJson(response);
  if (!response.ok) {
    throw new CapabilityWebError(remoteMessage(payload, response.status), 'discovery_error', response.status);
  }
  if (payload.schema !== REGISTRY_SCHEMA || !Array.isArray(payload.capabilities)) {
    throw new CapabilityWebError(protocolMessage('unsupportedRegistry'), 'protocol_error');
  }
  return payload as unknown as CapabilityManifest;
}

export async function getWebCapability(
  capabilityId: string,
  version?: string,
  fetchImpl: FetchLike = fetch,
): Promise<CapabilityDetail> {
  const query = version ? `?version=${encodeURIComponent(version)}` : '';
  const response = await fetchImpl(
    `/api/capability-specs/${encodeURIComponent(capabilityId)}${query}`,
    { credentials: 'include', headers: { Accept: 'application/json', ...getLocaleHeaders() } },
  );
  const payload = await responseJson(response);
  if (!response.ok) {
    throw new CapabilityWebError(remoteMessage(payload, response.status), 'discovery_error', response.status);
  }
  const spec = asObject(payload.spec, protocolMessage('missingCanonicalSpec')) as unknown as CapabilitySpec;
  if (
    typeof payload.fingerprint !== 'string'
    || typeof spec.capability_id !== 'string'
    || typeof spec.version !== 'string'
  ) {
    throw new CapabilityWebError(protocolMessage('missingIdentity'), 'protocol_error');
  }
  return payload as unknown as CapabilityDetail;
}

function validationIssues(errors: ErrorObject[] | null | undefined): string[] {
  return (errors ?? []).map((error) => {
    const path = error.instancePath || '$';
    return `${path}: ${error.message ?? error.keyword}`;
  });
}

function validatorFor(schema: JsonObject): ValidateFunction {
  const key = typeof schema.$id === 'string' ? schema.$id : canonicalJson(schema);
  const cached = validators.get(key);
  if (cached) return cached;
  const validator = ajv.compile(schema);
  validators.set(key, validator);
  return validator;
}

export function validateCapabilityInput(detail: CapabilityDetail, input: JsonObject): void {
  const validator = validatorFor(detail.spec.input.json_schema);
  if (!validator(input)) {
    throw new CapabilityValidationError(protocolMessage('invalidInputSchema'), validationIssues(validator.errors));
  }
}

function validateCapabilityOutput(detail: CapabilityDetail, output: JsonObject): void {
  const validator = validatorFor(detail.spec.output.json_schema);
  if (!validator(output)) {
    throw new CapabilityValidationError(protocolMessage('invalidOutputSchema'), validationIssues(validator.errors));
  }
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJson);
  if (typeof value === 'object' && value !== null) {
    return Object.keys(value as JsonObject).sort().reduce<JsonObject>((result, key) => {
      result[key] = sortJson((value as JsonObject)[key]);
      return result;
    }, {});
  }
  return value;
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortJson(value)).replace(/[\u007f-\uffff]/g, (character) => (
    `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`
  ));
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

export function requiresCapabilityConfirmation(detail: CapabilityDetail): boolean {
  return detail.spec.side_effect !== 'none'
    || detail.spec.risk === 'high'
    || detail.spec.risk === 'critical';
}

export async function buildCapabilityPreview(
  detail: CapabilityDetail,
  input: JsonObject,
  now = Date.now(),
): Promise<CapabilityPreview> {
  validateCapabilityInput(detail, input);
  const preview = {
    capability_id: detail.spec.capability_id,
    version: detail.spec.version,
    fingerprint: detail.fingerprint,
    operation: detail.spec.operation,
    risk: detail.spec.risk,
    side_effect: detail.spec.side_effect,
    input,
  };
  const confirmationCode = requiresCapabilityConfirmation(detail)
    ? (await sha256Hex(canonicalJson(preview))).slice(0, 12).toUpperCase()
    : null;
  return {
    ...preview,
    confirmation_code: confirmationCode,
    expires_at: now + CONFIRMATION_TTL_MS,
  };
}

export async function assertCapabilityConfirmation(
  detail: CapabilityDetail,
  input: JsonObject,
  preview: CapabilityPreview | undefined,
  confirmationCode: string | undefined,
  now = Date.now(),
): Promise<void> {
  if (!requiresCapabilityConfirmation(detail)) return;
  if (!preview) throw new CapabilityConfirmationError(protocolMessage('previewRequired'), 'preview_required');
  if (now > preview.expires_at) {
    throw new CapabilityConfirmationError(protocolMessage('confirmationExpired'), 'confirmation_expired');
  }
  const rebound = await buildCapabilityPreview(detail, input, preview.expires_at - CONFIRMATION_TTL_MS);
  if (
    rebound.confirmation_code !== preview.confirmation_code
    || preview.capability_id !== detail.spec.capability_id
    || preview.version !== detail.spec.version
    || preview.fingerprint !== detail.fingerprint
  ) {
    throw new CapabilityConfirmationError(protocolMessage('previewMismatch'), 'preview_mismatch');
  }
  if ((confirmationCode ?? '').trim().toUpperCase() !== preview.confirmation_code) {
    throw new CapabilityConfirmationError(protocolMessage('confirmationMismatch'));
  }
}

function projectRequest(detail: CapabilityDetail, input: JsonObject): {
  path: string;
  query: URLSearchParams;
  body: JsonObject | undefined;
  headers: Record<string, string>;
} {
  const http = detail.spec.http;
  if (!http) throw new CapabilityWebError(protocolMessage('missingHttpProjection'), 'projection_error');
  let path = http.path;
  const pathNames = new Set(http.path_parameters);
  for (const name of http.path_parameters) {
    path = path.replace(`{${name}}`, encodeURIComponent(String(input[name])));
  }
  const projected = Object.fromEntries(Object.entries(input).filter(([name]) => !pathNames.has(name)));
  const query = new URLSearchParams();
  let body: JsonObject | undefined;
  if (http.input_location === 'body') {
    body = projected;
  } else {
    for (const [name, value] of Object.entries(projected)) {
      const projectedName = http.parameter_aliases[name] ?? name;
      if (Array.isArray(value)) value.forEach((item) => query.append(projectedName, String(item)));
      else query.append(projectedName, String(value));
    }
  }
  return {
    path,
    query,
    body,
    headers: {
      Accept: 'application/json',
      ...getLocaleHeaders(),
      [FINGERPRINT_HEADER]: detail.fingerprint,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
  };
}

export async function invokeWebCapability(
  detail: CapabilityDetail,
  input: JsonObject,
  options: {
    fetchImpl?: FetchLike;
    preview?: CapabilityPreview;
    confirmationCode?: string;
    now?: number;
  } = {},
): Promise<CapabilityReceipt> {
  validateCapabilityInput(detail, input);
  await assertCapabilityConfirmation(
    detail,
    input,
    options.preview,
    options.confirmationCode,
    options.now,
  );
  const fetchImpl = options.fetchImpl ?? fetch;
  const serving = await getWebCapability(detail.spec.capability_id, detail.spec.version, fetchImpl);
  if (
    serving.spec.capability_id !== detail.spec.capability_id
    || serving.spec.version !== detail.spec.version
    || serving.fingerprint !== detail.fingerprint
  ) {
    throw new CapabilityDriftError(protocolMessage('preflightDrift'));
  }

  const http = detail.spec.http;
  if (!http) throw new CapabilityWebError(protocolMessage('missingHttpProjection'), 'projection_error');
  const projected = projectRequest(detail, input);
  const query = projected.query.toString();
  const response = await fetchImpl(`${projected.path}${query ? `?${query}` : ''}`, {
    method: http.method,
    credentials: 'include',
    headers: projected.headers,
    body: projected.body ? JSON.stringify(projected.body) : undefined,
  });
  const payload = await responseJson(response);
  const expectedStatuses = [http.success_status, ...(http.additional_success_statuses ?? [])];
  if (!expectedStatuses.includes(response.status)) {
    if (isContractMismatch(payload)) {
      throw new CapabilityDriftError(protocolMessage('executionDrift'));
    }
    throw new CapabilityWebError(
      remoteMessage(payload, response.status),
      'invocation_error',
      response.status,
    );
  }

  let data = payload;
  let requestId = response.headers.get('x-request-id');
  let created: boolean | null = null;
  if (http.response_envelope === 'platform_v1') {
    data = asObject(payload.data, protocolMessage('missingCanonicalData'));
    if (payload.error !== null || typeof payload.request_id !== 'string' || !payload.request_id) {
      throw new CapabilityWebError(protocolMessage('invalidEnvelope'), 'protocol_error');
    }
    requestId = payload.request_id;
    if (http.include_created) {
      if (typeof payload.created !== 'boolean') {
        throw new CapabilityWebError(protocolMessage('missingCreated'), 'protocol_error');
      }
      created = payload.created;
    }
  }
  validateCapabilityOutput(detail, data);
  return {
    capability_id: detail.spec.capability_id,
    version: detail.spec.version,
    fingerprint: detail.fingerprint,
    status_code: response.status,
    data,
    request_id: requestId,
    created,
  };
}

function localRef(root: JsonObject, schema: JsonObject): JsonObject {
  const ref = schema.$ref;
  if (typeof ref !== 'string' || !ref.includes('#/')) return schema;
  const pointer = ref.slice(ref.indexOf('#/') + 2).split('/');
  let value: unknown = root;
  for (const token of pointer) {
    const key = token.replace(/~1/g, '/').replace(/~0/g, '~');
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return schema;
    value = (value as JsonObject)[key];
  }
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as JsonObject
    : schema;
}

function scaffoldValue(root: JsonObject, rawSchema: JsonObject, propertyName = ''): unknown {
  let schema = localRef(root, rawSchema);
  const variants = (schema.anyOf ?? schema.oneOf) as unknown;
  if (Array.isArray(variants)) {
    const selected = variants.find((item) => (
      typeof item === 'object' && item !== null && (item as JsonObject).type !== 'null'
    ));
    if (selected) schema = localRef(root, selected as JsonObject);
  }
  if ('default' in schema) return schema.default;
  if (Array.isArray(schema.enum) && schema.enum.length) return schema.enum[0];
  if ('const' in schema) return schema.const;
  if (schema.type === 'object' || schema.properties) {
    const properties = (schema.properties ?? {}) as JsonObject;
    const required = new Set(Array.isArray(schema.required) ? schema.required as string[] : []);
    return Object.fromEntries(Object.entries(properties)
      .filter(([name, value]) => required.has(name) || (value as JsonObject).default !== undefined)
      .map(([name, value]) => [name, scaffoldValue(root, value as JsonObject, name)]));
  }
  if (schema.type === 'array') return [];
  if (schema.type === 'boolean') return false;
  if (schema.type === 'integer' || schema.type === 'number') {
    return typeof schema.minimum === 'number' ? schema.minimum : 0;
  }
  if (propertyName === 'client_request_id') return 'web-request-20260805-001';
  if (propertyName === 'logical_end') return '2026-08-06T00:00:00Z';
  if (schema.format === 'date-time') return '2026-08-05T00:00:00Z';
  if (schema.format === 'uuid' || propertyName.endsWith('_id')) {
    return '00000000-0000-4000-8000-000000000000';
  }
  if (propertyName.includes('fingerprint') || schema.minLength === 64) return '0'.repeat(64);
  if (propertyName === 'purpose' || propertyName === 'reason') return 'operator request';
  return '';
}

export function buildInputScaffold(detail: CapabilityDetail): JsonObject {
  return scaffoldValue(
    detail.spec.input.json_schema,
    detail.spec.input.json_schema,
  ) as JsonObject;
}
