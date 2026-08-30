import { describe, expect, it, vi } from 'vitest';

import {
  buildCapabilityPreview,
  type CapabilityDetail,
  CapabilityDriftError,
  CapabilityValidationError,
  invokeWebCapability,
} from './capabilityWebClient';

const INPUT = {
  run_id: '30000000-0000-4000-8000-000000000040',
  client_request_id: 'cancel-web-20260805-001',
  expected_state_version: 2,
  reason: 'operator cancelled an obsolete source refresh',
};

const DETAIL: CapabilityDetail = {
  fingerprint: 'a'.repeat(64),
  projections: {},
  spec: {
    capability_id: 'dataops.run.cancel',
    version: '1.0.0',
    title: 'Cancel a governed DataOps run',
    description: 'Cancel one governed run.',
    owner: 'data-platform.operations',
    tier: 'P0',
    lifecycle: 'active',
    operation: 'command',
    risk: 'high',
    side_effect: 'external_write',
    input: {
      semantic_type: 'gda.dataops.cancel-request.v1',
      json_schema: {
        $schema: 'https://json-schema.org/draft/2020-12/schema',
        $id: 'https://example.test/cancel-input.json',
        type: 'object',
        properties: {
          run_id: { type: 'string', format: 'uuid' },
          client_request_id: { type: 'string', minLength: 3 },
          expected_state_version: { type: 'integer', minimum: 1 },
          reason: { type: 'string', minLength: 3 },
        },
        required: ['run_id', 'client_request_id', 'expected_state_version', 'reason'],
        additionalProperties: false,
      },
    },
    output: {
      semantic_type: 'gda.dataops.cancel-admission.v1',
      json_schema: {
        $schema: 'https://json-schema.org/draft/2020-12/schema',
        $id: 'https://example.test/cancel-output.json',
        type: 'object',
        properties: { admission: { type: 'string' } },
        required: ['admission'],
        additionalProperties: false,
      },
    },
    policy: {
      action: 'dolphinscheduler.cancel',
      allowed_roles: ['admin', 'platform_operator'],
      tenant_scoped: true,
      resource_kinds: ['platform_run'],
    },
    execution: {
      idempotency: 'required',
      preview: 'unsupported',
      result: 'synchronous',
      cancellable: false,
      compensatable: false,
      reconcilable: true,
    },
    http: {
      method: 'POST',
      path: '/api/platform/v1/runs/{run_id}/cancel',
      operation_id: 'cancelDataOpsRun',
      input_location: 'body',
      success_status: 202,
      additional_success_statuses: [200],
      parameter_aliases: {},
      path_parameters: ['run_id'],
      response_envelope: 'platform_v1',
      include_created: true,
    },
  },
};

function detailResponse(detail: CapabilityDetail = DETAIL): Response {
  return new Response(JSON.stringify(detail), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function admissionResponse(status: 200 | 202, created: boolean): Response {
  return new Response(JSON.stringify({
    data: { admission: 'accepted' },
    error: null,
    request_id: 'request-1',
    created,
  }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('capabilityWebClient', () => {
  it('generates a stable input-bound 12 character confirmation code', async () => {
    const first = await buildCapabilityPreview(DETAIL, INPUT, 1_000);
    const second = await buildCapabilityPreview(DETAIL, { ...INPUT }, 2_000);

    expect(first.confirmation_code).toMatch(/^[0-9A-F]{12}$/);
    expect(second.confirmation_code).toBe(first.confirmation_code);
    expect(first.expires_at).toBe(301_000);
  });

  it.each([
    ['wrong code', 'WRONG-CODE', 2_000, 'confirmation_invalid'],
    ['expired code', undefined, 301_001, 'confirmation_expired'],
  ])('does not execute with a %s', async (_label, code, now, expectedCode) => {
    const preview = await buildCapabilityPreview(DETAIL, INPUT, 1_000);
    const fetchMock = vi.fn() as unknown as typeof fetch;

    await expect(invokeWebCapability(DETAIL, INPUT, {
      fetchImpl: fetchMock,
      preview,
      confirmationCode: code ?? preview.confirmation_code ?? undefined,
      now,
    })).rejects.toMatchObject({ code: expectedCode });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects invalid canonical input before any network call', async () => {
    const fetchMock = vi.fn() as unknown as typeof fetch;

    await expect(invokeWebCapability(DETAIL, { ...INPUT, expected_state_version: 0 }, {
      fetchImpl: fetchMock,
    })).rejects.toBeInstanceOf(CapabilityValidationError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('stops after discovery when execution preflight detects drift', async () => {
    const drifted = { ...DETAIL, fingerprint: 'b'.repeat(64) };
    const fetchMock = vi.fn(async () => detailResponse(drifted)) as unknown as typeof fetch;
    const preview = await buildCapabilityPreview(DETAIL, INPUT, 1_000);

    await expect(invokeWebCapability(DETAIL, INPUT, {
      fetchImpl: fetchMock,
      preview,
      confirmationCode: preview.confirmation_code ?? undefined,
      now: 2_000,
    })).rejects.toBeInstanceOf(CapabilityDriftError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('splits cancel path identity from body and binds the fingerprint header', async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return calls.length === 1 ? detailResponse() : admissionResponse(202, true);
    }) as unknown as typeof fetch;
    const preview = await buildCapabilityPreview(DETAIL, INPUT, 1_000);

    const receipt = await invokeWebCapability(DETAIL, INPUT, {
      fetchImpl: fetchMock,
      preview,
      confirmationCode: preview.confirmation_code ?? undefined,
      now: 2_000,
    });

    expect(String(calls[1].input)).toBe(
      '/api/platform/v1/runs/30000000-0000-4000-8000-000000000040/cancel',
    );
    expect(JSON.parse(String(calls[1].init?.body))).toEqual({
      client_request_id: INPUT.client_request_id,
      expected_state_version: 2,
      reason: INPUT.reason,
    });
    expect(calls[1].init?.headers).toMatchObject({
      'X-GDA-Capability-Fingerprint': DETAIL.fingerprint,
    });
    expect(receipt.status_code).toBe(202);
    expect(receipt.created).toBe(true);
  });

  it('accepts a 200 idempotent replay receipt', async () => {
    let callCount = 0;
    const fetchMock = vi.fn(async () => {
      callCount += 1;
      return callCount === 1 ? detailResponse() : admissionResponse(200, false);
    }) as unknown as typeof fetch;
    const preview = await buildCapabilityPreview(DETAIL, INPUT, 1_000);

    const receipt = await invokeWebCapability(DETAIL, INPUT, {
      fetchImpl: fetchMock,
      preview,
      confirmationCode: preview.confirmation_code ?? undefined,
      now: 2_000,
    });

    expect(receipt.status_code).toBe(200);
    expect(receipt.created).toBe(false);
    expect(receipt.data).toEqual({ admission: 'accepted' });
  });
});
