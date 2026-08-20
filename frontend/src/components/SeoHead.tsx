import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { getPageSeo, robotsDirective } from "@/seo";

function setNamedMeta(name: string, content: string): void {
  let element = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (!element) {
    element = document.createElement("meta");
    element.name = name;
    document.head.append(element);
  }
  element.content = content;
}

function setPropertyMeta(property: string, content: string): void {
  let element = document.head.querySelector<HTMLMetaElement>(`meta[property="${property}"]`);
  if (!element) {
    element = document.createElement("meta");
    element.setAttribute("property", property);
    document.head.append(element);
  }
  element.content = content;
}

function setCanonical(url: string): void {
  let element = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!element) {
    element = document.createElement("link");
    element.rel = "canonical";
    document.head.append(element);
  }
  element.href = url;
}

type SeoHeadProps = {
  forceNoIndex?: boolean;
};

/** Synchronizes crawl and share metadata with the current client-side route. */
export function SeoHead({ forceNoIndex = false }: SeoHeadProps) {
  const { pathname } = useLocation();

  useEffect(() => {
    const metadata = getPageSeo(pathname);
    const canonicalUrl = new URL(metadata.canonicalPath, window.location.origin).toString();
    const indexable = metadata.indexable && !forceNoIndex;

    document.title = metadata.title;
    setNamedMeta("description", metadata.description);
    setNamedMeta("keywords", metadata.keywords);
    setNamedMeta("robots", robotsDirective(indexable));
    setNamedMeta("twitter:title", metadata.title);
    setNamedMeta("twitter:description", metadata.description);
    setPropertyMeta("og:title", metadata.title);
    setPropertyMeta("og:description", metadata.description);
    setPropertyMeta("og:url", canonicalUrl);
    setCanonical(canonicalUrl);
  }, [forceNoIndex, pathname]);

  return null;
}
