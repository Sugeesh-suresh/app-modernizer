import api from './client';
import { JOBS } from './endpoints';

export const fetchJobs = (params) => api.get(JOBS, { params });

export const searchJobs = (q, scope, exact, tenant) =>
  api.get(`${JOBS}/search`, { params: { q, scope, exact, tenant } });

export const fetchRunningJobs = () => api.get(`${JOBS}/running`);

export const fetchCompletedJobs = (date) => api.get(`${JOBS}/completed`, { params: { date } });

export const cancelExecution = (execId) => api.get(`${JOBS}/executions/${execId}/cancel`);
