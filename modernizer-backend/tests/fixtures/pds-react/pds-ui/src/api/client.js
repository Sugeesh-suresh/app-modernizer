import axios from 'axios';

// Every PDS call goes through this client; the dev server proxies /api to pds-service.
const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

export default api;
