interface Capture {
  id: string;
  title: string;
  description: string;
  cols: number;
  rows: number;
}

const text = (value: string) => value.replace(/[\r\n]+/g, ' ').replace(/[\\`*_<>\[\]!#|]/g, '\\$&');

export function markdownGallery(captures: Capture[], metadata: string): string {
  const sections = captures.map(capture => {
    if (!/^[a-z0-9-]+$/.test(capture.id)) throw new Error('invalid screenshot identifier');
    return [
      `## ${text(capture.title)}`,
      '',
      text(capture.description),
      '',
      `Terminal: ${capture.cols} columns by ${capture.rows} rows.`,
      '',
      `![${text(capture.title)} terminal screenshot](screenshots/${capture.id}.png)`,
    ].join('\n');
  });
  return [
    '# Agentainer color review',
    '',
    'Agentainer colors, inspired by Ayu. Review contrast, selections, error colors, gutters and status lines.',
    '',
    text(metadata),
    '',
    "Captured from actual tools with generic files. Browser rendering uses a fixed font and an Ayu-inspired reference ANSI palette. Your terminal's font rendering and ANSI colors may differ, especially for bat. Sample dates and the tmux clock are fixed.",
    '',
    ...sections.flatMap(section => [section, '']),
    'Screenshots are review artifacts. Their generation does not mean a person has approved the appearance.',
    '',
  ].join('\n');
}
