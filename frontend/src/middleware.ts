import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Public routes that do not require authentication
const PUBLIC_PATHS = [
  '/login',
  '/register',
  '/forgot-password',
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 1. Skip Next.js internal assets, static files, and auth API route handler
  if (
    pathname.startsWith('/_next') ||
    pathname.startsWith('/api/auth') ||
    pathname.includes('/favicon.ico') ||
    pathname.includes('.') // static files with extensions
  ) {
    return NextResponse.next();
  }

  // 2. Check for Neon Auth / Better Auth session token in cookies
  // Neon Auth uses '__Secure-neon-auth.session_token' / '__Secure-neon-auth.session_data'
  const allCookies = request.cookies.getAll();
  const hasSessionToken = allCookies.some(
    (c) =>
      c.value &&
      c.value.trim().length > 0 &&
      (c.name.includes('neon-auth.session') ||
       c.name.includes('better-auth.session_token') ||
       c.name === 'session_token')
  );

  const isPublicPath = PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(path + '/'));

  // 3. If user is unauthenticated and attempting to visit a protected route -> redirect to /login
  if (!hasSessionToken && !isPublicPath) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('callbackUrl', pathname);
    return NextResponse.redirect(loginUrl);
  }

  // 4. If user is already authenticated and visits login/register -> redirect to dashboard /
  if (hasSessionToken && isPublicPath) {
    return NextResponse.redirect(new URL('/', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
