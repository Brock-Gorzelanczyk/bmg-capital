declare global {
  interface Window {
    BMGFloor?: {
      setCost?: (who: string, c: string | number) => void;
      setBriefing?: (who: string, t: string) => void;
      setDecision?: (who: string, t: string) => void;
      setStale?: (list: string[]) => void;
      setBudget?: (spent?: number, cap?: number) => void;
      vetoFlash?: () => void;
    };
  }
}

export {};
