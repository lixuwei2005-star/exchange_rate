import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Cheap pre-check: redirect to /admin/login if no admin_session cookie is
 * present on /admin/* (other than /admin/login itself). The backend still
 * verifies the JWT on every /api/admin/* call — this is just to avoid
 * rendering an empty admin shell when obviously logged out.
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (pathname.startsWith("/admin/login")) return NextResponse.next();
  if (!pathname.startsWith("/admin")) return NextResponse.next();

  const hasCookie = req.cookies.has("admin_session");
  if (!hasCookie) {
    const url = req.nextUrl.clone();
    url.pathname = "/admin/login";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/admin/:path*"],
};
