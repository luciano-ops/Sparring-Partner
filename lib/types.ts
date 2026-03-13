export interface BriefingSection {
  number: string;
  title: string;
  content: string;
  isComplete: boolean;
}

export interface GenerateRequest {
  companyName: string;
}
