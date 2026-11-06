interface Capture {
  id: string;
  title: string;
  description: string;
  cols: number;
  rows: number;
}

const text = (value: string) => value.replace(/[\r\n]+/g, ' ').replace(/[\\`*_<>\[\]!#|]/g, '\\$&');

export function markdownGallery(captures: Capture[], metadata: string[]): string {
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
    'Agentainer uses GitHub Dark colors on a #010409 background. Review contrast, selections, error colors, gutters and status lines.',
    '',
    ...metadata.map(item => `- ${text(item)}`),
    '',
    "Captured from actual tools with generic files. Browser rendering uses a fixed font and the GitHub Dark reference ANSI palette from tests/unit/palette.py. Your terminal's font rendering and ANSI colors may differ, especially for bat. Sample dates and the tmux time and date are fixed.",
    '',
    ...sections.flatMap(section => [section, '']),
    'Screenshots are review artifacts.',
    '',
  ].join('\n');
}
