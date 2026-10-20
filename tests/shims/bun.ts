export interface S3ClientOptions {
  endpoint?: string;
  accessKeyId?: string;
  secretAccessKey?: string;
  bucket?: string;
  region?: string;
}

export class S3Client {
  readonly endpoint: string;
  readonly bucket: string;

  constructor(options: S3ClientOptions = {}) {
    this.endpoint = options.endpoint ?? "http://localhost:9000";
    this.bucket = options.bucket ?? "app";
  }

  presign(key: string, options?: { method?: string; expiresIn?: number; type?: string }): string {
    const method = options?.method ?? "PUT";
    const typeParam = options?.type
      ? `&response-content-type=${encodeURIComponent(options.type)}`
      : "";
    return `${this.endpoint}/${this.bucket}/${key}?method=${method}&X-Amz-Signature=mock${typeParam}`;
  }
}

export class SQL {
  constructor(public connectionString?: string) {}
}

export class RedisClient {
  constructor(public url?: string) {}

  async get(_key: string): Promise<string | null> {
    return null;
  }

  async set(_key: string, _value: string): Promise<void> {}

  async del(_key: string): Promise<number> {
    return 1;
  }

  async incr(_key: string): Promise<number> {
    return 1;
  }

  async expire(_key: string, _seconds: number): Promise<boolean> {
    return true;
  }
}
