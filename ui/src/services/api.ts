import axios from 'axios';

const API_BASE = ''; // Same origin or relative path

export const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Mutex lock for concurrent 401 refresh requests
let isRefreshing = false;
let failedQueue: Array<{ resolve: (token: string) => void; reject: (err: any) => void }> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else if (token) {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

// Request Interceptor: Attach Access Token
apiClient.interceptors.request.use(
  config => {
    const token = localStorage.getItem('mcp_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  error => Promise.reject(error)
);

// Response Interceptor: Handle 401 Refresh Mutex Queue
apiClient.interceptors.response.use(
  response => response,
  async error => {
    const originalRequest = error.config;
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (originalRequest.url?.includes('/auth/signin') || originalRequest.url?.includes('/auth/signup')) {
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(token => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return apiClient(originalRequest);
          })
          .catch(err => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem('mcp_refresh_token');
      if (!refreshToken) {
        isRefreshing = false;
        localStorage.removeItem('mcp_token');
        return Promise.reject(error);
      }

      try {
        const res = await axios.post('/auth/refresh', { refresh_token: refreshToken });
        const newToken = res.data.access_token;
        localStorage.setItem('mcp_token', newToken);
        apiClient.defaults.headers.common['Authorization'] = `Bearer ${newToken}`;
        processQueue(null, newToken);
        return apiClient(originalRequest);
      } catch (refreshErr) {
        processQueue(refreshErr, null);
        localStorage.removeItem('mcp_token');
        localStorage.removeItem('mcp_refresh_token');
        window.location.href = '/';
        return Promise.reject(refreshErr);
      } finally {
        isRefreshing = false;
      }
    }
    return Promise.reject(error);
  }
);

// --- Complete Endpoint API Wrappers ---
export const api = {
  // Auth
  signin: (data: any) => apiClient.post('/auth/signin', data),
  signup: (data: any) => apiClient.post('/auth/signup', data),
  refresh: (refreshToken: string) => apiClient.post('/auth/refresh', { refresh_token: refreshToken }),
  whoami: () => apiClient.get('/whoami'),

  // System
  getHealth: () => apiClient.get('/healthz'),
  getReady: () => apiClient.get('/readyz'),
  getStatus: () => apiClient.get('/status'),
  getMetrics: () => apiClient.get('/metrics'),
  getLogs: (category?: string) => apiClient.get(category ? `/admin/logs/${category}` : '/admin/logs'),

  // Tools & Execution
  getToolsCatalog: () => apiClient.get('/tools'),
  callTool: (name: string, payload: any) => apiClient.post(`/tools/${name}/call`, payload),

  // Tool Onboarding & Lifecycle
  onboardTool: (data: any) => apiClient.post('/admin/tools/onboard', data),
  acceptProposal: (data: any) => apiClient.post('/admin/tools/onboard/accept_proposal', data),
  validateSource: (data: any) => apiClient.post('/admin/tools/validate_source', data),
  revertTool: (name: string) => apiClient.post(`/admin/tools/${name}/revert`),
  autoPatchTool: (name: string, data?: any) => apiClient.post(`/admin/tools/${name}/auto_patch`, data),
  reloadTool: (name: string) => apiClient.post(`/admin/reload/${name}`),
  enableTool: (name: string) => apiClient.post(`/admin/tool/${name}/enable`),
  disableTool: (name: string) => apiClient.post(`/admin/tool/${name}/disable`),

  // Pending Approvals
  getPendingTools: () => apiClient.get('/admin/tools/pending'),
  getPendingToolDetail: (name: string) => apiClient.get(`/admin/tools/pending/${name}`),
  approvePendingTool: (name: string) => apiClient.post(`/admin/tools/pending/${name}/approve`),
  rejectPendingTool: (name: string) => apiClient.post(`/admin/tools/pending/${name}/reject`),

  // OpenAPI Specs Vault
  registerOpenAPISpec: (data: any) => apiClient.post('/admin/openapi/register', data),
  getOpenAPISpecs: () => apiClient.get('/admin/openapi/specs'),
  removeOpenAPISpec: (collectionId: string) => apiClient.post(`/admin/openapi/${collectionId}/remove`),

  // Federation / Upstream Servers
  getUpstreams: () => apiClient.get('/mcp/upstreams'),
  getUpstreamTools: (server: string) => apiClient.get(`/mcp/upstreams/${server}/tools`),
  callUpstreamTool: (server: string, name: string, payload: any) => apiClient.post(`/mcp/upstreams/${server}/tools/${name}/call`, payload),
  addUpstream: (data: any) => apiClient.post('/admin/mcp/upstreams', data),
  removeUpstream: (server: string) => apiClient.post(`/admin/mcp/upstreams/${server}/remove`),

  // Multi-Tenancy & RBAC
  getOrgs: () => apiClient.get('/admin/orgs'),
  createOrg: (data: any) => apiClient.post('/admin/orgs', data),
  deleteOrg: (org: string) => apiClient.delete(`/admin/orgs/${org}`),
  getWorkspaces: (org: string) => apiClient.get(`/admin/orgs/${org}/workspaces`),
  createWorkspace: (org: string, data: any) => apiClient.post(`/admin/orgs/${org}/workspaces`, data),
  getMembers: (org: string) => apiClient.get(`/admin/orgs/${org}/members`),
  bindMember: (org: string, data: any) => apiClient.post(`/admin/orgs/${org}/members`, data),
  getToolGrants: (org: string) => apiClient.get(`/admin/orgs/${org}/tool-grants`),
  addToolGrant: (org: string, data: any) => apiClient.post(`/admin/orgs/${org}/tool-grants`, data),

  // Analytics & Chaos
  getAnalyticsSummary: () => apiClient.get('/admin/analytics/summary'),
  getToolTimeseries: (name: string) => apiClient.get(`/admin/analytics/tools/${name}/timeseries`),
  getLeaderboard: () => apiClient.get('/admin/analytics/leaderboard'),
  getChaosStatus: () => apiClient.get('/admin/chaos'),
  enableChaos: () => apiClient.post('/admin/chaos/enable'),
  disableChaos: () => apiClient.post('/admin/chaos/disable'),
  configureChaosRules: (data: any) => apiClient.post('/admin/chaos/rules', data),

  // Prompts
  getPrompts: () => apiClient.get('/admin/prompts'),
  registerPrompt: (data: any) => apiClient.post('/admin/prompts', data),
  getPromptVariant: (name: string) => apiClient.get(`/admin/prompts/${name}/variant`),
};
