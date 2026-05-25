import { Catalog } from "@/lib/api/endpoints";
import { HomeView } from "./home-view";

export const revalidate = 60;

export default async function HomePage() {
  const fetched = await Catalog.courses({
    page: 1,
    page_size: 6,
    sort: "-published_at",
  }).catch(() => null);
  const featured = fetched ?? { items: [], total: 0, page: 1, page_size: 6 };
  return <HomeView featured={featured} />;
}
