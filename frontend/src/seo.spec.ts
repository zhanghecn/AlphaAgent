import { describe, expect, it } from "vitest";
import indexHtml from "../index.html?raw";
import { getPageSeo } from "./seo";

describe("page SEO metadata", () => {
  it("returns indexable metadata for the public market overview", () => {
    const metadata = getPageSeo("/");

    expect(metadata.indexable).toBe(true);
    expect(metadata.canonicalPath).toBe("/");
    expect(metadata.title).toContain("A股量化投研");
  });

  it("keeps administrator and parameterized detail pages out of the index", () => {
    expect(getPageSeo("/login").indexable).toBe(false);
    expect(getPageSeo("/data").indexable).toBe(false);
    expect(getPageSeo("/stocks/600519.SSE").indexable).toBe(false);
  });

  it("ships a complete default metadata baseline for crawlers before JavaScript runs", () => {
    expect(indexHtml).toContain('name="description"');
    expect(indexHtml).toContain('name="robots"');
    expect(indexHtml).toContain('property="og:title"');
    expect(indexHtml).toContain('rel="manifest"');
    expect(indexHtml).toContain('application/ld+json');
  });
});
