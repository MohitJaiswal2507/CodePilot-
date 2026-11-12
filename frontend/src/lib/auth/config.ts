const BUILD_PHASE = 'phase-production-build';
const PLACEHOLDER_AUTH_URL = 'https://auth.placeholder.invalid/neondb/auth';

export interface ResolvedNeonAuthConfig {
  baseUrl: string;
  cookies: {
    secret: string;
  };
}

function generateEphemeralSecret(): string {
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function validateUrl(rawUrl: string, requireHttps: boolean): string {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error('NEON_AUTH_BASE_URL must be a valid URL.');
  }

  if (requireHttps && parsed.protocol !== 'https:') {
    throw new Error('NEON_AUTH_BASE_URL must use HTTPS in production.');
  }

  if (!requireHttps && parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error('NEON_AUTH_BASE_URL must use HTTP or HTTPS.');
  }

  return rawUrl;
}

export function resolveNeonAuthConfig(
  env: Record<string, string | undefined> = process.env,
): ResolvedNeonAuthConfig {
  const isProduction = env.NODE_ENV === 'production';
  const isBuildPhase = env.NEXT_PHASE === BUILD_PHASE;
  const isProductionRuntime = isProduction && !isBuildPhase;

  const rawBaseUrl = env.NEON_AUTH_BASE_URL?.trim();
  const rawSecret = env.NEON_AUTH_COOKIE_SECRET;

  let baseUrl: string;
  if (isProductionRuntime) {
    if (!rawBaseUrl) {
      throw new Error('NEON_AUTH_BASE_URL is required in production.');
    }
    baseUrl = validateUrl(rawBaseUrl, true);
  } else if (rawBaseUrl) {
    baseUrl = validateUrl(rawBaseUrl, false);
  } else {
    if (!isBuildPhase) {
      console.warn(
        '[auth] NEON_AUTH_BASE_URL is not set; using placeholder URL for local development. Set NEON_AUTH_BASE_URL in .env.local to enable authentication.',
      );
    }
    baseUrl = PLACEHOLDER_AUTH_URL;
  }

  let secret: string;
  if (isProductionRuntime) {
    if (!rawSecret || rawSecret.length < 32) {
      throw new Error(
        'NEON_AUTH_COOKIE_SECRET must be set and at least 32 characters long in production.',
      );
    }
    secret = rawSecret;
  } else if (isBuildPhase) {
    secret = rawSecret && rawSecret.length >= 32 ? rawSecret : generateEphemeralSecret();
  } else if (rawSecret !== undefined) {
    if (rawSecret.length < 32) {
      throw new Error('NEON_AUTH_COOKIE_SECRET must be at least 32 characters long.');
    }
    secret = rawSecret;
  } else {
    console.warn(
      '[auth] NEON_AUTH_COOKIE_SECRET is not set; generating an ephemeral development-only cookie secret. Restarting the server will invalidate existing sessions. Set NEON_AUTH_COOKIE_SECRET in .env.local for persistent local sessions.',
    );
    secret = generateEphemeralSecret();
  }

  return {
    baseUrl,
    cookies: {
      secret,
    },
  };
}

