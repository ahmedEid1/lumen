import { Catalog } from "@/lib/api/endpoints";
import { HomeView } from "./home-view";

export const revalidate = 60;

const HOME_GRID_SIZE = 6;

export default async function HomePage() {
  // Curated (is_featured) courses lead the grid, so whatever was published
  // last never takes the top slot. A fresh install with nothing featured
  // falls back to the newest listed courses.
  const params = { page: 1, page_size: HOME_GRID_SIZE, sort: "-published_at" };
  const featured = await Catalog.courses({ ...params, featured: true }).catch(() => null);
  const fetched =
    featured && featured.items.length > 0
      ? featured
      : await Catalog.courses(params).catch(() => null);
  const courses = fetched ?? { items: [], total: 0, page: 1, page_size: HOME_GRID_SIZE };
  return <HomeView featured={courses} />;
}
