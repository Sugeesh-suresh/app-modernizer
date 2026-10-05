import api from './client';
import { ATTRIBUTES } from './endpoints';

export function fetchAttributes(page, size, showValues) {
  return api.get(ATTRIBUTES, { params: { page, size, showValues } });
}

export function searchAttributes(id, name, page) {
  return api.get(`${ATTRIBUTES}/search`, { params: { id, name, page } });
}

export function fetchAttribute(id) {
  return api.get(`${ATTRIBUTES}/${id}`);
}
