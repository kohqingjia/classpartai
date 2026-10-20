// oxlint-disable node/no-process-env
import { S3Client } from "bun";

/** Map validated content types to safe file extensions, preventing extension spoofing. */
export const CONTENT_TYPE_EXTENSIONS: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/svg+xml": "svg",
  "application/pdf": "pdf",
  "text/plain": "txt",
};

const MAX_BYTES = 10 * 1024 * 1024;

export interface UploadRequest {
  filename: string;
  contentType: string;
  size: number;
}

export function validateUploadRequest(req: UploadRequest): string | null {
  if (!CONTENT_TYPE_EXTENSIONS[req.contentType]) return "Unsupported file type";
  if (req.size > MAX_BYTES) return "File must be 10 MB or smaller";
  return null;
}

/** Derive a safe file extension from a validated content type. */
export function safeExtension(contentType: string): string {
  return CONTENT_TYPE_EXTENSIONS[contentType] ?? "bin";
}

export function createStorageClient(
  endpoint: string | undefined,
  accessKey: string | undefined,
  secretKey: string | undefined,
  bucket = "app"
): S3Client | null {
  if (!endpoint || !accessKey || !secretKey) return null;
  return new S3Client({
    endpoint,
    accessKeyId: accessKey,
    secretAccessKey: secretKey,
    bucket,
  });
}

let cachedKey: string | undefined;
let cachedStorageClient: S3Client | null | undefined;

export function getStorageClient(
  endpoint = process.env.MINIO_ENDPOINT,
  accessKey = process.env.MINIO_ACCESS_KEY,
  secretKey = process.env.MINIO_SECRET_KEY,
  bucket = process.env.MINIO_BUCKET ?? "app"
): S3Client | null {
  const key = `${endpoint}:${accessKey}:${secretKey}:${bucket}`;
  if (cachedStorageClient !== undefined && cachedKey === key) return cachedStorageClient;
  cachedKey = key;
  cachedStorageClient = createStorageClient(endpoint, accessKey, secretKey, bucket);
  return cachedStorageClient;
}
