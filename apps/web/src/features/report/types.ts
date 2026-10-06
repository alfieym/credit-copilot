/**
 * Type definitions aligned with the backend's `credit_copilot.agents.models`.
 * The backend returns `CreditMemo.model_dump()` (snake_case), which is kept here.
 */
export interface Section {
  title: string;
  content: string;
  citations: string[];
}

export interface CreditMemo {
  entity_name: string;
  sections: Section[];
  compliance_flags: string[];
  data_gaps: string[];
  generated_at: string;
}
