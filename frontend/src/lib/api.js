import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const api = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
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
  getIndices: () => api.get('/stocks/indices'),
  getHistorical: (symbol, params) => api.get(`/stocks/historical/${symbol}`, { params }),
};

export const optionsApi = {
  getChain: (symbol, expiry) => api.get(`/options/chain/${symbol}`, { params: { expiry } }),
  getExpirations: (symbol) => api.get(`/options/expirations/${symbol}`),
};

export const screenerApi = {
  getCoveredCalls: (params) => api.get('/screener/covered-calls', { params }),
  getPMCC: (params) => api.get('/screener/pmcc', { params }),
  getFilters: () => api.get('/screener/filters'),
  saveFilter: (data) => api.post('/screener/filters', data),
  deleteFilter: (id) => api.delete(`/screener/filters/${id}`),
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
