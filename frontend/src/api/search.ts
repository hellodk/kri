import { api } from './client'
import type { Paginated, SearchResult } from '../types'

export const searchApi = {
  search: (q: string) =>
    api.get<Paginated<SearchResult>>(`/api/v1/search?q=${encodeURIComponent(q)}`),
}
