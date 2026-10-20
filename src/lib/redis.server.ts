import { RedisClient } from "bun";

import { env } from "#/env";

export const redis = env.REDIS_URL ? new RedisClient(env.REDIS_URL) : null;
