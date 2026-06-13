/**
 * Batch selection hook.
 *
 * Owns the multi-select state (which symbols are checked) and the selecting
 * toggle, extracted from PortfolioPage so lane components can read selection
 * without the page threading it through every prop.
 */
import { useCallback, useState } from "react";

export function useBatchSelection() {
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set());
  const [isSelecting, setIsSelecting] = useState(false);

  const toggle = useCallback((vtSymbol: string) => {
    setSelectedSymbols((prev) => {
      const next = new Set(prev);
      if (next.has(vtSymbol)) next.delete(vtSymbol);
      else next.add(vtSymbol);
      return next;
    });
  }, []);

  const selectAll = useCallback((symbols: string[]) => {
    setSelectedSymbols(new Set(symbols));
  }, []);

  const clear = useCallback(() => {
    setSelectedSymbols(new Set());
    setIsSelecting(false);
  }, []);

  const toggleSelecting = useCallback(() => setIsSelecting((value) => !value), []);

  return {
    selectedSymbols,
    isSelecting,
    selectedCount: selectedSymbols.size,
    toggle,
    selectAll,
    clear,
    toggleSelecting,
    setIsSelecting,
  };
}
