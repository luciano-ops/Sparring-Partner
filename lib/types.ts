export interface BriefingSection {
  number: string;
  title: string;
  content: string;
  isComplete: boolean;
  side: "buyer" | "seller";
}

export interface GenerateRequest {
  companyName: string;
}
