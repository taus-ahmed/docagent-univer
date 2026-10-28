/**
 * The extract page's list of files to upload, each with its PDF password
 * (Review-3 F10).
 *
 * Passwords were kept in a map keyed by FILE NAME, apart from the list. So
 * removing a file left its password behind, and adding a file of the same
 * name again — a different file, or the same one after a mistake — brought
 * the old password back into the field and into the next upload. Each entry
 * now carries its own id and its own password: removing an entry removes
 * the password with it, a re-added file is a new entry with an empty one, and
 * `clearPasswords` wipes every password at once (after a submit, a cancel or
 * a reset).
 *
 * Passwords live in React state only — never localStorage, sessionStorage,
 * the URL or history — and the field is marked autocomplete="new-password"
 * (Chrome ignores "off" on a password field, Recheck R5).
 */

export interface PendingFile {
  id: string;
  file: File;
  password: string;
}

let seq = 0;

/** A new id, unique for this page's lifetime (not crypto: it names an entry). */
export function nextFileId(): string {
  seq += 1;
  return `file-${seq}`;
}

/** Append `accepted`, skipping a name already listed (as the page always did). */
export function addFiles(prev: PendingFile[], accepted: File[],
                         makeId: () => string = nextFileId): PendingFile[] {
  const names = new Set(prev.map(p => p.file.name));
  const added: PendingFile[] = [];
  for (const f of accepted) {
    if (names.has(f.name)) continue;
    names.add(f.name);
    added.push({ id: makeId(), file: f, password: "" });
  }
  return [...prev, ...added];
}

/** Drop one entry — and its password with it. */
export function removeFile(prev: PendingFile[], id: string): PendingFile[] {
  return prev.filter(p => p.id !== id);
}

export function setPassword(prev: PendingFile[], id: string, password: string): PendingFile[] {
  return prev.map(p => (p.id === id ? { ...p, password } : p));
}

/** Every password wiped; the files stay listed. */
export function clearPasswords(prev: PendingFile[]): PendingFile[] {
  return prev.some(p => p.password) ? prev.map(p => ({ ...p, password: "" })) : prev;
}

/** The files, in order, for the upload. */
export function filesOf(list: PendingFile[]): File[] {
  return list.map(p => p.file);
}

/** One password (or null) per file, in the same order as `filesOf`. */
export function passwordsOf(list: PendingFile[]): (string | null)[] {
  return list.map(p => p.password || null);
}
