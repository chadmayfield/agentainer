import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { markdownGallery } from './markdown';

const output = path.resolve(__dirname, '../../artifacts/visual');
const expectedIds = ['shell', 'ls-colors', 'eza', 'eza-tree', 'eza-broken', 'git-status', 'git-diff',
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
  const metadata = [
    `Image: ${recording.image}`,
    `Defaults: ${recording.defaults}`,
    `Renderer: ${browser.version()}`,
    'Terminal: 120 × 32 and narrow 80 × 24, JetBrains Mono 14px.',
  ];
  const navigationGroups = [
    ['Shell', [['shell', 'Prompt and ls'], ['ls-colors', 'All file types']]],
    ['eza', [['eza', 'Listing'], ['eza-tree', 'Tree'], ['eza-broken', 'Broken link']]],
    ['Git', [['git-status', 'Status'], ['git-diff', 'Diff'], ['git-staged', 'Staged'], ['git-conflict', 'Conflict']]],
    ['bat', [['bat', 'Python'], ['bat-yaml', 'YAML']]],
    ['fzf', [['fzf-idle', 'Idle'], ['fzf', 'Filtered'], ['fzf-selected', 'Selected'], ['fzf-empty', 'No matches']]],
    ['Vim', [['vim', 'Python'], ['vim-yaml', 'YAML'], ['vim-browser', 'Browser'], ['vim-search', 'Search'],
      ['vim-selection', 'Selection'], ['vim-browser-narrow', '80 columns']]],
    ['tmux', [['tmux-single', 'Single pane'], ['tmux', 'Split panes'], ['tmux-copy', 'Copy mode'],
      ['tmux-activity', 'Activity'], ['tmux-narrow', '80 columns']]],
  ] as const;
  const navigation = navigationGroups.map(([tool, links]) =>
    `<div class="nav-group"><span class="nav-label">${tool}</span><div class="nav-links">${links.map(([id, label]) =>
      `<a href="#${id}">${label}</a>`).join('')}</div></div>`).join('');
  const html = (cards: string) => template
    .replace('/*__FONT__*/', '')
    .replace('/*__XTERM_CSS__*/', '')
    .replace('__METADATA__', metadata.map(item => `<li>${escapeHtml(item)}</li>`).join(''))
    .replace('__NAV__', navigation)
    .replace('__CARDS__', cards).replace('__RENDERER__', '');
  const terminalPage = `<!doctype html><html><head><meta charset="utf-8"><style>
    ${fontCss()}
${xtermCss}
    html, body { margin: 0; background: #010409; }
    .terminal { padding: 12px; width: max-content; background: #010409; }
    /* xterm.css paints the viewport #000; match the reference background. */
    .xterm .xterm-viewport { background-color: #010409; }
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
          // Reference GitHub Dark palette, copied from TERMINAL in tests/unit/palette.py.
          theme: {
            background: '#010409', foreground: '#e6edf3', cursor: '#f78166',
            selectionBackground: '#264f78', black: '#484f58', brightBlack: '#6e7681',
            red: '#ff7b72', brightRed: '#ffa198', green: '#3fb950', brightGreen: '#56d364',
            yellow: '#d29922', brightYellow: '#e3b341', blue: '#58a6ff', brightBlue: '#79c0ff',
            magenta: '#bc8cff', brightMagenta: '#d2a8ff', cyan: '#39c5cf', brightCyan: '#56d4dd',
            white: '#b1bac4', brightWhite: '#ffffff',
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
        const rgbColors = new Set<string>();
        const backgrounds = new Set<string>();
        const buffer = terminal.buffer.active;
        for (let row = 0; row < terminal.rows; row++) {
          const line = buffer.getLine(buffer.baseY + row);
          text += line.translateToString(true) + '\n';
          for (let col = 0; col < terminal.cols; col++) {
            const cell = line.getCell(col);
            if (cell.getChars() && !cell.isFgDefault()) colors.add(cell.getFgColor());
            if (cell.getChars() && cell.isFgRGB()) rgbColors.add('#' + cell.getFgColor().toString(16).padStart(6, '0'));
            if (cell.isBgRGB()) backgrounds.add('#' + cell.getBgColor().toString(16).padStart(6, '0'));
          }
        }
        return { text, colors: [...colors], rgbColors: [...rgbColors], backgrounds: [...backgrounds] };
      }, capture);
      for (const expected of capture.expectedText) expect(screen.text, capture.id).toContain(expected);
      for (const absent of capture.absentText || []) expect(screen.text, capture.id).not.toContain(absent);
      for (const background of capture.expectedBackgrounds || []) expect(screen.backgrounds, capture.id).toContain(background);
      for (const color of capture.expectedColors || []) expect(screen.rgbColors, capture.id).toContain(color);
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
    await expect(page.locator('nav .nav-group')).toHaveCount(7);
    expect(await page.locator('nav a').evaluateAll(links => links.map(link => link.getAttribute('href'))))
      .toEqual(expectedIds.map(id => `#${id}`));
    await expect(page.locator('ul.metadata > li')).toHaveCount(4);
    expect(gallery).not.toContain('Their generation does not mean a person has approved the appearance.');
    await expect(page.locator('figure img')).toHaveCount(expectedIds.length);
    const frameWidths = await page.locator('figure').evaluateAll(figures => figures.map(figure => ({
      frame: figure.getBoundingClientRect().width,
      image: figure.querySelector('img')!.getBoundingClientRect().width,
    })));
    for (const widths of frameWidths) expect(widths.frame - widths.image).toBeCloseTo(2, 0);
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

test('gallery uses the GitHub Dark page colors in either client color scheme', async ({ page }) => {
  await page.setContent(fs.readFileSync(path.join(__dirname, 'gallery.html'), 'utf8')
    .replace('__NAV__', '<a href="#sample">Sample</a>')
    .replace('__CARDS__', '<figure><img alt="Sample"></figure>'));
  for (const scheme of ['light', 'dark', 'light'] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(1, 4, 9)');
    await expect(page.locator('body')).toHaveCSS('color', 'rgb(230, 237, 243)');
    await expect(page.locator('nav a')).toHaveCSS('color', 'rgb(88, 166, 255)');
    await expect(page.locator('figure')).toHaveCSS('background-color', 'rgb(1, 4, 9)');
  }
});

test('Markdown links only captured screenshots', () => {
  expect(markdownGallery([], [])).not.toContain('](screenshots/');
});

test('Markdown keeps screenshot links relative and escapes captured text', () => {
  const markdown = markdownGallery([{ id: 'vim-selection', title: 'Vim [selection]',
    description: '<script>example</script>', cols: 120, rows: 32 }], ['Example image']);
  expect(markdown).toContain('![Vim \\[selection\\] terminal screenshot](screenshots/vim-selection.png)');
  expect(markdown).not.toContain('<script>');
  expect(markdown).not.toContain('data:image');
  expect(markdown).toContain('\n- Example image\n');
  expect(markdown).not.toContain('Their generation does not mean a person has approved the appearance.');
  expect(() => markdownGallery([{ id: '../outside', title: 'Invalid',
    description: '', cols: 120, rows: 32 }], [])).toThrow('invalid screenshot identifier');
});
