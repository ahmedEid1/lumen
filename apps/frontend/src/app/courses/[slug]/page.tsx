import type { Metadata } from "next";
import { cookies } from "next/headers";
import { api, ApiError } from "@/lib/api/client";
import type { CourseDetail } from "@/lib/api/types";
import { CourseDetailView } from "./course-detail-view";

type RouteParams = { slug: string };

// generateMetadata reads the viewer's auth cookies (see below), so this route
// renders dynamically per-request — it cannot be statically cached / ISR'd.
// We therefore do NOT set `export const revalidate`; reading cookies() opts the
// route into dynamic rendering regardless, and a stale `revalidate` would only
// mislead. The client CourseDetailView still fetches its own data on the
// browser (carrying the same cookies via the same-origin rewrite).

export async function generateMetadata(
  { params }: { params: Promise<RouteParams> },
): Promise<Metadata> {
  const { slug } = await params;
  try {
    // Forward the incoming request cookies to the SSR fetch so the metadata
    // layer sees the same authorization as the owner's browser. Without this
    // the server-to-server fetch is anonymous and a PRIVATE course 404s here,
    // producing a "Course not found" tab title for an owner who can otherwise
    // see the page body (W11 F4). If the API rejects (private course viewed by
    // a non-owner) or the viewer is anonymous, we fall through to the existing
    // not-found / generic fallbacks.
    const cookieHeader = (await cookies()).toString();
    const course = await api<CourseDetail>(
      `/api/v1/courses/${encodeURIComponent(slug)}`,
      cookieHeader ? { headers: { Cookie: cookieHeader } } : {},
    );
    const description =
      course.overview && course.overview.length > 0
        ? course.overview.slice(0, 280)
        : `${course.title} on Lumen.`;
    const image = course.cover_url ?? undefined;
    return {
      title: course.title,
      description,
      openGraph: {
        title: course.title,
        description,
        type: "article",
        images: image ? [{ url: image }] : undefined,
        siteName: "Lumen",
      },
      twitter: {
        card: image ? "summary_large_image" : "summary",
        title: course.title,
        description,
        images: image ? [image] : undefined,
      },
      alternates: { canonical: `/courses/${course.slug}` },
    };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return { title: "Course not found" };
    }
    return { title: "Course" };
  }
}

export default async function Page({
  params,
}: {
  params: Promise<RouteParams>;
}) {
  const { slug } = await params;
  return <CourseDetailView slug={slug} />;
}
