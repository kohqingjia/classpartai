import { afterEach, describe, expect, test, vi } from "vitest";
import { S3Client } from "bun";

import {
  validateUploadRequest,
  createStorageClient,
  getStorageClient,
  safeExtension,
} from "#/lib/storage.server";

describe("validateUploadRequest", () => {
  test("accepts valid image mime type", () => {
    expect(
      validateUploadRequest({ filename: "photo.jpg", contentType: "image/jpeg", size: 1024 })
    ).toBeNull();
  });

  test("rejects unsupported mime type", () => {
    expect(
      validateUploadRequest({ filename: "script.sh", contentType: "application/x-sh", size: 100 })
    ).toBe("Unsupported file type");
  });

  test("rejects file over 10MB", () => {
    expect(
      validateUploadRequest({
        filename: "big.png",
        contentType: "image/png",
        size: 11 * 1024 * 1024,
      })
    ).toBe("File must be 10 MB or smaller");
  });

  test("accepts file of exactly 10MB", () => {
    expect(
      validateUploadRequest({
        filename: "limit.png",
        contentType: "image/png",
        size: 10 * 1024 * 1024,
      })
    ).toBeNull();
  });
});

describe("createStorageClient", () => {
  test("returns null when endpoint is missing", () => {
    expect(createStorageClient(undefined, undefined, undefined)).toBeNull();
  });

  test("returns null when access key is missing", () => {
    expect(createStorageClient("http://localhost:9000", undefined, "password")).toBeNull();
  });

  test("returns null when secret key is missing", () => {
    expect(createStorageClient("http://localhost:9000", "admin", undefined)).toBeNull();
  });

  test("returns S3Client when endpoint is provided", () => {
    const client = createStorageClient("http://localhost:9000", "admin", "password");
    expect(client).not.toBeNull();
  });
});

describe("safeExtension", () => {
  test("maps image/jpeg to jpg", () => {
    expect(safeExtension("image/jpeg")).toBe("jpg");
  });

  test("maps application/pdf to pdf", () => {
    expect(safeExtension("application/pdf")).toBe("pdf");
  });

  test("returns bin for unknown content type", () => {
    expect(safeExtension("application/octet-stream")).toBe("bin");
  });
});

describe("client.presign", () => {
  test("builds the URL from the endpoint and bucket passed to createStorageClient", () => {
    const client = createStorageClient("http://localhost:9000", "admin", "password", "test-bucket");
    expect(client).not.toBeNull();
    if (!client) throw new Error("Client was null");
    const url = client.presign("test.png", { method: "PUT", type: "image/png" });
    // The key is echoed straight through, so asserting on it alone proves nothing about this
    // module. The endpoint and bucket are what `createStorageClient` wires into the client.
    expect(url).toContain("http://localhost:9000/test-bucket/test.png");
  });
});

describe("getStorageClient", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  test("caches one client per configuration and constructs it from the endpoint and bucket", () => {
    vi.stubEnv("MINIO_ENDPOINT", "http://storage.test:9000");
    vi.stubEnv("MINIO_ACCESS_KEY", "access");
    vi.stubEnv("MINIO_SECRET_KEY", "secret");
    vi.stubEnv("MINIO_BUCKET", "uploads");

    const client = getStorageClient();

    expect(client).toBeInstanceOf(S3Client);
    expect(client).toMatchObject({ endpoint: "http://storage.test:9000", bucket: "uploads" });
    expect(getStorageClient()).toBe(client);
  });
});
