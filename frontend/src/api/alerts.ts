import { api } from './client'

export interface AlertRule {
  id: string
  name: string
  event_type: string
  threshold: number | null
  enabled: boolean
  created_at: string
}

export interface WebhookConfig {
  id: string
  name: string
  url: string
  type: 'slack' | 'generic'
  enabled: boolean
  created_at: string
}

export interface AlertEvent {
  id: string
  rule_id: string | null
  node_id: string | null
  message: string
  fired_at: string
  delivered: boolean
}

export interface AlertRulesResponse {
  items: AlertRule[]
}

export interface WebhooksResponse {
  items: WebhookConfig[]
}

export interface AlertEventsResponse {
  items: AlertEvent[]
}

export interface CreateRuleBody {
  name: string
  event_type: string
  threshold?: number | null
  enabled?: boolean
}

export interface CreateWebhookBody {
  name: string
  url: string
  type: 'slack' | 'generic'
  enabled?: boolean
}

export const alertsApi = {
  listRules: () => api.get<AlertRulesResponse>('/api/v1/alerts/rules'),
  createRule: (body: CreateRuleBody) =>
    api.post<AlertRule>('/api/v1/alerts/rules', body),
  deleteRule: (id: string) => api.delete(`/api/v1/alerts/rules/${id}`),

  listWebhooks: () => api.get<WebhooksResponse>('/api/v1/alerts/webhooks'),
  createWebhook: (body: CreateWebhookBody) =>
    api.post<WebhookConfig>('/api/v1/alerts/webhooks', body),
  deleteWebhook: (id: string) => api.delete(`/api/v1/alerts/webhooks/${id}`),
  testWebhook: (id: string) =>
    api.post<{ status: string; message: string }>(`/api/v1/alerts/test-webhook/${id}`),

  listEvents: (limit = 50) =>
    api.get<AlertEventsResponse>(`/api/v1/alerts/events?limit=${limit}`),
}
