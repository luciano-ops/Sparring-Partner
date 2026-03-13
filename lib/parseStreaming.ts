import { BriefingSection } from "./types";

export function parseBriefingSections(
  rawText: string,
  isStreamComplete: boolean
): BriefingSection[] {
  const sectionRegex = /### (\d{2}) \/ (.+)/g;
  const sections: BriefingSection[] = [];
  const matches: {
    number: string;
    title: string;
    contentStart: number;
    matchStart: number;
  }[] = [];

  let match: RegExpExecArray | null;
  while ((match = sectionRegex.exec(rawText)) !== null) {
    matches.push({
      number: match[1],
      title: match[2].trim(),
      contentStart: match.index + match[0].length,
      matchStart: match.index,
    });
  }

  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].contentStart;
    const end =
      i + 1 < matches.length ? matches[i + 1].matchStart : rawText.length;

    const content = rawText.slice(start, end).trim();
    const isComplete = i + 1 < matches.length || isStreamComplete;

    sections.push({
      number: matches[i].number,
      title: matches[i].title,
      content,
      isComplete,
    });
  }

  return sections;
}
