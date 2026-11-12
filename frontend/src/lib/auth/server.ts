import { createNeonAuth } from '@neondatabase/auth/next/server';
import { resolveNeonAuthConfig } from './config';

export { resolveNeonAuthConfig, type ResolvedNeonAuthConfig } from './config';

export const auth = createNeonAuth(resolveNeonAuthConfig());
