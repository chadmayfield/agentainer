" Agentainer colors, GitHub Dark. Near-black panes and a blue status line.
" Palette: https://github.com/primer/primitives/blob/%40primer/primitives%4011.10.0/src/tokens/base/color/dark/dark.json5
" Terminal colors: https://terminalcolors.com/downloads/ghostty/github-dark
" Highlight groups: :help highlight-groups
highlight clear
if exists('syntax_on')
  syntax reset
endif
set background=dark
let g:colors_name = 'agentainer'

highlight Normal       guifg=#e6edf3 guibg=#010409 gui=NONE
highlight NonText      guifg=#656c76 guibg=#010409 gui=NONE
highlight EndOfBuffer  guifg=#3d444d guibg=#010409 gui=NONE
highlight LineNr       guifg=#656c76 guibg=#010409 gui=NONE cterm=NONE term=NONE
highlight CursorLineNr guifg=#e6edf3 guibg=#0d1117 gui=bold cterm=bold term=bold
highlight CursorLine   guifg=NONE guibg=#0d1117 gui=NONE cterm=NONE term=NONE
highlight ColorColumn  guifg=NONE guibg=#151b23 gui=NONE
highlight SignColumn   guifg=#656c76 guibg=#010409 gui=NONE
highlight StatusLine   guifg=#79c0ff guibg=#0c2d6b gui=bold cterm=bold term=bold
highlight StatusLineNC guifg=#9198a1 guibg=#151b23 gui=NONE cterm=NONE term=NONE
highlight VertSplit    guifg=#3d444d guibg=#010409 gui=NONE cterm=NONE
highlight Visual       guifg=NONE guibg=#264f78 gui=NONE
highlight Search       guifg=#010409 guibg=#58a6ff gui=NONE
highlight IncSearch    guifg=#010409 guibg=#79c0ff gui=bold cterm=bold
highlight MatchParen   guifg=#e6edf3 guibg=#264f78 gui=bold
highlight Pmenu        guifg=#e6edf3 guibg=#151b23 gui=NONE
highlight PmenuSel     guifg=#010409 guibg=#58a6ff gui=NONE
highlight PmenuSbar    guifg=NONE guibg=#151b23 gui=NONE
highlight PmenuThumb   guifg=NONE guibg=#3d444d gui=NONE
highlight Directory   guifg=#58a6ff guibg=NONE gui=NONE
highlight Title       guifg=#58a6ff guibg=NONE gui=bold
highlight Comment     guifg=#9198a1 guibg=NONE gui=italic
highlight Constant    guifg=#79c0ff guibg=NONE gui=NONE
highlight String      guifg=#a5d6ff guibg=NONE gui=NONE
highlight Identifier  guifg=#ffa657 guibg=NONE gui=NONE cterm=NONE
highlight Function    guifg=#d2a8ff guibg=NONE gui=NONE
highlight Statement   guifg=#ff7b72 guibg=NONE gui=NONE cterm=NONE
highlight PreProc     guifg=#ff7b72 guibg=NONE gui=NONE
highlight Type        guifg=#ff7b72 guibg=NONE gui=NONE cterm=NONE
highlight Special     guifg=#79c0ff guibg=NONE gui=NONE
highlight Underlined  guifg=#58a6ff guibg=NONE gui=underline
highlight Error       guifg=#ff7b72 guibg=#010409 gui=bold
highlight ErrorMsg    guifg=#ff7b72 guibg=#010409 gui=bold
highlight WarningMsg  guifg=#d29922 guibg=#010409 gui=NONE
highlight Todo        guifg=#d29922 guibg=#151b23 gui=bold
highlight SpecialKey  guifg=#656c76 guibg=NONE gui=NONE
