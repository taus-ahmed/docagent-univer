import axios, { AxiosInstance, AxiosError } from "axios";

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
  const token = getToken();
  if (!token) return false;
  const exp = localStorage.getItem(TOKEN_KEY + "_exp");
  if (!exp) return true;
  return Date.now() < parseInt(exp);
}

// --- Types ---

export interface User {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  role: "admin" | "client";
  client_id: string | null;
  is_active: boolean;
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
}

export interface JobStatus {
  id: number;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
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

// --- Templates API ---

export const templatesApi = {
  list: async (documentType?: string): Promise<ColumnTemplate[]> => {
    const res = await api.get<ColumnTemplate[]>("/api/templates", {
      params: documentType ? { document_type: documentType } : undefined,
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
  ): Promise<{ job_id: number; message: string; total_files: number; status: string }> => {
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    fd.append("client_id", clientId);
    if (templateId != null) fd.append("template_id", String(templateId));
    // Backend-processed options only (not "graphs" which is frontend-only)
    const backendOptions = options.filter(o => o !== "graphs");
    if (backendOptions.length > 0) fd.append("options", JSON.stringify(backendOptions));
    const res = await api.post("/api/extract/upload", fd);
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
    return res.data;
  },

  approveDocument: async (jobId: number, docId: number) => {
    const res = await api.post(`/api/jobs/${jobId}/docs/${docId}/approve`);
    return res.data;
  },

  cancelJob: async (jobId: number) => {
    const res = await api.delete(`/api/jobs/${jobId}`);
    return res.data;
  },
};

// --- Export API ---

export const exportApi = {
  combined: async (params: {
    job_id: number;
    template_id?: number;
    include_line_items?: boolean;
  }): Promise<Blob> => {
    const res = await api.post("/api/export/combined", params, { responseType: "blob" });
    return res.data;
  },
  perFile: async (params: { job_id: number; template_id?: number }): Promise<Blob> => {
    const res = await api.post("/api/export/per-file", params, { responseType: "blob" });
    return res.data;
  },
  templateExport: async (jobId: number): Promise<Blob> => {
    const res = await api.get(`/api/jobs/${jobId}/export`, { responseType: "blob" });
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
};
