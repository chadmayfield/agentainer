import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { markdownGallery } from './markdown';

const output = path.resolve(__dirname, '../../artifacts/visual');
const expectedIds = ['shell', 'eza', 'eza-tree', 'eza-broken', 'git-status', 'git-diff',
  'git-staged', 'git-conflict', 'bat', 'bat-yaml', 'fzf-idle', 'fzf', 'fzf-selected', 'fzf-empty',
  'vim', 'vim-yaml', 'vim-browser', 'vim-search', 'vim-selection', 'vim-browser-narrow',
  'tmux-single', 'tmux', 'tmux-copy', 'tmux-activity', 'tmux-narrow'];
const escapeHtml = (value: string) => value.replace(/[&<>"']/g, char =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!));

function fontCss() {
  return [400, 700].map(weight => {
    const file = path.join(__dirname, `node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-${weight}-normal.woff2`);
    return `@font-face { font-family: 'JetBrains Mono'; font-style: normal; font-weight: ${weight}; src: url(data:font/woff2;base64,${fs.readFileSync(file).toString('base64')}) format('woff2'); }`;
  }).join('\n');
}

test('render all terminal states and publish an offline review gallery', async ({ page, browser }) => {
  const recording = JSON.parse(fs.readFileSync(path.join(output, 'captures.json'), 'utf8'));
  expect(recording.schema).toBe(1);
  expect(recording.captures.map((capture: any) => capture.id)).toEqual(expectedIds);
  const template = fs.readFileSync(path.join(__dirname, 'gallery.html'), 'utf8');
  const xtermJs = fs.readFileSync(path.join(__dirname, 'node_modules/@xterm/xterm/lib/xterm.js'), 'utf8');
  const xtermCss = fs.readFileSync(path.join(__dirname, 'node_modules/@xterm/xterm/css/xterm.css'), 'utf8');
  const metadata = `Image: ${recording.image}. Defaults: ${recording.defaults}. Renderer: ${browser.version()}. Terminal: 120 × 32 and narrow 80 × 24, JetBrains Mono 14px.`;
  const html = (cards: string) => template
    .replace('/*__FONT__*/', '')
    .replace('/*__XTERM_CSS__*/', '')
    .replace('__METADATA__', escapeHtml(metadata))
    .replace('__NAV__', recording.captures.map((item: any) => `<a href="#${item.id}">${escapeHtml(item.title)}</a>`).join(''))
    .replace('__CARDS__', cards).replace('__RENDERER__', '');
  const terminalPage = `<!doctype html><html><head><meta charset="utf-8"><style>
    ${fontCss()}
${xtermCss}
    html, body { margin: 0; background: #000; }
    .terminal { padding: 12px; width: max-content; background: #000; }
    </style></head><body><div class="terminal" id="terminal"></div></body></html>`;
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  // Rendering uses embedded assets and must not depend on an external service.
  await page.route('**/*', route => route.abort());
  const staging = fs.mkdtempSync(path.join(output, 'cx-render-'));
  const cards: string[] = [];
  try {
    for (const capture of recording.captures) {
      const narrow = ['vim-browser-narrow', 'tmux-narrow'].includes(capture.id);
      expect(capture.cols).toBe(narrow ? 80 : 120);
      expect(capture.rows).toBe(narrow ? 24 : 32);
      expect(capture.expectedText.length).toBeGreaterThan(0);
      const heading = `<h2>${escapeHtml(capture.title)}</h2><p>${escapeHtml(capture.description)}</p><p class="metadata">${capture.cols} columns × ${capture.rows} rows</p>`;
      await page.setContent(terminalPage);
      await page.addScriptTag({ content: xtermJs });
      await page.evaluate(async () => {
        await document.fonts.load('14px "JetBrains Mono"');
        await document.fonts.load('700 14px "JetBrains Mono"');
        await document.fonts.ready;
        if (!document.fonts.check('14px "JetBrains Mono"')) throw new Error('terminal font did not load');
      });
      const screen = await page.evaluate(async (capture: any) => {
        const terminal = new (window as any).Terminal({
          cols: capture.cols, rows: capture.rows, fontFamily: 'JetBrains Mono', fontSize: 14,
          fontWeight: '400', fontWeightBold: '700', lineHeight: 1.2,
          cursorBlink: false, scrollback: 0, allowProposedApi: true,
          theme: {
            background: '#000000', foreground: '#bfbdb6', cursor: '#e6b450',
            selectionBackground: '#202020', black: '#000000', brightBlack: '#747474',
            red: '#f07178', brightRed: '#f07178', green: '#aad94c', brightGreen: '#aad94c',
            yellow: '#e6b450', brightYellow: '#ffb454', blue: '#59c2ff', brightBlue: '#59c2ff',
            magenta: '#d2a6ff', brightMagenta: '#d2a6ff', cyan: '#95e6cb', brightCyan: '#95e6cb',
            white: '#bfbdb6', brightWhite: '#ffffff',
          },
        });
        terminal.open(document.getElementById('terminal'));
        (window as any).reviewTerminal = terminal;
        const bytes = Uint8Array.from(atob(capture.output), char => char.charCodeAt(0));
        await new Promise<void>(resolve => terminal.write(bytes, resolve));
        await new Promise<void>(resolve => {
          const subscription = terminal.onRender(() => { subscription.dispose(); resolve(); });
          terminal.refresh(0, terminal.rows - 1);
        });
        await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        let text = '';
        const colors = new Set<number>();
        const backgrounds = new Set<string>();
        const buffer = terminal.buffer.active;
        for (let row = 0; row < terminal.rows; row++) {
          const line = buffer.getLine(buffer.baseY + row);
          text += line.translateToString(true) + '\n';
          for (let col = 0; col < terminal.cols; col++) {
            const cell = line.getCell(col);
            if (cell.getChars() && !cell.isFgDefault()) colors.add(cell.getFgColor());
            if (cell.isBgRGB()) backgrounds.add('#' + cell.getBgColor().toString(16).padStart(6, '0'));
          }
        }
        return { text, colors: [...colors], backgrounds: [...backgrounds] };
      }, capture);
      for (const expected of capture.expectedText) expect(screen.text, capture.id).toContain(expected);
      for (const absent of capture.absentText || []) expect(screen.text, capture.id).not.toContain(absent);
      for (const background of capture.expectedBackgrounds || []) expect(screen.backgrounds, capture.id).toContain(background);
      expect(screen.colors.length, `${capture.id} must contain colored text`).toBeGreaterThan(0);
      const bounds = await page.locator('#terminal').boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.y).toBeGreaterThanOrEqual(0);
      expect(bounds!.y + bounds!.height, 'terminal must be fully visible before capture').toBeLessThanOrEqual(page.viewportSize()!.height);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
      const png = path.join(staging, `${capture.id}.png`);
      await page.locator('#terminal').screenshot({ path: png, animations: 'disabled' });
      const data = fs.readFileSync(png).toString('base64');
      expect(data.length).toBeGreaterThan(1000);
      cards.push(`<section id="${capture.id}">${heading}<figure><img alt="${escapeHtml(capture.title)} terminal screenshot" src="data:image/png;base64,${data}"></figure></section>`);
      await page.evaluate(() => (window as any).reviewTerminal.dispose());
    }
    expect(errors).toEqual([]);
    // Validate the delivered page before replacing the last complete gallery.
    const gallery = html(cards.join('\n'));
    await page.setContent(gallery);
    await expect(page.locator('figure img')).toHaveCount(expectedIds.length);
    await expect(page.locator('script, link, iframe')).toHaveCount(0);
    expect(await page.locator('figure img').evaluateAll(images => images.every(image =>
      (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
    const markdown = markdownGallery(recording.captures, metadata);
    const links = [...markdown.matchAll(/^!\[.*\]\((screenshots\/[a-z0-9-]+\.png)\)$/gm)].map(match => match[1]);
    expect(links).toEqual(expectedIds.map(id => `screenshots/${id}.png`));
    for (const id of expectedIds) expect(fs.existsSync(path.join(staging, `${id}.png`))).toBe(true);
    fs.writeFileSync(path.join(staging, 'index.md'), markdown);
    const destination = path.join(output, 'screenshots');
    fs.mkdirSync(destination, { recursive: true });
    for (const id of expectedIds) fs.copyFileSync(path.join(staging, `${id}.png`), path.join(destination, `${id}.png`));
    const index = path.join(staging, 'index.html');
    fs.writeFileSync(index, gallery);
    fs.renameSync(index, path.join(output, 'index.html'));
    fs.renameSync(path.join(staging, 'index.md'), path.join(output, 'index.md'));
    console.log(`Review gallery: ${path.join(output, 'index.html')}`);
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
});

test('Markdown keeps screenshot links relative and escapes captured text', () => {
  const markdown = markdownGallery([{ id: 'vim-selection', title: 'Vim [selection]',
    description: '<script>example</script>', cols: 120, rows: 32 }], 'Example image');
  expect(markdown).toContain('![Vim \\[selection\\] terminal screenshot](screenshots/vim-selection.png)');
  expect(markdown).not.toContain('<script>');
  expect(markdown).not.toContain('data:image');
  expect(() => markdownGallery([{ id: '../outside', title: 'Invalid',
    description: '', cols: 120, rows: 32 }], '')).toThrow('invalid screenshot identifier');
});
