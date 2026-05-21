import type { Metadata } from "next";
import { Courses } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { CourseDetailView } from "./course-detail-view";

type RouteParams = { slug: string };

export const revalidate = 60;

export async function generateMetadata(
  { params }: { params: Promise<RouteParams> },
): Promise<Metadata> {
  const { slug } = await params;
  try {
    const course = await Courses.get(slug);
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
