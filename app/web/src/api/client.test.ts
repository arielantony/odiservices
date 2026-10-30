import { afterEach, vi } from "vitest";
import { ApiError, request } from "./client";

function stubFetch(impl: () => Promise<unknown>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

function jsonResponse(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}

async function failure(): Promise<ApiError> {
  try {
    await request("/api/x");
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("expected request to reject");
}

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
  it("network failure", async () => {
    stubFetch(() => Promise.reject(new TypeError("down")));
    const e = await failure();
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ kind: "network", status: 0, code: "network" });
  });

  it("error body is parsed", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse(404, { error: { code: "not_found", message: "Recurso não encontrado." } }),
      ),
    );
    expect(await failure()).toMatchObject({
      kind: "http",
      status: 404,
      code: "not_found",
      message: "Recurso não encontrado.",
    });
  });

  it("error without body", async () => {
    stubFetch(() => Promise.resolve(new Response("oops", { status: 500 })));
    expect(await failure()).toMatchObject({ status: 500, code: "http_500" });
  });

  it("opaque redirect means session expired", async () => {
    const res = { type: "opaqueredirect", ok: false, status: 0 };
    stubFetch(() => Promise.resolve(res));
    expect(await failure()).toMatchObject({ status: 401, code: "unauthenticated" });
  });

  it("conflict carries version", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse(409, { error: { code: "conflict", message: "Versão desatualizada.", version: 3 } }),
      ),
    );
    expect(await failure()).toMatchObject({ status: 409, code: "conflict", version: 3 });
  });

  it("invalid JSON on 2xx", async () => {
    stubFetch(() => Promise.resolve(new Response("not json", { status: 200 })));
    expect(await failure()).toMatchObject({ code: "bad_response" });
  });

  it("returns parsed JSON on success", async () => {
    stubFetch(() => Promise.resolve(jsonResponse(200, { ok: true })));
    expect(await request("/api/x")).toEqual({ ok: true });
  });
});
