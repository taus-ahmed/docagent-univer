import { tokenValid } from "./session-gate";
import axios, { AxiosInstance, AxiosError } from "axios";
import type { JobReview, ReasonMap, ReviewSummary, ReviewValue } from "./review";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --- Token storage ---

const TOKEN_KEY = "da_token";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}
function setToken(token: string, expiresIn: number): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(TOKEN_KEY + "_exp", String(Date.now() + expiresIn * 1000));
}
function removeToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_KEY + "_exp");
}
function isTokenValid(): boolean {
  if (typeof window === "undefined") return false;
  return tokenValid(getToken(), localStorage.getItem(TOKEN_KEY + "_exp"), Date.now());
}

// --- Types ---

export interface User {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  role: "admin" | "client" | "reviewer" | "company_admin";
  client_id: string | null;
  is_active: boolean;
  /** What this role may do (server-computed); see lib/permissions.ts. */
  permissions?: string[];
  /**
   * This account's client_id is configured as a demo tenant (backend
   * DEMO_CLIENT_IDS). Computed per response by the server, never stored, and
   * false for everyone when the variable is unset. The frontend TREATS IT AS
   * PRESENTATION ONLY -- the limits and the sample-document folder are
   * enforced in the backend, which is why hiding the panel is enough here.
   */
  is_demo?: boolean;
  /** The account still has a one-time password: nothing opens until the user
   *  chooses their own (AppLayout shows ChangePasswordForm). */
  must_change_password?: boolean;
}

/** GET /api/usage: this month's pages against the firm's limit (0 = none). */
export interface Usage {
  client_id: string;
  month: string;
  pages_used: number;
  page_limit: number;
  limit_source: "global" | "firm";
  pages_remaining: number | null;
  resets_on: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface TemplateColumn {
  name: string;
  type: "Text" | "Number" | "Date" | "Currency";
  order: number;
  extraction_type?: "header" | "lineitem";
}

export interface ColumnTemplate {
  id: number;
  name: string;
  document_type: string;
  description: string | null;
  columns: TemplateColumn[];
  is_default: boolean;
  is_shared: boolean;
  created_at: string;
  /** Phase 2a — the shape the engine derived from this template's grid.
   *  Read-only: correct it by editing cells, not by overriding it here. */
  shape?: TemplateShape | null;
}

export interface TemplateShape {
  header_rows: number[];
  label_columns: number[];
  value_columns: number[];
  repeat_bands: Array<{
    name: string;
    header_row: number;
    start_row: number;
    end_row: number;
    columns: Array<{ col: number; header: string }>;
  }>;
  field_slots: Array<{ ref: string; row_label: string }>;
  required_columns: number;
  summary?: string;
}

export interface JobStatus {
  id: number;
  // "partial" = some documents produced results and some failed. A job where
  // every document failed reports "failed", never "completed".
  status: "pending" | "processing" | "completed" | "partial" | "failed" | "cancelled";
  total_docs: number;
  successful: number;
  failed: number;
  needs_review: number;
  client_id: string;
  input_source: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  total_time_sec: number;
  output_file: string | null;
  error_message: string | null;
  user_id?: number | null;
  /** Set after a hard delete: files and results are gone, the record stays. */
  deleted_at?: string | null;
  /** Why the system ended the job (cancelled by whom, interrupted by restart). */
  status_reason?: string | null;
  progress_message?: string | null;
  schema_id: string | null;
}

export interface DocumentResult {
  id: number;
  job_id: number;
  filename: string;
  document_type: string | null;
  overall_confidence: "high" | "medium" | "low" | null;
  extracted_data: Record<string, any> | null;
  validation_errors: string;
  validation_warnings: string;
  needs_review: boolean;
  reviewed: boolean;
  reviewed_by: string | null;
  model_used: string | null;
  tokens_used: number;
  latency_ms: number;
  created_at: string;
}

export interface SchemaInfo {
  id: number;
  client_id: string;
  client_name: string;
  document_types: string[];
  created_at: string;
  updated_at: string;
}

export interface DriveAuthStatus {
  is_configured: boolean;
  is_authenticated: boolean;
}

export interface DriveFolderContents {
  folders: { id: string; name: string; path?: string }[];
  files: {
    id: string;
    name: string;
    mime_type: string;
    size: number;
    modified_time: string | null;
    is_supported: boolean;
  }[];
  total_files: number;
  supported_files: number;
}

export interface WatchFolder {
  id: number;
  folder_id: string;
  folder_name: string;
  client_id: string;
  is_active: boolean;
  last_checked: string | null;
  last_file_count: number;
  auto_upload_results: boolean;
  poll_interval_minutes: number;
  created_at: string;
}

export interface SystemStats {
  total_jobs: number;
  total_documents: number;
  total_users: number;
  documents_reviewed: number;
  documents_pending_review: number;
  high_confidence_docs: number;
  jobs_last_7_days: number;
}

/**
 * Post-extraction processing options.
 * categorize: AI assigns Category to each table row (backend, uses LLM)
 * summary:    AI generates 2-3 sentence summary (backend, uses LLM)
 * anomaly:    AI flags unusual values (backend, uses LLM)
 * graphs:     Charts rendered from extracted data (frontend only, no LLM)
 */
export type ExtractionOption = "categorize" | "summary" | "anomaly" | "graphs";

// --- Axios Instance ---

function createApi(): AxiosInstance {
  const instance = axios.create({ baseURL: BASE_URL });
  instance.interceptors.request.use(config => {
    const token = getToken();
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
  });
  instance.interceptors.response.use(
    res => res,
    (err: AxiosError) => {
      if (err.response?.status === 401) {
        removeToken();
        if (typeof window !== "undefined") window.location.href = "/login";
      }
      return Promise.reject(err);
    }
  );
  return instance;
}

const api = createApi();

// --- Auth API ---

export const authApi = {
  login: async (username: string, password: string): Promise<TokenResponse> => {
    const res = await api.post<TokenResponse>("/api/auth/login", { username, password });
    setToken(res.data.access_token, res.data.expires_in);
    return res.data;
  },
  logout: () => removeToken(),
  isAuthenticated: isTokenValid,
  getToken,
  me: async (): Promise<User> => {
    const res = await api.get<User>("/api/auth/me");
    return res.data;
  },
  changePassword: async (current_password: string, new_password: string): Promise<User> => {
    const res = await api.post<User>("/api/auth/change-password",
                                     { current_password, new_password });
    return res.data;
  },
};

// --- Schemas API ---

export const schemasApi = {
  list: async (): Promise<SchemaInfo[]> => {
    const res = await api.get<SchemaInfo[]>("/api/schemas");
    return res.data;
  },
  upload: async (file: File, clientId: string, clientName: string): Promise<SchemaInfo> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("client_id", clientId);
    fd.append("client_name", clientName);
    const res = await api.post<SchemaInfo>("/api/schemas/upload", fd);
    return res.data;
  },
  delete: async (clientId: string) => api.delete(`/api/schemas/${clientId}`),
};

// --- Demo API (sample documents; 404 for non-demo accounts) ---

export interface SampleDoc {
  filename: string;
  size_bytes: number;
}

export const demoApi = {
  listSampleDocs: async (): Promise<SampleDoc[]> => {
    const res = await api.get<{ files: SampleDoc[] }>("/api/demo/sample-docs");
    return res.data.files ?? [];
  },
  /** Download URL for one sample document, authorised like any other call. */
  downloadSampleDoc: async (filename: string): Promise<Blob> => {
    const res = await api.get(
      `/api/demo/sample-docs/${encodeURIComponent(filename)}/download`,
      { responseType: "blob" });
    return res.data as Blob;
  },
};

// --- Templates API ---

export interface ShapePreview {
  field_cells: string[];   // "row,col" keys the engine will fill as fields
  band_cells: string[];    // "row,col" keys inside a detected table band
  field_count: number;
  band_count: number;
  bands: Array<{ name: string; header_row: number; start_row: number;
                 end_row: number; columns: string[];
                 /** "rows" = records run down; "columns" = transposed. */
                 orientation?: "rows" | "columns";
                 /** true when the template declared it rather than the engine
                  *  inferring it from the layout. */
                 declared?: boolean }>;
  required_columns: number;
  summary: string;
  /** R6 — what the engine understood, and what it had to leave behind.
   *  Computed on the SERVER; the editor displays it rather than re-deriving
   *  the rule in TypeScript, which is what retiring `extractTarget` was
   *  about. `complete` is false when a label got no slot or a structure was
   *  refused. */
  coverage?: {
    labels: number;
    labels_with_slots: number;
    orphan_labels: Array<{ ref: string; label: string }>;
    orphan_count: number;
    field_slots: number;
    band_cells: number;
    skipped: string[];
    /** Things the user should look at but which do not stop a save: a band
     *  column with no heading, two declared tables overlapping. Chosen on
     *  their false-positive rate against every real template in the repo —
     *  a gate that fires on a legitimate template is the bug it replaces. */
    warnings: string[];
    /** Things the engine cannot act on: a band with NO column headings, so it
     *  would ask the model to fill columns it cannot name. Blocks the save. */
    blocking: string[];
    complete: boolean;
  };
  /** false when there is nowhere at all to put anything. */
  usable?: boolean;
  /** The engine's own refusal message when `usable` is false. */
  error?: string | null;
}

export const templatesApi = {
  /** Ask the engine which cells it will actually fill for this grid.
   *  The editor highlights exactly these, so what you see is what gets
   *  extracted — the rule has one implementation, on the server. */
  shape: async (grid: unknown): Promise<ShapePreview> => {
    const res = await api.post<ShapePreview>("/api/templates/shape", { grid });
    return res.data;
  },
  list: async (documentType?: string, q?: string): Promise<ColumnTemplate[]> => {
    const params: Record<string, string> = {};
    if (documentType) params.document_type = documentType;
    if (q) params.q = q;
    const res = await api.get<ColumnTemplate[]>("/api/templates", {
      params: Object.keys(params).length ? params : undefined,
    });
    return res.data;
  },
  get: async (id: number): Promise<ColumnTemplate> => {
    const res = await api.get<ColumnTemplate>(`/api/templates/${id}`);
    return res.data;
  },
  create: async (payload: {
    name: string;
    document_type: string;
    columns: TemplateColumn[];
    description?: string;
    is_shared?: boolean;
  }): Promise<ColumnTemplate> => {
    const res = await api.post<ColumnTemplate>("/api/templates", payload);
    return res.data;
  },
  update: async (id: number, payload: Partial<{
    name: string;
    document_type: string;
    columns: TemplateColumn[];
    description: string;
    is_shared: boolean;
  }>): Promise<ColumnTemplate> => {
    const res = await api.put<ColumnTemplate>(`/api/templates/${id}`, payload);
    return res.data;
  },
  delete: async (id: number) => api.delete(`/api/templates/${id}`),
};

// --- Extract API ---

export const extractApi = {
  /**
   * Upload files for extraction.
   *
   * options: post-extraction processing to run server-side.
   *   "categorize" - AI assigns Category to each table row using LLM
   *   "summary"    - AI generates a plain-English summary, stored in extracted_data.summary
   *   "anomaly"    - AI detects anomalies, stored in extracted_data.anomalies
   *   "graphs"     - frontend rendering only, no backend processing
   */
  upload: async (
    files: File[],
    clientId: string,
    templateId?: number,
    options: ExtractionOption[] = [],
    selectedPages?: number[],
  ): Promise<{ job_id: number; message: string; total_files: number; status: string }> => {
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    fd.append("client_id", clientId);
    if (templateId != null) fd.append("template_id", String(templateId));
    // Backend-processed options only (not "graphs" which is frontend-only)
    const backendOptions = options.filter(o => o !== "graphs");
    if (backendOptions.length > 0) fd.append("options", JSON.stringify(backendOptions));
    if (selectedPages && selectedPages.length > 0) fd.append("selected_pages", JSON.stringify(selectedPages));
    const res = await api.post("/api/extract/upload", fd);
    return res.data;
  },

  /**
   * Start extraction on one of the demo tenant's shipped sample documents.
   * Server-side this runs the SAME pipeline as `upload`, as this user.
   */
  extractSampleDoc: async (
    filename: string,
    templateId?: number,
    options: ExtractionOption[] = [],
    selectedPages?: number[],
  ): Promise<{ job_id: number; message: string; total_files: number; status: string }> => {
    const fd = new FormData();
    if (templateId != null) fd.append("template_id", String(templateId));
    const backendOptions = options.filter(o => o !== "graphs");
    if (backendOptions.length > 0) fd.append("options", JSON.stringify(backendOptions));
    if (selectedPages && selectedPages.length > 0) fd.append("selected_pages", JSON.stringify(selectedPages));
    const res = await api.post(
      `/api/demo/sample-docs/${encodeURIComponent(filename)}/extract`, fd);
    return res.data;
  },

  getPageCount: async (
    files: File[],
  ): Promise<Array<{ filename: string; page_count: number }>> => {
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    const res = await api.post("/api/extract/page-count", fd);
    return res.data;
  },

  listJobs: async (params?: {
    limit?: number;
    offset?: number;
    status_filter?: string;
  }): Promise<JobStatus[]> => {
    const res = await api.get<JobStatus[]>("/api/jobs", { params });
    return res.data;
  },

  getJob: async (jobId: number): Promise<JobStatus> => {
    const res = await api.get<JobStatus>(`/api/jobs/${jobId}`);
    return res.data;
  },

  getResults: async (
    jobId: number,
    params?: { doc_type?: string; needs_review?: boolean },
  ): Promise<DocumentResult[]> => {
    const res = await api.get<DocumentResult[]>(`/api/jobs/${jobId}/results`, { params });
    return res.data;
  },

  updateDocument: async (
    jobId: number,
    docId: number,
    extractedData: Record<string, any>,
  ) => {
    const res = await api.put(`/api/jobs/${jobId}/docs/${docId}`, {
      extracted_data: extractedData,
    });
    return res.data as { extracted_data: Record<string, any> };
  },

  /** Edit ONE field slot, addressed by its cell reference (e.g. "B7").
   *  Returns the updated document, so the caller's copy stays current. */
  editField: async (jobId: number, docId: number, ref: string, value: string) => {
    const res = await api.patch(
      `/api/jobs/${jobId}/docs/${docId}/fields/${encodeURIComponent(ref)}`,
      { value },
    );
    return res.data as { ref: string; extracted_data: Record<string, any> };
  },

  approveDocument: async (jobId: number, docId: number) => {
    const res = await api.post(`/api/jobs/${jobId}/docs/${docId}/approve`);
    return res.data;
  },

  cancelJob: async (jobId: number) => {
    const res = await api.delete(`/api/jobs/${jobId}`);
    return res.data;
  },

  /** Hard delete (the job's user, a tenant or platform admin): files, page
   *  images and results go; the job record stays, marked deleted. The server
   *  requires the explicit confirm, sent only after the user confirmed. */
  deleteJobData: async (jobId: number) => {
    const res = await api.delete(`/api/jobs/${jobId}/data`, { params: { confirm: true } });
    return res.data as { job_id: number; deleted_at: string; already_deleted: boolean;
                         files_deleted: number; results_deleted: number };
  },
};

// --- Review API ---
// The review screen: the server classifies every value (backend/app/core/
// review.py); these calls read that, page images, and write review marks.

export interface PageMeta {
  page: number;
  origin: "native" | "ocr" | "pre_ocr" | string;
  frame: string;
  width_pt: number | null;
  height_pt: number | null;
  record_box_pt: number[] | null;
  boxes: {
    kind: "field" | "cell"; ref: string | null; table: string | null;
    row: number | null; column: string | null;
    box_pt: number[] | null; match: "value" | "line" | null;
    no_box_reason: string | null;
  }[];
}

export const reviewApi = {
  reasons: async (): Promise<{ reasons: ReasonMap; statuses: ReasonMap }> => {
    const res = await api.get("/api/review/reasons");
    return res.data;
  },
  job: async (jobId: number): Promise<JobReview> => {
    const res = await api.get<JobReview>(`/api/jobs/${jobId}/review`);
    return res.data;
  },
  page: async (jobId: number, docId: number, page: number): Promise<PageMeta> => {
    const res = await api.get<PageMeta>(`/api/jobs/${jobId}/docs/${docId}/pages/${page}`);
    return res.data;
  },
  /** The page image as an object URL (the request needs the auth header, so
   *  it cannot be a plain <img src>). The caller revokes it. */
  pageImageUrl: async (jobId: number, docId: number, page: number): Promise<string> => {
    const res = await api.get(`/api/jobs/${jobId}/docs/${docId}/pages/${page}/image`,
                              { responseType: "blob" });
    return URL.createObjectURL(res.data as Blob);
  },
  mark: async (jobId: number, docId: number, body: {
    scope?: "values" | "document";
    values?: ({ ref: string } | { table: string; row: number })[];
    reviewed?: boolean;
  }) => {
    const res = await api.post(`/api/jobs/${jobId}/docs/${docId}/review`, body);
    return res.data as { summary: ReviewSummary; values: ReviewValue[]; document_reviewed: boolean };
  },
};

// --- Export API ---

export const exportApi = {
  combined: async (params: {
    job_id: number;
    template_id?: number;
    /** Keep only these columns. Omit for all of them. */
    selected_columns?: string[];
    /** These columns lead, in this order; the rest follow. */
    column_order?: string[];
    /** Keep only these document types. Omit for all of them. */
    doc_types?: string[];
    /** Keep only documents flagged for review. */
    include_needs_review_only?: boolean;
  }): Promise<Blob> => {
    const res = await api.post("/api/export/combined", params, { responseType: "blob" });
    return res.data;
  },
  perFile: async (params: {
    job_id: number;
    template_id?: number;
    selected_columns?: string[];
    doc_ids?: number[];
  }): Promise<Blob> => {
    // The route is /perfile, not /per-file. It was called with a hyphen here,
    // so every per-file download from the History page was a 404.
    const res = await api.post("/api/export/perfile", params, { responseType: "blob" });
    return res.data;
  },
  templateExport: async (jobId: number): Promise<Blob> => {
    const res = await api.get(`/api/jobs/${jobId}/export`, { responseType: "blob" });
    return res.data;
  },
  zipExport: async (jobId: number): Promise<Blob> => {
    const res = await api.get(`/api/jobs/${jobId}/export/zip`, { responseType: "blob" });
    return res.data;
  },
  downloadBlob: (blob: Blob, filename: string): void => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};

// --- Drive API ---

export const driveApi = {
  authStatus: async (): Promise<DriveAuthStatus> => {
    const res = await api.get<DriveAuthStatus>("/api/drive/auth/status");
    return res.data;
  },
  authenticate: async (): Promise<void> => {
    const res = await api.get<{ auth_url: string }>("/api/drive/auth/url");
    if (res.data.auth_url && typeof window !== "undefined") {
      window.open(res.data.auth_url, "_blank");
    }
  },
  getAuthStatus: async (): Promise<DriveAuthStatus> => {
    const res = await api.get<DriveAuthStatus>("/api/drive/auth/status");
    return res.data;
  },
  getAuthUrl: async (): Promise<{ auth_url: string }> => {
    const res = await api.get<{ auth_url: string }>("/api/drive/auth/url");
    return res.data;
  },
  handleCallback: async (code: string): Promise<{ success: boolean }> => {
    const res = await api.post<{ success: boolean }>("/api/drive/auth/callback", { code });
    return res.data;
  },
  listFolder: async (folderId?: string): Promise<DriveFolderContents> => {
    const res = await api.get<DriveFolderContents>("/api/drive/browse", {
      params: folderId ? { folder_id: folderId } : undefined,
    });
    return res.data;
  },
  extractFolder: async (
    folderId: string,
    clientId: string,
    templateId?: number,
  ): Promise<{ job_id: number }> => {
    const res = await api.post("/api/drive/extract", {
      folder_id: folderId,
      client_id: clientId,
      template_id: templateId,
    });
    return res.data;
  },
  listWatchFolders: async (): Promise<WatchFolder[]> => {
    const res = await api.get<WatchFolder[]>("/api/drive/watch");
    return res.data;
  },
  addWatchFolder: async (
    folderIdOrPayload:
      | string
      | {
          folder_id: string;
          folder_name: string;
          client_id: string;
          auto_upload_results?: boolean;
        },
    folderName?: string,
    clientId?: string,
  ): Promise<WatchFolder> => {
    const payload =
      typeof folderIdOrPayload === "object"
        ? folderIdOrPayload
        : {
            folder_id: folderIdOrPayload,
            folder_name: folderName!,
            client_id: clientId!,
          };
    const res = await api.post<WatchFolder>("/api/drive/watch", payload);
    return res.data;
  },
  removeWatchFolder: async (watchId: number) =>
    api.delete(`/api/drive/watch/${watchId}`),
};

// --- Admin API ---

export const adminApi = {
  stats: async (): Promise<SystemStats> => {
    const res = await api.get<SystemStats>("/api/admin/stats");
    return res.data;
  },
  getStats: async (): Promise<SystemStats> => {
    const res = await api.get<SystemStats>("/api/admin/stats");
    return res.data;
  },
  listUsers: async (): Promise<User[]> => {
    const res = await api.get<User[]>("/api/admin/users");
    return res.data;
  },
  createUser: async (payload: {
    username: string;
    display_name: string;
    email?: string;
    password: string;
    role: string;
    client_id?: string;
    must_change_password?: boolean;
  }): Promise<User> => {
    const res = await api.post<User>("/api/admin/users", payload);
    return res.data;
  },
  updateUser: async (
    userId: number,
    payload: Partial<{
      display_name: string;
      email: string;
      password: string;
      role: string;
      client_id: string;
      is_active: boolean;
      must_change_password: boolean;
    }>,
  ): Promise<User> => {
    const res = await api.put<User>(`/api/admin/users/${userId}`, payload);
    return res.data;
  },
  deactivateUser: async (userId: number): Promise<User> => {
    const res = await api.put<User>(`/api/admin/users/${userId}`, { is_active: false });
    return res.data;
  },
  deleteUser: async (userId: number) => api.delete(`/api/admin/users/${userId}`),
  usage: async (): Promise<Usage> => {
    const res = await api.get<Usage>("/api/usage");
    return res.data;
  },
};
