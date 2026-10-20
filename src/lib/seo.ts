import { env } from "#/env";

export interface SeoHeadOptions {
  title?: string;
  description?: string;
  path?: string;
  baseUrl?: string;
  image?: string;
  type?: "website" | "article";
  noindex?: boolean;
  structuredData?: Record<string, unknown> | Array<Record<string, unknown>>;
}

export function getBaseUrl(explicitUrl?: string): string {
  if (explicitUrl) {
    return explicitUrl.replace(/\/+$/, "");
  }

  let serverUrl: string | undefined;

  if (typeof window !== "undefined" && window.location.origin) {
    serverUrl = window.location.origin;
  }

  if (!serverUrl) {
    try {
      serverUrl = env.SERVER_URL || env.BETTER_AUTH_URL;
    } catch {
      // Ignored on client-side access
    }
  }

  const resolved = serverUrl || "http://localhost:3000";
  return resolved.replace(/\/+$/, "");
}

export function createSeoHead(options: SeoHeadOptions) {
  const meta: Array<{
    charSet?: string;
    name?: string;
    property?: string;
    content?: string;
    title?: string;
  }> = [];

  const links: Array<{
    rel: string;
    href: string;
    as?: string;
    type?: string;
    crossOrigin?: "anonymous" | "use-credentials" | "";
  }> = [];

  const scripts: Array<{
    type?: string;
    children?: string;
  }> = [];

  if (options.title) {
    meta.push({ title: options.title });
  }

  if (options.noindex) {
    meta.push({
      name: "robots",
      content: "noindex, nofollow",
    });
  } else {
    const baseUrl = getBaseUrl(options.baseUrl);
    const path = options.path ?? "/";
    const canonicalUrl = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const imageUrl = options.image
      ? options.image.startsWith("http")
        ? options.image
        : `${baseUrl}${options.image.startsWith("/") ? options.image : `/${options.image}`}`
      : `${baseUrl}/og-image.png`;

    if (options.description) {
      meta.push({
        name: "description",
        content: options.description,
      });
    }

    if (options.title) {
      meta.push({
        property: "og:title",
        content: options.title,
      });
      meta.push({
        name: "twitter:title",
        content: options.title,
      });
    }

    if (options.description) {
      meta.push({
        property: "og:description",
        content: options.description,
      });
      meta.push({
        name: "twitter:description",
        content: options.description,
      });
    }

    meta.push({
      property: "og:url",
      content: canonicalUrl,
    });

    meta.push({
      property: "og:type",
      content: options.type ?? "website",
    });

    meta.push({
      property: "og:image",
      content: imageUrl,
    });

    meta.push({
      name: "twitter:card",
      content: "summary_large_image",
    });

    meta.push({
      name: "twitter:image",
      content: imageUrl,
    });

    links.push({
      rel: "canonical",
      href: canonicalUrl,
    });
  }

  if (options.structuredData) {
    scripts.push({
      type: "application/ld+json",
      children: JSON.stringify(options.structuredData),
    });
  }

  return {
    meta,
    links: links.length > 0 ? links : undefined,
    scripts: scripts.length > 0 ? scripts : undefined,
  };
}

export function getStructuredData(explicitBaseUrl?: string) {
  const baseUrl = getBaseUrl(explicitBaseUrl);

  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        "@id": `${baseUrl}/#website`,
        url: baseUrl,
        name: "TanStack Start Template",
        description:
          "Full-stack React template with TanStack Start, Nitro, React 19, Better Auth, Drizzle ORM, and Tailwind CSS v4.",
        publisher: {
          "@id": `${baseUrl}/#organization`,
        },
      },
      {
        "@type": "Organization",
        "@id": `${baseUrl}/#organization`,
        name: "TanStack Start Template",
        url: baseUrl,
        logo: {
          "@type": "ImageObject",
          url: `${baseUrl}/favicon.svg`,
        },
      },
      {
        "@type": "SoftwareSourceCode",
        "@id": `${baseUrl}/#software`,
        name: "TanStack Start Template",
        programmingLanguage: "TypeScript",
        runtimePlatform: "Bun / Node.js",
        codeRepository: "https://github.com/zek01svg/tanstack-start-template",
        description:
          "Production-ready template for full-stack React applications with TanStack Start, Better Auth, Drizzle ORM, and Tailwind CSS.",
      },
    ],
  };
}

export function generateRobotsTxt(explicitBaseUrl?: string): string {
  const baseUrl = getBaseUrl(explicitBaseUrl);

  return `User-agent: *
Allow: /
Disallow: /dashboard
Disallow: /settings
Disallow: /verify-otp
Disallow: /sentry-example
Disallow: /api/

Sitemap: ${baseUrl}/sitemap.xml
`;
}

export function generateSitemapXml(explicitBaseUrl?: string, paths: string[] = ["/"]): string {
  const baseUrl = getBaseUrl(explicitBaseUrl);

  const urlEntries = paths
    .map(
      path => `  <url>
    <loc>${baseUrl}${path.startsWith("/") ? path : `/${path}`}</loc>
    <changefreq>weekly</changefreq>
    <priority>${path === "/" ? "1.0" : "0.8"}</priority>
  </url>`
    )
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urlEntries}
</urlset>
`;
}
