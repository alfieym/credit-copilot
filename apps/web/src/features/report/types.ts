/**
 * 与后端 `credit_copilot.agents.models` 对齐的类型定义。
 * 后端返回的是 `CreditMemo.model_dump()`（snake_case），这里保持一致。
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
