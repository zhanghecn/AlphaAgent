export type PageSeo = {
  title: string;
  description: string;
  keywords: string;
  canonicalPath: string;
  indexable: boolean;
};

const defaultKeywords = "A股量化投研,A股行情,市场分析,板块主线,短线复盘,连板梯队";

export const DEFAULT_PAGE_SEO: PageSeo = {
  title: "AlphaAgent - A股量化投研与市场分析平台",
  description:
    "AlphaAgent 提供 A 股行情、板块主线、短线复盘、连板梯队与个股研究工具，帮助投资者更高效地开展量化投研。",
  keywords: defaultKeywords,
  canonicalPath: "/",
  indexable: true,
};

const indexablePages: Record<string, PageSeo> = {
  "/": DEFAULT_PAGE_SEO,
  "/stocks": {
    title: "A股股票行情与个股研究 | AlphaAgent",
    description: "浏览 A 股股票行情与个股研究信息，快速定位市场关注标的并开展后续投研分析。",
    keywords: "A股股票行情,个股研究,股票分析," + defaultKeywords,
    canonicalPath: "/stocks",
    indexable: true,
  },
  "/market": {
    title: "A股市场时机与择时分析 | AlphaAgent",
    description: "结合市场状态、资金情绪与量化指标观察 A 股市场时机，为投研决策提供结构化参考。",
    keywords: "A股择时,市场情绪,市场分析," + defaultKeywords,
    canonicalPath: "/market",
    indexable: true,
  },
  "/mainline": {
    title: "A股主线与板块轮动复盘 | AlphaAgent",
    description: "追踪 A 股市场主线、板块热度与资金流向，辅助识别题材轮动和阶段性强势方向。",
    keywords: "A股主线,板块轮动,题材复盘,资金流向," + defaultKeywords,
    canonicalPath: "/mainline",
    indexable: true,
  },
  "/short-term": {
    title: "A股短线研究与强势股复盘 | AlphaAgent",
    description: "聚合 A 股短线信号、强势股表现与复盘数据，支持短线研究和市场节奏观察。",
    keywords: "A股短线,强势股,短线复盘," + defaultKeywords,
    canonicalPath: "/short-term",
    indexable: true,
  },
  "/lianban": {
    title: "A股连板梯队与涨停复盘 | AlphaAgent",
    description: "查看 A 股连板梯队、涨停表现与晋级结构，系统化复盘短线情绪和强势股演变。",
    keywords: "A股连板,涨停复盘,连板梯队,短线情绪," + defaultKeywords,
    canonicalPath: "/lianban",
    indexable: true,
  },
  "/lianban/ladder": {
    title: "A股连板梯队历史数据 | AlphaAgent",
    description: "回顾 A 股连板梯队历史表现，分析强势股晋级、断板与市场情绪变化。",
    keywords: "连板梯队历史,A股涨停数据,强势股晋级," + defaultKeywords,
    canonicalPath: "/lianban/ladder",
    indexable: true,
  },
  "/sectors": {
    title: "A股行业板块与概念分析 | AlphaAgent",
    description: "浏览 A 股行业板块、概念题材及关联个股信息，辅助研究板块强弱与产业链关系。",
    keywords: "A股行业板块,A股概念板块,产业链分析," + defaultKeywords,
    canonicalPath: "/sectors",
    indexable: true,
  },
};

function normalizePath(pathname: string): string {
  const path = pathname.startsWith("/") ? pathname : `/${pathname}`;
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

function matchesPathPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function noIndexPage(pathname: string): PageSeo {
  return {
    ...DEFAULT_PAGE_SEO,
    canonicalPath: pathname,
    indexable: false,
  };
}

/**
 * 仅稳定且匿名可访问的栏目页允许收录。管理入口和参数化详情页依赖实时数据，
 * 不纳入索引，避免产生大量内容稀薄或重复的搜索结果。
 */
export function getPageSeo(pathname: string): PageSeo {
  const normalizedPath = normalizePath(pathname);
  const staticPage = indexablePages[normalizedPath];
  if (staticPage) return staticPage;

  if (
    matchesPathPrefix(normalizedPath, "/login")
    || matchesPathPrefix(normalizedPath, "/data")
    || matchesPathPrefix(normalizedPath, "/data-sync")
    || matchesPathPrefix(normalizedPath, "/stocks")
    || matchesPathPrefix(normalizedPath, "/indices")
    || matchesPathPrefix(normalizedPath, "/explore")
    || matchesPathPrefix(normalizedPath, "/chain")
  ) {
    return noIndexPage(normalizedPath);
  }

  return noIndexPage("/");
}

export function robotsDirective(indexable: boolean): string {
  return indexable
    ? "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"
    : "noindex,nofollow,noarchive";
}
