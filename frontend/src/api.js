const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: options.body instanceof FormData
      ? undefined
      : { 'Content-Type': 'application/json' },
    ...options,
  });
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new Error((data && data.detail) || `请求失败 (${res.status})`);
  }
  return data;
}

export const api = {
  listProjects: () => request('/projects'),
  createProject: (name) =>
    request('/projects', { method: 'POST', body: JSON.stringify({ name }) }),
  getProject: (id) => request(`/projects/${id}`),
  saveProject: (id, { name, document }) =>
    request(`/projects/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ name, document }),
    }),
  deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),
  exportUrl: (id) => `${BASE}/projects/${id}/export`,

  importTranscript: async (payload) => {
    if (payload instanceof FormData) {
      return request('/import', { method: 'POST', body: payload });
    }
    return request('/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  importIntoProject: (id, formData) =>
    request(`/projects/${id}/import`, { method: 'POST', body: formData }),

  merge: (payload) =>
    request('/merge', { method: 'POST', body: JSON.stringify(payload) }),
};
