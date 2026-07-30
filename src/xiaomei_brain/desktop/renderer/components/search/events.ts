export const UNIFIED_SEARCH_EVENT = "xiaomei:open-unified-search";

export function openUnifiedSearch(): void {
  window.dispatchEvent(new Event(UNIFIED_SEARCH_EVENT));
}

