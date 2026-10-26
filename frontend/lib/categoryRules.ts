// Category rules as the template editor shows them (Part A2): one rule per
// line, "Category: keyword, another phrase, /regex/". The server's matcher is
// engine/categorize.py; this only reads and writes the text form.

export type CategoryRule = { category: string; keywords?: string[]; regex?: string[] };

export function parseRules(text: string): { rules: CategoryRule[]; problems: string[] } {
  const rules: CategoryRule[] = [];
  const problems: string[] = [];
  (text || "").split(/\r?\n/).forEach((line, i) => {
    const t = line.trim();
    if (!t) return;
    const at = t.indexOf(":");
    if (at <= 0) { problems.push(`line ${i + 1}: write it as "Category: keyword, keyword"`); return; }
    const category = t.slice(0, at).trim();
    const keywords: string[] = [], regex: string[] = [];
    let bad = false;
    for (const raw of t.slice(at + 1).split(",")) {
      const k = raw.trim();
      if (!k) continue;
      if (k.length > 2 && k.startsWith("/") && k.endsWith("/")) {
        const body = k.slice(1, -1);
        try { new RegExp(body); regex.push(body); }
        catch { bad = true; problems.push(`line ${i + 1}: the pattern ${k} is not valid`); }
      } else keywords.push(k);
    }
    if (!keywords.length && !regex.length) { if (bad) return; problems.push(`line ${i + 1}: add at least one keyword for ${category}`); return; }
    rules.push({ category, keywords, ...(regex.length ? { regex } : {}) });
  });
  return { rules, problems };
}

export function formatRules(rules: CategoryRule[]): string {
  return (rules || []).map(r =>
    `${r.category}: ${[...(r.keywords || []), ...(r.regex || []).map(x => `/${x}/`)].join(", ")}`).join("\n");
}
