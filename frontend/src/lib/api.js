import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const api = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 180000, // 3 minutes for long-running screener requests
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      if (window.location.pathname !== '/login' && window.location.pathname !== '/') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;

// API helper functions
export const stocksApi = {
  getQuote: (symbol) => api.get(`/stocks/quote/${symbol}`),
  getDetails: (symbol) => api.get(`/stocks/details/${symbol}`),
  getIndices: () => api.get('/stocks/indices'),
  getHistorical: (symbol, params) => api.get(`/stocks/historical/${symbol}`, { params }),
  search: (query) => api.get('/stocks/search', { params: { query } }),
};

export const optionsApi = {
  getChain: (symbol, expiry) => api.get(`/options/chain/${symbol}`, { params: { expiry } }),
  getExpirations: (symbol) => api.get(`/options/expirations/${symbol}`),
};

export const screenerApi = {
  getCoveredCalls: (params) => api.get('/screener/covered-calls', { params }),
  getDashboardOpportunities: () => api.get('/screener/dashboard-opportunities'),
  getDashboardPMCC: () => api.get('/screener/dashboard-pmcc'),
  getPMCC: (params) => api.get('/screener/pmcc', { params }),
  getFilters: () => api.get('/screener/filters'),
  saveFilter: (data) => api.post('/screener/filters', data),
  deleteFilter: (id) => api.delete(`/screener/filters/${id}`),
  clearCache: () => api.post('/screener/clear-cache'),
};

export const portfolioApi = {
  getPositions: () => api.get('/portfolio/positions'),
  addPosition: (data) => api.post('/portfolio/positions', data),
  updatePosition: (id, data) => api.put(`/portfolio/positions/${id}`, data),
  deletePosition: (id) => api.delete(`/portfolio/positions/${id}`),
  importCSV: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/portfolio/import-csv', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  },
  getSummary: () => api.get('/portfolio/summary'),
  
  // Manual trade entry
  addManualTrade: (data) => api.post('/portfolio/manual-trade', data),
  updateManualTrade: (id, data) => api.put(`/portfolio/manual-trade/${id}`, data),
  deleteManualTrade: (id) => api.delete(`/portfolio/manual-trade/${id}`),
  closeTrade: (id, closePrice) => api.put(`/portfolio/trade/${id}/close?close_price=${closePrice}`),
  
  // IBKR Import APIs
  importIBKR: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/portfolio/import-ibkr', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  },
  getIBKRAccounts: () => api.get('/portfolio/ibkr/accounts'),
  getIBKRTrades: (params = {}) => {
    const queryParams = new URLSearchParams();
    if (params.account) queryParams.append('account', params.account);
    if (params.strategy) queryParams.append('strategy', params.strategy);
    if (params.status) queryParams.append('status', params.status);
    if (params.symbol) queryParams.append('symbol', params.symbol);
    if (params.page) queryParams.append('page', params.page);
    if (params.limit) queryParams.append('limit', params.limit);
    return api.get(`/portfolio/ibkr/trades?${queryParams.toString()}`);
  },
  getIBKRTradeDetail: (tradeId) => api.get(`/portfolio/ibkr/trades/${tradeId}`),
  getIBKRSummary: (account = null) => {
    const params = account ? `?account=${account}` : '';
    return api.get(`/portfolio/ibkr/summary${params}`);
  },
  getAISuggestion: (tradeId) => api.post(`/portfolio/ibkr/trades/${tradeId}/ai-suggestion`),
  generateAllSuggestions: () => api.post('/portfolio/ibkr/generate-suggestions'),
  clearIBKRData: () => api.delete('/portfolio/ibkr/clear'),
};

export const watchlistApi = {
  getAll: () => api.get('/watchlist/'),
  add: (data) => api.post('/watchlist/', data),
  remove: (id) => api.delete(`/watchlist/${id}`),
};

export const newsApi = {
  getNews: (params) => api.get('/news/', { params }),
};

export const aiApi = {
  analyze: (data) => api.post('/ai/analyze', data),
  getOpportunities: (params) => api.get('/ai/opportunities', { params }),
};

export const adminApi = {
  getSettings: () => api.get('/admin/settings'),
  updateSettings: (data) => api.post('/admin/settings', data),
  makeAdmin: (userId) => api.post(`/admin/make-admin/${userId}`),
};
