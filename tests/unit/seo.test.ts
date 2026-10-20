import { describe, expect, it } from "vitest";
import {
  getBaseUrl,
  createSeoHead,
  getStructuredData,
  generateRobotsTxt,
  generateSitemapXml,
} from "#/lib/seo";

describe("SEO utilities", () => {
  describe("getBaseUrl", () => {
    it("returns a normalized URL without trailing slash", () => {
      const url = getBaseUrl("https://example.com/");
      expect(url).toBe("https://example.com");
    });

    it("handles URLs without trailing slash", () => {
      const url = getBaseUrl("https://example.com");
      expect(url).toBe("https://example.com");
    });

    it("falls back to localhost:3000 if not provided", () => {
      const url = getBaseUrl(undefined);
      expect(url).toBe("http://localhost:3000");
    });
  });

  describe("createSeoHead", () => {
    it("creates full metadata for public pages", () => {
      const head = createSeoHead({
        title: "Test Page — TanStack Start Template",
        description: "A test page description",
        path: "/",
        baseUrl: "https://example.com",
      });

      expect(head.meta).toEqual(
        expect.arrayContaining([
          { title: "Test Page — TanStack Start Template" },
          { name: "description", content: "A test page description" },
          { property: "og:title", content: "Test Page — TanStack Start Template" },
          { property: "og:description", content: "A test page description" },
          { property: "og:url", content: "https://example.com/" },
          { property: "og:type", content: "website" },
          { property: "og:image", content: "https://example.com/og-image.png" },
          { name: "twitter:card", content: "summary_large_image" },
          { name: "twitter:title", content: "Test Page — TanStack Start Template" },
          { name: "twitter:description", content: "A test page description" },
          { name: "twitter:image", content: "https://example.com/og-image.png" },
        ])
      );

      expect(head.links).toEqual(
        expect.arrayContaining([{ rel: "canonical", href: "https://example.com/" }])
      );
    });

    it("creates noindex metadata for private pages", () => {
      const head = createSeoHead({
        title: "Dashboard — TanStack Start Template",
        noindex: true,
      });

      expect(head.meta).toEqual(
        expect.arrayContaining([
          { title: "Dashboard — TanStack Start Template" },
          { name: "robots", content: "noindex, nofollow" },
        ])
      );

      expect(head.links).toBeUndefined();
    });

    it("includes JSON-LD script when structuredData is provided", () => {
      const sampleLd = { "@context": "https://schema.org", "@type": "WebSite", name: "Test" };
      const head = createSeoHead({
        title: "Home",
        structuredData: sampleLd,
      });

      expect(head.scripts).toEqual([
        {
          type: "application/ld+json",
          children: JSON.stringify(sampleLd),
        },
      ]);
    });
  });

  describe("getStructuredData", () => {
    it("generates Schema.org graph structured data", () => {
      const data = getStructuredData("https://example.com");
      expect(data).toHaveProperty("@context", "https://schema.org");
      expect(data).toHaveProperty("@graph");
      expect(Array.isArray(data["@graph"])).toBe(true);

      const types = (data["@graph"] as Array<{ "@type": string }>).map(item => item["@type"]);
      expect(types).toContain("WebSite");
      expect(types).toContain("Organization");
      expect(types).toContain("SoftwareSourceCode");
    });
  });

  describe("generateRobotsTxt", () => {
    it("generates valid robots.txt with disallow rules and sitemap", () => {
      const robots = generateRobotsTxt("https://example.com");
      expect(robots).toContain("User-agent: *");
      expect(robots).toContain("Allow: /");
      expect(robots).toContain("Disallow: /dashboard");
      expect(robots).toContain("Disallow: /settings");
      expect(robots).toContain("Disallow: /verify-otp");
      expect(robots).toContain("Disallow: /sentry-example");
      expect(robots).toContain("Disallow: /api/");
      expect(robots).toContain("Sitemap: https://example.com/sitemap.xml");
    });
  });

  describe("generateSitemapXml", () => {
    it("generates valid XML sitemap with provided urls", () => {
      const xml = generateSitemapXml("https://example.com", ["/"]);
      expect(xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
      expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
      expect(xml).toContain("<loc>https://example.com/</loc>");
      expect(xml).toContain("<changefreq>weekly</changefreq>");
      expect(xml).toContain("<priority>1.0</priority>");
      expect(xml).toContain("</urlset>");
    });
  });
});
