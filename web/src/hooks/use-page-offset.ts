import { type Dispatch, type SetStateAction, useState } from "react";

/**
 * Paged-list offset that resets to the first page whenever `filters` changes
 * identity (React's adjust-state-during-render pattern).
 */
export function usePageOffset(
  filters: unknown,
): [offset: number, setOffset: Dispatch<SetStateAction<number>>] {
  const [offset, setOffset] = useState(0);
  const [appliedFilters, setAppliedFilters] = useState(filters);
  if (appliedFilters !== filters) {
    setAppliedFilters(filters);
    setOffset(0);
  }
  return [offset, setOffset];
}
