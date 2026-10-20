import { test, expect } from "@playwright/test";

test.describe("SEO and Metadata", () => {
  test("landing page has comprehensive SEO, OpenGraph, Twitter, and JSON-LD structured data", async ({
    page,
  }) => {
    await page.goto("/");

    // Title & Description
    await expect(page).toHaveTitle(/TanStack Start Template/i);
    const description = page.locator('meta[name="description"]');
    await expect(description).toHaveAttribute("content", /Full-stack React template/i);

    // Canonical link
    const canonical = page.locator('link[rel="canonical"]');
    await expect(canonical).toHaveAttribute("href", /http/);

    // OpenGraph meta
    const ogTitle = page.locator('meta[property="og:title"]');
    await expect(ogTitle).toHaveAttribute("content", /TanStack Start Template/i);

    const ogDescription = page.locator('meta[property="og:description"]');
    await expect(ogDescription).toHaveAttribute("content", /Full-stack React template/i);

    const ogType = page.locator('meta[property="og:type"]');
    await expect(ogType).toHaveAttribute("content", "website");

    const ogImage = page.locator('meta[property="og:image"]');
    await expect(ogImage).toHaveAttribute("content", /og-image\.png/);

    // Twitter card
    const twitterCard = page.locator('meta[name="twitter:card"]');
    await expect(twitterCard).toHaveAttribute("content", "summary_large_image");

    const twitterTitle = page.locator('meta[name="twitter:title"]');
    await expect(twitterTitle).toHaveAttribute("content", /TanStack Start Template/i);

    // Favicon & Icons & Theme color
    const themeColor = page.locator('meta[name="theme-color"]');
    await expect(themeColor).toHaveAttribute("content", "#09090b");

    const faviconIco = page.locator('link[rel="icon"][href="/favicon.ico"]');
    await expect(faviconIco).toBeAttached();

    const faviconSvg = page.locator('link[rel="icon"][href="/favicon.svg"]');
    await expect(faviconSvg).toBeAttached();

    const appleTouchIcon = page.locator('link[rel="apple-touch-icon"]');
    await expect(appleTouchIcon).toHaveAttribute("href", "/apple-touch-icon.png");

    const manifest = page.locator('link[rel="manifest"]');
    await expect(manifest).toHaveAttribute("href", "/site.webmanifest");

    // JSON-LD Structured Data
    const jsonLdScript = page.locator('script[type="application/ld+json"]');
    await expect(jsonLdScript).toBeAttached();

    // A `<script>` has no rendered text, so web-first text assertions see an empty string;
    // read `textContent` and assert on the value instead.
    const jsonLdContent = await jsonLdScript.textContent();
    expect(jsonLdContent).toContain("schema.org");

    const parsed = JSON.parse(jsonLdContent ?? "") as {
      "@context": string;
      "@graph": Array<{ "@type": string }>;
    };
    expect(parsed["@context"]).toBe("https://schema.org");
    expect(parsed["@graph"]).toBeInstanceOf(Array);
    const types = parsed["@graph"].map((item: { "@type": string }) => item["@type"]);
    expect(types).toContain("WebSite");
    expect(types).toContain("Organization");
    expect(types).toContain("SoftwareSourceCode");
  });

  test("login route contains noindex directive and title", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow"
    );
    await expect(page).toHaveTitle(/Sign In/i);
  });

  test("signup route contains noindex directive and title", async ({ page }) => {
    await page.goto("/signup");
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow"
    );
    await expect(page).toHaveTitle(/Sign Up/i);
  });

  test("reset-password route contains noindex directive and title", async ({ page }) => {
    await page.goto("/reset-password");
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow"
    );
    await expect(page).toHaveTitle(/Reset Password/i);
  });

  test("verify-otp route contains noindex directive and title", async ({ page }) => {
    await page.goto("/verify-otp?email=test%40example.com&flow=sign-in");
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow"
    );
    await expect(page).toHaveTitle(/Verify Code/i);
  });

  test("404 error page includes noindex directive", async ({ page }) => {
    await page.goto("/non-existent-page-url");
    await expect(page.getByText("404 - Not Found")).toBeVisible();
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow"
    );
  });

  test("robots.txt endpoint returns valid crawler rules and sitemap reference", async ({
    request,
  }) => {
    const response = await request.get("/robots.txt");
    expect(response.status()).toBe(200);
    const contentType = response.headers()["content-type"];
    expect(contentType).toContain("text/plain");

    const text = await response.text();
    expect(text).toContain("User-agent: *");
    expect(text).toContain("Allow: /");
    expect(text).toContain("Disallow: /dashboard");
    expect(text).toContain("Disallow: /settings");
    expect(text).toContain("Disallow: /verify-otp");
    expect(text).toContain("Disallow: /sentry-example");
    expect(text).toContain("Disallow: /api/");
    expect(text).toContain("Sitemap:");
    expect(text).toContain("/sitemap.xml");
  });

  test("sitemap.xml endpoint returns valid XML urlset", async ({ request }) => {
    const response = await request.get("/sitemap.xml");
    expect(response.status()).toBe(200);
    const contentType = response.headers()["content-type"];
    expect(contentType).toMatch(/xml/);

    const xml = await response.text();
    expect(xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml).toContain("<loc>");
    expect(xml).toContain("</loc>");
    expect(xml).toContain("</urlset>");
  });
});
