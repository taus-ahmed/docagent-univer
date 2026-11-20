/**
 * Overnight E2 — moving between the pages of a multi-page document in the
 * review dialog.
 *
 * mammoth_2pg has two pages; the dialog listed only the pages that held a
 * value, so with page 2's rows lost it showed "p.1" alone and the page the
 * reviewer had to check could not be reached. The page list is every page the
 * document has (the server's list, widened to the page count the page
 * endpoint reports), and previous / next step through it.
 */

export interface PageNav {
  pages: number[];
  index: number;          // position of the current page in `pages`
  prev: number | null;
  next: number | null;
  label: string;          // "Page 2 of 2"
}

export function pageList(docPages: number[], pageCount?: number | null): number[] {
  const s = new Set<number>(docPages.filter(p => Number.isInteger(p) && p >= 1));
  if (pageCount && pageCount >= 1) for (let p = 1; p <= pageCount; p++) s.add(p);
  if (!s.size) s.add(1);
  return [...s].sort((a, b) => a - b);
}

export function pageNav(docPages: number[], current: number, pageCount?: number | null): PageNav {
  const pages = pageList(docPages, pageCount);
  let index = pages.indexOf(current);
  if (index < 0) index = 0;
  return {
    pages,
    index,
    prev: index > 0 ? pages[index - 1] : null,
    next: index < pages.length - 1 ? pages[index + 1] : null,
    label: `Page ${pages[index]} of ${pages[pages.length - 1]}`,
  };
}

/** The slot list follows the page: the first value printed on `page`, or -1. */
export function firstValueOn(values: { page?: number | null }[], page: number): number {
  return values.findIndex(v => v.page === page);
}
